"""Vietnamese exchange trading calendar and intraday session clock."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

VN_TZ = timezone(timedelta(hours=7))

# Exchange holidays (inclusive ranges). 2024-2025 follow the published schedules;
# 2026 is an estimate - check the official exchange calendar before relying on it.
_HOLIDAYS: list[tuple[date, date, str]] = [
    (date(2023, 9, 1), date(2023, 9, 4), "Quốc khánh"),
    (date(2024, 1, 1), date(2024, 1, 1), "Tết Dương lịch"),
    (date(2024, 2, 8), date(2024, 2, 14), "Tết Nguyên đán"),
    (date(2024, 4, 18), date(2024, 4, 18), "Giỗ Tổ Hùng Vương"),
    (date(2024, 4, 29), date(2024, 5, 1), "Giải phóng miền Nam và Quốc tế Lao động"),
    (date(2024, 9, 2), date(2024, 9, 3), "Quốc khánh"),
    (date(2025, 1, 1), date(2025, 1, 1), "Tết Dương lịch"),
    (date(2025, 1, 27), date(2025, 1, 31), "Tết Nguyên đán"),
    (date(2025, 4, 7), date(2025, 4, 7), "Giỗ Tổ Hùng Vương"),
    (date(2025, 4, 30), date(2025, 5, 1), "Giải phóng miền Nam và Quốc tế Lao động"),
    (date(2025, 9, 1), date(2025, 9, 2), "Quốc khánh"),
    (date(2026, 1, 1), date(2026, 1, 2), "Tết Dương lịch"),
    (date(2026, 2, 16), date(2026, 2, 20), "Tết Nguyên đán"),
    (date(2026, 4, 27), date(2026, 4, 27), "Giỗ Tổ Hùng Vương"),
    (date(2026, 4, 30), date(2026, 5, 1), "Giải phóng miền Nam và Quốc tế Lao động"),
    (date(2026, 9, 1), date(2026, 9, 2), "Quốc khánh"),
]


@lru_cache(maxsize=1)
def holidays() -> dict[date, str]:
    result: dict[date, str] = {}
    for start, end, name in _HOLIDAYS:
        d = start
        while d <= end:
            result[d] = name
            d += timedelta(days=1)
    return result


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays()


def trading_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
    return days


def add_trading_days(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    while remaining:
        d += timedelta(days=step)
        if is_trading_day(d):
            remaining -= 1
    return d


def next_trading_day(d: date) -> date:
    return add_trading_days(d, 1)


def first_trading_day_on_or_after(d: date) -> date:
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def vn_time(d: date, hour: int, minute: int = 0, second: float = 0.0) -> datetime:
    """Local Vietnam wall-clock time on business date d, returned as an aware UTC datetime."""
    local = datetime(d.year, d.month, d.day, hour, minute, tzinfo=VN_TZ) + timedelta(seconds=second)
    return local.astimezone(timezone.utc)


# Continuous-matching minutes (HOSE model): 09:15-11:29 and 13:00-14:29.
CONTINUOUS_MINUTES: list[tuple[int, int]] = (
    [(9, m) for m in range(15, 60)] + [(10, m) for m in range(60)] + [(11, m) for m in range(30)]
    + [(13, m) for m in range(60)] + [(14, m) for m in range(30)]
)
N_MINUTES = len(CONTINUOUS_MINUTES)  # 225


def minute_time(d: date, index: int, second: float = 0.0) -> datetime:
    hour, minute = CONTINUOUS_MINUTES[index]
    return vn_time(d, hour, minute, second)


def minute_index(d: date, t: datetime) -> int:
    """Index of the continuous minute containing t, clamped to the session.
    Times in the lunch break map to the first afternoon minute."""
    local = t.astimezone(VN_TZ)
    hm = (local.hour, local.minute)
    if hm < (9, 15):
        return 0
    if hm >= (14, 30):
        return N_MINUTES - 1
    if (11, 30) <= hm < (13, 0):
        return 135
    if hm < (11, 30):
        return (local.hour - 9) * 60 + local.minute - 15
    return 135 + (local.hour - 13) * 60 + local.minute
