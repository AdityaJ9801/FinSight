"""Small convention for embedding structured context inside an LLM prompt as a tagged
JSON blob, and reading it back out. Agents use `embed_json` when building prompts; the
fake gateway uses `extract_json` to recover the same data without truly "understanding"
the prompt, so its canned responses can still be grounded in the real input.
"""
from __future__ import annotations

import json
import re


def embed_json(tag: str, obj) -> str:
    return f"{tag}:{json.dumps(obj)}"


def extract_json(tag: str, text: str):
    match = re.search(rf"{re.escape(tag)}:(\[.*?\]|\{{.*?\}})\s*(?:\n|$)", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def all_message_text(messages: list[dict]) -> str:
    return "\n".join(m.get("content", "") for m in messages)


def last_user_text(messages: list[dict]) -> str:
    """Content of the last user-role message only. Keyword-heuristic dispatch (routing,
    classification) must use this, not all_message_text -- system prompts describe every
    possible route/category in prose (e.g. QA_ROUTER's own text contains the word "says"),
    so scanning the whole concatenated text would match on the prompt's own wording
    regardless of what the user actually asked."""
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content", "")
    return ""
