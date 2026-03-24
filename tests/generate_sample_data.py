"""Generate synthetic TAIEX futures OHLCV data for testing."""

import numpy as np
import pandas as pd
from pathlib import Path


def generate_sample_data(
    output_path: str = "data/processed/TX_5m_sample.csv",
    num_days: int = 60,
    bars_per_day: int = 60,  # ~5min bars in day session (8:45-13:45 = 5h = 60 bars)
    base_price: float = 17000,
    volatility: float = 30,
    trend: float = 0.5,
    seed: int = 42,
):
    """Generate realistic-looking synthetic OHLCV data.

    Creates data with trends, mean-reversion, and volatility clustering
    to make backtesting meaningful.
    """
    np.random.seed(seed)

    total_bars = num_days * bars_per_day
    dates = []
    current_date = pd.Timestamp("2024-01-02 08:45:00")

    for day in range(num_days):
        day_start = current_date + pd.Timedelta(days=day)
        # Skip weekends
        while day_start.weekday() >= 5:
            day_start += pd.Timedelta(days=1)

        for bar in range(bars_per_day):
            bar_time = day_start + pd.Timedelta(minutes=5 * bar)
            dates.append(bar_time)

    dates = dates[:total_bars]

    # Generate price series with trend + noise + mean reversion
    prices = np.zeros(total_bars)
    prices[0] = base_price

    for i in range(1, total_bars):
        # Add trend component
        trend_component = trend * np.random.randn()

        # Add volatility clustering (GARCH-like)
        vol = volatility * (1 + 0.3 * np.sin(2 * np.pi * i / (bars_per_day * 5)))

        # Mean reversion towards base
        mean_rev = -0.001 * (prices[i - 1] - base_price)

        # Random walk
        noise = vol * np.random.randn() / np.sqrt(bars_per_day)

        prices[i] = prices[i - 1] + trend_component + mean_rev + noise

    # Generate OHLCV from close prices
    opens = np.zeros(total_bars)
    highs = np.zeros(total_bars)
    lows = np.zeros(total_bars)
    closes = prices.copy()
    volumes = np.zeros(total_bars)

    opens[0] = prices[0]
    for i in range(1, total_bars):
        opens[i] = closes[i - 1] + np.random.randn() * 2

    for i in range(total_bars):
        spread = abs(np.random.randn() * volatility * 0.3)
        highs[i] = max(opens[i], closes[i]) + abs(spread)
        lows[i] = min(opens[i], closes[i]) - abs(spread)
        volumes[i] = max(100, int(np.random.exponential(500) + 200))

    # Round to integer (TAIEX tick = 1 point)
    opens = np.round(opens).astype(int)
    highs = np.round(highs).astype(int)
    lows = np.round(lows).astype(int)
    closes = np.round(closes).astype(int)
    volumes = volumes.astype(int)

    df = pd.DataFrame({
        "datetime": dates[:total_bars],
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Generated {total_bars} bars of sample data -> {output_path}")
    return output_path


if __name__ == "__main__":
    generate_sample_data()
