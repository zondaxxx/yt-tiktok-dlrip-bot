import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Callable

import yt_dlp as ytdlp


# Максимальный размер файла для отдачи пользователю через прямую ссылку
# (не загружаем в Telegram, но позволяем получить URL):
MAX_FILE_MB = 4096  # 4 ГБ

# Мягкий предел для загрузки в Telegram ботом (у ботов ограничение ~50 МБ)
TELEGRAM_UPLOAD_LIMIT_MB = 48


@dataclass
class DownloadResult:
    ok: bool
    filepath: Optional[str]
    title: Optional[str]
    ext: Optional[str]
    filesize: Optional[int]
    duration: Optional[float]
    thumbnail: Optional[str]
    webpage_url: Optional[str]
    direct_url: Optional[str]
    kind: Optional[str]  # 'video' | 'audio' | 'image' | 'document'
    error: Optional[str] = None


@dataclass
class FormatOption:
    kind: str  # 'va' | 'v' | 'a'
    quality: str  # 'best' | '1080' | '720' | '480' | '360'
    est_size: Optional[int]  # bytes
    label: str  # human label
    height: Optional[int] = None
    bitrate_k: Optional[float] = None  # kbps
    ext: Optional[str] = None


@dataclass
class BasicInfo:
    title: Optional[str]
    duration: Optional[float]
    thumbnail: Optional[str]
    width: Optional[int]
    height: Optional[int]


def _format_limit_str(max_bytes: int) -> str:
    # yt-dlp понимает суффиксы, используем мегабайты
    mb = max_bytes // (1024 * 1024)
    return f"{mb}M"


def _pick_kind(info: dict) -> str:
    ext = (info.get("ext") or "").lower()
    vcodec = (info.get("vcodec") or "").lower()
    acodec = (info.get("acodec") or "").lower()
    if ext in {"jpg", "jpeg", "png", "webp"}:
        return "image"
    if vcodec and vcodec != "none":
        return "video"
    if acodec and acodec != "none":
        return "audio"
    return "document"


def _extract_info(url: str) -> Tuple[Optional[dict], Optional[str]]:
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "extract_flat": False,
        }
        with ytdlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info, None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def _best_direct_url(info: dict, max_bytes: int) -> Optional[str]:
    # Постараемся выбрать прямой URL подходящего формата в пределах max_bytes
    fmts = info.get("formats") or []
    best = None
    best_score = -1e9
    for f in fmts:
        url = f.get("url")
        if not url:
            continue
        size = f.get("filesize") or f.get("filesize_approx")
        if size and size > max_bytes:
            continue
        proto = (f.get("protocol") or "").lower()
        ext = (f.get("ext") or "").lower()
        height = f.get("height") or 0
        tbr = f.get("tbr") or 0
        score = 0.0
        if ext == "mp4":
            score += 50
        if "hls" in proto or "m3u8" in proto:
            score -= 20
        if "dash" in proto:
            score -= 15
        score += height / 1000.0
        score += float(tbr) / 1000.0
        if score > best_score:
            best_score = score
            best = f
    return (best or {}).get("url") or info.get("url") or info.get("webpage_url")


def _has_known_under_limit(info: dict, limit_bytes: int) -> bool:
    size_top = info.get("filesize") or info.get("filesize_approx")
    if size_top and size_top <= limit_bytes:
        return True
    fmts = info.get("formats") or []
    for f in fmts:
        size = f.get("filesize") or f.get("filesize_approx")
        if size and size <= limit_bytes:
            return True
    return False


