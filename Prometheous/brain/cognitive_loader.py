import os
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Callable
from pydantic import BaseModel

# yaml imported lazily in load() so the system can start even if not installed yet
yaml = None

# ------------------ Pydantic Models for Validation ------------------
class SuperPromptConfig(BaseModel):
    base_metadata: Dict[str, str]
    objective_placeholder: str
    template: str

    def render(self, task: str, objective: Optional[str] = None) -> str:
        metadata = self.base_metadata.copy()
        metadata["objective"] = objective if objective else self.objective_placeholder
        return self.template.format(task=task, **metadata)

class ContextFieldConfig(BaseModel):
    description: Optional[str] = None
    constraints: List[str]
    thinking_style: Optional[str] = None

class CognitiveConfig(BaseModel):
    version: str
    description: str
    superprompt: SuperPromptConfig
    context_fields: Dict[str, ContextFieldConfig]


# ------------------ Singleton Loader with Hot-Reload ------------------
class CognitiveLoader:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._config: Optional[CognitiveConfig] = None
        self._config_path: Optional[Path] = None
        self._last_mtime: float = 0.0
        self._callbacks: List[Callable] = []
        self._stop_event = threading.Event()
        self._watcher_thread: Optional[threading.Thread] = None

    def load(self, config_path: str = "config/cognitive_config.yaml") -> "CognitiveLoader":
        global yaml
        if yaml is None:
            try:
                import yaml as _yaml
                yaml = _yaml
            except ImportError:
                yaml = False

        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Cognitive config not found: {config_path}")

        self._config_path = path
        self._last_mtime = path.stat().st_mtime

        with open(path, 'r') as f:
            if yaml:
                raw_data = yaml.safe_load(f)
            else:
                import json
                raw_data = json.load(f)  # fallback unlikely
        self._config = CognitiveConfig(**raw_data)
        print(f"[CognitiveLoader] Config loaded successfully from {path}")
        return self

    def _reload_if_changed(self):
        if not self._config_path:
            return
        try:
            current_mtime = self._config_path.stat().st_mtime
            if current_mtime > self._last_mtime:
                print(f"[CognitiveLoader] Detected change in {self._config_path}. Reloading...")
                self.load(str(self._config_path))
                for callback in self._callbacks:
                    try:
                        callback(self._config)
                    except Exception as e:
                        print(f"[CognitiveLoader] Error in callback: {e}")
        except FileNotFoundError:
            print(f"[CognitiveLoader] Warning: Config file {self._config_path} was deleted or moved.")

    def _watch_loop(self, poll_interval: float = 2.0):
        while not self._stop_event.is_set():
            self._reload_if_changed()
            time.sleep(poll_interval)
        print("[CognitiveLoader] Watcher thread stopped.")

    def start_watching(self, poll_interval: float = 2.0):
        if self._watcher_thread and self._watcher_thread.is_alive():
            print("[CognitiveLoader] Watcher already running.")
            return
        self._stop_event.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_loop, 
            args=(poll_interval,), 
            daemon=True,
            name="CognitiveWatcher"
        )
        self._watcher_thread.start()
        print(f"[CognitiveLoader] Hot-reload watcher started (polling every {poll_interval}s).")

    def stop_watching(self):
        if self._watcher_thread and self._watcher_thread.is_alive():
            self._stop_event.set()
            self._watcher_thread.join(timeout=1.0)
            print("[CognitiveLoader] Watcher stopped.")

    def register_callback(self, callback: Callable[[CognitiveConfig], None]):
        if callback not in self._callbacks:
            self._callbacks.append(callback)
            print(f"[CognitiveLoader] Callback registered: {callback.__name__}")

    def get_superprompt(self, task: str, objective: Optional[str] = None) -> str:
        if not self._config:
            raise RuntimeError("Config not loaded. Call .load() first.")
        return self._config.superprompt.render(task, objective)

    def get_context_field(self, role: str) -> Optional[ContextFieldConfig]:
        if not self._config:
            raise RuntimeError("Config not loaded.")
        return self._config.context_fields.get(role)

    def get_constraints_string(self, role: str) -> str:
        field = self.get_context_field(role)
        if not field:
            return ""
        return "\n".join([f"- {c}" for c in field.constraints])

    def get_all_roles(self) -> List[str]:
        if not self._config:
            return []
        return list(self._config.context_fields.keys())

    def get_config(self) -> Optional[CognitiveConfig]:
        return self._config
