"""Grid search parameter optimizer."""

import itertools
import multiprocessing
from pathlib import Path
from typing import Callable

import yaml
import numpy as np

from src.backtest.engine import BacktestEngine, BacktestResult


def extract_param_ranges(config: dict) -> dict[str, list]:
    """Extract parameter ranges from strategy config.

    Returns dict mapping param name to list of values to test.
    """
    ranges = {}

    for indicator in config.get("indicators", []):
        name = indicator["name"]
        for pname, pval in indicator.get("params", {}).items():
            if isinstance(pval, dict) and "min" in pval and "max" in pval:
                step = pval.get("step", 1)
                min_val = pval["min"]
                max_val = pval["max"]

                if isinstance(step, float) or isinstance(min_val, float):
                    values = list(np.arange(min_val, max_val + step / 2, step))
                else:
                    values = list(range(int(min_val), int(max_val) + 1, int(step)))

                ranges[f"{name}.{pname}"] = values

    return ranges


def _run_single(args: tuple) -> tuple[dict, float, BacktestResult]:
    """Worker function for parallel grid search."""
    config, params, data_path, metric_name, initial_capital = args
    engine = BacktestEngine(config, params)
    result = engine.run(data_path=data_path, initial_capital=initial_capital)
    metric_value = getattr(result.metrics, metric_name, 0)
    return params, metric_value, result


def grid_search(
    config: dict,
    data_path: str | Path,
    metric: str = "sharpe_ratio",
    max_combinations: int = 10000,
    workers: int = -1,
    initial_capital: float = 1_000_000,
) -> list[tuple[dict, float, BacktestResult]]:
    """Run grid search over all parameter combinations.

    Args:
        config: Strategy config dict
        data_path: Path to OHLCV data
        metric: Metric to optimize (attribute of BacktestMetrics)
        max_combinations: Maximum number of combinations to test
        workers: Number of parallel workers (-1 = all CPUs)

    Returns:
        List of (params, metric_value, result) tuples, sorted by metric descending.
    """
    ranges = extract_param_ranges(config)

    if not ranges:
        raise ValueError("No optimizable parameters found in config (need min/max/step)")

    param_names = list(ranges.keys())
    param_values = list(ranges.values())

    # Build all combinations
    total = 1
    for v in param_values:
        total *= len(v)

    if total > max_combinations:
        print(f"WARNING: {total} combinations exceeds limit {max_combinations}. "
              f"Sampling {max_combinations} random combinations.")
        combinations = []
        for _ in range(max_combinations):
            combo = {name: np.random.choice(values) for name, values in zip(param_names, param_values)}
            combinations.append(combo)
    else:
        combinations = [
            dict(zip(param_names, combo))
            for combo in itertools.product(*param_values)
        ]

    print(f"Grid search: {len(combinations)} parameter combinations")
    print(f"Optimizing for: {metric}")

    # Prepare worker args
    args_list = [
        (config, params, str(data_path), metric, initial_capital)
        for params in combinations
    ]

    if workers == -1:
        workers = multiprocessing.cpu_count()

    # Run in parallel
    if workers > 1 and len(combinations) > 1:
        with multiprocessing.Pool(workers) as pool:
            results = pool.map(_run_single, args_list)
    else:
        results = [_run_single(args) for args in args_list]

    # Sort by metric descending
    results.sort(key=lambda x: x[1], reverse=True)

    return results


def grid_search_from_yaml(
    strategy_path: str | Path,
    data_path: str | Path,
    metric: str = "sharpe_ratio",
    max_combinations: int = 10000,
    workers: int = -1,
    initial_capital: float = 1_000_000,
) -> list[tuple[dict, float, BacktestResult]]:
    """Convenience: load YAML and run grid search."""
    with open(strategy_path) as f:
        config = yaml.safe_load(f)
    return grid_search(config, data_path, metric, max_combinations, workers, initial_capital)
