from __future__ import annotations

import asyncio
from typing import Optional, Callable, Awaitable
import json
import os
import shlex

from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError
import logging

# Support running both as a module and as a script
try:
    from .config import get_userbot_config  # type: ignore
except Exception:  # pragma: no cover
    from config import get_userbot_config


_client: Optional[Client] = None
_lock = asyncio.Lock()
_dialog_lock = asyncio.Lock()
_warm_dialogs: set[str] = set()


async def get_user_client() -> Optional[Client]:
    global _client
    cfg = get_userbot_config()
    if not (cfg.enabled and cfg.api_id and cfg.api_hash and cfg.session_string):
        return None
    async with _lock:
        if _client is None:
            def _get_workdir() -> str:
                try:
                    base = os.path.join(os.getcwd(), ".userbot")
                    os.makedirs(base, exist_ok=True)
                    return base
                except Exception:
                    import tempfile
                    base = os.path.join(tempfile.gettempdir(), "userbot_pyrogram")
                    os.makedirs(base, exist_ok=True)
                    return base
            _client = Client(
                name="userbot",
                api_id=cfg.api_id,
                api_hash=cfg.api_hash,
                session_string=cfg.session_string,
                workdir=_get_workdir(),
                in_memory=True,
            )
            await _client.start()
        return _client


def _progress_printer_factory(prefix: str = ""):
    state = {"last": -1}

    def cb(current: int, total: int) -> None:
        if total <= 0:
            return
        pct = int(current * 100 / total)
        if pct != state["last"] and pct % 5 == 0:
            state["last"] = pct
            print(f"{prefix} {pct}% ({current}/{total})")

    return cb


