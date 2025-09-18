import argparse
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore

try:
    from yt_dlp.cookies import extract_cookies_from_browser, save_cookies  # type: ignore
except Exception as e:  # pragma: no cover
    print("yt-dlp is required. Install with: pip install yt-dlp", file=sys.stderr)
    raise


def update_env(cookies_path: str) -> None:
    env_path = Path(".env")
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    wrote = False
    for i, line in enumerate(lines):
        if line.startswith("YTDLP_COOKIES_FILE="):
            lines[i] = f"YTDLP_COOKIES_FILE={cookies_path}"
            wrote = True
            break
    if not wrote:
        lines.append(f"YTDLP_COOKIES_FILE={cookies_path}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Updated .env with YTDLP_COOKIES_FILE={cookies_path}")


def main() -> int:
    if load_dotenv:
        try:
            load_dotenv()
        except Exception:
            pass

    p = argparse.ArgumentParser(description="Extract YouTube cookies for yt-dlp from a local browser")
    p.add_argument("--from-browser", dest="browser", required=True, help="Browser: chrome|chromium|firefox|safari|edge")
    p.add_argument("--profile", dest="profile", help="Browser profile name/index", default=None)
    p.add_argument("--out", dest="out", help="Path to save cookies.txt", default="cookies.txt")
    p.add_argument("--set-env", dest="set_env", action="store_true", help="Write YTDLP_COOKIES_FILE to .env")
    args = p.parse_args()

    cookies = extract_cookies_from_browser(args.browser, profile=args.profile)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_cookies(cookies, str(out_path))
    print(f"Saved cookies to {out_path}")

    if args.set_env:
        update_env(str(out_path))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

