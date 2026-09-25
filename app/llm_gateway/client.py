"""HTTP adapter speaking the OpenAI chat-completions/embeddings JSON shape.

Not just for a custom deployment: this one class backs the custom endpoint, OpenAI, AND
Gemini (via Google's OpenAI-compatibility endpoint) -- all three speak this same shape
natively, so provider selection (app/llm_gateway/__init__.py) is just a different
base_url/api_key/model_name, not a different client. Most self-hosted stacks (vLLM, TGI,
Ollama's OpenAI-compat mode, LM Studio, a custom FastAPI wrapper) speak it too. If your
deployment's request/response shape differs, this is the ONLY file that needs to change --
everything else in the app talks to the `LLMGateway` interface in base.py, not to this
HTTP shape directly.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Type, TypeVar

import requests
from pydantic import BaseModel, ValidationError

from app.llm_gateway.base import LLMGateway, LLMValidationError

T = TypeVar("T", bound=BaseModel)

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# (connect_timeout, read_timeout): a self-hosted endpoint that's fully down/unreachable
# should fail fast (short connect timeout) rather than hang -- confirmed live: a plain curl
# against a degraded deployment hung past 20s with no response at all, and with the old
# single 240s timeout that meant ~4 minutes wasted PER call before even trying the next
# retry. The read timeout stays generous (a "thinking"-mode model genuinely computing a
# structured answer can take 30-60s), just not unbounded. A hard failure after retries still
# degrades gracefully -- see the per-agent try/except in the data/analysis/delivery
# supervisors, which turn it into a PARTIAL/FAILED result for just that one document or
# module instead of crashing the whole stage, so failing faster here directly speeds up the
# whole pipeline instead of trading reliability for it.
_HTTP_TIMEOUT_S = (8, 60)
# Retries + backoff cover transient timeouts/5xx/connection errors per design doc §6.11.
# Kept modest (not the earlier 4 retries / up to 16s backoff): against a genuinely
# unreachable endpoint, more attempts just delays the same graceful fallback further, which
# fights directly against wanting the whole pipeline to finish quickly.
_MAX_HTTP_RETRIES = 2
_RETRY_BACKOFF_S = [2, 4]


class RealLLMGateway(LLMGateway):
    def __init__(self, base_url: str, api_key: str, model_name: str, reasoning_model_name: str | None = None,
                 embeddings_enabled: bool = False, parallel_calls: bool = False,
                 max_concurrent_requests: int = 3, max_tokens: int = 8192):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.reasoning_model_name = reasoning_model_name
        self.embeddings_enabled = embeddings_enabled
        # max_tokens matters more than usual here: a thinking-mode model (e.g. Qwen3) burns
        # a chunk of the budget on the <think> block before it even starts the real answer,
        # so a small/unset limit truncates the JSON mid-string -- confirmed against a live
        # model (InsightSet came back with an "Unterminated string" JSON error). No request
        # here previously set max_tokens at all, silently relying on the server's default.
        self.max_tokens = max_tokens
        # LLM_PARALLEL_CALLS is the master switch: false pins this to 1 regardless of
        # max_concurrent_requests, so every LLM call across the whole process (every agent,
        # every thread, every stage's fan-out) is strictly serialized -- for a deployment
        # that can't handle any overlapping requests at all. true allows up to
        # max_concurrent_requests in flight, still capped because even a deployment that
        # supports concurrency may not support unlimited concurrency (confirmed: 5 at once
        # caused sustained 503s against a live endpoint; lowering to 2 fixed it).
        self.parallel_calls = parallel_calls
        effective_concurrency = max(1, max_concurrent_requests) if parallel_calls else 1
        self._semaphore = threading.Semaphore(effective_concurrency)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _chat(self, messages: list[dict], temperature: float = 0.2, model: str | None = None) -> str:
        last_error: Exception | None = None
        max_tokens = self.max_tokens
        active_model = model or self.model_name
        with self._semaphore:
            for attempt in range(_MAX_HTTP_RETRIES + 1):
                try:
                    resp = requests.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json={"model": active_model, "messages": messages, "temperature": temperature,
                              "max_tokens": max_tokens},
                        timeout=_HTTP_TIMEOUT_S,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    if choice.get("finish_reason") == "length":
                        # Cut off by max_tokens, not because the model was done -- a
                        # thinking-mode model can burn most of the budget on the <think>
                        # block before it even reaches the real answer. Retry with a bigger
                        # budget rather than handing back a guaranteed-truncated JSON string.
                        last_error = LLMValidationError(
                            f"response truncated at max_tokens={max_tokens} (finish_reason=length)"
                        )
                        max_tokens = int(max_tokens * 1.5)
                        if attempt < _MAX_HTTP_RETRIES:
                            continue
                        raise last_error
                    # OpenAI-compatible shape: {"choices": [{"message": {"content": "..."}}]}
                    return choice["message"]["content"]
                except requests.exceptions.RequestException as exc:
                    last_error = exc
                    if attempt < _MAX_HTTP_RETRIES:
                        wait_s = _RETRY_BACKOFF_S[min(attempt, len(_RETRY_BACKOFF_S) - 1)]
                        retry_after = exc.response.headers.get("Retry-After") if exc.response is not None else None
                        if retry_after is not None:
                            try:
                                wait_s = max(wait_s, float(retry_after))
                            except ValueError:
                                pass
                        time.sleep(wait_s)
        raise last_error

    def _invoke_chat(self, messages: list[dict], model: str | None = None, temperature: float = 0.2) -> str:
        try:
            return self._chat(messages, temperature=temperature, model=model)
        except TypeError:
            # Fallback for monkeypatched _chat in tests that only accepts (messages, temperature=0.2)
            return self._chat(messages, temperature=temperature)

    def complete(self, messages, schema: Type[T] | None = None, tier: str = "default", max_retries: int = 1):
        active_model = (
            self.reasoning_model_name
            if (tier in ("reasoning", "advanced") and self.reasoning_model_name)
            else self.model_name
        )
        if schema is None:
            return self._invoke_chat(messages, model=active_model)

        schema_hint = {
            "role": "system",
            "content": (
                "Respond with ONLY a single JSON object matching this JSON Schema, no prose, "
                f"no markdown fences:\n{json.dumps(schema.model_json_schema())}"
            ),
        }
        working_messages = [schema_hint] + messages
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            raw = self._invoke_chat(working_messages, model=active_model)
            try:
                payload = _extract_json(raw)
                return schema.model_validate(payload)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                working_messages = working_messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"That was invalid: {exc}. Reply again with ONLY corrected JSON."},
                ]

        raise LLMValidationError(f"LLM failed to produce valid {schema.__name__} after retries: {last_error}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embeddings_enabled:
            raise NotImplementedError(
                "LLM_EMBEDDINGS_ENABLED is false; vector_search falls back to a local "
                "HashingVectorizer instead of calling this."
            )
        resp = requests.post(
            f"{self.base_url}/embeddings",
            headers=self._headers(),
            json={"model": self.model_name, "input": texts},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]


def _find_balanced_json_object(text: str) -> str | None:
    """Scans for the first top-level {...} object, respecting string literals so braces
    inside quoted strings don't throw off the balance count. More robust than a greedy
    regex against models (e.g. Qwen3) that wrap the real answer in extra prose/braces."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def _extract_json(raw: str) -> dict:
    # Reasoning models (e.g. Qwen3 with thinking enabled) prepend a <think>...</think>
    # block before the actual answer -- strip it first so braces used in the reasoning
    # prose (e.g. the model discussing example JSON) can't be mistaken for the real object.
    raw = _THINK_BLOCK_RE.sub("", raw).strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        candidate = _find_balanced_json_object(raw)
        if candidate is None:
            raise
        return json.loads(candidate)
