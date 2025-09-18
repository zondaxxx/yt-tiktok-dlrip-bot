import os
import sys
import time
import shutil
import subprocess
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore

from yt_dlp.cookies import extract_cookies_from_browser, save_cookies  # type: ignore


def find_chrome() -> str | None:
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "chrome",
    ]
    for c in candidates:
        path = shutil.which(c)
        if path:
            return path
    return None


def update_env_cookies(path: str) -> None:
    env_path = Path(".env")
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    wrote = False
    for i, line in enumerate(lines):
        if line.startswith("YTDLP_COOKIES_FILE="):
            lines[i] = f"YTDLP_COOKIES_FILE={path}"
            wrote = True
            break
    if not wrote:
        lines.append(f"YTDLP_COOKIES_FILE={path}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Updated .env with YTDLP_COOKIES_FILE={path}")


def main() -> int:
    if load_dotenv:
        try:
            load_dotenv()
        except Exception:
            pass

    chrome = find_chrome()
    if not chrome:
        print("[!] Chrome/Chromium not found. Install Chrome/Chromium or use tools.ytdlp_auth.")
        return 2

    workdir = Path(os.getcwd())
    profile_dir = workdir / ".google-auth-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    url = "https://www.youtube.com",
    cmd = [
        chrome,
        f"--user-data-dir={str(profile_dir)}",
        "--no-default-browser-check",
        "--no-first-run",
        "https://www.youtube.com",
    ]
    print("Launching Chrome. Please log into your Google account in the opened window.")
    print("After you see YouTube home as logged in user, return here and press Enter.")

    try:
        proc = subprocess.Popen(cmd)  # noqa: S603,S607
    except Exception as e:
        print(f"[!] Failed to launch Chrome: {e}")
        return 3

    try:
        input("Press Enter to capture cookies… ")
    finally:
        # Try to terminate browser (optional)
        try:
            proc.terminate()
        except Exception:
            pass

    # Extract cookies from the temporary profile
    try:
        cookies = extract_cookies_from_browser("chrome", profile=str(profile_dir))
    except Exception as e:
        print(f"[!] Failed to extract cookies from browser: {e}")
        return 4

    out = workdir / "cookies.txt"
    save_cookies(cookies, str(out))
    print(f"Saved cookies to {out}")
    update_env_cookies(str(out))
    print("Done. Restart your bot to apply cookies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

