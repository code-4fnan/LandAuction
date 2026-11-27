"""Display formatting: money, durations and local times."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def group_indian(n: int) -> str:
    """12345678 -> '1,23,45,678' (Indian digit grouping)."""
    sign = "-" if n < 0 else ""
    s = str(abs(int(n)))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join(groups + [tail])


def money(n: int | float, symbol: str = "₹") -> str:
    if symbol == "₹":
        return f"₹{group_indian(round(n))}"
    return f"{symbol}{round(n):,}"


def money_compact(n: int | float, symbol: str = "₹") -> str:
    """Short form for metrics: ₹4.5 L, ₹1.20 Cr (or K/M/B for other currencies)."""
    n = float(n)
    if symbol == "₹":
        if n >= 1e7:
            return f"₹{n / 1e7:,.2f} Cr"
        if n >= 1e5:
            return f"₹{n / 1e5:,.1f} L"
        return money(n, symbol)
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            return f"{symbol}{n / div:,.1f}{suffix}"
    return money(n, symbol)


def duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    d, rem = divmod(seconds, 86_400)
    h, rem = divmod(rem, 3_600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m {s:02d}s"
    return f"{m}m {s:02d}s"


def to_local(dt_utc: datetime, tz_name: str) -> datetime:
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))


def local_str(dt_utc: datetime, tz_name: str) -> str:
    return to_local(dt_utc, tz_name).strftime("%d %b %Y, %I:%M %p %Z")


def local_to_utc(dt_local_naive: datetime, tz_name: str) -> datetime:
    aware = dt_local_naive.replace(tzinfo=ZoneInfo(tz_name))
    return aware.astimezone(timezone.utc).replace(tzinfo=None)
