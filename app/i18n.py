from __future__ import annotations

MESSAGES = {
    "ru": {
        "start": "<b>Привет!</b> Я — твой видеоконсьерж. Отправь ссылку на YouTube, TikTok, Instagram и другие площадки — я подберу идеальный формат и доставлю файл без лишних задержек.",
        "help": "<b>Как пользоваться</b>\n• Киньте ссылку — подберу качества и покажу размер.\n• До ≈{limit} МБ прилетит сразу ботом. Крупнее — аккуратно передам через userbot.\n• Выбирайте: <i>видео+аудио</i>, <i>только видео</i> или <i>только аудио</i>.",
        "original": "🔗 Оригинал",
        "downloading": "⏬ {bar} {pct}%\n{size}/{total} • {speed}/s • ETA {eta}",
        "download_finished": "✅ Файл готов. Финальная обработка…",
        "uploading_userbot": "⏫ Передаю через userbot {pct}% {bar}",
        "userbot_done": "✅ Готово! Файл уже в пути к вам.",
        "direct_link": "Файл большой. Можно скачать по ссылке:",
        "delivered": "✅ Готово! Файл уже в чате.",
        "delivered_link": "✅ Готово! Ссылка ниже.",
        "settings_title": "Выберите язык интерфейса",
        "lang_ru": "🇷🇺 Русский",
        "lang_en": "🇬🇧 English",
        "settings_saved": "✅ Язык сохранён: {lang}",
        "formats_unavailable": "Не удалось получить информацию о форматах. Проверьте ссылку.",
        "error_download": "Произошла ошибка при скачивании. Попробуйте другую ссылку.",
        "queued": "⌛️ Поставил в очередь — всё скоро будет готово{hint}",
        "preparing": "🔄 Подбираю лучший источник…",
        "queue_full": "🚦 Очередь переполнена. Попробуйте ещё раз через минуту.",
        "queue_chat_full": "🙈 У вас уже несколько загрузок в обработке. Дождитесь окончания и повторите запрос.",
        "menu_recommended": "<b>Рекомендованные форматы</b>",
        "menu_full": "<b>Все варианты</b>",
        "menu_hint": "Нажмите кнопку ниже — и я начну загрузку.",
        "menu_more": "🎛 Все форматы",
        "menu_back": "⬅️ Рекомендации",
        "quality_best_short": "Лучшее",
        "quality_unknown": "—",
        "opt_best": "✨ Лучшее",
        "opt_compact": "⚡️ Быстрее",
        "opt_audio": "🎵 Аудио",
        "opt_video": "🎬 Видео",
        "meta_duration": "⏱ Длительность: {value}",
        "cooldown_active": "⌚️ Сделайте паузу {seconds} с — запрос отправлен слишком быстро.",
        "queue_status": "<b>Очередь</b>\nВсего задач: {total}\nСкачивается: {downloading}\nВаших запросов: {chat}",
        "queue_limits": "Пределы: система {max_total} · на чат {max_chat} · задержка {cooldown}",
    },
    "en": {
        "start": "<b>Hey!</b> I’m your personal media concierge. Drop a link from YouTube, TikTok, Instagram or more — I’ll pick the perfect format and deliver it in style.",
        "help": "<b>How it works</b>\n• Share a link — I’ll preview qualities with size hints.\n• Up to ≈{limit} MB is sent instantly via the bot. Larger files glide through userbot.\n• Choose between <i>video+audio</i>, <i>video only</i>, or <i>audio only</i>.",
        "original": "🔗 Original",
        "downloading": "⏬ {bar} {pct}%\n{size}/{total} • {speed}/s • ETA {eta}",
        "download_finished": "✅ Ready. Giving it a final polish…",
        "uploading_userbot": "⏫ Handing off via userbot {pct}% {bar}",
        "userbot_done": "✅ All set! Your file is on the way.",
        "direct_link": "File is large. Download via link:",
        "delivered": "✅ Done! The file is now in the chat.",
        "delivered_link": "✅ Done! Grab the link below.",
        "settings_title": "Choose interface language",
        "lang_ru": "🇷🇺 Russian",
        "lang_en": "🇬🇧 English",
        "settings_saved": "✅ Language saved: {lang}",
        "formats_unavailable": "Failed to get formats. Check the link.",
        "error_download": "Error while downloading. Try another link.",
        "queued": "⌛️ Added to the queue — getting everything ready{hint}",
        "preparing": "🔄 Lining up the best source…",
        "queue_full": "🚦 Queue is at capacity right now. Please retry in a minute.",
        "queue_chat_full": "🙈 You already have a few downloads running. Let them finish and try again.",
        "menu_recommended": "<b>Recommended formats</b>",
        "menu_full": "<b>All formats</b>",
        "menu_hint": "Tap a button to start the download.",
        "menu_more": "🎛 Full list",
        "menu_back": "⬅️ Recommended",
        "quality_best_short": "Best",
        "quality_unknown": "—",
        "opt_best": "✨ Best",
        "opt_compact": "⚡️ Faster",
        "opt_audio": "🎵 Audio",
        "opt_video": "🎬 Video",
        "meta_duration": "⏱ Duration: {value}",
        "cooldown_active": "⌚️ Easy there! Try again in {seconds}s.",
        "queue_status": "<b>Queue</b>\nTotal jobs: {total}\nDownloading now: {downloading}\nYour requests: {chat}",
        "queue_limits": "Limits: global {max_total} · per chat {max_chat} · cooldown {cooldown}",
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
