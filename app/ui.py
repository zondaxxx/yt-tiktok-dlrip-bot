def human_size(nbytes: int | None) -> str:
    if not nbytes or nbytes < 0:
        return "?"
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    size = float(nbytes)
    for u in units:
        if size < 1024 or u == units[-1]:
            val = f"{size:.1f}".rstrip("0").rstrip(".")
            return f"{val} {u}"
        size /= 1024
    return f"{nbytes} Б"


def human_time(seconds: float | int | None) -> str:
    if seconds is None or seconds < 0:
        return "?"
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def progress_bar(pct: float, width: int = 18) -> str:
    if pct < 0:
        pct = 0
    if pct > 100:
        pct = 100
    filled = int(round(width * pct / 100.0))
    return "▰" * filled + "▱" * (width - filled)

