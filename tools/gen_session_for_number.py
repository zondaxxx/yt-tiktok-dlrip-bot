import os
import sys
import asyncio
from typing import Optional

from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PasswordHashInvalid, PhoneCodeInvalid, PhoneCodeExpired

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore


PHONE_DEFAULT = "+79957976939"
API_ID_DEFAULT = "27134043"
API_HASH_DEFAULT = "4584af3d8afd83db538c9adececbc010"


def _parse_bool(val: Optional[str]) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _update_env(session_string: str) -> None:
    path = os.path.join(os.getcwd(), ".env")
    try:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"TG_SESSION_STRING={session_string}\n")
            print(f".env created and TG_SESSION_STRING written: {path}")
            return
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        wrote = False
        for i, line in enumerate(lines):
            if line.strip().startswith("TG_SESSION_STRING="):
                lines[i] = f"TG_SESSION_STRING={session_string}\n"
                wrote = True
                break
        if not wrote:
            lines.append(f"TG_SESSION_STRING={session_string}\n")
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"TG_SESSION_STRING saved to {path}")
    except Exception as e:  # noqa: BLE001
        print(f"[!] Failed to update .env: {e}")


async def main() -> None:
    if load_dotenv:
        try:
            load_dotenv()
        except Exception:
            pass

    phone = os.getenv("TG_PHONE", PHONE_DEFAULT).strip()
    api_id_str = os.getenv("TG_API_ID", API_ID_DEFAULT).strip()
    api_hash = os.getenv("TG_API_HASH", API_HASH_DEFAULT).strip()

    try:
        api_id = int(api_id_str)
    except Exception:
        print("[!] TG_API_ID must be an integer")
        sys.exit(1)

    print("Using:")
    print(f"  PHONE      = {phone}")
    print(f"  TG_API_ID  = {api_id}")
    print(f"  TG_API_HASH= {api_hash[:6]}…")

    app = Client(
        name="gen_session_fixed",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,
    )

    await app.connect()

    sent = await app.send_code(phone)
    print("A code was sent to your Telegram. Enter it below.")
    code = input("Code: ").strip().replace(" ", "")
    try:
        await app.sign_in(phone_number=phone, phone_code_hash=sent.phone_code_hash, phone_code=code)
    except SessionPasswordNeeded:
        pwd = input("2FA password: ")
        try:
            await app.check_password(password=pwd)
        except PasswordHashInvalid:
            print("[!] Invalid 2FA password")
            await app.disconnect()
            sys.exit(2)
    except PhoneCodeInvalid:
        print("[!] Invalid code")
        await app.disconnect()
        sys.exit(3)
    except PhoneCodeExpired:
        print("[!] Code expired, run again")
        await app.disconnect()
        sys.exit(4)

    session = await app.export_session_string()
    await app.disconnect()

    print("\nYour TG_SESSION_STRING (keep it secret):\n")
    print(session)
    print("\nCopy it into your .env as TG_SESSION_STRING=…\n")

    if _parse_bool(os.getenv("WRITE_ENV")):
        _update_env(session)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Aborted")
