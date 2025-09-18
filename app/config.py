import os
from dataclasses import dataclass
from dotenv import load_dotenv


def _load_env_once() -> None:
    # idempotent load
    load_dotenv()


def get_bot_token() -> str:
    _load_env_once()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Create .env with BOT_TOKEN=... or set env variable."
        )
    return token


@dataclass
class UserbotConfig:
    enabled: bool
    api_id: int | None
    api_hash: str | None
    session_string: str | None


def get_userbot_config() -> UserbotConfig:
    _load_env_once()
    enabled = (os.getenv("BYPASS_MODE", "userbot").strip().lower() == "userbot")
    api_id = os.getenv("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    session_string = os.getenv("TG_SESSION_STRING")
    return UserbotConfig(
        enabled=enabled,
        api_id=int(api_id) if (api_id and api_id.isdigit()) else None,
        api_hash=api_hash if api_hash else None,
        session_string=session_string if session_string else None,
    )


def get_bypass_mode() -> str:
    _load_env_once()
    # Only: off | userbot
    mode = os.getenv("BYPASS_MODE", "userbot").strip().lower()
    if mode not in {"off", "userbot"}:
        mode = "userbot"
    return mode


def get_ytdlp_cookies_file() -> str | None:
    _load_env_once()
    path = (os.getenv("YTDLP_COOKIES_FILE") or "").strip()
    if path and os.path.exists(path):
        return path
    return None


def get_ytdlp_cookies_from_browser() -> str | None:
    _load_env_once()
    # Examples: chrome | chromium | firefox | safari (platform dependent)
    val = (os.getenv("YTDLP_COOKIES_FROM_BROWSER") or "").strip()
    return val or None
