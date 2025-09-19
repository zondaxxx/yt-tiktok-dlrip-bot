from __future__ import annotations

MESSAGES = {
    "ru": {
        "start": "<b>Привет!</b> Я — твой видеоконсьерж. Отправь ссылку на YouTube, TikTok, Instagram и другие площадки — я подберу идеальный формат и доставлю файл без лишних задержек.",
        "help": "<b>Как пользоваться</b>\n• Киньте ссылку — подберу качества и покажу размер.\n• До ≈{limit} МБ прилетит сразу ботом. Крупнее — аккуратно передам через userbot.\n• Выбирайте: <i>видео+аудио</i>, <i>только видео</i> или <i>только аудио</i>.",
        "choose_category": "<b>Выберите сценарий</b>",
        "cat_fast": "⚡️ Моментально",
        "cat_best": "✨ Максимум качества",
        "cat_custom": "🎛 Точный выбор",
        "original": "🔗 Оригинал",
        "repeat": "🔁 Повторить выбор",
        "cancel": "✖️ Отмена",
        "downloading": "⏬ {bar} {pct}%\n{size}/{total} • {speed}/s • ETA {eta}",
        "download_finished": "✅ Файл готов. Финальная обработка…",
        "uploading_userbot": "⏫ Передаю через userbot {pct}% {bar}",
        "userbot_done": "✅ Готово! Файл уже в пути к вам.",
        "direct_link": "Файл большой. Можно скачать по ссылке:",
        "delivered": "✅ Готово! Файл уже в чате.",
        "delivered_link": "✅ Готово! Ссылка ниже.",
        "pick_quality": "<b>Выберите качество</b>",
        "audio_only": "🎵 Только аудио",
        "video_only": "🎬 Видео {height}p",
        "video_audio": "🎥 Видео+аудио {height}p",
        "best_label": "🎥 Лучшее",
        "settings_title": "Выберите язык интерфейса",
        "lang_ru": "🇷🇺 Русский",
        "lang_en": "🇬🇧 English",
        "settings_saved": "✅ Язык сохранён: {lang}",
        "formats_unavailable": "Не удалось получить информацию о форматах. Проверьте ссылку.",
        "error_download": "Произошла ошибка при скачивании. Попробуйте другую ссылку.",
        "queued": "⌛️ Поставил в очередь — всё скоро будет готово{hint}",
        "preparing": "🔄 Подбираю лучший источник…",
    },
    "en": {
        "start": "<b>Hey!</b> I’m your personal media concierge. Drop a link from YouTube, TikTok, Instagram or more — I’ll pick the perfect format and deliver it in style.",
        "help": "<b>How it works</b>\n• Share a link — I’ll preview qualities with size hints.\n• Up to ≈{limit} MB is sent instantly via the bot. Larger files glide through userbot.\n• Choose between <i>video+audio</i>, <i>video only</i>, or <i>audio only</i>.",
        "choose_category": "<b>Select the scenario</b>",
        "cat_fast": "⚡️ Instant",
        "cat_best": "✨ Best look",
        "cat_custom": "🎛 Tailored",
        "original": "🔗 Original",
        "repeat": "🔁 Repeat",
        "cancel": "✖️ Cancel",
        "downloading": "⏬ {bar} {pct}%\n{size}/{total} • {speed}/s • ETA {eta}",
        "download_finished": "✅ Ready. Giving it a final polish…",
        "uploading_userbot": "⏫ Handing off via userbot {pct}% {bar}",
        "userbot_done": "✅ All set! Your file is on the way.",
        "direct_link": "File is large. Download via link:",
        "delivered": "✅ Done! The file is now in the chat.",
        "delivered_link": "✅ Done! Grab the link below.",
        "pick_quality": "<b>Choose quality</b>",
        "audio_only": "🎵 Audio only",
        "video_only": "🎬 Video {height}p",
        "video_audio": "🎥 Video+audio {height}p",
        "best_label": "🎥 Best",
        "settings_title": "Choose interface language",
        "lang_ru": "🇷🇺 Russian",
        "lang_en": "🇬🇧 English",
        "settings_saved": "✅ Language saved: {lang}",
        "formats_unavailable": "Failed to get formats. Check the link.",
        "error_download": "Error while downloading. Try another link.",
        "queued": "⌛️ Added to the queue — getting everything ready{hint}",
        "preparing": "🔄 Lining up the best source…",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in MESSAGES else "ru"
    msg = MESSAGES[lang].get(key) or MESSAGES["ru"].get(key) or key
    if kwargs:
        try:
            return msg.format(**kwargs)
        except Exception:
            return msg
    return msg
