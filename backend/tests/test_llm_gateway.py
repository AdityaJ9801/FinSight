import pytest
from pydantic import BaseModel

from app.agents import schemas as sch
from app.llm_gateway import resolve_backend
from app.llm_gateway.client import RealLLMGateway, _extract_json
from app.llm_gateway.fake_client import FakeLLMGateway
from app.llm_gateway.base import LLMValidationError


class Dummy(BaseModel):
    name: str
    count: int


def test_extract_json_handles_markdown_fences():
    raw = '```json\n{"name": "a", "count": 3}\n```'
    assert _extract_json(raw) == {"name": "a", "count": 3}


def test_extract_json_extracts_embedded_object_from_prose():
    raw = 'Sure, here you go: {"name": "a", "count": 3} -- hope that helps!'
    assert _extract_json(raw) == {"name": "a", "count": 3}


def test_real_gateway_retries_once_on_invalid_json(monkeypatch):
    gateway = RealLLMGateway(base_url="http://x", api_key="k", model_name="m")
    responses = iter(['not json at all', '{"name": "a", "count": 3}'])
    monkeypatch.setattr(gateway, "_chat", lambda messages, temperature=0.2: next(responses))

    result = gateway.complete([{"role": "user", "content": "hi"}], schema=Dummy, max_retries=1)
    assert result == Dummy(name="a", count=3)


def test_real_gateway_raises_after_exhausting_retries(monkeypatch):
    gateway = RealLLMGateway(base_url="http://x", api_key="k", model_name="m")
    monkeypatch.setattr(gateway, "_chat", lambda messages, temperature=0.2: "still not json")

    with pytest.raises(LLMValidationError):
        gateway.complete([{"role": "user", "content": "hi"}], schema=Dummy, max_retries=1)


def test_fake_gateway_classifies_bank_statement():
    gateway = FakeLLMGateway()
    result = gateway.complete(
        [{"role": "user", "content": "Date Narration Debit Credit Balance"}],
        schema=sch.ClassificationResult,
    )
    assert result.doc_type == "bank_statement"


def test_fake_gateway_generic_fallback_for_unknown_schema():
    gateway = FakeLLMGateway()
    result = gateway.complete([{"role": "user", "content": "anything"}], schema=Dummy)
    assert isinstance(result, Dummy)


def test_parallel_calls_false_forces_single_concurrency_regardless_of_max():
    gateway = RealLLMGateway(base_url="http://x", api_key="k", model_name="m",
                              parallel_calls=False, max_concurrent_requests=5)
    assert gateway._semaphore._value == 1


def test_parallel_calls_true_uses_max_concurrent_requests():
    gateway = RealLLMGateway(base_url="http://x", api_key="k", model_name="m",
                              parallel_calls=True, max_concurrent_requests=5)
    assert gateway._semaphore._value == 5


def _keys(openai="", gemini="", custom=""):
    return {"LLM_BACKEND": "auto", "OPENAI_API_KEY": openai, "GEMINI_API_KEY": gemini, "LLM_API_KEY": custom}


def test_resolve_backend_falls_back_to_fake_with_no_keys():
    assert resolve_backend(_keys()) == "fake"


def test_resolve_backend_prefers_openai_over_gemini_and_custom():
    assert resolve_backend(_keys(openai="k1", gemini="k2", custom="k3")) == "openai"


def test_resolve_backend_prefers_gemini_over_custom_when_no_openai_key():
    assert resolve_backend(_keys(gemini="k2", custom="k3")) == "gemini"


def test_resolve_backend_falls_back_to_custom_when_only_that_key_is_set():
    assert resolve_backend(_keys(custom="k3")) == "real"


def test_resolve_backend_explicit_value_overrides_auto_detection():
    config = _keys(openai="k1")
    config["LLM_BACKEND"] = "gemini"
    assert resolve_backend(config) == "gemini"


def test_fake_gateway_low_confidence_for_unrecognized_label():
    """An unrecognized row label should map to a low-confidence guess, which is what
    triggers the human review queue in the real pipeline (see mapper.py REVIEW_THRESHOLD)."""
    from app.llm_gateway.prompt_utils import embed_json

    gateway = FakeLLMGateway()
    prompt = [{"role": "user", "content": embed_json("LABELS_JSON", ["Some Totally Unknown Line Item"])}]
    result = gateway.complete(prompt, schema=sch.MappingSet)
    assert result.mappings[0].confidence < 0.85


def test_real_gateway_tier_reasoning_uses_reasoning_model(monkeypatch):
    gateway = RealLLMGateway(
        base_url="http://x",
        api_key="k",
        model_name="gpt-4o-mini",
        reasoning_model_name="gpt-4o",
    )
    captured = {}

    def mock_chat(messages, temperature=0.2, model=None):
        captured["model"] = model
        return '{"name": "test", "count": 10}'

    monkeypatch.setattr(gateway, "_chat", mock_chat)

    # default tier uses standard model
    gateway.complete([{"role": "user", "content": "hi"}], schema=Dummy, tier="default")
    assert captured["model"] == "gpt-4o-mini"

    # reasoning tier uses reasoning model
    gateway.complete([{"role": "user", "content": "hi"}], schema=Dummy, tier="reasoning")
    assert captured["model"] == "gpt-4o"

    # advanced tier also uses reasoning model
    gateway.complete([{"role": "user", "content": "hi"}], schema=Dummy, tier="advanced")
    assert captured["model"] == "gpt-4o"


def test_resolve_backend_reasoning_auto():
    config = _keys(openai="k1", gemini="k2")
    config["LLM_BACKEND"] = "reasoning"
    assert resolve_backend(config) == "openai_reasoning"

    config2 = _keys(gemini="k2")
    config2["LLM_BACKEND"] = "reasoning"
    assert resolve_backend(config2) == "gemini_reasoning"


def test_resolve_backend_supports_explicit_reasoning_backends():
    config = _keys(openai="k1")
    config["LLM_BACKEND"] = "gemini_reasoning"
    assert resolve_backend(config) == "gemini_reasoning"

    config["LLM_BACKEND"] = "openai_reasoning"
    assert resolve_backend(config) == "openai_reasoning"


def test_llm_api_endpoints(client):
    status_resp = client.get("/api/llm/status")
    assert status_resp.status_code == 200
    data = status_resp.json
    assert data["status"] == "ok"
    assert "active_model" in data
    assert "keys_configured" in data
    assert "parallel_calls" in data
    assert data["parallel_calls"] is True

    update_resp = client.post("/api/llm/config", json={
        "openai_api_key": "sk-live-abc123xyz789",
        "backend": "openai",
        "parallel_calls": True,
    })
    assert update_resp.status_code == 200
    update_data = update_resp.json
    assert update_data["configured_backend"] == "openai"
    assert update_data["keys_configured"]["openai"] is True

