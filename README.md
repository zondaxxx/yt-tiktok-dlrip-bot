# Telegram Video Downloader Bot (aiogram + yt-dlp)

Бот скачивает видео и изображения по ссылке из популярных ресурсов: YouTube, TikTok, Instagram (публичные), Pinterest и др. Построен на `aiogram` и `yt-dlp`.

## Возможности
- Выбор качества и типа дорожки: лучшее/1080p/720p/480p/360p, только видео, только аудио.
- Предварительная оценка размера варианта перед скачиванием.
- Отправка файлов в Telegram, если они не превышают безопасный лимит для ботов (~48 МБ).
- Обход для больших файлов: userbot (Pyrogram) — отправка через пользовательский аккаунт (до 2–4 ГБ в пределах ограничений Telegram).
- Если обход не настроен, бот вернёт прямую ссылку (до ~4 ГБ).
- Поддерживаются многие сайты благодаря `yt-dlp`.

## Требования
- Python 3.10+
- Установленный `ffmpeg` (желательно, для склейки аудио/видео у некоторых источников).
  - macOS: `brew install ffmpeg`
  - Linux (Debian/Ubuntu): `sudo apt-get update && sudo apt-get install -y ffmpeg`
  - Windows: скачайте бинарники с сайта проекта и добавьте в PATH

## Настройка
1. Создайте бота через @BotFather и получите токен.
2. Скопируйте `.env.example` в `.env` и подставьте ваш токен:
   ```
   cp .env.example .env
   # затем отредактируйте .env и укажите BOT_TOKEN
   ```
3. Установите зависимости:
   ```
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. (Опционально) Обход лимитов Telegram для больших файлов:
   - В `.env` установите `BYPASS_MODE=userbot`.
   - Для `userbot` заполните `TG_API_ID`, `TG_API_HASH` и `TG_SESSION_STRING`.
     - Получите `TG_API_ID`/`TG_API_HASH` на https://my.telegram.org.
     - Сгенерируйте `TG_SESSION_STRING` локально:
       - Через SMS/код: `python -m tools.gen_session`
       - Через QR (рекомендуется):
         ```
         # Используются переменные окружения TG_API_ID/TG_API_HASH или будет интерактивный ввод
         python -m tools.gen_session_qr
         ```
       Скопируйте строку в `.env`: `TG_SESSION_STRING=...`

## Запуск
```bash
# Вариант 1 (предпочтительный): как пакет
python -m app.main

# Вариант 2: как скрипт
python app/main.py
```

## Деплой на сервер (systemd)
- Скрипт: `scripts/deploy.sh` — автоматизирует установку и запуск под systemd.

Быстрый старт (Ubuntu/Debian):
```bash
git clone <repo_url> ytdlp-bot && cd ytdlp-bot
cp .env.example .env  # заполните BOT_TOKEN и TG_* для userbot
chmod +x scripts/deploy.sh
SERVICE_NAME=yt-dlp-bot ./scripts/deploy.sh install
```

Команды обслуживания:
- `./scripts/deploy.sh update` — обновить зависимости и перезапустить
- `./scripts/deploy.sh restart` — перезапуск сервиса
- `./scripts/deploy.sh status` — статус
- `./scripts/deploy.sh logs` — логи (journalctl)

Переменные:
- `SERVICE_NAME` — имя systemd сервиса (по умолчанию `yt-dlp-bot`)
- `VENVDIR` — путь к virtualenv (по умолчанию `.venv`)
- `PYTHON_BIN` — бинарник Python для создания venv (по умолчанию `python3`)
- `WORKDIR` — путь к каталогу проекта (по умолчанию текущий)

## Использование
- Отправьте боту любую ссылку на видео/изображение (YouTube, TikTok, Instagram, Pinterest и т.д.).
- Бот покажет варианты качества с примерным размером и предложит кнопки: «Видео+аудио», «Только видео», «Только аудио».
- Если итоговый файл ≤ ~48 МБ — бот отправит его прямо в чат.
- Если больше, и включён обход:
  - `userbot`: файл загрузится вашим user‑аккаунтом в личку боту, бот автоматически перешлёт его в исходный чат (без ограничений Bot API по размеру).
- Если обход не включён — бот пришлёт прямую ссылку на скачивание (до ~4 ГБ).

## Примечания
- Для приватных/закрытых видео скачивание работать не будет.
- В редких случаях прямые ссылки от `yt-dlp` могут быть временными.
- Лимит отправки больших файлов ботом ограничен Telegram. Бот автоматически отдаёт прямую ссылку, если файл больше лимита загрузки. Порог прямых ссылок установлен до ~4 ГБ.

## Структура
- `app/main.py` — запуск бота и диспетчера
- `app/handlers.py` — обработчики сообщений, выбор форматов и отправка
- `app/downloader.py` — извлечение форматов, оценка размеров, скачивание через `yt-dlp`
- `app/config.py` — загрузка конфигурации (токен, обход, pyrogram)
- `app/user_sender.py` — отправка больших файлов через Pyrogram (userbot)
- `app/state.py` — временное хранение выбора пользователя для callback-кнопок

## Docker (опционально)
Если предпочитаете Docker, можно быстро собрать образ с `ffmpeg` внутри. Скажите — добавлю `Dockerfile`.
