import os
import sys
import asyncio
import time
from typing import Optional

from pyrogram import Client
try:
    from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid  # type: ignore
except Exception:  # pragma: no cover
    SessionPasswordNeeded = Exception  # type: ignore
    PasswordHashInvalid = Exception  # type: ignore

import qrcode


def print_qr_ascii(data: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    mat = qr.get_matrix()
    # Two-row vertical compression for terminal readability
    black = "\u2588\u2588"
    white = "  "
    for row in mat:
        line = "".join(black if cell else white for cell in row)
        print(line)


async def generate_session_via_qr(api_id: int, api_hash: str) -> Optional[str]:
    async with Client("gen_session_qr", api_id=api_id, api_hash=api_hash) as app:
        qr = await app.qr_login()
        print("\nОткройте Telegram → Настройки → Устройства → Привязать устройство по QR.")
        print("Сканируйте этот QR в течение ~1 минуты:\n")
        print_qr_ascii(qr.url)
        # Ожидаем подтверждения
        started = time.time()
        timeout = 90
        while True:
            try:
                await qr.confirm()
                break
            except SessionPasswordNeeded:
                print("\nВключена двухфакторная аутентификация. Введите пароль:")
                pwd = input("Пароль 2FA: ")
                try:
                    await app.check_password(password=pwd)
                    break
                except PasswordHashInvalid:
                    print("Неверный пароль. Повторите.")
                    continue
            except Exception:
                # Подождём и попробуем ещё
                await asyncio.sleep(2)
            if time.time() - started > timeout:
                print("\nИстекло время ожидания сканирования QR.")
                return None

        s = await app.export_session_string()
        return s


async def main() -> None:
    api_id_env = os.getenv("TG_API_ID")
    api_hash_env = os.getenv("TG_API_HASH")
    if not api_id_env or not api_hash_env:
        print("Укажите TG_API_ID и TG_API_HASH через переменные окружения или ввод:")
    try:
        api_id = int(api_id_env or input("TG_API_ID: ").strip())
    except Exception:
        print("TG_API_ID должен быть числом")
        sys.exit(1)
    api_hash = api_hash_env or input("TG_API_HASH: ").strip()
    if not api_hash:
        print("TG_API_HASH не может быть пустым")
        sys.exit(1)

    s = await generate_session_via_qr(api_id, api_hash)
    if not s:
        sys.exit(2)
    print("\nВаш TG_SESSION_STRING (держите в секрете):\n")
    print(s)
    print("\nСкопируйте в .env как TG_SESSION_STRING=...\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
