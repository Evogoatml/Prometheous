"""
Central configuration for Prometheous.

Single source of truth for paths, env vars, and tunables.
The LLM gateway and the core system both read from here.
"""
import os
from pathlib import Path

# Load .env if present (the API keys/tokens are stored here)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, rely on real environment variables


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
VAULT_DIR = DATA_DIR / "vault"
LEARNING_DIR = DATA_DIR / "learning"
LOG_DIR = ROOT / ".logs"
SQLITE_PATH = DATA_DIR / "brain.db"
STATE_PATH = DATA_DIR / "state.json"
BASE_DIR = ROOT

for d in (DATA_DIR, VAULT_DIR, LEARNING_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)


class Config:
    # Paths (on instance so `from utils.config import cfg; cfg.VAULT_DIR` works)
    BASE_DIR: Path = BASE_DIR
    ROOT: Path = ROOT
    DATA_DIR: Path = DATA_DIR
    VAULT_DIR: Path = VAULT_DIR
    LEARNING_DIR: Path = LEARNING_DIR
    LOG_DIR: Path = LOG_DIR
    SQLITE_PATH: str = str(SQLITE_PATH)
    STATE_PATH: str = str(STATE_PATH)

    # LLM
    LLM_MODEL = os.getenv("PROM_LLM_MODEL", "llama3.2")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    GROK_API_KEY = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY", "")
    LLM_TIMEOUT = int(os.getenv("PROM_LLM_TIMEOUT", "60"))

    # Telegram (optional)
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    TELEGRAM_ALLOWED_CHAT_IDS = [
        int(x) for x in os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()
    ]

    # OS access
    # When true, shell.run runs ANY command anywhere on the OS (no allowlist,
    # no project-root restriction). Defaults to the safe sandbox.
    FULL_OS_ACCESS = os.getenv("PROM_FULL_OS_ACCESS", "").lower() in ("1", "true", "yes")

    # Scanning defaults (single source of truth for scan ports/timeouts)
    SCAN_PORTS: tuple = tuple(
        int(x) for x in os.getenv(
            "PROM_SCAN_PORTS", "22,80,443,8080,3389,5900,3306,5432,6379,27017,8443"
        ).split(",") if x.strip()
    )
    SCAN_TIMEOUT = int(os.getenv("PROM_SCAN_TIMEOUT", "60"))
    SHELL_TIMEOUT = int(os.getenv("PROM_SHELL_TIMEOUT", "60"))

    # Ollama
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

    # LLM output budgets
    LLM_MAX_TOKENS_CHAT = int(os.getenv("PROM_LLM_MAX_TOKENS_CHAT", "700"))
    LLM_MAX_TOKENS_TASK = int(os.getenv("PROM_LLM_MAX_TOKENS_TASK", "500"))

    # Swarm / mission fleets
    SWARM_MAX_PARALLEL = int(os.getenv("PROM_SWARM_MAX_PARALLEL", "16"))
    SWARM_TASK_TIMEOUT = int(os.getenv("PROM_SWARM_TASK_TIMEOUT", "120"))
    # Max agents a single mission may code+deploy+run (default 100)
    MISSION_MAX_AGENTS = int(os.getenv("PROM_MISSION_MAX_AGENTS", "100"))

    # Memory
    CONVERSATION_HISTORY_LIMIT = 20


cfg = Config()
