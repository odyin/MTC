"""Core backtest engine for TAIEX futures strategies.

Mirrors MultiCharts execution semantics:
- Bar-by-bar iteration (no look-ahead)
- Next-bar-at-market order execution
- Position tracking: long/short/flat
"""

import numpy as np
import pandas as pd
import yaml
from pathlib import Path
from dataclasses import dataclass, field

from src.backtest import indicators as ind
from src.backtest.data_loader import prepare_data
from src.backtest.metrics import calculate_metrics, BacktestMetrics
from src.utils.taiex import get_instrument, calculate_trade_cost


@dataclass
class Position:
    direction: str          # "long" or "short"
    entry_price: float
    entry_bar: int
    entry_time: object      # datetime
    contracts: int = 1


@dataclass
class Trade:
    direction: str
    entry_price: float
    entry_time: object
    exit_price: float
    exit_time: object
    pnl: float
    bars_held: int
    exit_reason: str
    contracts: int = 1

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "entry_price": self.entry_price,
            "entry_time": str(self.entry_time),
            "exit_price": self.exit_price,
            "exit_time": str(self.exit_time),
            "pnl": self.pnl,
            "bars_held": self.bars_held,
            "exit_reason": self.exit_reason,
            "contracts": self.contracts,
        }


@dataclass
class BacktestResult:
    trades: list[Trade]
    metrics: BacktestMetrics
    equity_curve: list[float]
    params: dict