def _download(
    url: str,
    tg_limit_bytes: int,
    dl_max_bytes: int,
    on_progress: Optional[Callable[[str, int, Optional[int], Optional[float], Optional[float]], None]] = None,
) -> DownloadResult:
    temp_dir = tempfile.mkdtemp(prefix="dlyt_")
    tg_limit = _format_limit_str(tg_limit_bytes)

    try:
        # Сначала извлечём метаданные, чтобы понять — пробуем ли качать под лимит TG
        probe_info, _ = _extract_info(url)
        if not isinstance(probe_info, dict):
            raise RuntimeError("Failed to extract info")

        # Если нет формата с известным размером <= лимита TG — отдаём прямой URL, не качаем
        if not _has_known_under_limit(probe_info, tg_limit_bytes):
            direct_url = _best_direct_url(probe_info, dl_max_bytes)
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            return DownloadResult(
                ok=True,
                filepath=None,
                title=probe_info.get("title"),
                ext=probe_info.get("ext"),
                filesize=None,
                duration=probe_info.get("duration"),
                thumbnail=probe_info.get("thumbnail"),
                webpage_url=probe_info.get("webpage_url") or url,
                direct_url=direct_url,
                kind=_pick_kind(probe_info),
            )

        # Пытаемся подобрать формат в пределах лимита и с mp4, чтобы Телеграм принял
        format_selector = (
            f"bestvideo[ext=mp4][filesize<=?{tg_limit}]+bestaudio[ext=m4a][filesize<=?{tg_limit}]"
            f"/best[ext=mp4][filesize<=?{tg_limit}]"
            f"/best[filesize<=?{tg_limit}]"
        )

        def _hook(d: Dict):
            if not on_progress:
                return
            status = d.get("status") or ""
            if status == "downloading":
                downloaded = int(d.get("downloaded_bytes") or 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                speed = d.get("speed")
                eta = d.get("eta")
                on_progress(
                    "downloading",
                    downloaded,
                    int(total) if total else None,
                    float(speed) if speed else None,
                    float(eta) if eta else None,
                )
            elif status == "finished":
                on_progress("finished", int(d.get("downloaded_bytes") or 0), int(d.get("total_bytes") or 0), None, None)

        ydl_opts = {
            "format": format_selector,
            "outtmpl": os.path.join(temp_dir, "%(title).180B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": False,
            "merge_output_format": "mp4",
            "postprocessors": [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }
            ],
            "progress_hooks": [_hook],
        }

        with ytdlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Выясняем итоговый путь файла
            filepath = None
            if isinstance(info, dict):
                req = info.get("requested_downloads") or []
                for r in req:
                    fp = r.get("filepath")
                    if fp and os.path.exists(fp):
                        filepath = fp
                        break
                if not filepath:
                    filepath = info.get("_filename")
            if not filepath or not os.path.exists(filepath):
                files = [
                    os.path.join(temp_dir, f)
                    for f in os.listdir(temp_dir)
                    if os.path.isfile(os.path.join(temp_dir, f))
                ]
                if files:
                    filepath = files[0]

            size = os.path.getsize(filepath) if filepath and os.path.exists(filepath) else None
            kind = _pick_kind(info) if isinstance(info, dict) else "document"

            if size is not None and size > tg_limit_bytes:
                # Не отправляем файл, отдаём прямую ссылку
                direct_url = _best_direct_url(info if isinstance(info, dict) else probe_info, dl_max_bytes)
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass
                return DownloadResult(
                    ok=True,
                    filepath=None,
                    title=(info or {}).get("title"),
                    ext=(info or {}).get("ext"),
                    filesize=size,
                    duration=(info or {}).get("duration"),
                    thumbnail=(info or {}).get("thumbnail"),
                    webpage_url=(info or {}).get("webpage_url") or url,
                    direct_url=direct_url,
                    kind=kind,
                )

            return DownloadResult(
                ok=True,
                filepath=filepath,
                title=(info or {}).get("title"),
                ext=(info or {}).get("ext"),
                filesize=size,
                duration=(info or {}).get("duration"),
                thumbnail=(info or {}).get("thumbnail"),
                webpage_url=(info or {}).get("webpage_url") or url,
                direct_url=None,
                kind=kind,
            )
    except Exception as e:  # noqa: BLE001
        # Пытаемся хотя бы вернуть метаданные и прямую ссылку
        info, _ = _extract_info(url)
        direct_url = None
        if isinstance(info, dict):
            direct_url = _best_direct_url(info, dl_max_bytes)
        # Чистим временную папку на всякий случай
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        return DownloadResult(
            ok=False,
            filepath=None,
            title=(info or {}).get("title") if info else None,
            ext=(info or {}).get("ext") if info else None,
            filesize=None,
            duration=(info or {}).get("duration") if info else None,
            thumbnail=(info or {}).get("thumbnail") if info else None,
            webpage_url=(info or {}).get("webpage_url") if info else None,
            direct_url=direct_url,
            kind=_pick_kind(info) if info else None,
            error=str(e),
        )


async def download_media(
    url: str,
    telegram_limit_mb: int = TELEGRAM_UPLOAD_LIMIT_MB,
    download_max_mb: int = MAX_FILE_MB,
) -> DownloadResult:
    tg_limit_bytes = max(1, telegram_limit_mb) * 1024 * 1024
    dl_max_bytes = max(1, download_max_mb) * 1024 * 1024
    return await asyncio.to_thread(_download, url, tg_limit_bytes, dl_max_bytes, None)


# -------- Форматы и выбор качества ---------

def _human_size(nbytes: Optional[int]) -> str:
    if not nbytes:
        return "?"
    units = ["Б", "КБ", "МБ", "ГБ"]
    size = float(nbytes)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.1f} {u}".replace(".0", "")
        size /= 1024
    return f"{nbytes} Б"


