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


def _get_int_env(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    _load_env_once()
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def get_probe_concurrency() -> int:
    """Maximum number of parallel metadata probes (yt-dlp extract_info)."""
    return _get_int_env("PROBE_CONCURRENCY", default=4, min_value=1)


def get_download_concurrency() -> int:
    """Maximum number of parallel downloads executed by yt-dlp."""
    return _get_int_env("DOWNLOAD_CONCURRENCY", default=6, min_value=1)


def get_metadata_cache_ttl() -> int:
    """How long (seconds) to keep metadata from yt-dlp to avoid repeated probing."""
    return _get_int_env("METADATA_CACHE_TTL", default=300, min_value=0)


def get_metadata_cache_size() -> int:
    """Cap metadata cache to prevent unbounded growth under high load."""
    return _get_int_env("METADATA_CACHE_SIZE", default=128, min_value=1)


def get_thread_pool_workers() -> int:
    default = max(8, get_probe_concurrency() + get_download_concurrency())
    return _get_int_env("DL_THREAD_WORKERS", default=default, min_value=2, max_value=128)


def get_ytdlp_fragment_concurrency() -> int:
    return _get_int_env("YTDLP_CONCURRENT_FRAGMENTS", default=8, min_value=1, max_value=32)


def get_max_active_jobs() -> int:
    """Hard cap on simultaneously scheduled downloads; 0 disables the limit."""
    return _get_int_env("MAX_ACTIVE_JOBS", default=12, min_value=0, max_value=128)


def get_max_chat_jobs() -> int:
    """Limit queued downloads per chat to prevent a single chat from hogging the queue."""
    return _get_int_env("MAX_CHAT_JOBS", default=3, min_value=0, max_value=32)


def get_user_cooldown_seconds() -> int:
    """Delay between successive download requests from the same user."""
    return _get_int_env("USER_REQUEST_COOLDOWN", default=5, min_value=0, max_value=600)