class BacktestEngine:
    """Bar-by-bar backtest engine."""

    def __init__(self, config: dict, params: dict | None = None):
        """
        Args:
            config: Strategy YAML config as dict
            params: Optional parameter overrides (for optimization)
        """
        self.config = config
        self.params = self._resolve_params(config, params)
        self.instrument = get_instrument(config.get("instrument", "TX").replace("_FUT", "").replace("TAIEX", "TX"))
        self.trade_cost = calculate_trade_cost(
            self.instrument,
            slippage_ticks=config.get("backtest_settings", {}).get("slippage_ticks", 1),
        )

    def _resolve_params(self, config: dict, overrides: dict | None) -> dict:
        """Extract default params from config, apply overrides."""
        params = {}
        for indicator in config.get("indicators", []):
            name = indicator["name"]
            for pname, pval in indicator.get("params", {}).items():
                key = f"{name}.{pname}"
                if isinstance(pval, dict):
                    params[key] = pval.get("default", 0)
                else:
                    params[key] = pval

        # Exit params
        exit_cfg = config.get("exit", {})
        if "stop_loss" in exit_cfg:
            params["stop_loss"] = exit_cfg["stop_loss"].get("value", 0)
        if "take_profit" in exit_cfg:
            params["take_profit"] = exit_cfg["take_profit"].get("value", 0)
        if "trailing_stop" in exit_cfg:
            ts = exit_cfg["trailing_stop"]
            params["trailing_stop_enabled"] = ts.get("enabled", False)
            params["trailing_stop_value"] = ts.get("value", 0)

        # Risk params
        risk_cfg = config.get("risk", {})
        params["max_daily_loss"] = risk_cfg.get("max_daily_loss", 0)

        if overrides:
            params.update(overrides)
        return params

    def _get_param(self, name: str, default=None):
        return self.params.get(name, default)

    def _compute_indicators(self, df: pd.DataFrame) -> dict[str, pd.Series | dict]:
        """Compute all indicators defined in config."""
        computed = {}
        for indicator in self.config.get("indicators", []):
            itype = indicator["type"]
            iname = indicator["name"]

            if itype == "ma":
                period = int(self._get_param(f"{iname}.period", 20))
                method = self._get_param(f"{iname}.method", "SMA")
                source = self._get_param(f"{iname}.source", "close")
                computed[iname] = ind.moving_average(df[source], period, method)

            elif itype == "rsi":
                period = int(self._get_param(f"{iname}.period", 14))
                source = self._get_param(f"{iname}.source", "close")
                computed[iname] = ind.rsi(df[source], period)

            elif itype == "macd":
                fast = int(self._get_param(f"{iname}.fast", 12))
                slow = int(self._get_param(f"{iname}.slow", 26))
                signal = int(self._get_param(f"{iname}.signal", 9))
                source = self._get_param(f"{iname}.source", "close")
                result = ind.macd(df[source], fast, slow, signal)
                computed[f"{iname}_macd"] = result["macd"]
                computed[f"{iname}_signal"] = result["signal"]
                computed[f"{iname}_histogram"] = result["histogram"]

            elif itype == "bollinger":
                period = int(self._get_param(f"{iname}.period", 20))
                std_dev = float(self._get_param(f"{iname}.std_dev", 2.0))
                source = self._get_param(f"{iname}.source", "close")
                result = ind.bollinger_bands(df[source], period, std_dev)
                computed[f"{iname}_upper"] = result["upper"]
                computed[f"{iname}_middle"] = result["middle"]
                computed[f"{iname}_lower"] = result["lower"]
                computed[f"{iname}_bandwidth"] = result["bandwidth"]

            elif itype == "kd":
                k_period = int(self._get_param(f"{iname}.k_period", 9))
                k_smooth = int(self._get_param(f"{iname}.k_smooth", 3))
                d_smooth = int(self._get_param(f"{iname}.d_smooth", 3))
                result = ind.stochastic_kd(df["high"], df["low"], df["close"],
                                           k_period, k_smooth, d_smooth)
                computed[f"{iname}_k"] = result["k"]
                computed[f"{iname}_d"] = result["d"]

            elif itype == "atr":
                period = int(self._get_param(f"{iname}.period", 14))
                computed[iname] = ind.atr(df["high"], df["low"], df["close"], period)

        return computed

    def _evaluate_condition(self, condition: str, indicators: dict,
                            df: pd.DataFrame, bar: int) -> bool:
        """Evaluate an entry/exit condition string at a specific bar.

        Supported operators: crosses_above, crosses_below, above, below, and, or
        Also supports: value comparisons like "rsi1 below 30"
        """
        # Handle 'and' / 'or' compound conditions
        if " and " in condition:
            parts = condition.split(" and ")
            return all(self._evaluate_condition(p.strip(), indicators, df, bar) for p in parts)
        if " or " in condition:
            parts = condition.split(" or ")
            return any(self._evaluate_condition(p.strip(), indicators, df, bar) for p in parts)

        tokens = condition.strip().split()

        if len(tokens) == 3:
            left_name, op, right_name = tokens
            left_val = self._resolve_value(left_name, indicators, df, bar)
            right_val = self._resolve_value(right_name, indicators, df, bar)

            if left_val is None or right_val is None:
                return False

            if op == "crosses_above":
                left_prev = self._resolve_value(left_name, indicators, df, bar - 1)
                right_prev = self._resolve_value(right_name, indicators, df, bar - 1)
                if left_prev is None or right_prev is None:
                    return False
                return left_prev <= right_prev and left_val > right_val
            elif op == "crosses_below":
                left_prev = self._resolve_value(left_name, indicators, df, bar - 1)
                right_prev = self._resolve_value(right_name, indicators, df, bar - 1)
                if left_prev is None or right_prev is None:
                    return False
                return left_prev >= right_prev and left_val < right_val
            elif op == "above":
                return left_val > right_val
            elif op == "below":
                return left_val < right_val
            else:
                return False

        return False

    def _resolve_value(self, name: str, indicators: dict, df: pd.DataFrame, bar: int):
        """Resolve a value from indicator name, OHLCV column, or literal number."""
        if bar < 0 or bar >= len(df):
            return None

        # Try as indicator
        if name in indicators:
            val = indicators[name].iloc[bar]
            return None if pd.isna(val) else float(val)

        # Try as OHLCV column
        if name in ("open", "high", "low", "close", "volume"):
            return float(df[name].iloc[bar])

        # Try as numeric literal
        try:
            return float(name)
        except ValueError:
            return None

    def run(self, data_path: str | Path | None = None, df: pd.DataFrame | None = None,
            initial_capital: float = 1_000_000) -> BacktestResult:
        """Run the backtest.

        Provide either data_path (to load from CSV) or df (pre-loaded DataFrame).
        """
        if df is None:
            if data_path is None:
                raise ValueError("Must provide either data_path or df")
            session = self.config.get("risk", {}).get("session_filter", "day")
            df = prepare_data(data_path, session=session)

        indicators = self._compute_indicators(df)

        # Determine lookback (skip NaN period)
        lookback = 0
        for series in indicators.values():
            if isinstance(series, pd.Series):
                first_valid = series.first_valid_index()
                if first_valid is not None:
                    idx = df.index.get_loc(first_valid)
                    lookback = max(lookback, idx)
        lookback = max(lookback + 1, 2)  # at least 2 bars

        position: Position | None = None
        trades: list[Trade] = []
        equity_curve = [initial_capital]
        equity = initial_capital
        daily_pnl = 0.0
        current_date = None
        trailing_high = 0.0
        trailing_low = float("inf")

        entry_cfg = self.config.get("entry", {})
        exit_cfg = self.config.get("exit", {})
        stop_loss = self._get_param("stop_loss", 0)
        take_profit = self._get_param("take_profit", 0)
        trailing_enabled = self._get_param("trailing_stop_enabled", False)
        trailing_value = self._get_param("trailing_stop_value", 0)
        max_daily_loss = self._get_param("max_daily_loss", 0)
        time_exit_enabled = exit_cfg.get("time_exit", {}).get("enabled", False)
        time_exit_str = exit_cfg.get("time_exit", {}).get("time", "13:30")
        time_exit_minutes = int(time_exit_str.split(":")[0]) * 60 + int(time_exit_str.split(":")[1])
        max_positions = self.config.get("risk", {}).get("max_positions", 1)
        point_value = self.instrument.point_value

        for i in range(lookback, len(df)):
            bar_time = df.index[i]
            bar_open = df["open"].iloc[i]
            bar_high = df["high"].iloc[i]
            bar_low = df["low"].iloc[i]
            bar_close = df["close"].iloc[i]

            # Reset daily PnL
            bar_date = bar_time.date() if hasattr(bar_time, "date") else None
            if bar_date != current_date:
                current_date = bar_date
                daily_pnl = 0.0

            # Check max daily loss
            if max_daily_loss > 0 and daily_pnl <= -max_daily_loss * point_value:
                if position is not None:
                    trade = self._close_position(position, bar_open, bar_time, i, "max_daily_loss", point_value)
                    trades.append(trade)
                    equity += trade.pnl
                    daily_pnl += trade.pnl
                    position = None
                equity_curve.append(equity)
                continue

            # --- Exit logic (check at bar open / intra-bar) ---
            if position is not None:
                exit_price = None
                exit_reason = ""

                # Stop loss
                if stop_loss > 0:
                    if position.direction == "long":
                        sl_price = position.entry_price - stop_loss
                        if bar_low <= sl_price:
                            exit_price = sl_price
                            exit_reason = "stop_loss"
                    else:
                        sl_price = position.entry_price + stop_loss
                        if bar_high >= sl_price:
                            exit_price = sl_price
                            exit_reason = "stop_loss"

                # Take profit
                if take_profit > 0 and exit_price is None:
                    if position.direction == "long":
                        tp_price = position.entry_price + take_profit
                        if bar_high >= tp_price:
                            exit_price = tp_price
                            exit_reason = "take_profit"
                    else:
                        tp_price = position.entry_price - take_profit
                        if bar_low <= tp_price:
                            exit_price = tp_price
                            exit_reason = "take_profit"

                # Trailing stop
                if trailing_enabled and trailing_value > 0 and exit_price is None:
                    if position.direction == "long":
                        trailing_high = max(trailing_high, bar_high)
                        ts_price = trailing_high - trailing_value
                        if bar_low <= ts_price:
                            exit_price = ts_price
                            exit_reason = "trailing_stop"
                    else:
                        trailing_low = min(trailing_low, bar_low)
                        ts_price = trailing_low + trailing_value
                        if bar_high >= ts_price:
                            exit_price = ts_price
                            exit_reason = "trailing_stop"

                # Time exit
                if time_exit_enabled and exit_price is None:
                    if hasattr(bar_time, "hour"):
                        bar_minutes = bar_time.hour * 60 + bar_time.minute
                        if bar_minutes >= time_exit_minutes:
                            exit_price = bar_close
                            exit_reason = "time_exit"

                if exit_price is not None:
                    trade = self._close_position(position, exit_price, bar_time, i, exit_reason, point_value)
                    trades.append(trade)
                    equity += trade.pnl
                    daily_pnl += trade.pnl
                    position = None

            # --- Entry logic (signal at bar close, fill next bar at market) ---
            if position is None and i < len(df) - 1:
                # Long entry
                long_cfg = entry_cfg.get("long", {})
                if long_cfg and long_cfg.get("condition"):
                    if self._evaluate_condition(long_cfg["condition"], indicators, df, i):
                        next_open = df["open"].iloc[i + 1]
                        contracts = long_cfg.get("contracts", 1)
                        position = Position(
                            direction="long",
                            entry_price=next_open,
                            entry_bar=i + 1,
                            entry_time=df.index[i + 1],
                            contracts=contracts,
                        )
                        trailing_high = next_open
                        trailing_low = float("inf")
                        equity -= self.trade_cost * contracts
                        continue

                # Short entry
                short_cfg = entry_cfg.get("short", {})
                if short_cfg and short_cfg.get("condition"):
                    if self._evaluate_condition(short_cfg["condition"], indicators, df, i):
                        next_open = df["open"].iloc[i + 1]
                        contracts = short_cfg.get("contracts", 1)
                        position = Position(
                            direction="short",
                            entry_price=next_open,
                            entry_bar=i + 1,
                            entry_time=df.index[i + 1],
                            contracts=contracts,
                        )
                        trailing_high = 0.0
                        trailing_low = next_open
                        equity -= self.trade_cost * contracts
                        continue

            equity_curve.append(equity)

        # Close any remaining position at last bar close
        if position is not None:
            trade = self._close_position(
                position, df["close"].iloc[-1], df.index[-1],
                len(df) - 1, "end_of_data", point_value
            )
            trades.append(trade)
            equity += trade.pnl

        equity_curve.append(equity)
        metrics = calculate_metrics([t.to_dict() for t in trades], initial_capital)

        return BacktestResult(
            trades=trades,
            metrics=metrics,
            equity_curve=equity_curve,
            params=self.params.copy(),
        )

    def _close_position(self, pos: Position, exit_price: float,
                        exit_time, bar_idx: int, reason: str,
                        point_value: float) -> Trade:
        """Close a position and create a Trade record."""
        if pos.direction == "long":
            pnl = (exit_price - pos.entry_price) * point_value * pos.contracts
        else:
            pnl = (pos.entry_price - exit_price) * point_value * pos.contracts

        return Trade(
            direction=pos.direction,
            entry_price=pos.entry_price,
            entry_time=pos.entry_time,
            exit_price=exit_price,
            exit_time=exit_time,
            pnl=pnl,
            bars_held=bar_idx - pos.entry_bar,
            exit_reason=reason,
            contracts=pos.contracts,
        )


def run_backtest(
    strategy_path: str | Path,
    data_path: str | Path,
    params: dict | None = None,
    initial_capital: float = 1_000_000,
) -> BacktestResult:
    """Convenience function: load strategy YAML and run backtest."""
    with open(strategy_path) as f:
        config = yaml.safe_load(f)
    engine = BacktestEngine(config, params)
    return engine.run(data_path=data_path, initial_capital=initial_capital)