def _pick_audio_fmt(formats: List[Dict]) -> Optional[Dict]:
    cand = []
    for f in formats:
        ac = (f.get("acodec") or "none").lower()
        vc = (f.get("vcodec") or "none").lower()
        if ac != "none" and vc == "none":
            cand.append(f)
    # Предпочитаем m4a/mp3/ogg/opus по bitrate
    def score(f: Dict) -> float:
        ext = (f.get("ext") or "").lower()
        tbr = f.get("abr") or f.get("tbr") or 0
        s = float(tbr)
        if ext == "m4a":
            s += 20
        elif ext in ("mp3", "ogg", "opus"):
            s += 10
        size = f.get("filesize") or f.get("filesize_approx")
        if size:
            s += min(size / (1024 * 1024), 10)  # небольшой бонус
        return s

    cand.sort(key=score, reverse=True)
    return cand[0] if cand else None


def _pick_video_fmt(formats: List[Dict], max_height: Optional[int]) -> Optional[Dict]:
    cand = []
    for f in formats:
        ac = (f.get("acodec") or "none").lower()
        vc = (f.get("vcodec") or "none").lower()
        if vc != "none" and ac == "none":
            h = f.get("height") or 0
            if (max_height is None) or (h and h <= max_height):
                cand.append(f)

    def score(f: Dict) -> float:
        ext = (f.get("ext") or "").lower()
        h = f.get("height") or 0
        tbr = f.get("tbr") or 0
        s = float(h) / 10 + float(tbr)
        if ext == "mp4":
            s += 50
        return s

    cand.sort(key=score, reverse=True)
    return cand[0] if cand else None


def _pick_progressive_fmt(formats: List[Dict], max_height: Optional[int]) -> Optional[Dict]:
    cand = []
    for f in formats:
        ac = (f.get("acodec") or "none").lower()
        vc = (f.get("vcodec") or "none").lower()
        if vc != "none" and ac != "none":
            h = f.get("height") or 0
            if (max_height is None) or (h and h <= max_height):
                cand.append(f)

    def score(f: Dict) -> float:
        ext = (f.get("ext") or "").lower()
        h = f.get("height") or 0
        tbr = f.get("tbr") or 0
        s = float(h) / 10 + float(tbr)
        if ext == "mp4":
            s += 50
        return s

    cand.sort(key=score, reverse=True)
    return cand[0] if cand else None


