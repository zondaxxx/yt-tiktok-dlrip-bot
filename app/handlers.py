import asyncio
import os
import logging
import shutil
from pathlib import Path
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from html import escape as html_escape
from typing import Awaitable, Callable

from aiogram import Router, F
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.types import LinkPreviewOptions

# Support running both as a module and as a script
try:
    from .downloader import (
        download_media,
        probe_media_options,
        download_media_selected,
        TELEGRAM_UPLOAD_LIMIT_MB,
        FormatOption,
        BasicInfo,
        fetch_media_metadata,
        DownloadResult,
    )  # type: ignore
    from .config import get_bypass_mode  # type: ignore
    from .state import put_payload, get_payload, get_user_lang, set_user_lang  # type: ignore
    from .user_sender import send_file_via_user, send_file_to_bot  # type: ignore
    from .ui import human_size, human_time, progress_bar  # type: ignore
    from .i18n import t  # type: ignore
except Exception:  # pragma: no cover
    from downloader import (
        download_media,
        probe_media_options,
        download_media_selected,
        TELEGRAM_UPLOAD_LIMIT_MB,
        FormatOption,
        BasicInfo,
        fetch_media_metadata,
        DownloadResult,
    )
    from config import get_bypass_mode
    from state import put_payload, get_payload, get_user_lang, set_user_lang
    from user_sender import send_file_via_user, send_file_to_bot
    from ui import human_size, human_time, progress_bar
    from i18n import t


router = Router()

URL_RE = re.compile(r"(https?://\S+)")
UB_MARK_RE = re.compile(r"\bUB\|([A-Za-z0-9_\-]+)\b")


_ACTIVE_DOWNLOADS: set[asyncio.Task] = set()


@dataclass
class DownloadListener:
    origin_message: Message
    wait_msg: Message
    lang: str
    edit_progress: Callable[[str, str, float | None], Awaitable[None]]


@dataclass
class DownloadJob:
    key: tuple[int, str, str, str]
    url: str
    kind: str
    quality: str
    listeners: list[DownloadListener]
    task: asyncio.Task | None = None


_ACTIVE_JOBS: dict[tuple[int, str, str, str], DownloadJob] = {}


@dataclass
class DeliveryCacheEntry:
    mode: str  # 'bot_file' | 'direct_link'
    kind: str | None
    file_id: str | None
    caption: str | None
    direct_url: str | None
    expires_at: float


_DELIVERY_CACHE: dict[tuple[int, str, str, str], DeliveryCacheEntry] = {}
_CACHE_TTL_SECONDS = 15 * 60


