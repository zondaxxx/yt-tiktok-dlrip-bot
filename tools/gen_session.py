import os
import asyncio

from pyrogram import Client
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore


async def main() -> None:
    # Автоподхват переменных из .env, если установлен python-dotenv
    if load_dotenv:
        try:
            load_dotenv()
        except Exception:
            pass
    api_id = os.getenv("TG_API_ID") or input("Enter TG_API_ID: ").strip()
    api_hash = os.getenv("TG_API_HASH") or input("Enter TG_API_HASH: ").strip()
    async with Client("gen_session", api_id=int(api_id), api_hash=api_hash) as app:
        s = await app.export_session_string()
        print("\nYour TG_SESSION_STRING (keep it secret):\n")
        print(s)
        print("\nCopy it into your .env as TG_SESSION_STRING=...\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
