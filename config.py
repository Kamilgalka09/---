"""Конфигурация из .env (без внешних зависимостей)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL", "radarrussiia")
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "12"))
TTL_MINUTES = int(os.environ.get("TTL_MINUTES", "180"))
SEND_AS_DOCUMENT = os.environ.get("SEND_AS_DOCUMENT", "0") == "1"


def _data_dir() -> Path:
    """Постоянное хранилище: на сервере Amvera это /data, локально — ./data."""
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    if Path("/data").is_dir():
        return Path("/data")
    return ROOT / "data"


DATA_DIR = _data_dir()
STATE_PATH = Path(os.environ.get("STATE_PATH") or DATA_DIR / "state.json")
# локально пишем в папку проекта, на хостинге — в постоянное хранилище DATA_DIR (/data)
_local = DATA_DIR == ROOT / "data"
OUT_PATH = Path(os.environ.get("OUT_PATH")
                or (ROOT / "out" / "map.png" if _local else DATA_DIR / "map.png"))
LOG_PATH = Path(os.environ.get("LOG_PATH")
                or (ROOT / "logs" / "bot.log" if _local else DATA_DIR / "bot.log"))