def _fmt_selector(kind: str, quality: str, limit_mb: Optional[int] = None) -> str:
    # kind: 'va' | 'v' | 'a'; quality: 'best'|'1080'|'720'|'480'|'360'
    limit = _format_limit_str(limit_mb * 1024 * 1024) if limit_mb else None

    hsel = ""
    if quality.isdigit():
        hsel = f"[height<=?{quality}]"

    if kind == "a":
        base = "bestaudio[ext=m4a]/bestaudio/best"
        return base
    if kind == "v":
        parts = [
            f"bestvideo[ext=mp4]{hsel}",
            f"/bestvideo{hsel}",
        ]
        s = "".join(parts)
        return s
    # kind == 'va'
    parts = [
        f"bestvideo[ext=mp4]{hsel}+bestaudio[ext=m4a]",
        f"/best{hsel}[ext=mp4]",
        f"/best{hsel}",
    ]
    s = "".join(parts)
    if limit:
        # yt-dlp не позволяет легко ограничить суммарный размер, поэтому оставляем без ограничения здесь
        return s
    return s


def _estimate_sizes(info: dict) -> List[FormatOption]:
    formats = info.get("formats") or []
    opts: List[FormatOption] = []
    heights = [1080, 720, 480, 360]
    aud = _pick_audio_fmt(formats)
    aud_size = (aud.get("filesize") or aud.get("filesize_approx")) if aud else None

    # Audio only
    opts.append(
        FormatOption(
            kind="a",
            quality="best",
            est_size=aud_size,
            label=f"Только аудио (~{_human_size(aud_size)})",
            bitrate_k=(aud.get("abr") or aud.get("tbr")) if aud else None,
            ext=(aud.get("ext") if aud else None),
        )
    )

    # Video only for heights
    for h in heights:
        v = _pick_video_fmt(formats, h)
        v_size = (v.get("filesize") or v.get("filesize_approx")) if v else None
        opts.append(
            FormatOption(
                kind="v",
                quality=str(h),
                est_size=v_size,
                label=f"Только видео {h}p (~{_human_size(v_size)})",
                height=h,
                bitrate_k=(v.get("tbr") if v else None),
                ext=(v.get("ext") if v else None),
            )
        )

    # Video+audio
    for h in heights:
        v = _pick_video_fmt(formats, h)
        if v and aud:
            v_size = (v.get("filesize") or v.get("filesize_approx"))
            est = (v_size or 0) + (aud_size or 0)
        else:
            # Фолбек — прогрессивный формат
            p = _pick_progressive_fmt(formats, h)
            est = (p.get("filesize") or p.get("filesize_approx")) if p else None
            v = p or v
        opts.append(
            FormatOption(
                kind="va",
                quality=str(h),
                est_size=est,
                label=f"Видео+аудио {h}p (~{_human_size(est)})",
                height=h,
                bitrate_k=(v.get("tbr") if v else None) if v else None,
                ext=(v.get("ext") if v else None) if v else None,
            )
        )

    # Best VA
    pbest = _pick_progressive_fmt(formats, None)
    est_best = (pbest.get("filesize") or pbest.get("filesize_approx")) if pbest else None
    opts.insert(
        0,
        FormatOption(
            kind="va",
            quality="best",
            est_size=est_best,
            label=f"Лучшее качество (~{_human_size(est_best)})",
            height=(pbest.get("height") if pbest else None) if pbest else None,
            bitrate_k=(pbest.get("tbr") if pbest else None) if pbest else None,
            ext=(pbest.get("ext") if pbest else None) if pbest else None,
        ),
    )
    return opts


def get_basic_info(url: str) -> BasicInfo:
    info, _ = _extract_info(url)
    if not isinstance(info, dict):
        return BasicInfo(None, None, None, None, None)
    w = None
    h = None
    # Try general fields first
    if info.get("width") or info.get("height"):
        w = info.get("width")
        h = info.get("height")
    else:
        fmts = info.get("formats") or []
        for f in fmts:
            if f.get("vcodec") and f.get("vcodec") != "none":
                w = f.get("width") or w
                h = f.get("height") or h
                if w and h:
                    break
    return BasicInfo(
        title=info.get("title"),
        duration=info.get("duration"),
        thumbnail=info.get("thumbnail"),
        width=w,
        height=h,
    )


