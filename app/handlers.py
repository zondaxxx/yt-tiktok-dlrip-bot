import os
import logging
import shutil
from pathlib import Path
import re
from contextlib import suppress

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
        get_basic_info,
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
        get_basic_info,
    )
    from config import get_bypass_mode
    from state import put_payload, get_payload, get_user_lang, set_user_lang
    from user_sender import send_file_via_user, send_file_to_bot
    from ui import human_size, human_time, progress_bar
    from i18n import t


router = Router()

URL_RE = re.compile(r"(https?://\S+)")
UB_MARK_RE = re.compile(r"\bUB\|([A-Za-z0-9_\-]+)\b")


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

    # Предложим выбор по категориям
    options = await probe_media_options(url)
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

    token = put_payload({"url": url})
    basic = get_basic_info(url)

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
        wait_msg = await cb.message.answer("⏬ …")

        async def on_dl_progress(status: str, downloaded: int, total: int | None, speed: float | None, eta: float | None) -> None:
            pct = 0.0
            if total:
                pct = max(0.0, min(100.0, (downloaded / total) * 100.0))
            bar = progress_bar(pct)
            size_s = human_size(downloaded)
            total_s = human_size(total or 0)
            spd = f"{human_size(int(speed))}/s" if speed else "—"
            eta_s = human_time(eta) if eta else "—"
            if status == "downloading":
                txt = t(lang, "downloading", pct=f"{pct:.0f}", bar=bar, size=size_s, total=total_s, speed=spd, eta=eta_s)
            elif status == "finished":
                txt = t(lang, "download_finished")
            else:
                txt = "⏳ Обработка…"
            with suppress(Exception):
                await wait_msg.edit_text(txt)

        result = await download_media_selected(url, kind, quality, progress=on_dl_progress)
        if not result.ok:
            await wait_msg.edit_text(t(lang, "error_download"))
            return

        # Отправка: сначала пробуем через бота, если размер в пределах
        caption = (result.title or "")[:1024]
        size = result.filesize or 0
        if result.filepath and os.path.exists(result.filepath) and size <= TELEGRAM_UPLOAD_LIMIT_MB * 1024 * 1024:
            await _send_via_bot(cb.message, result.filepath, result.kind or "document", caption)
            await _cleanup_temp(result.filepath)
            await wait_msg.delete()
            return

        # За пределами лимита — режим обхода
        mode = get_bypass_mode()
        if mode == "userbot" and result.filepath and os.path.exists(result.filepath):
            # Готовим токен и просим userbot отправить файл самому боту, чтобы бот получил file_id и смог переслать
            me = await cb.message.bot.get_me()
            token2 = put_payload({
                "target_chat_id": cb.message.chat.id,
                "caption": caption,
            })
            mark = f"UB|{token2}"
            cap2 = (caption + "\n\n" if caption else "") + mark
            async def notify(pct: int) -> None:
                bar = progress_bar(pct)
                with suppress(Exception):
                    await wait_msg.edit_text(t(lang, "uploading_userbot", pct=pct, bar=bar))

            ok = await send_file_to_bot(
                me.username or "",
                result.filepath,
                cap2,
                result.kind or "document",
                notify=notify,
            )
            if ok:
                await wait_msg.edit_text(t(lang, "userbot_done"))
                # Не удаляем временный файл сразу — на всякий случай; но можно очистить:
                await _cleanup_temp(result.filepath)
                return
            # если не получилось — продолжим ниже
        # Фолбек — прямая ссылка
        if result.direct_url:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(lang, "original"), url=result.direct_url)]])
            await wait_msg.edit_text(
                (caption + "\n" if caption else "") + t(lang, "direct_link"),
                reply_markup=kb,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        else:
            await wait_msg.edit_text(t(lang, "error_download"))
    except Exception:
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
        opts = await probe_media_options(url)
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
        wait_msg = await cb.message.answer("⏬ …")

        async def on_dl_progress(status: str, downloaded: int, total: int | None, speed: float | None, eta: float | None) -> None:
            pct = 0.0
            if total:
                pct = max(0.0, min(100.0, (downloaded / total) * 100.0))
            bar = progress_bar(pct)
            size_s = human_size(downloaded)
            total_s = human_size(total or 0)
            spd = f"{human_size(int(speed))}/s" if speed else "—"
            eta_s = human_time(eta) if eta else "—"
            text = t(lang, "downloading", pct=f"{pct:.0f}", bar=bar, size=size_s, total=total_s, speed=spd, eta=eta_s)
            with suppress(Exception):
                await wait_msg.edit_text(text)

        kind, quality = target
        result = await download_media_selected(url, kind, quality, progress=on_dl_progress)
        if not result.ok:
            with suppress(Exception):
                await wait_msg.edit_text(t(lang, "error_download"))
            return

        caption = (result.title or "")[:1024]
        size = result.filesize or 0
        if result.filepath and os.path.exists(result.filepath) and size <= TELEGRAM_UPLOAD_LIMIT_MB * 1024 * 1024:
            await _send_via_bot(cb.message, result.filepath, result.kind or "document", caption)
            await _cleanup_temp(result.filepath)
            with suppress(Exception):
                await wait_msg.delete()
            return

        mode = get_bypass_mode()
        if mode == "userbot" and result.filepath and os.path.exists(result.filepath):
            me = await cb.message.bot.get_me()
            token2 = put_payload({"target_chat_id": cb.message.chat.id, "caption": caption})
            mark = f"UB|{token2}"
            cap2 = (caption + "\n\n" if caption else "") + mark

            async def notify(pct: int) -> None:
                bar = progress_bar(pct)
                with suppress(Exception):
                    await wait_msg.edit_text(t(lang, "uploading_userbot", pct=pct, bar=bar))

            ok = await send_file_to_bot(me.username or "", result.filepath, cap2, result.kind or "document", notify=notify)
            if ok:
                await wait_msg.edit_text(t(lang, "userbot_done"))
                await _cleanup_temp(result.filepath)
                return

        if result.direct_url:
            await wait_msg.edit_text(
                t(lang, "direct_link"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t(lang, "original"), url=result.direct_url)]]),
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        else:
            await wait_msg.edit_text(t(lang, "error_download"))
    except Exception:
        with suppress(Exception):
            await cb.answer("Error", show_alert=True)


async def _send_via_bot(message: Message, filepath: str, kind: str, caption: str | None) -> None:
    if kind == "image":
        await message.answer_photo(FSInputFile(filepath), caption=caption or None)
        return
    if kind == "audio":
        await message.answer_audio(FSInputFile(filepath), caption=caption or None)
        return
    if kind == "video":
        await message.answer_video(FSInputFile(filepath), caption=caption or None)
        return
    await message.answer_document(FSInputFile(filepath), caption=caption or None)


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