async def _probe_video_meta(path: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Return (duration_sec, width, height) using ffprobe if available."""
    if not os.path.exists(path):
        return None, None, None
    cmd = (
        "ffprobe -v error -select_streams v:0 "
        "-show_entries stream=width,height:format=duration -of json "
        f"{shlex.quote(path)}"
    )
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0 or not out:
            return None, None, None
        data = json.loads(out.decode("utf-8", errors="ignore"))
        duration = data.get("format", {}).get("duration")
        if isinstance(duration, str):
            try:
                duration_i = int(float(duration))
            except Exception:
                duration_i = None
        else:
            duration_i = None
        streams = data.get("streams") or []
        if streams:
            w = streams[0].get("width")
            h = streams[0].get("height")
            return duration_i, int(w) if w else None, int(h) if h else None
        return duration_i, None, None
    except Exception:
        return None, None, None


def _suggest_file_name(path: str, fallback: str = "video.mp4") -> str:
    name = os.path.basename(path) or fallback
    safe = "".join(ch if ch.isalnum() or ch in " .-_()[]" else "_" for ch in name)
    return safe or fallback


async def send_file_via_user(
    chat_id: int,
    filepath: str,
    caption: str | None,
    kind: str,
    notify: Optional[Callable[[int], Awaitable[None]]] = None,
) -> bool:
    client = await get_user_client()
    if client is None:
        return False
    progress = _progress_printer_factory("Userbot upload:")
    # Wrap to also notify chat about progress
    if notify is not None:
        import time
        loop = asyncio.get_running_loop()
        last_pct = -1
        last_ts = 0.0

        def progress_wrap(current: int, total: int) -> None:
            nonlocal last_pct, last_ts
            if total <= 0:
                return
            pct = int(current * 100 / total)
            if pct == last_pct:
                return
            now = time.time()
            if pct - last_pct >= 3 or (now - last_ts) >= 1.5:
                last_pct = pct
                last_ts = now
                try:
                    loop.call_soon_threadsafe(asyncio.create_task, notify(pct))
                except Exception:
                    pass
            # still print to console each 5%
            progress(current, total)

        progress_cb = progress_wrap
    else:
        progress_cb = progress
    file_name = _suggest_file_name(filepath)
    try:
        if kind == "image":
            await client.send_photo(
                chat_id, filepath, caption=caption or "", file_name=file_name, progress=progress_cb
            )
            return True
        if kind == "audio":
            await client.send_audio(
                chat_id, filepath, caption=caption or "", file_name=file_name, progress=progress_cb
            )
            return True
        if kind == "video":
            dur, w, h = await _probe_video_meta(filepath)
            try:
                await client.send_video(
                    chat_id,
                    filepath,
                    caption=caption or "",
                    file_name=file_name,
                    duration=dur or 0,
                    width=w or 0,
                    height=h or 0,
                    supports_streaming=True,
                    progress=progress_cb,
                )
                return True
            except RPCError:
                await client.send_document(
                    chat_id, filepath, caption=caption or "", file_name=file_name, progress=progress_cb
                )
                return True
        await client.send_document(
            chat_id, filepath, caption=caption or "", file_name=file_name, progress=progress_cb
        )
        return True
    except FloodWait as e:
        logging.warning("Userbot FloodWait: %s", e)
        await asyncio.sleep(int(getattr(e, "value", 5)))
        return await send_file_via_user(chat_id, filepath, caption, kind)
    except Exception as e:
        logging.exception("Userbot send_file_via_user failed: %s", e)
        return False


async def send_file_to_bot(
    bot_username: str,
    filepath: str,
    caption: str | None,
    kind: str,
    notify: Optional[Callable[[int], Awaitable[None]]] = None,
) -> bool:
    """Отправить файл в личные сообщения боту (@username) через пользовательский аккаунт.
    Требуется, чтобы вы заранее нажали Start у бота со своего user-аккаунта.
    """
    client = await get_user_client()
    if client is None:
        return False
    to = bot_username if bot_username.startswith("@") else f"@{bot_username}"
    progress = _progress_printer_factory("Userbot→Bot upload:")
    if notify is not None:
        import time
        loop = asyncio.get_running_loop()
        last_pct = -1
        last_ts = 0.0

        def progress_wrap(current: int, total: int) -> None:
            nonlocal last_pct, last_ts
            if total <= 0:
                return
            pct = int(current * 100 / total)
            if pct == last_pct:
                return
            now = time.time()
            if pct - last_pct >= 3 or (now - last_ts) >= 1.5:
                last_pct = pct
                last_ts = now
                try:
                    loop.call_soon_threadsafe(asyncio.create_task, notify(pct))
                except Exception:
                    pass
            progress(current, total)

        progress_cb = progress_wrap
    else:
        progress_cb = progress
    file_name = _suggest_file_name(filepath)
    async def _ensure_dialog() -> None:
        key = to.lower().lstrip("@")
        if not key:
            return
        async with _dialog_lock:
            if key in _warm_dialogs:
                return
            try:
                await client.send_message(to, "/start")
            except Exception:
                return
            _warm_dialogs.add(key)

    try:
        await _ensure_dialog()
        if kind == "image":
            await client.send_photo(to, filepath, caption=caption or "", file_name=file_name, progress=progress_cb)
            return True
        if kind == "audio":
            await client.send_audio(to, filepath, caption=caption or "", file_name=file_name, progress=progress_cb)
            return True
        if kind == "video":
            dur, w, h = await _probe_video_meta(filepath)
            try:
                await client.send_video(
                    to,
                    filepath,
                    caption=caption or "",
                    file_name=file_name,
                    duration=dur or 0,
                    width=w or 0,
                    height=h or 0,
                    supports_streaming=True,
                    progress=progress_cb,
                )
                return True
            except RPCError:
                await client.send_document(to, filepath, caption=caption or "", file_name=file_name, progress=progress_cb)
                return True
        await client.send_document(to, filepath, caption=caption or "", file_name=file_name, progress=progress_cb)
        return True
    except FloodWait as e:
        logging.warning("Userbot→Bot FloodWait: %s", e)
        await asyncio.sleep(int(getattr(e, "value", 5)))
        return await send_file_to_bot(bot_username, filepath, caption, kind)
    except Exception as e:
        logging.exception("Userbot send_file_to_bot failed: %s", e)
        return False
