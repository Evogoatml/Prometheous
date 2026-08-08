"""
Backend registry — single source of truth for which backends exist.

Adding a 4th backend (Anthropic, Gemini, etc.):
  1. Create llm/backends/anthropic.py with a class inheriting Backend
  2. Import + register it here
  3. Done — no edits to llm/client.py needed

The registry returns live backend instances (re-read on every lookup)
so config changes (e.g. setting OPENAI_API_KEY after startup) are picked
up on the next call without a restart.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List

from llm.backends.base import Backend
from llm.backends.anthropic import AnthropicBackend
from llm.backends.openai import OpenAIBackend
from llm.backends.grok import GrokBackend
from llm.backends.ollama import OllamaBackend
from llm.model_resolver import resolve_backend_model

logger = logging.getLogger(__name__)

# Default ordering if env vars don't specify one. OpenAI is preferred when
# a real key is set; Ollama is the always-available local fallback.
DEFAULT_ORDER = ("openai", "anthropic", "grok", "ollama")


def _cfg_openai_key() -> str:
    try:
        from utils.config import cfg
        return getattr(cfg, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    except Exception:
        return os.getenv("OPENAI_API_KEY", "")


def _cfg_grok_key() -> str:
    try:
        from utils.config import cfg
        return getattr(cfg, "GROK_API_KEY", "") or os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY", "")
    except Exception:
        return os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY", "")


def _cfg_model() -> str:
    for key in ("PROM_LLM_MODEL", "LLM_MODEL"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _cfg_anthropic_key() -> str:
    try:
        from utils.config import cfg
        return getattr(cfg, "ANTHROPIC_API_KEY", "") or os.getenv("ANTHROPIC_API_KEY", "")
    except Exception:
        return os.getenv("ANTHROPIC_API_KEY", "")


def _cfg_timeout() -> int:
    return int(os.getenv("PROM_LLM_TIMEOUT", "30"))


def build_backends() -> Dict[str, Backend]:
    """Return a fresh dict of name->Backend, picking up current config."""
    requested = _cfg_model()
    timeout = _cfg_timeout()
    return {
        "openai": OpenAIBackend(
            api_key=_cfg_openai_key(),
            model=resolve_backend_model("openai", requested),
            timeout=timeout,
        ),
        "anthropic": AnthropicBackend(
            api_key=_cfg_anthropic_key(),
            model=resolve_backend_model("anthropic", requested),
            timeout=timeout,
        ),
        "grok": GrokBackend(
            api_key=_cfg_grok_key(),
            model=resolve_backend_model("grok", requested),
            timeout=timeout,
        ),
        "ollama": OllamaBackend(
            model=resolve_backend_model("ollama", requested),
            timeout=timeout,
        ),
    }


def ordered_names(primary: str = "", fallbacks: str = "") -> List[str]:
    """Resolve env-driven priority into a concrete ordered list."""
    primary = (primary or os.getenv("PROM_LLM_PRIMARY", "")).lower().strip()
    fb_str = fallbacks or os.getenv("PROM_LLM_FALLBACKS", "")
    fb_list = [b.strip().lower() for b in fb_str.split(",") if b.strip()] if fb_str else list(DEFAULT_ORDER)
    out: List[str] = []
    if primary:
        out.append(primary)
    for b in fb_list:
        if b not in out:
            out.append(b)
    # Always include the default tail so a mistyped backend doesn't dead-end
    for b in DEFAULT_ORDER:
        if b not in out:
            out.append(b)
    return out
