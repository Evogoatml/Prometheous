"""
brain/loader.py
Compatibility shim. The full featured hot-reload loader lives in
brain/cognitive_loader.py (preferred).

Re-exports the real CognitiveLoader so old imports keep working.
"""
from .cognitive_loader import (
    CognitiveLoader,
    CognitiveConfig,
    SuperPromptConfig,
    ContextFieldConfig,
)

# For direct `from brain.loader import CognitiveLoader`
__all__ = ["CognitiveLoader", "CognitiveConfig", "SuperPromptConfig", "ContextFieldConfig"]