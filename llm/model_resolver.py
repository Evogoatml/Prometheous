"""Provider-aware model resolution for Prometheous LLM backends."""
from __future__ import annotations

import os

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-20250514",
    "grok": "grok-2",
    "ollama": "llama3.2",
}

_PREFIXES = {
    "openai": ("gpt", "o1", "o3", "o4", "chatgpt"),
    "anthropic": ("claude",),
    "grok": ("grok",),
    "ollama": (
        "llama",
        "mistral",
        "mixtral",
        "qwen",
        "phi",
        "gemma",
        "deepseek",
        "codellama",
        "command-r",
    ),
}


def requested_model(preferred: str = "") -> str:
    """Return the user-requested shared model, if any."""
    model = (preferred or "").strip()
    if model:
        return model
    for key in ("PROM_LLM_MODEL", "LLM_MODEL"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def resolve_backend_model(provider: str, preferred: str = "") -> str:
    """Return a provider-compatible model with a sane fallback."""
    provider = (provider or "").strip().lower()
    if provider not in DEFAULT_MODELS:
        return requested_model(preferred)

    if provider == "ollama":
        direct = os.getenv("OLLAMA_MODEL", "").strip()
        if direct:
            return direct

    model = requested_model(preferred)
    if _is_compatible(provider, model):
        return model
    return DEFAULT_MODELS[provider]


def _is_compatible(provider: str, model: str) -> bool:
    if not model:
        return False
    norm = model.strip().lower()
    if not norm:
        return False
    prefixes = _PREFIXES.get(provider, ())
    if provider == "openai":
        return not any(norm.startswith(prefix) for name, values in _PREFIXES.items() if name != "openai" for prefix in values)
    return any(norm.startswith(prefix) for prefix in prefixes)
