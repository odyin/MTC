"""Tests for backtest engine."""

import pytest
import pandas as pd
import numpy as np
from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.metrics import calculate_metrics, _max_consecutive


@pytest.fixture
def trending_up_data():
    """Create OHLCV data with a clear uptrend for testing MA crossover."""
    n = 200
    dates = pd.date_range("2024-01-02 08:45", periods=n, freq="5min")
    # Create a trend: first half sideways, then up
    close = np.concatenate([
        np.full(50, 17000.0),
        np.linspace(17000, 17500, 100),
        np.full(50, 17500.0),
    ])
    # Add small noise
    np.random.seed(42)
    close = close + np.random.randn(n) * 5
    open_ = close + np.random.randn(n) * 2
    high = np.maximum(close, open_) + abs(np.random.randn(n) * 3)
    low = np.minimum(close, open_) - abs(np.random.randn(n) * 3)
    volume = np.random.randint(100, 1000, n)

    df = pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    }, index=dates)
    return df


@pytest.fixture
def simple_ma_config():
    """Simple MA crossover strategy config."""
    return {
        "name": "Test_MA_Cross",
        "version": "1.0",
        "instrument": "TX",
        "indicators": [
            {
                "type": "ma", "name": "fast_ma",
                "params": {"period": 5, "method": "SMA", "source": "close"},
            },
            {
                "type": "ma", "name": "slow_ma",
                "params": {"period": 20, "method": "SMA", "source": "close"},
            },
        ],
        "entry": {
            "long": {"condition": "fast_ma crosses_above slow_ma", "contracts": 1},
            "short": {"condition": "fast_ma crosses_below slow_ma", "contracts": 1},
        },
        "exit": {
            "stop_loss": {"type": "points", "value": 100},
            "take_profit": {"type": "points", "value": 200},
            "trailing_stop": {"enabled": False},
            "time_exit": {"enabled": False},
        },
        "risk": {
            "max_positions": 1,
            "max_daily_loss": 0,
            "session_filter": "both",
        },
    }


class TestBacktestEngine:
    def test_engine_runs(self, simple_ma_config, trending_up_data):
        engine = BacktestEngine(simple_ma_config)
        result = engine.run(df=trending_up_data)
        assert isinstance(result, BacktestResult)
        assert isinstance(result.metrics.total_trades, int)
        assert len(result.equity_curve) > 0

    def test_params_override(self, simple_ma_config, trending_up_data):
        overrides = {"fast_ma.period": 3, "slow_ma.period": 10}
        engine = BacktestEngine(simple_ma_config, params=overrides)
        assert engine.params["fast_ma.period"] == 3
        assert engine.params["slow_ma.period"] == 10

    def test_no_data_raises(self, simple_ma_config):
        engine = BacktestEngine(simple_ma_config)
        with pytest.raises(ValueError):
            engine.run()


class TestMetrics:
    def test_empty_trades(self):
        metrics = calculate_metrics([])
        assert metrics.total_trades == 0
        assert metrics.net_profit == 0

    def test_all_winning(self):
        trades = [{"pnl": 1000, "bars_held": 5} for _ in range(10)]
        metrics = calculate_metrics(trades)
        assert metrics.win_rate == 1.0
        assert metrics.net_profit == 10000
        assert metrics.max_consecutive_wins == 10

    def test_mixed_trades(self):
        trades = [
            {"pnl": 2000, "bars_held": 3},
            {"pnl": -500, "bars_held": 2},
            {"pnl": 1500, "bars_held": 4},
            {"pnl": -1000, "bars_held": 1},
        ]
        metrics = calculate_metrics(trades)
        assert metrics.total_trades == 4
        assert metrics.winning_trades == 2
        assert metrics.losing_trades == 2
        assert metrics.net_profit == 2000
        assert metrics.win_rate == 0.5

    def test_max_consecutive(self):
        mask = np.array([True, True, False, True, True, True, False])
        assert _max_consecutive(mask) == 3

    def test_profit_factor(self):
        trades = [
            {"pnl": 3000, "bars_held": 1},
            {"pnl": -1000, "bars_held": 1},
        ]
        metrics = calculate_metrics(trades)
        assert metrics.profit_factor == pytest.approx(3.0)
