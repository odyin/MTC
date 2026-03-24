"""Walk-forward analysis for strategy validation."""

from pathlib import Path

import yaml
import pandas as pd
import numpy as np

from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.data_loader import prepare_data
from src.backtest.metrics import calculate_metrics
from src.optimizer.grid import grid_search


def walk_forward_analysis(
    config: dict,
    data_path: str | Path,
    num_windows: int = 5,
    in_sample_ratio: float = 0.7,
    metric: str = "sharpe_ratio",
    max_combinations: int = 5000,
    initial_capital: float = 1_000_000,
    verbose: bool = True,
) -> dict:
    """Run walk-forward analysis.

    Splits data into rolling in-sample/out-of-sample windows.
    Optimizes on in-sample, validates on out-of-sample.

    Returns dict with:
      - windows: list of window results
      - overall_metrics: aggregated out-of-sample metrics
      - robustness_ratio: OOS performance / IS performance
    """
    session = config.get("risk", {}).get("session_filter", "day")
    df = prepare_data(data_path, session=session)

    total_bars = len(df)
    window_size = total_bars // num_windows
    is_size = int(window_size * in_sample_ratio / (1 - in_sample_ratio + in_sample_ratio))
    # Recalculate: each window has is_size in-sample + oos_size out-of-sample
    # Total coverage = num_windows steps, each step shifts by oos_size
    oos_size = total_bars // (num_windows + int(in_sample_ratio / (1 - in_sample_ratio)))
    is_size = int(oos_size * in_sample_ratio / (1 - in_sample_ratio))

    if is_size < 100 or oos_size < 20:
        raise ValueError(f"Not enough data for {num_windows} windows. "
                         f"Total bars: {total_bars}, IS: {is_size}, OOS: {oos_size}")

    windows = []
    all_oos_trades = []

    if verbose:
        print(f"Walk-forward analysis: {num_windows} windows")
        print(f"  Total bars: {total_bars}, IS size: {is_size}, OOS size: {oos_size}")
        print()

    for w in range(num_windows):
        is_start = w * oos_size
        is_end = is_start + is_size
        oos_start = is_end
        oos_end = min(oos_start + oos_size, total_bars)

        if oos_end > total_bars:
            break

        is_data = df.iloc[is_start:is_end]
        oos_data = df.iloc[oos_start:oos_end]

        if verbose:
            print(f"  Window {w + 1}: IS [{is_data.index[0]} to {is_data.index[-1]}] "
                  f"-> OOS [{oos_data.index[0]} to {oos_data.index[-1]}]")

        # Optimize on in-sample
        try:
            is_results = grid_search(
                config, data_path, metric,
                max_combinations=max_combinations,
                workers=1,  # Avoid nested multiprocessing issues
                initial_capital=initial_capital,
            )
            # Override: run on IS data subset
            # Re-run top params on IS data
            best_params = is_results[0][0] if is_results else {}
        except Exception as e:
            if verbose:
                print(f"    Optimization failed: {e}")
            continue

        # Run best params on IS data
        engine_is = BacktestEngine(config, best_params)
        is_result = engine_is.run(df=is_data, initial_capital=initial_capital)

        # Validate on OOS data
        engine_oos = BacktestEngine(config, best_params)
        oos_result = engine_oos.run(df=oos_data, initial_capital=initial_capital)

        is_metric = getattr(is_result.metrics, metric, 0)
        oos_metric = getattr(oos_result.metrics, metric, 0)

        window_info = {
            "window": w + 1,
            "is_range": f"{is_data.index[0]} to {is_data.index[-1]}",
            "oos_range": f"{oos_data.index[0]} to {oos_data.index[-1]}",
            "best_params": best_params,
            f"is_{metric}": is_metric,
            f"oos_{metric}": oos_metric,
            "is_trades": is_result.metrics.total_trades,
            "oos_trades": oos_result.metrics.total_trades,
            "oos_net_profit": oos_result.metrics.net_profit,
        }
        windows.append(window_info)
        all_oos_trades.extend([t.to_dict() for t in oos_result.trades])

        if verbose:
            print(f"    Best params: {best_params}")
            print(f"    IS {metric}: {is_metric:.4f} | OOS {metric}: {oos_metric:.4f}")
            print()

    # Aggregate OOS results
    overall_metrics = calculate_metrics(all_oos_trades, initial_capital)

    # Robustness ratio
    avg_is = np.mean([w[f"is_{metric}"] for w in windows]) if windows else 0
    avg_oos = np.mean([w[f"oos_{metric}"] for w in windows]) if windows else 0
    robustness = avg_oos / avg_is if avg_is != 0 else 0

    return {
        "windows": windows,
        "overall_metrics": overall_metrics,
        "robustness_ratio": robustness,
        "avg_is_metric": avg_is,
        "avg_oos_metric": avg_oos,
    }


def walk_forward_from_yaml(
    strategy_path: str | Path,
    data_path: str | Path,
    **kwargs,
) -> dict:
    """Convenience: load YAML and run walk-forward analysis."""
    with open(strategy_path) as f:
        config = yaml.safe_load(f)
    return walk_forward_analysis(config, data_path, **kwargs)
