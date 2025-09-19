import asyncio
import os
import logging
import shutil
from pathlib import Path
import re
import time
from contextlib import suppress
from dataclasses import dataclass
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

    token = put_payload({"url": url, "options": _options_to_payload(options)})

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t(lang, "cat_fast"), callback_data=f"cat|{token}|fast"),
                InlineKeyboardButton(text=t(lang, "cat_best"), callback_data=f"cat|{token}|best"),
            ],
            [InlineKeyboardButton(text=t(lang, "cat_custom"), callback_data=f"cat|{token}|custom")],
            [InlineKeyboardButton(text=t(lang, "original"), url=url)],
        ]
    )
    caption = (basic.title or url) + (f"\n{human_time(basic.duration)}" if getattr(basic, "duration", None) else "")
    thumb = getattr(basic, "thumbnail", None)
    if thumb:
        await message.answer_photo(thumb, caption=caption, reply_markup=kb)
    else:
        await message.answer(t(lang, "choose_category"), reply_markup=kb, link_preview_options=LinkPreviewOptions(is_disabled=True))


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
        await cb.answer("OK")
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


@router.callback_query(F.data.startswith("cat|"))
async def on_category_selected(cb: CallbackQuery) -> None:
    lang = get_user_lang(cb.from_user.id) if cb.from_user else "ru"
    try:
        parts = (cb.data or "").split("|")
        if len(parts) != 3:
            await cb.answer("Bad", show_alert=True)
            return
        _, token, cat = parts
        payload = get_payload(token)
        if not payload or not payload.get("url"):
            await cb.answer("Expired", show_alert=True)
            return
        url = payload["url"]
        opts = _options_from_payload(payload.get("options"))
        if not opts:
            opts = await probe_media_options(url)
            if opts:
                payload["options"] = _options_to_payload(opts)
        if not opts:
            await cb.answer(t(lang, "formats_unavailable"), show_alert=True)
            return
        if cat == "custom":
            # Show detailed list
            best_va = next((o for o in opts if o.kind == "va" and o.quality == "best"), None)
            va_1080 = next((o for o in opts if o.kind == "va" and o.quality == "1080"), None)
            va_720 = next((o for o in opts if o.kind == "va" and o.quality == "720"), None)
            va_480 = next((o for o in opts if o.kind == "va" and o.quality == "480"), None)
            va_360 = next((o for o in opts if o.kind == "va" and o.quality == "360"), None)
            v_1080 = next((o for o in opts if o.kind == "v" and o.quality == "1080"), None)
            v_720 = next((o for o in opts if o.kind == "v" and o.quality == "720"), None)
            a_best = next((o for o in opts if o.kind == "a" and o.quality == "best"), None)

            def mk_text(prefix: str, o) -> str:
                parts = []
                if getattr(o, "height", None):
                    parts.append(f"{int(o.height)}p")
                if getattr(o, "bitrate_k", None):
                    mbps = float(o.bitrate_k) / 1000.0
                    parts.append(f"{mbps:.1f} Mbps")
                if getattr(o, "ext", None):
                    parts.append(o.ext)
                parts.append(f"~{human_size(o.est_size)}")
                return f"{prefix} " + " • ".join(parts)

            rows: list[list[InlineKeyboardButton]] = []
            if best_va:
                rows.append([InlineKeyboardButton(text=t(lang, "best_label"), callback_data=f"fmt|{token}|va|best")])
            row = []
            if va_1080:
                row.append(InlineKeyboardButton(text=mk_text("🎥", va_1080)[:64], callback_data=f"fmt|{token}|va|1080"))
            if va_720:
                row.append(InlineKeyboardButton(text=mk_text("🎥", va_720)[:64], callback_data=f"fmt|{token}|va|720"))
            if row:
                rows.append(row)
            row = []
            if va_480:
                row.append(InlineKeyboardButton(text=mk_text("🎥", va_480)[:64], callback_data=f"fmt|{token}|va|480"))
            if va_360:
                row.append(InlineKeyboardButton(text=mk_text("🎥", va_360)[:64], callback_data=f"fmt|{token}|va|360"))
            if row:
                rows.append(row)
            row = []
            if v_1080:
                row.append(InlineKeyboardButton(text=mk_text("🎬", v_1080)[:64], callback_data=f"fmt|{token}|v|1080"))
            if v_720:
                row.append(InlineKeyboardButton(text=mk_text("🎬", v_720)[:64], callback_data=f"fmt|{token}|v|720"))
            if row:
                rows.append(row)
            if a_best:
                rows.append([InlineKeyboardButton(text=t(lang, "audio_only"), callback_data=f"fmt|{token}|a|best")])
            # repeat/cancel
            rows.append([
                InlineKeyboardButton(text=t(lang, "repeat"), callback_data=f"cat|{token}|custom"),
                InlineKeyboardButton(text=t(lang, "cancel"), callback_data=f"cat|{token}|cancel"),
            ])

            await cb.message.answer(t(lang, "pick_quality"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
            return

        if cat == "cancel":
            with suppress(Exception):
                await cb.message.answer("✖️")
            return

        # fast/best shortcuts
        best_va = next((o for o in opts if o.kind == "va" and o.quality == "best"), None)
        va_opts = [o for o in opts if o.kind == "va" and o.est_size]
        fastest = min(va_opts, key=lambda x: x.est_size or 10**18) if va_opts else None
        target = None
        if cat == "best" and best_va:
            target = ("va", "best")
        elif cat == "fast" and fastest:
            target = ("va", fastest.quality)
        else:
            target = ("va", "best") if best_va else ("va", "720")

        await cb.answer("OK")
        wait_msg = await cb.message.answer(t(lang, "queued", hint=_queue_hint(lang)))
        kind, quality = target
        _schedule_download(cb.message, wait_msg, url, kind, quality, lang)
    except Exception:
        with suppress(Exception):
            await cb.answer("Error", show_alert=True)


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
