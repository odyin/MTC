"""Technical indicator calculations using numpy/pandas.

All functions return pd.Series aligned with the input data index.
"""

import numpy as np
import pandas as pd


# --- Moving Averages ---

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def wma(series: pd.Series, period: int) -> pd.Series:
    """Weighted Moving Average."""
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(window=period, min_periods=period).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )


def moving_average(series: pd.Series, period: int, method: str = "SMA") -> pd.Series:
    """Generic moving average dispatcher."""
    dispatch = {"SMA": sma, "EMA": ema, "WMA": wma}
    method = method.upper()
    if method not in dispatch:
        raise ValueError(f"Unknown MA method: {method}. Available: {list(dispatch.keys())}")
    return dispatch[method](series, period)


# --- RSI ---

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# --- MACD ---

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, pd.Series]:
    """MACD indicator. Returns dict with 'macd', 'signal', 'histogram'."""
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


# --- Bollinger Bands ---

def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict[str, pd.Series]:
    """Bollinger Bands. Returns dict with 'upper', 'middle', 'lower', 'bandwidth'."""
    middle = sma(series, period)
    rolling_std = series.rolling(window=period, min_periods=period).std()
    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std
    bandwidth = (upper - lower) / middle
    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "bandwidth": bandwidth,
    }


# --- KD Stochastic ---

def stochastic_kd(
    high: pd.Series, low: pd.Series, close: pd.Series,
    k_period: int = 9, k_smooth: int = 3, d_smooth: int = 3,
) -> dict[str, pd.Series]:
    """KD Stochastic oscillator. Returns dict with 'k' and 'd'."""
    lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
    highest_high = high.rolling(window=k_period, min_periods=k_period).max()

    raw_k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    k = sma(raw_k, k_smooth)
    d = sma(k, d_smooth)
    return {"k": k, "d": d}


# --- ATR ---

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


# --- Helper: cross detection ---

def crosses_above(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """Returns True on bars where series_a crosses above series_b."""
    prev_a = series_a.shift(1)
    prev_b = series_b.shift(1)
    return (prev_a <= prev_b) & (series_a > series_b)


def crosses_below(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """Returns True on bars where series_a crosses below series_b."""
    prev_a = series_a.shift(1)
    prev_b = series_b.shift(1)
    return (prev_a >= prev_b) & (series_a < series_b)
