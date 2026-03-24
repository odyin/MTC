"""TAIEX Futures domain constants and helpers."""

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class InstrumentSpec:
    """Specification for a TAIEX futures instrument."""
    symbol: str
    name: str
    point_value: float      # TWD per point
    tick_size: float         # minimum price movement
    commission: float        # TWD per round trip (estimate)
    margin: float            # TWD required margin (estimate)


# Instrument definitions
TX = InstrumentSpec(
    symbol="TX",
    name="台指期 (TAIEX Futures)",
    point_value=200.0,
    tick_size=1.0,
    commission=80.0,
    margin=184000.0,
)

MTX = InstrumentSpec(
    symbol="MTX",
    name="小台指 (Mini-TAIEX Futures)",
    point_value=50.0,
    tick_size=1.0,
    commission=40.0,
    margin=46000.0,
)

INSTRUMENTS = {"TX": TX, "MTX": MTX}

# Session times (Asia/Taipei)
DAY_SESSION_START = time(8, 45)
DAY_SESSION_END = time(13, 45)
NIGHT_SESSION_START = time(15, 0)
NIGHT_SESSION_END = time(5, 0)  # next day


def get_instrument(symbol: str) -> InstrumentSpec:
    """Get instrument spec by symbol."""
    symbol = symbol.upper()
    if symbol not in INSTRUMENTS:
        raise ValueError(f"Unknown instrument: {symbol}. Available: {list(INSTRUMENTS.keys())}")
    return INSTRUMENTS[symbol]


def is_day_session(t: time) -> bool:
    """Check if a time falls within the day session."""
    return DAY_SESSION_START <= t <= DAY_SESSION_END


def is_night_session(t: time) -> bool:
    """Check if a time falls within the night session."""
    return t >= NIGHT_SESSION_START or t <= NIGHT_SESSION_END


def calculate_trade_cost(instrument: InstrumentSpec, slippage_ticks: int = 1) -> float:
    """Calculate total cost per round-trip trade (commission + slippage)."""
    slippage_cost = slippage_ticks * instrument.tick_size * instrument.point_value * 2
    return instrument.commission + slippage_cost
