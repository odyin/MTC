"""Load and normalize TAIEX futures OHLCV data."""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import time
from src.utils.taiex import is_day_session, is_night_session


def load_csv(filepath: str | Path, datetime_col: str = "datetime") -> pd.DataFrame:
    """Load OHLCV data from CSV file.

    Expected columns: datetime, open, high, low, close, volume
    Returns DataFrame with DatetimeIndex.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Data file not found: {filepath}")

    df = pd.read_csv(filepath, parse_dates=[datetime_col])
    df = df.rename(columns={datetime_col: "datetime"})
    df = df.set_index("datetime").sort_index()

    # Normalize column names to lowercase
    df.columns = [c.lower().strip() for c in df.columns]

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Drop rows with NaN in OHLC
    df = df.dropna(subset=["open", "high", "low", "close"])

    # Ensure numeric types
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


def filter_session(df: pd.DataFrame, session: str = "day") -> pd.DataFrame:
    """Filter data by trading session.

    Args:
        session: "day", "night", or "both"
    """
    if session == "both":
        return df

    times = df.index.time
    if session == "day":
        mask = np.array([is_day_session(t) for t in times])
    elif session == "night":
        mask = np.array([is_night_session(t) for t in times])
    else:
        raise ValueError(f"Unknown session: {session}. Use 'day', 'night', or 'both'")

    return df[mask]


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample OHLCV data to a different timeframe.

    Args:
        timeframe: pandas-compatible frequency string, e.g. "5min", "15min", "1h"
    """
    # Map common shorthand to pandas freq strings
    freq_map = {
        "1m": "1min", "5m": "5min", "15m": "15min",
        "30m": "30min", "60m": "1h", "1h": "1h",
        "daily": "1D", "1d": "1D",
    }
    freq = freq_map.get(timeframe, timeframe)

    resampled = df.resample(freq).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    return resampled


def prepare_data(
    filepath: str | Path,
    timeframe: str | None = None,
    session: str = "day",
) -> pd.DataFrame:
    """Full pipeline: load CSV -> filter session -> resample."""
    df = load_csv(filepath)
    df = filter_session(df, session)
    if timeframe:
        df = resample_ohlcv(df, timeframe)
    return df
