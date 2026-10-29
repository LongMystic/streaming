"""Price rules (tick size, price band) and the intraday price path model."""
from __future__ import annotations

import math

import numpy as np

from .calendar_vn import N_MINUTES


def tick_size(exchange: str | None, instrument_type: str, price: float) -> int:
    if exchange == "HOSE":
        if instrument_type != "STOCK":
            return 10
        if price < 10_000:
            return 10
        if price < 50_000:
            return 50
        return 100
    if instrument_type == "COVERED_WARRANT":
        return 10
    return 100


def round_to_tick(price: float, exchange: str | None, instrument_type: str, mode: str = "nearest") -> int:
    tick = tick_size(exchange, instrument_type, price)
    units = price / tick
    if mode == "down":
        units = math.floor(units + 1e-9)
    elif mode == "up":
        units = math.ceil(units - 1e-9)
    else:
        units = round(units)
    return max(tick, int(units) * tick)


def price_limits(reference: int, band_pct: float, exchange: str | None, instrument_type: str) -> tuple[int, int]:
    """(floor, ceiling): ceiling rounds down and floor rounds up to the tick so both stay inside the band."""
    ceiling = round_to_tick(reference * (1 + band_pct / 100), exchange, instrument_type, "down")
    floor = round_to_tick(reference * (1 - band_pct / 100), exchange, instrument_type, "up")
    return floor, max(ceiling, floor)


def _ticks_array(prices: np.ndarray, exchange: str | None, instrument_type: str) -> np.ndarray:
    if exchange == "HOSE" and instrument_type == "STOCK":
        return np.where(prices < 10_000, 10, np.where(prices < 50_000, 50, 100))
    if exchange == "HOSE" or instrument_type == "COVERED_WARRANT":
        return np.full(prices.shape, 10)
    return np.full(prices.shape, 100)


def intraday_path(rng: np.random.Generator, reference: int, floor: int, ceiling: int, daily_return: float,
                  sigma: float, exchange: str | None, instrument_type: str) -> tuple[int, np.ndarray, int]:
    """Open price, per-minute continuous-session prices (N_MINUTES ints) and close price.

    The close is drawn from the daily return; the path is a Brownian bridge between open and
    close in log space, clipped to the price band and rounded to valid ticks."""
    def clip_round(x: np.ndarray) -> np.ndarray:
        x = np.clip(x, floor, ceiling)
        ticks = _ticks_array(x, exchange, instrument_type)
        return np.clip(np.round(x / ticks) * ticks, floor, ceiling).astype(np.int64)

    close = int(clip_round(np.array([reference * math.exp(daily_return)]))[0])
    open_ = int(clip_round(np.array([reference * math.exp(rng.normal(0, sigma * 0.35))]))[0])
    t = np.arange(1, N_MINUTES + 1) / N_MINUTES
    walk = np.cumsum(rng.normal(0, sigma * 0.7 / math.sqrt(N_MINUTES), N_MINUTES))
    bridge = walk - t * walk[-1]
    log_path = math.log(open_) + t * (math.log(close) - math.log(open_)) + bridge
    path = clip_round(np.exp(log_path))
    path[-1] = close
    return open_, path, close
