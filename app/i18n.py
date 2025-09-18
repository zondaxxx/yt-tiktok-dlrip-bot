from __future__ import annotations

MESSAGES = {
    "ru": {
        "start": "<b>Привет!</b> Отправь ссылку на видео/картинку (YouTube, TikTok, Instagram, Pinterest и др.).\nЯ предложу варианты, а большие файлы загружу через userbot.",
        "help": "<b>Как пользоваться</b>\n• Киньте ссылку — покажу варианты.\n• До ≈{limit} МБ отправлю сразу. Крупнее — через userbot.\n• Можно выбрать: <i>видео+аудио</i> / <i>только видео</i> / <i>только аудио</i>.",
        "choose_category": "<b>Выберите режим</b>",
        "cat_fast": "⚡️ Самый быстрый",
        "cat_best": "🏆 Самый качественный",
        "cat_custom": "🎛 Свой выбор",
        "original": "🔗 Оригинал",
        "repeat": "🔁 Повторить выбор",
        "cancel": "✖️ Отмена",
        "downloading": "⏬ Скачивание {pct}%  {bar}\n{size}/{total} • {speed}/s • ETA {eta}",
        "download_finished": "✅ Скачано. Обработка…",
        "uploading_userbot": "⏫ Загрузка через userbot {pct}%  {bar}",
        "userbot_done": "✅ Загрузка завершена через userbot. Пересылаю сюда…",
        "direct_link": "Файл большой. Можно скачать по ссылке:",
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
    },
    "en": {
        "start": "<b>Hi!</b> Send a video/image link (YouTube, TikTok, Instagram, Pinterest, etc.).\nI’ll offer options and upload large files via userbot.",
        "help": "<b>How to use</b>\n• Send a link — I’ll show options.\n• Up to ≈{limit} MB I send directly. Larger — via userbot.\n• Choose: <i>video+audio</i> / <i>video only</i> / <i>audio only</i>.",
        "choose_category": "<b>Choose mode</b>",
        "cat_fast": "⚡️ Fastest",
        "cat_best": "🏆 Best quality",
        "cat_custom": "🎛 Custom",
        "original": "🔗 Original",
        "repeat": "🔁 Repeat",
        "cancel": "✖️ Cancel",
        "downloading": "⏬ Downloading {pct}%  {bar}\n{size}/{total} • {speed}/s • ETA {eta}",
        "download_finished": "✅ Downloaded. Processing…",
        "uploading_userbot": "⏫ Uploading via userbot {pct}%  {bar}",
        "userbot_done": "✅ Uploaded via userbot. Forwarding…",
        "direct_link": "File is large. Download via link:",
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