def _download_with_selector(
    url: str,
    selector: str,
    on_progress: Optional[Callable[[str, int, Optional[int], Optional[float], Optional[float]], None]] = None,
) -> DownloadResult:
    temp_dir = tempfile.mkdtemp(prefix="dlyt_")
    def _hook(d: Dict):
        if not on_progress:
            return
        status = d.get("status") or ""
        if status == "downloading":
            downloaded = int(d.get("downloaded_bytes") or 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            speed = d.get("speed")
            eta = d.get("eta")
            on_progress(
                "downloading",
                downloaded,
                int(total) if total else None,
                float(speed) if speed else None,
                float(eta) if eta else None,
            )
        elif status == "finished":
            on_progress("finished", int(d.get("downloaded_bytes") or 0), int(d.get("total_bytes") or 0), None, None)

    ydl_opts = {
        "format": selector,
        "outtmpl": os.path.join(temp_dir, "%(title).180B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": False,
        "merge_output_format": "mp4",
        "postprocessors": [
            {
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }
        ],
        "progress_hooks": [_hook],
    }
    try:
        with ytdlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = None
            if isinstance(info, dict):
                req = info.get("requested_downloads") or []
                for r in req:
                    fp = r.get("filepath")
                    if fp and os.path.exists(fp):
                        filepath = fp
                        break
                if not filepath:
                    filepath = info.get("_filename")
            if not filepath or not os.path.exists(filepath):
                files = [
                    os.path.join(temp_dir, f)
                    for f in os.listdir(temp_dir)
                    if os.path.isfile(os.path.join(temp_dir, f))
                ]
                if files:
                    filepath = files[0]
            size = os.path.getsize(filepath) if filepath and os.path.exists(filepath) else None
            kind = _pick_kind(info) if isinstance(info, dict) else "document"
            return DownloadResult(
                ok=True,
                filepath=filepath,
                title=(info or {}).get("title"),
                ext=(info or {}).get("ext"),
                filesize=size,
                duration=(info or {}).get("duration"),
                thumbnail=(info or {}).get("thumbnail"),
                webpage_url=(info or {}).get("webpage_url") or url,
                direct_url=None,
                kind=kind,
            )
    except Exception as e:  # noqa: BLE001
        info, _ = _extract_info(url)
        return DownloadResult(
            ok=False,
            filepath=None,
            title=(info or {}).get("title") if info else None,
            ext=(info or {}).get("ext") if info else None,
            filesize=None,
            duration=(info or {}).get("duration") if info else None,
            thumbnail=(info or {}).get("thumbnail") if info else None,
            webpage_url=(info or {}).get("webpage_url") if info else None,
            direct_url=_best_direct_url(info, MAX_FILE_MB * 1024 * 1024) if info else None,
            kind=_pick_kind(info) if info else None,
            error=str(e),
        )


async def probe_media_options(url: str) -> List[FormatOption]:
    info, err = await asyncio.to_thread(_extract_info, url)
    if not info:
        return []
    return _estimate_sizes(info)


async def download_media_selected(
    url: str,
    kind: str,
    quality: str,
    progress: Optional[Callable[[str, int, Optional[int], Optional[float], Optional[float]], None]] = None,
) -> DownloadResult:
    selector = _fmt_selector(kind, quality)
    loop = asyncio.get_running_loop()

    def _safe_progress(status: str, downloaded: int, total: Optional[int], speed: Optional[float], eta: Optional[float]) -> None:
        if progress is None:
            return
        try:
            import asyncio as _asyncio  # local alias
            loop.call_soon_threadsafe(_asyncio.create_task, progress(status, downloaded, total, speed, eta))
        except Exception:
            pass

    return await asyncio.to_thread(_download_with_selector, url, selector, _safe_progress)
