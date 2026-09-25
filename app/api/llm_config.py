from __future__ import annotations

import os
from pathlib import Path
from flask import Blueprint, current_app, jsonify, request

from app.llm_gateway import resolve_backend, reset_llm_gateway, is_configured_key, _PROVIDER_CONFIG_KEYS

bp = Blueprint("llm_config", __name__)


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "********"
    return f"{key[:4]}...{key[-4:]}"


def _update_env_file(updates: dict[str, str]) -> None:
    if current_app.config.get("TESTING"):
        return
    parent = Path(current_app.root_path).parent
    targets = [parent / ".env", parent / ".env.docker"]
    for env_path in targets:
        if not env_path.exists():
            continue
        try:
            content = env_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            new_lines = []
            applied_keys = set()
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        new_lines.append(f"{key}={updates[key]}")
                        applied_keys.add(key)
                        continue
                new_lines.append(line)
            for k, v in updates.items():
                if k not in applied_keys:
                    new_lines.append(f"{k}={v}")
            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except Exception as exc:
            current_app.logger.warning(f"Could not write to {env_path.name}: {exc}")


@bp.get("/status")
def get_status():
    backend = resolve_backend(current_app.config)
    config_keys = _PROVIDER_CONFIG_KEYS.get(backend)

    active_model = current_app.config.get(config_keys[2], "") if config_keys else "fake"
    reasoning_model = current_app.config.get(config_keys[3], "") if config_keys and config_keys[3] else None

    return jsonify({
        "status": "ok",
        "resolved_backend": backend,
        "configured_backend": current_app.config.get("LLM_BACKEND", "auto"),
        "active_model": active_model,
        "reasoning_model": reasoning_model,
        "parallel_calls": current_app.config.get("LLM_PARALLEL_CALLS", True),
        "max_concurrent_requests": current_app.config.get("LLM_MAX_CONCURRENT_REQUESTS", 5),
        "keys_configured": {
            "openai": is_configured_key(current_app.config.get("OPENAI_API_KEY")),
            "gemini": is_configured_key(current_app.config.get("GEMINI_API_KEY")),
            "custom": is_configured_key(current_app.config.get("LLM_API_KEY")),
        },
        "masked_keys": {
            "openai": _mask_key(current_app.config.get("OPENAI_API_KEY", "")),
            "gemini": _mask_key(current_app.config.get("GEMINI_API_KEY", "")),
            "custom": _mask_key(current_app.config.get("LLM_API_KEY", "")),
        },
        "models": {
            "openai_model": current_app.config.get("OPENAI_MODEL_NAME", "gpt-4o-mini"),
            "openai_reasoning_model": current_app.config.get("OPENAI_REASONING_MODEL_NAME", "gpt-4o"),
            "gemini_model": current_app.config.get("GEMINI_MODEL_NAME", "gemini-2.0-flash"),
            "gemini_reasoning_model": current_app.config.get("GEMINI_REASONING_MODEL_NAME", "gemini-1.5-pro"),
            "custom_model": current_app.config.get("LLM_MODEL_NAME", "custom-model"),
        },
        "available_backends": list(_PROVIDER_CONFIG_KEYS.keys()) + ["auto", "fake"],
    })


@bp.post("/config")
def update_config():
    data = request.get_json(silent=True) or {}
    env_updates: dict[str, str] = {}

    if "openai_api_key" in data:
        key = str(data["openai_api_key"]).strip()
        current_app.config["OPENAI_API_KEY"] = key
        os.environ["OPENAI_API_KEY"] = key
        env_updates["OPENAI_API_KEY"] = key

    if "gemini_api_key" in data:
        key = str(data["gemini_api_key"]).strip()
        current_app.config["GEMINI_API_KEY"] = key
        os.environ["GEMINI_API_KEY"] = key
        env_updates["GEMINI_API_KEY"] = key

    if "backend" in data:
        backend = str(data["backend"]).strip()
        current_app.config["LLM_BACKEND"] = backend
        os.environ["LLM_BACKEND"] = backend
        env_updates["LLM_BACKEND"] = backend

    if "parallel_calls" in data:
        parallel = bool(data["parallel_calls"])
        current_app.config["LLM_PARALLEL_CALLS"] = parallel
        os.environ["LLM_PARALLEL_CALLS"] = "true" if parallel else "false"
        env_updates["LLM_PARALLEL_CALLS"] = "true" if parallel else "false"

    if env_updates:
        _update_env_file(env_updates)

    reset_llm_gateway()
    return get_status()