def _options_to_payload(options: list[FormatOption]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for opt in options:
        payload.append(
            {
                "kind": opt.kind,
                "quality": opt.quality,
                "est_size": int(opt.est_size) if isinstance(opt.est_size, (int, float)) else None,
                "label": opt.label,
                "height": int(opt.height) if isinstance(opt.height, (int, float)) else None,
                "bitrate_k": float(opt.bitrate_k) if isinstance(opt.bitrate_k, (int, float)) else None,
                "ext": opt.ext,
            }
        )
    return payload


def _options_from_payload(raw: object) -> list[FormatOption]:
    if not isinstance(raw, list):
        return []
    options: list[FormatOption] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        est_size = item.get("est_size")
        if isinstance(est_size, float):
            est_size = int(est_size)
        elif not isinstance(est_size, int):
            est_size = None
        height = item.get("height")
        if isinstance(height, float):
            height = int(height)
        elif not isinstance(height, int):
            height = None
        bitrate = item.get("bitrate_k")
        if isinstance(bitrate, str):
            try:
                bitrate = float(bitrate)
            except ValueError:
                bitrate = None
        elif not isinstance(bitrate, (int, float)):
            bitrate = None
        options.append(
            FormatOption(
                kind=str(item.get("kind") or "va"),
                quality=str(item.get("quality") or "best"),
                est_size=est_size,
                label=str(item.get("label") or ""),
                height=height,
                bitrate_k=float(bitrate) if bitrate is not None else None,
                ext=(str(item.get("ext")) if item.get("ext") else None),
            )
        )
    return options


def _ext_priority(ext: str | None) -> int:
    if not ext:
        return 0
    ext = ext.lower()
    if ext == "mp4":
        return 4
    if ext in {"mkv", "mov"}:
        return 3
    if ext in {"webm", "m4a"}:
        return 2
    return 1


def _dedupe_options(options: list[FormatOption]) -> list[FormatOption]:
    unique: dict[tuple[str, str], FormatOption] = {}
    for opt in options:
        key = (opt.kind, str(opt.quality))
        best = unique.get(key)
        if not best:
            unique[key] = opt
            continue
        # Prefer option with known size, smaller size, or better extension.
        best_size = best.est_size or 0
        opt_size = opt.est_size or 0
        if best.est_size is None and opt.est_size is not None:
            unique[key] = opt
            continue
        if opt.est_size is not None and best.est_size is not None and opt_size < best_size:
            unique[key] = opt
            continue
        if opt.est_size == best.est_size and _ext_priority(opt.ext) > _ext_priority(best.ext):
            unique[key] = opt
    return list(unique.values())


def _quality_value(opt: FormatOption) -> int:
    quality = str(opt.quality or "").lower()
    if quality == "best":
        return 10000 + int(opt.height or 0)
    if quality.isdigit():
        return int(quality)
    if opt.height:
        return int(opt.height)
    return 0


def _format_size_localized(nbytes: int | None, lang: str) -> str:
    text = human_size(nbytes or 0)
    if lang == "en":
        return (
            text.replace("Б", "B")
            .replace("К", "K")
            .replace("М", "M")
            .replace("Г", "G")
            .replace("Т", "T")
        )
    return text


def _quality_label(opt: FormatOption, lang: str) -> str:
    if opt.height:
        return f"{int(opt.height)}p"
    quality = str(opt.quality or "").strip()
    if quality.lower() == "best":
        return t(lang, "quality_best_short")
    if quality:
        return quality
    if opt.label:
        return opt.label[:16]
    return t(lang, "quality_unknown")


def _format_option_label(
    opt: FormatOption,
    lang: str,
    *,
    mode: str,
    tag: str | None = None,
) -> str:
    size = _format_size_localized(opt.est_size, lang)
    quality = _quality_label(opt, lang)
    if mode == "recommended" and tag in {"best", "compact", "audio", "video"}:
        base = t(lang, f"opt_{tag}")
        parts: list[str] = []
        if tag != "audio" and quality not in {"", t(lang, "quality_unknown"), t(lang, "quality_best_short")}:
            parts.append(quality)
        if size != "?":
            parts.append(f"~{size}")
        if not parts and tag == "best" and size != "?":
            parts.append(f"~{size}")
        suffix = " · ".join(parts)
        return f"{base} · {suffix}" if suffix else base
    icon = {"va": "🎥", "v": "🎬", "a": "🎵"}.get(opt.kind, "📦")
    parts: list[str] = []
    if quality and quality != t(lang, "quality_unknown"):
        parts.append(quality)
    if opt.ext:
        parts.append(opt.ext.upper())
    if size != "?":
        parts.append(f"~{size}")
    return f"{icon} {' • '.join(parts) if parts else quality or icon}"[:64]


def _pick_recommended_options(options: list[FormatOption]) -> list[tuple[str, FormatOption]]:
    pool = _dedupe_options(options)
    recommended: list[tuple[str, FormatOption]] = []
    va_opts = [o for o in pool if o.kind == "va"]
    v_opts = [o for o in pool if o.kind == "v"]
    a_opts = [o for o in pool if o.kind == "a"]

    used: set[tuple[str, str]] = set()

    if va_opts:
        va_sorted = sorted(va_opts, key=_quality_value, reverse=True)
        best = va_sorted[0]
        recommended.append(("best", best))
        used.add((best.kind, best.quality))
        sized = sorted(va_sorted, key=lambda o: o.est_size or 10**12)
        if sized and sized[0] is not best:
            recommended.append(("compact", sized[0]))
            used.add((sized[0].kind, sized[0].quality))
    elif v_opts:
        v_sorted = sorted(v_opts, key=_quality_value, reverse=True)
        recommended.append(("video", v_sorted[0]))
        used.add((v_sorted[0].kind, v_sorted[0].quality))

    if a_opts:
        a_sorted = sorted(a_opts, key=_quality_value, reverse=True)
        audio_pick = a_sorted[0]
        if (audio_pick.kind, audio_pick.quality) not in used:
            recommended.append(("audio", audio_pick))
            used.add((audio_pick.kind, audio_pick.quality))

    if len(recommended) < 2 and v_opts:
        v_sorted = sorted(v_opts, key=_quality_value, reverse=True)
        pick = v_sorted[0]
        if (pick.kind, pick.quality) not in used:
            recommended.append(("video", pick))
            used.add((pick.kind, pick.quality))

    return recommended[:3]


def _build_recommend_keyboard(
    token: str,
    options: list[FormatOption],
    lang: str,
    url: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for tag, opt in _pick_recommended_options(options):
        label = _format_option_label(opt, lang, mode="recommended", tag=tag)
        rows.append(
            [
                InlineKeyboardButton(
                    text=label[:64],
                    callback_data=f"fmt|{token}|{opt.kind}|{opt.quality}",
                )
            ]
        )

    if len(_dedupe_options(options)) > len(rows):
        rows.append([
            InlineKeyboardButton(text=t(lang, "menu_more"), callback_data=f"menu|{token}|more")
        ])

    rows.append([InlineKeyboardButton(text=t(lang, "original"), url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_full_keyboard(
    token: str,
    options: list[FormatOption],
    lang: str,
    url: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    grouped = {"va": [], "v": [], "a": []}
    for opt in _dedupe_options(options):
        grouped.setdefault(opt.kind, []).append(opt)

    for kind in ("va", "v", "a"):
        chunk: list[InlineKeyboardButton] = []
        opts = grouped.get(kind) or []
        if not opts:
            continue
        for opt in sorted(opts, key=_quality_value, reverse=True):
            label = _format_option_label(opt, lang, mode="full")
            chunk.append(
                InlineKeyboardButton(
                    text=label[:64],
                    callback_data=f"fmt|{token}|{opt.kind}|{opt.quality}",
                )
            )
            if len(chunk) == 2:
                rows.append(chunk)
                chunk = []
        if chunk:
            rows.append(chunk)

    rows.append([InlineKeyboardButton(text=t(lang, "menu_back"), callback_data=f"menu|{token}|back")])
    rows.append([InlineKeyboardButton(text=t(lang, "original"), url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_menu_text(payload: dict[str, object], lang: str, *, mode: str) -> str:
    title = str(payload.get("title") or "")
    duration = payload.get("duration")
    parts: list[str] = []
    if title:
        parts.append(f"<b>{html_escape(title)}</b>")
    if isinstance(duration, (int, float)) and duration > 0:
        parts.append(t(lang, "meta_duration", value=human_time(duration)))
    if parts:
        parts.append("")
    if mode == "full":
        parts.append(t(lang, "menu_full"))
    else:
        parts.append(t(lang, "menu_recommended"))
    parts.append(t(lang, "menu_hint"))
    return "\n".join(part for part in parts if part)


async def _edit_menu_message(message: Message | None, text: str, kb: InlineKeyboardMarkup) -> None:
    if message is None:
        return
    try:
        if message.photo or (message.caption is not None):
            await message.edit_caption(text, reply_markup=kb)
        else:
            await message.edit_text(
                text,
                reply_markup=kb,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
    except Exception:
        with suppress(Exception):
            await message.edit_reply_markup(reply_markup=kb)


def _make_progress_editor(wait_msg: Message):
    loop = asyncio.get_running_loop()
    state = {"pct": -5.0, "ts": 0.0}

    async def _edit(text: str, status: str, pct: float | None) -> None:
        now = loop.time()
        last_pct = state["pct"]
        last_ts = state["ts"]
        should_update = True
        if status in {"downloading", "uploading"}:
            if pct is None:
                should_update = (now - last_ts) >= 1.0
            else:
                should_update = pct >= 99.0 or (pct - last_pct) >= 2.0 or (now - last_ts) >= 1.0
        elif status == "finished":
            should_update = True
        else:
            should_update = (now - last_ts) >= 1.0
        if not should_update:
            return
        state["ts"] = now
        if pct is not None:
            state["pct"] = pct
        with suppress(Exception):
            await wait_msg.edit_text(text)

    return _edit


def _queue_hint(lang: str) -> str:
    active = len(_ACTIVE_DOWNLOADS)
    if active <= 0:
        return ""
    if lang == "ru":
        return f" · в обработке {active}"
    return f" · {active} in progress"


def _get_cached_delivery(key: tuple[int, str, str, str]) -> DeliveryCacheEntry | None:
    entry = _DELIVERY_CACHE.get(key)
    if not entry:
        return None
    if entry.expires_at <= time.time():
        _DELIVERY_CACHE.pop(key, None)
        return None
    return entry


def _store_file_delivery(
    key: tuple[int, str, str, str],
    kind: str,
    file_id: str,
    caption: str | None,
) -> None:
    _DELIVERY_CACHE[key] = DeliveryCacheEntry(
        mode="bot_file",
        kind=kind,
        file_id=file_id,
        caption=caption,
        direct_url=None,
        expires_at=time.time() + _CACHE_TTL_SECONDS,
    )


def _store_link_delivery(
    key: tuple[int, str, str, str],
    direct_url: str,
    caption: str | None,
) -> None:
    _DELIVERY_CACHE[key] = DeliveryCacheEntry(
        mode="direct_link",
        kind=None,
        file_id=None,
        caption=caption,
        direct_url=direct_url,
        expires_at=time.time() + _CACHE_TTL_SECONDS,
    )


def _track_task(task: asyncio.Task) -> None:
    _ACTIVE_DOWNLOADS.add(task)

    def _cleanup(fut: asyncio.Task) -> None:
        _ACTIVE_DOWNLOADS.discard(fut)
        if fut.cancelled():
            return
        try:
            exc = fut.exception()
        except Exception as err:  # pragma: no cover - defensive
            logging.exception("download task exception read failed: %s", err)
            return
        if exc:
            logging.exception("download task failed", exc_info=exc)

    task.add_done_callback(_cleanup)


async def _send_cached_file(message: Message, kind: str, file_id: str, caption: str | None) -> None:
    caption = caption or None
    if kind == "image":
        await message.answer_photo(file_id, caption=caption)
        return
    if kind == "audio":
        await message.answer_audio(file_id, caption=caption)
        return
    if kind == "video":
        await message.answer_video(file_id, caption=caption)
        return
    await message.answer_document(file_id, caption=caption)


async def _deliver_from_cache(listener: DownloadListener, entry: DeliveryCacheEntry) -> None:
    try:
        if entry.mode == "bot_file" and entry.file_id:
            await _send_cached_file(listener.origin_message, entry.kind or "document", entry.file_id, entry.caption)
            await listener.edit_progress(t(listener.lang, "delivered"), "finished", 100.0)
            return
        if entry.mode == "direct_link" and entry.direct_url:
            caption = entry.caption or ""
            header = t(listener.lang, "delivered_link")
            body = f"{caption}\n" if caption else ""
            direct_label = t(listener.lang, "direct_link")
            text = f"{header}\n\n{body}{direct_label}"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=t(listener.lang, "original"), url=entry.direct_url)]]
            )
            with suppress(Exception):
                await listener.wait_msg.edit_text(
                    text,
                    reply_markup=kb,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
            return
        await listener.edit_progress(t(listener.lang, "error_download"), "error", None)
    except Exception:
        await listener.edit_progress(t(listener.lang, "error_download"), "error", None)


def _extract_file_id(kind: str | None, msg: Message) -> str | None:
    try:
        if kind == "image":
            if msg.photo:
                return msg.photo[-1].file_id
            if msg.document:
                return msg.document.file_id
        if kind == "audio" and msg.audio:
            return msg.audio.file_id
        if kind == "video" and msg.video:
            return msg.video.file_id
        if msg.document:
            return msg.document.file_id
        if msg.photo:
            return msg.photo[-1].file_id
    except Exception:
        return None
    return None


def _schedule_download(
    origin_message: Message,
    wait_msg: Message,
    url: str,
    kind: str,
    quality: str,
    lang: str,
) -> None:
    key = (origin_message.chat.id, url, kind, quality)
    listener = DownloadListener(
        origin_message=origin_message,
        wait_msg=wait_msg,
        lang=lang,
        edit_progress=_make_progress_editor(wait_msg),
    )

    cached = _get_cached_delivery(key)
    if cached:
        asyncio.create_task(_deliver_from_cache(listener, cached))
        return

    job = _ACTIVE_JOBS.get(key)
    if job:
        job.listeners.append(listener)

        async def _queued_update() -> None:
            try:
                await listener.edit_progress(t(lang, "queued", hint=_queue_hint(lang)), "queued", None)
            except Exception:
                pass

        asyncio.create_task(_queued_update())
        return

    job = DownloadJob(key=key, url=url, kind=kind, quality=quality, listeners=[listener])
    _ACTIVE_JOBS[key] = job

    async def _initial_queue_notice() -> None:
        try:
            await listener.edit_progress(t(lang, "queued", hint=_queue_hint(lang)), "queued", None)
        except Exception:
            pass

    asyncio.create_task(_initial_queue_notice())

    task = asyncio.create_task(_run_download_job(job), name=f"dl:{kind}:{quality}")
    job.task = task
    _track_task(task)

    def _cleanup_job(_: asyncio.Task) -> None:
        _ACTIVE_JOBS.pop(key, None)

    task.add_done_callback(_cleanup_job)


async def _run_download_job(job: DownloadJob) -> None:
    async def _broadcast(
        status: str,
        downloaded: int,
        total: int | None,
        speed: float | None,
        eta: float | None,
        final: bool = False,
    ) -> None:
        pct_value: float | None = None
        if total:
            pct_value = max(0.0, min(100.0, (downloaded / total) * 100.0))
        if final:
            pct_value = 100.0
        tasks = []
        bar = progress_bar(pct_value or 0.0)
        size_s = human_size(downloaded)
        total_s = human_size(total or 0)
        spd = f"{human_size(int(speed))}/s" if speed else "—"
        eta_s = human_time(eta) if eta else "—"
        for listener in list(job.listeners):
            lang = listener.lang
            if status == "preparing":
                text = t(lang, "preparing")
            elif status == "downloading":
                text = t(
                    lang,
                    "downloading",
                    pct=f"{pct_value:.0f}" if pct_value is not None else "?",
                    bar=bar,
                    size=size_s,
                    total=total_s,
                    speed=spd,
                    eta=eta_s,
                )
            elif status == "uploading":
                text = t(lang, "uploading_userbot", pct=int(pct_value or 0), bar=bar)
            elif status == "finished":
                text = t(lang, "download_finished")
            else:
                text = "⏳ Обработка…"
            tasks.append(listener.edit_progress(text, status, pct_value))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    await _broadcast("preparing", 0, None, None, None)

    async def on_dl_progress(
        status: str,
        downloaded: int,
        total: int | None,
        speed: float | None,
        eta: float | None,
    ) -> None:
        if status == "finished":
            await _broadcast("finished", downloaded, total, speed, eta, final=True)
        else:
            await _broadcast(status, downloaded, total, speed, eta)

    try:
        result = await download_media_selected(job.url, job.kind, job.quality, progress=on_dl_progress)
        if not result.ok:
            await _broadcast_error(job)
            return
        await _deliver_result(job, result)
    except Exception as exc:  # pragma: no cover - defensive
        logging.exception("download flow failed: %s", exc)
        await _broadcast_error(job)


async def _broadcast_error(job: DownloadJob) -> None:
    tasks = [
        listener.edit_progress(t(listener.lang, "error_download"), "error", None)
        for listener in list(job.listeners)
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _deliver_result(job: DownloadJob, result: DownloadResult) -> None:
    listeners = list(job.listeners)
    if not listeners:
        return
    caption = (result.title or "")[:1024]
    limit_bytes = TELEGRAM_UPLOAD_LIMIT_MB * 1024 * 1024
    filepath = result.filepath if result.filepath and os.path.exists(result.filepath) else None
    size = result.filesize or 0
    primary = listeners[0]

    async def _mark_all(key: str) -> None:
        tasks = [listener.edit_progress(t(listener.lang, key), "finished", 100.0) for listener in list(job.listeners)]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    if filepath and size <= limit_bytes:
        sent_msg = await _send_via_bot(primary.origin_message, filepath, result.kind or "document", caption)
        file_id = _extract_file_id(result.kind, sent_msg)
        if file_id:
            _store_file_delivery(job.key, result.kind or "document", file_id, caption)
        await _mark_all("delivered")
        await _cleanup_temp(filepath)
        return

    mode = get_bypass_mode()
    if mode == "userbot" and filepath:
        me = await primary.origin_message.bot.get_me()
        token2 = put_payload({
            "target_chat_id": primary.origin_message.chat.id,
            "caption": caption,
            "delivery_key": list(job.key),
            "kind": result.kind or "document",
        })
        mark = f"UB|{token2}"
        cap2 = (caption + "\n\n" if caption else "") + mark

        async def notify(pct: int) -> None:
            bar = progress_bar(pct)
            tasks = [
                listener.edit_progress(t(listener.lang, "uploading_userbot", pct=pct, bar=bar), "uploading", float(pct))
                for listener in list(job.listeners)
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        ok = await send_file_to_bot(
            me.username or "",
            filepath,
            cap2,
            result.kind or "document",
            notify=notify,
        )
        if ok:
            await _mark_all("userbot_done")
            await _cleanup_temp(filepath)
            return

    if result.direct_url:
        for listener in list(job.listeners):
            header = t(listener.lang, "delivered_link")
            body = f"{caption}\n" if caption else ""
            direct_label = t(listener.lang, "direct_link")
            text = f"{header}\n\n{body}{direct_label}"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=t(listener.lang, "original"), url=result.direct_url)]]
            )
            with suppress(Exception):
                await listener.wait_msg.edit_text(
                    text,
                    reply_markup=kb,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
        _store_link_delivery(job.key, result.direct_url, caption)
        if filepath:
            await _cleanup_temp(filepath)
        return

    await _broadcast_error(job)
    if filepath:
        await _cleanup_temp(filepath)

@router.message(CommandStart())
async def on_start(message: Message) -> None:
    lang = get_user_lang(message.from_user.id) if message.from_user else "ru"
    await message.answer(t(lang, "start"))


@router.message(Command("help"))
async def on_help(message: Message) -> None:
    lang = get_user_lang(message.from_user.id) if message.from_user else "ru"
    await message.answer(
        t(lang, "help", limit=TELEGRAM_UPLOAD_LIMIT_MB),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(Command("settings"))
async def on_settings(message: Message) -> None:
    lang = get_user_lang(message.from_user.id) if message.from_user else "ru"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t(lang, "lang_ru"), callback_data="lang|ru"),
                InlineKeyboardButton(text=t(lang, "lang_en"), callback_data="lang|en"),
            ]
        ]
    )
    await message.answer(t(lang, "settings_title"), reply_markup=kb)


@router.message(Command("ubtest"))
async def on_userbot_test(message: Message) -> None:
    try:
        me = await message.bot.get_me()
        token = put_payload({"target_chat_id": message.chat.id, "caption": "Userbot test OK"})
        mark = f"UB|{token}"
        async def notify(p: int) -> None:
            with suppress(Exception):
                await message.answer(f"Тест userbot: {p}%")
        ok = await send_file_to_bot(me.username or "", __file__, mark, "document", notify=None)
        if ok:
            await message.answer("Отправил тестовый файл через userbot. Ожидайте пересылку здесь.")
        else:
            await message.answer("Не удалось отправить через userbot. Проверьте TG_SESSION_STRING и что вы нажали Start у бота.")
    except Exception as e:
        logging.exception("ubtest failed: %s", e)
        await message.answer("Ошибка ubtest. Проверьте логи.")


def _extract_url(text: str | None) -> str | None:
    if not text:
        return None
    m = URL_RE.search(text)
    return m.group(1) if m else None


@router.message(F.text)
async def on_text_with_url(message: Message) -> None:
    lang = get_user_lang(message.from_user.id) if message.from_user else "ru"
    url = _extract_url(message.text or "")
    if not url:
        return  # игнорируем любые не-ссылки

    # Сообщаем о действии
    with suppress(Exception):
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    basic: BasicInfo
    options: list[FormatOption]
    try:
        basic, options = await fetch_media_metadata(url)
    except Exception as exc:
        logging.exception("fetch_media_metadata failed: %s", exc)
        basic = BasicInfo(None, None, None, None, None)
        options = []

    # Предложим выбор по категориям
    if not options:
        # Попробуем скачать напрямую (возможно, это изображение/документ)
        wait_msg = await message.reply("Скачиваю… Пожалуйста, подождите")
        try:
            result = await download_media(url)
            if result.filepath and os.path.exists(result.filepath):
                await _send_via_bot(message, result.filepath, result.kind or "document", (result.title or "")[:1024])
                await _cleanup_temp(result.filepath)
                await wait_msg.delete()
                return
            if result.direct_url:
                await wait_msg.edit_text(
                    ((result.title or "") + "\n" if result.title else "")
                    + f"Прямая ссылка: {result.direct_url}"
                )
                return
            await wait_msg.edit_text("Не удалось скачать файл. Проверьте ссылку.")
            return
        except Exception:
            with suppress(Exception):
                await wait_msg.delete()
            await message.answer("Не удалось получить информацию о форматах. Проверьте ссылку.")
            return

    payload = {
        "url": url,
        "options": _options_to_payload(options),
        "title": basic.title,
        "duration": basic.duration,
    }
    token = put_payload(payload)
    keyboard = _build_recommend_keyboard(token, options, lang, url)
    preview_text = _render_menu_text(payload, lang, mode="recommended")
    thumb = getattr(basic, "thumbnail", None)
    if thumb:
        await message.answer_photo(thumb, caption=preview_text, reply_markup=keyboard)
    else:
        await message.answer(
            preview_text,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )


@router.callback_query(F.data.startswith("menu|"))
async def on_menu_navigation(cb: CallbackQuery) -> None:
    lang = get_user_lang(cb.from_user.id) if cb.from_user else "ru"
    try:
        parts = (cb.data or "").split("|")
        if len(parts) != 3:
            await cb.answer("Bad", show_alert=True)
            return
        _, token, action = parts
        payload = get_payload(token)
        if not payload or not payload.get("url"):
            await cb.answer(t(lang, "formats_unavailable"), show_alert=True)
            return
        url = payload["url"]
        options = _options_from_payload(payload.get("options"))
        if not options:
            options = await probe_media_options(url)
            if options:
                payload["options"] = _options_to_payload(options)
        if not options:
            await cb.answer(t(lang, "formats_unavailable"), show_alert=True)
            return

        if action == "more":
            keyboard = _build_full_keyboard(token, options, lang, url)
            text = _render_menu_text(payload, lang, mode="full")
        elif action == "back":
            keyboard = _build_recommend_keyboard(token, options, lang, url)
            text = _render_menu_text(payload, lang, mode="recommended")
        else:
            await cb.answer("Bad", show_alert=True)
            return

        await _edit_menu_message(cb.message, text, keyboard)
        await cb.answer()
    except Exception as exc:
        logging.exception("menu navigation failed: %s", exc)
        with suppress(Exception):
            await cb.answer("Error", show_alert=True)


@router.callback_query(F.data.startswith("fmt|"))
async def on_format_selected(cb: CallbackQuery) -> None:
    try:
        parts = (cb.data or "").split("|")
        if len(parts) != 4:
            await cb.answer("Некорректный выбор", show_alert=True)
            return
        _, token, kind, quality = parts
        payload = get_payload(token)
        if not payload or not payload.get("url"):
            await cb.answer("Истёк срок действия выбора", show_alert=True)
            return
        url = payload["url"]
        lang = get_user_lang(cb.from_user.id) if cb.from_user else "ru"
        await cb.answer()
        wait_msg = await cb.message.answer(t(lang, "queued", hint=_queue_hint(lang)))
        _schedule_download(cb.message, wait_msg, url, kind, quality, lang)
    except Exception:
        logging.exception("on_format_selected failed")
        with suppress(Exception):
            await cb.answer("Ошибка при загрузке", show_alert=True)


@router.callback_query(F.data.startswith("lang|"))
async def on_lang_switch(cb: CallbackQuery) -> None:
    code = (cb.data or "").split("|", 1)[-1]
    if cb.from_user:
        set_user_lang(cb.from_user.id, code)
        await cb.answer("OK")
        await cb.message.edit_text(t(code, "settings_saved", lang=("Русский" if code == "ru" else "English")))



async def _send_via_bot(message: Message, filepath: str, kind: str, caption: str | None) -> Message:
    if kind == "image":
        return await message.answer_photo(FSInputFile(filepath), caption=caption or None)
    if kind == "audio":
        return await message.answer_audio(FSInputFile(filepath), caption=caption or None)
    if kind == "video":
        return await message.answer_video(FSInputFile(filepath), caption=caption or None)
    return await message.answer_document(FSInputFile(filepath), caption=caption or None)


async def _cleanup_temp(filepath: str) -> None:
    try:
        tmp_dir = Path(filepath).parent
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass



# Ловим сообщения в ЛС боту от userbot с маркером UB|<token>
@router.message(F.chat.type == ChatType.PRIVATE)
async def on_userbot_private_upload(message: Message) -> None:
    cap = message.caption or message.text or ""
    m = UB_MARK_RE.search(cap)
    if not m:
        return
    token = m.group(1)
    payload = get_payload(token)
    if not payload:
        return

    target_chat_id = payload.get("target_chat_id")
    caption = payload.get("caption")
    if not target_chat_id:
        return

    try:
        await message.bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            caption=caption or None,
        )
    except Exception:
        # ignore errors silently
        pass
    else:
        delivery_key = payload.get("delivery_key")
        kind = str(payload.get("kind") or "document")
        key_tuple: tuple[int, str, str, str] | None = None
        if isinstance(delivery_key, (list, tuple)) and len(delivery_key) == 4:
            try:
                key_tuple = (
                    int(delivery_key[0]),
                    str(delivery_key[1]),
                    str(delivery_key[2]),
                    str(delivery_key[3]),
                )
            except Exception:
                key_tuple = None
        if key_tuple:
            file_id = _extract_file_id(kind, message)
            if file_id:
                _store_file_delivery(
                    key_tuple,
                    kind,
                    file_id,
                    caption if isinstance(caption, str) else None,
                )
