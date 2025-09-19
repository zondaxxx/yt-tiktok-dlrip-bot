import time
import secrets
from typing import Any, Dict, Optional


_STORE: Dict[str, Dict[str, Any]] = {}
_TTL_SECONDS = 60 * 30  # 30 минут

# Simple in-memory user preferences (language)
_USER_LANG: Dict[int, str] = {}
_USER_LAST_REQ: Dict[int, float] = {}


def _cleanup() -> None:
    now = time.time()
    to_del = [k for k, v in _STORE.items() if (now - v.get("ts", 0)) > _TTL_SECONDS]
    for k in to_del:
        _STORE.pop(k, None)


def put_payload(payload: Dict[str, Any]) -> str:
    _cleanup()
    token = secrets.token_urlsafe(8)
    payload = dict(payload)
    payload["ts"] = time.time()
    _STORE[token] = payload
    return token


def get_payload(token: str) -> Optional[Dict[str, Any]]:
    _cleanup()
    return _STORE.get(token)


def set_user_lang(user_id: int, lang: str) -> None:
    if lang not in {"ru", "en"}:
        return
    _USER_LANG[user_id] = lang


def get_user_lang(user_id: int) -> str:
    return _USER_LANG.get(user_id, "ru")


def set_user_last_request(user_id: int, ts: float) -> None:
    _USER_LAST_REQ[user_id] = ts


def get_user_last_request(user_id: int) -> float | None:
    return _USER_LAST_REQ.get(user_id)
