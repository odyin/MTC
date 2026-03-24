"""Tests for optimizer modules."""

import pytest
import yaml
from src.optimizer.grid import extract_param_ranges


class TestParamExtraction:
    def test_extract_ranges(self):
        config = {
            "indicators": [
                {
                    "type": "ma", "name": "fast_ma",
                    "params": {
                        "period": {"default": 10, "min": 5, "max": 20, "step": 5},
                        "method": "SMA",
                    },
                },
            ],
        }
        ranges = extract_param_ranges(config)
        assert "fast_ma.period" in ranges
        assert ranges["fast_ma.period"] == [5, 10, 15, 20]
        # Non-range params should not be included
        assert "fast_ma.method" not in ranges

    def test_no_ranges(self):
        config = {
            "indicators": [
                {
                    "type": "ma", "name": "ma1",
                    "params": {"period": 10, "method": "SMA"},
                },
            ],
        }
        ranges = extract_param_ranges(config)
        assert len(ranges) == 0

    def test_multiple_indicators(self):
        with open("strategies/examples/ma_cross.yaml") as f:
            config = yaml.safe_load(f)
        ranges = extract_param_ranges(config)
        assert "fast_ma.period" in ranges
        assert "slow_ma.period" in ranges
