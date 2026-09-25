from flask import current_app

from app.llm_gateway.base import LLMGateway
from app.llm_gateway.client import RealLLMGateway
from app.llm_gateway.fake_client import FakeLLMGateway

_instance: LLMGateway | None = None

# Priority order for LLM_BACKEND=auto: first provider in this list whose API key is
# actually set wins. "real" is the custom-deployed endpoint (LLM_API_KEY) -- kept last so
# a hosted provider is preferred once you've added a key for one, without you having to
# remember to flip LLM_BACKEND yourself.
_AUTO_PRIORITY = ["openai", "gemini", "real"]

# Each resolved backend name -> the current_app.config keys holding its
# (base_url, api_key, model_name, reasoning_model_name).
# Every provider here speaks the same OpenAI chat-completions shape (OpenAI's API natively;
# Gemini via Google's OpenAI-compatibility endpoint), so they all go through the same
# RealLLMGateway class -- just different connection details, not different code.
_PROVIDER_CONFIG_KEYS = {
    "real": ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL_NAME", None),
    "openai": ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL_NAME", "OPENAI_REASONING_MODEL_NAME"),
    "openai_reasoning": ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_REASONING_MODEL_NAME", None),
    "gemini": ("GEMINI_BASE_URL", "GEMINI_API_KEY", "GEMINI_MODEL_NAME", "GEMINI_REASONING_MODEL_NAME"),
    "gemini_reasoning": ("GEMINI_BASE_URL", "GEMINI_API_KEY", "GEMINI_REASONING_MODEL_NAME", None),
}


def reset_llm_gateway() -> None:
    """Clears the cached gateway instance so the next get_llm_gateway() reinitializes."""
    global _instance
    _instance = None


_DUMMY_KEY_PLACEHOLDERS = {
    "test-key-123",
    "placeholder",
    "your-api-key-here",
    "<your key>",
    "<your-api-key>",
    "change-me",
}


def is_configured_key(val: str | None) -> bool:
    if not val or not isinstance(val, str):
        return False
    return bool(val.strip()) and val.strip().lower() not in _DUMMY_KEY_PLACEHOLDERS


def resolve_backend(config) -> str:
    """LLM_BACKEND=auto (the default) picks whichever provider has an API key configured;
    any other value ("fake", "real", "openai", "openai_reasoning", "gemini", "gemini_reasoning")
    pins that one regardless."""
    backend = config.get("LLM_BACKEND", "auto")
    if backend not in ("auto", "reasoning", "auto_reasoning"):
        return backend

    prefer_reasoning = backend in ("reasoning", "auto_reasoning")
    for candidate in _AUTO_PRIORITY:
        api_key_field = _PROVIDER_CONFIG_KEYS[candidate][1]
        if is_configured_key(config.get(api_key_field)):
            if prefer_reasoning and f"{candidate}_reasoning" in _PROVIDER_CONFIG_KEYS:
                return f"{candidate}_reasoning"
            return candidate
    return "fake"



def get_llm_gateway() -> LLMGateway:
    """Returns the process-wide gateway instance, selected by LLM_BACKEND
    ('auto' | 'fake' | 'real' | 'openai' | 'openai_reasoning' | 'gemini' | 'gemini_reasoning').

    Everything downstream (agents) talks to this interface only, so pointing at a real LLM
    -- your custom deployment, OpenAI, or Gemini -- is a config change (see .env.example),
    not a code change.
    """
    global _instance
    backend = resolve_backend(current_app.config)

    config_keys = _PROVIDER_CONFIG_KEYS.get(backend)
    current_key = current_app.config.get(config_keys[1], "") if config_keys else ""
    current_model = current_app.config.get(config_keys[2], "") if config_keys else ""

    # Re-create if backend changed or credentials/model changed dynamically
    if (
        _instance is None
        or getattr(_instance, "_backend_name", None) != backend
        or getattr(_instance, "api_key", None) != current_key
        or getattr(_instance, "model_name", None) != current_model
    ):
        if config_keys:
            base_url_key, api_key_key, model_key, reasoning_key = config_keys
            reasoning_model = current_app.config.get(reasoning_key) if reasoning_key else None
            _instance = RealLLMGateway(
                base_url=current_app.config[base_url_key],
                api_key=current_app.config[api_key_key],
                model_name=current_app.config[model_key],
                reasoning_model_name=reasoning_model,
                embeddings_enabled=current_app.config.get("LLM_EMBEDDINGS_ENABLED", False),
                parallel_calls=current_app.config.get("LLM_PARALLEL_CALLS", True),
                max_concurrent_requests=current_app.config.get("LLM_MAX_CONCURRENT_REQUESTS", 5),
                max_tokens=current_app.config.get("LLM_MAX_TOKENS", 8192),
            )
        else:
            _instance = FakeLLMGateway()
        _instance._backend_name = backend
    return _instance
