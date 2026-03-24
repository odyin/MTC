"""Tests for technical indicators."""

import pytest
import pandas as pd
import numpy as np
from src.backtest.indicators import (
    sma, ema, wma, moving_average, rsi, macd, bollinger_bands,
    stochastic_kd, atr, crosses_above, crosses_below,
)


@pytest.fixture
def sample_series():
    """Simple price series for testing."""
    return pd.Series([10, 11, 12, 13, 14, 15, 14, 13, 12, 11, 10, 11, 12, 13, 14])


@pytest.fixture
def ohlcv_data():
    """OHLCV data for testing."""
    np.random.seed(42)
    n = 50
    close = pd.Series(np.cumsum(np.random.randn(n)) + 100)
    high = close + abs(np.random.randn(n))
    low = close - abs(np.random.randn(n))
    return high, low, close


class TestMovingAverages:
    def test_sma_basic(self, sample_series):
        result = sma(sample_series, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == pytest.approx(11.0)  # (10+11+12)/3
        assert result.iloc[3] == pytest.approx(12.0)  # (11+12+13)/3

    def test_ema_length(self, sample_series):
        result = ema(sample_series, 5)
        assert len(result) == len(sample_series)
        assert pd.isna(result.iloc[3])
        assert not pd.isna(result.iloc[4])

    def test_wma_basic(self, sample_series):
        result = wma(sample_series, 3)
        assert len(result) == len(sample_series)
        # WMA(10,11,12) with weights 1,2,3 = (10*1 + 11*2 + 12*3)/(1+2+3) = 68/6
        assert result.iloc[2] == pytest.approx(68 / 6, rel=1e-4)

    def test_moving_average_dispatch(self, sample_series):
        sma_result = moving_average(sample_series, 3, "SMA")
        ema_result = moving_average(sample_series, 3, "EMA")
        assert not sma_result.equals(ema_result)

    def test_unknown_ma_method(self, sample_series):
        with pytest.raises(ValueError, match="Unknown MA method"):
            moving_average(sample_series, 3, "INVALID")


class TestRSI:
    def test_rsi_range(self, sample_series):
        result = rsi(sample_series, 5)
        valid = result.dropna()
        assert all(0 <= v <= 100 for v in valid)

    def test_rsi_trending_up(self):
        # Use data with mostly up moves but some down to avoid division by zero
        np.random.seed(42)
        changes = np.random.randn(100) + 0.5  # biased upward
        up = pd.Series(np.cumsum(changes) + 100)
        result = rsi(up, 14)
        valid = result.dropna()
        assert len(valid) > 0
        assert valid.iloc[-1] > 50


class TestMACD:
    def test_macd_structure(self, sample_series):
        result = macd(sample_series, fast=3, slow=5, signal=3)
        assert "macd" in result
        assert "signal" in result
        assert "histogram" in result
        assert len(result["macd"]) == len(sample_series)


class TestBollinger:
    def test_bollinger_structure(self, sample_series):
        result = bollinger_bands(sample_series, period=5, std_dev=2.0)
        assert "upper" in result
        assert "middle" in result
        assert "lower" in result
        # Upper should be above middle, lower below
        valid_idx = result["middle"].dropna().index
        for idx in valid_idx:
            assert result["upper"][idx] >= result["middle"][idx]
            assert result["lower"][idx] <= result["middle"][idx]


class TestKD:
    def test_kd_structure(self, ohlcv_data):
        high, low, close = ohlcv_data
        result = stochastic_kd(high, low, close, k_period=9, k_smooth=3, d_smooth=3)
        assert "k" in result
        assert "d" in result


class TestATR:
    def test_atr_positive(self, ohlcv_data):
        high, low, close = ohlcv_data
        result = atr(high, low, close, period=5)
        valid = result.dropna()
        assert all(v >= 0 for v in valid)


class TestCross:
    def test_crosses_above(self):
        a = pd.Series([1, 2, 3, 4, 5])
        b = pd.Series([3, 3, 3, 3, 3])
        result = crosses_above(a, b)
        # a crosses above b between index 2 and 3 (a goes from 3 to 4, b stays at 3)
        assert result.iloc[3] == True

    def test_crosses_below(self):
        a = pd.Series([5, 4, 3, 2, 1])
        b = pd.Series([3, 3, 3, 3, 3])
        result = crosses_below(a, b)
        assert result.iloc[3] == True
