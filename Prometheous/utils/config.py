"""
Central configuration for Prometheous.

Single source of truth for paths, env vars, and tunables.
The LLM gateway and the core system both read from here.
"""
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
VAULT_DIR = DATA_DIR / "vault"
LOG_DIR = ROOT / ".logs"
SQLITE_PATH = DATA_DIR / "brain.db"
STATE_PATH = DATA_DIR / "state.json"

for d in (DATA_DIR, VAULT_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)


class Config:
    # LLM
    LLM_MODEL = os.getenv("PROM_LLM_MODEL", "llama3.2")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    LLM_TIMEOUT = int(os.getenv("PROM_LLM_TIMEOUT", "60"))

    # Telegram (optional)
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_ALLOWED_CHAT_IDS = [
        int(x) for x in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()
    ]

    # Swarm
    SWARM_MAX_PARALLEL = int(os.getenv("PROM_SWARM_MAX_PARALLEL", "4"))
    SWARM_TASK_TIMEOUT = int(os.getenv("PROM_SWARM_TASK_TIMEOUT", "120"))

    # Memory
    CONVERSATION_HISTORY_LIMIT = 20
    SQLITE_PATH = str(SQLITE_PATH)
    STATE_PATH = str(STATE_PATH)


cfg = Config()
