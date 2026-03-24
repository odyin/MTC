"""CLI entry point for MTC - MultiCharts Trading Code system."""

import argparse
import sys
import json
from pathlib import Path

import yaml

from src.codegen.generator import PowerLanguageGenerator
from src.codegen.validator import validate_powerlanguage
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import calculate_metrics
from src.tracker.db import TrackerDB
from src.tracker.versioning import (
    compute_config_hash, iterate_strategy, save_strategy_yaml, increment_version
)


def cmd_generate(args):
    """Generate PowerLanguage code from strategy YAML."""
    generator = PowerLanguageGenerator(template_dir=args.templates)
    output_path = generator.generate(args.strategy, output_dir=args.output)

    # Validate
    code = output_path.read_text()
    errors = validate_powerlanguage(code)
    if errors:
        print("Validation warnings:")
        for err in errors:
            print(f"  {err}")
    else:
        print("Validation: OK")

    print(f"Generated: {output_path}")


def cmd_backtest(args):
    """Run backtest on a strategy."""
    with open(args.strategy) as f:
        config = yaml.safe_load(f)

    engine = BacktestEngine(config)
    result = engine.run(data_path=args.data, initial_capital=args.capital)

    print(result.metrics.summary())

    # Save to DB
    if not args.no_save:
        db = TrackerDB(args.db)
        strategy_yaml = Path(args.strategy).read_text()
        strategy_id = db.save_strategy(
            name=config.get("name", "Unknown"),
            version=config.get("version", "1.0"),
            config_yaml=strategy_yaml,
            yaml_hash=compute_config_hash(config),
        )
        backtest_id = db.save_backtest(
            strategy_id=strategy_id,
            params=result.params,
            metrics=result.metrics,
            data_file=str(args.data),
            timeframe=config.get("timeframe", ""),
            trades=[t.to_dict() for t in result.trades],
        )
        print(f"Saved to DB: strategy_id={strategy_id}, backtest_id={backtest_id}")
        db.close()

    if args.trades:
        print(f"\n{'Direction':<8} {'Entry Price':>11} {'Exit Price':>10} {'PnL':>10} {'Reason':<15}")
        print("-" * 60)
        for t in result.trades:
            print(f"{t.direction:<8} {t.entry_price:>11.0f} {t.exit_price:>10.0f} "
                  f"{t.pnl:>10.0f} {t.exit_reason:<15}")


def cmd_optimize(args):
    """Optimize strategy parameters."""
    with open(args.strategy) as f:
        config = yaml.safe_load(f)

    print(f"Strategy: {config.get('name')} v{config.get('version')}")
    print(f"Method: {args.method}")
    print(f"Metric: {args.metric}")
    print()

    if args.method == "grid":
        from src.optimizer.grid import grid_search
        results = grid_search(
            config, args.data,
            metric=args.metric,
            max_combinations=args.max_combos,
            workers=args.workers,
            initial_capital=args.capital,
        )
        print(f"\nTop {min(args.top, len(results))} results:")
        print(f"{'Rank':<6} {args.metric:>12} {'Net Profit':>12} {'Win Rate':>10} {'Trades':>8}  Params")
        print("-" * 80)
        for i, (params, metric_val, result) in enumerate(results[:args.top]):
            m = result.metrics
            param_str = ", ".join(f"{k}={v}" for k, v in params.items())
            print(f"{i+1:<6} {metric_val:>12.4f} {m.net_profit:>12,.0f} "
                  f"{m.win_rate:>9.1%} {m.total_trades:>8}  {param_str}")

        # Auto-save best result
        if results and not args.no_save:
            best_params, _, best_result = results[0]
            new_config = iterate_strategy(config, best_params)
            saved_path = save_strategy_yaml(new_config)
            print(f"\nBest params saved: {saved_path}")

    elif args.method == "genetic":
        from src.optimizer.genetic import genetic_optimize
        population = genetic_optimize(
            config, args.data,
            metric=args.metric,
            population_size=args.population,
            generations=args.generations,
            initial_capital=args.capital,
        )
        print(f"\nTop {min(args.top, len(population))} results:")
        for i, (params, fitness) in enumerate(population[:args.top]):
            param_str = ", ".join(f"{k}={v}" for k, v in params.items())
            print(f"  {i+1}. {args.metric}={fitness:.4f}  {param_str}")

    elif args.method == "walk_forward":
        from src.optimizer.walk_forward import walk_forward_analysis
        result = walk_forward_analysis(
            config, args.data,
            num_windows=args.windows,
            metric=args.metric,
            initial_capital=args.capital,
        )
        print(f"\nWalk-Forward Results:")
        print(f"  Robustness Ratio: {result['robustness_ratio']:.3f}")
        print(f"  Avg IS {args.metric}: {result['avg_is_metric']:.4f}")
        print(f"  Avg OOS {args.metric}: {result['avg_oos_metric']:.4f}")
        print(f"\nOverall OOS Performance:")
        print(result["overall_metrics"].summary())


def cmd_report(args):
    """Show backtest reports from DB."""
    db = TrackerDB(args.db)

    if args.list_strategies:
        strategies = db.list_strategies()
        print(f"{'ID':<6} {'Name':<30} {'Version':<10} {'Created':<20}")
        print("-" * 70)
        for s in strategies:
            print(f"{s['id']:<6} {s['name']:<30} {s['version']:<10} {s['created_at']:<20}")
        db.close()
        return

    results = db.get_top_backtests(
        strategy_name=args.strategy,
        metric=args.metric,
        limit=args.top,
    )

    if not results:
        print("No backtest results found.")
        db.close()
        return

    print(f"Top {len(results)} backtests by {args.metric}:")
    print(f"{'ID':<6} {'Strategy':<25} {'Ver':<5} {args.metric:>12} {'Net Profit':>12} "
          f"{'Win Rate':>9} {'Trades':>7} {'MDD':>10}")
    print("-" * 95)
    for r in results:
        print(f"{r['id']:<6} {r['strategy_name']:<25} {r['version']:<5} "
              f"{r.get(args.metric, 0):>12.4f} {r['net_profit']:>12,.0f} "
              f"{r['win_rate']:>8.1%} {r['total_trades']:>7} {r['max_drawdown']:>10,.0f}")

    db.close()


def cmd_iterate(args):
    """Create new strategy version with parameter updates."""
    with open(args.strategy) as f:
        config = yaml.safe_load(f)

    # Parse param updates: "fast_ma.period=15,slow_ma.period=40"
    param_updates = {}
    if args.params:
        for item in args.params.split(","):
            key, val = item.strip().split("=")
            try:
                val = int(val)
            except ValueError:
                try:
                    val = float(val)
                except ValueError:
                    pass
            param_updates[key.strip()] = val

    new_config = iterate_strategy(config, param_updates, args.version)
    saved_path = save_strategy_yaml(new_config)

    print(f"New strategy version created: {saved_path}")
    print(f"  Name: {new_config['name']} v{new_config['version']}")

    if param_updates:
        print(f"  Updated params: {param_updates}")

    # Optionally generate code
    if args.generate:
        generator = PowerLanguageGenerator()
        output_path = generator.generate_code(new_config)
        print(f"  PowerLanguage code generated")

    # Optionally run backtest
    if args.backtest and args.data:
        engine = BacktestEngine(new_config)
        result = engine.run(data_path=args.data, initial_capital=args.capital)
        print(result.metrics.summary())


def main():
    parser = argparse.ArgumentParser(
        description="MTC - MultiCharts Trading Code System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate PowerLanguage code
  python -m src.cli generate strategies/examples/ma_cross.yaml

  # Run backtest
  python -m src.cli backtest strategies/examples/ma_cross.yaml --data data/processed/TX_5m.csv

  # Grid search optimization
  python -m src.cli optimize strategies/examples/ma_cross.yaml --data data/processed/TX_5m.csv --method grid

  # Genetic algorithm optimization
  python -m src.cli optimize strategies/examples/ma_cross.yaml --data data/processed/TX_5m.csv --method genetic

  # Walk-forward analysis
  python -m src.cli optimize strategies/examples/ma_cross.yaml --data data/processed/TX_5m.csv --method walk_forward

  # View reports
  python -m src.cli report --strategy MA_Cross_TAIEX --top 10

  # Create new version with updated params
  python -m src.cli iterate strategies/examples/ma_cross.yaml --params "fast_ma.period=15,slow_ma.period=40"
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- generate ---
    gen_parser = subparsers.add_parser("generate", help="Generate PowerLanguage code")
    gen_parser.add_argument("strategy", help="Path to strategy YAML file")
    gen_parser.add_argument("--output", default="output/powerlanguage", help="Output directory")
    gen_parser.add_argument("--templates", default="templates", help="Templates directory")

    # --- backtest ---
    bt_parser = subparsers.add_parser("backtest", help="Run backtest")
    bt_parser.add_argument("strategy", help="Path to strategy YAML file")
    bt_parser.add_argument("--data", required=True, help="Path to OHLCV data file")
    bt_parser.add_argument("--capital", type=float, default=1_000_000, help="Initial capital (TWD)")
    bt_parser.add_argument("--trades", action="store_true", help="Print individual trades")
    bt_parser.add_argument("--no-save", action="store_true", help="Don't save to DB")
    bt_parser.add_argument("--db", default="output/mtc.db", help="Database path")

    # --- optimize ---
    opt_parser = subparsers.add_parser("optimize", help="Optimize strategy parameters")
    opt_parser.add_argument("strategy", help="Path to strategy YAML file")
    opt_parser.add_argument("--data", required=True, help="Path to OHLCV data file")
    opt_parser.add_argument("--method", choices=["grid", "genetic", "walk_forward"],
                            default="grid", help="Optimization method")
    opt_parser.add_argument("--metric", default="sharpe_ratio", help="Metric to optimize")
    opt_parser.add_argument("--top", type=int, default=10, help="Show top N results")
    opt_parser.add_argument("--capital", type=float, default=1_000_000, help="Initial capital")
    opt_parser.add_argument("--no-save", action="store_true", help="Don't save best result")
    opt_parser.add_argument("--db", default="output/mtc.db", help="Database path")
    # Grid-specific
    opt_parser.add_argument("--max-combos", type=int, default=10000, help="Max grid combinations")
    opt_parser.add_argument("--workers", type=int, default=-1, help="Parallel workers (-1=all)")
    # Genetic-specific
    opt_parser.add_argument("--population", type=int, default=50, help="GA population size")
    opt_parser.add_argument("--generations", type=int, default=100, help="GA generations")
    # Walk-forward
    opt_parser.add_argument("--windows", type=int, default=5, help="Walk-forward windows")

    # --- report ---
    rpt_parser = subparsers.add_parser("report", help="View backtest reports")
    rpt_parser.add_argument("--strategy", help="Filter by strategy name")
    rpt_parser.add_argument("--metric", default="sharpe_ratio", help="Sort by metric")
    rpt_parser.add_argument("--top", type=int, default=10, help="Show top N results")
    rpt_parser.add_argument("--list-strategies", action="store_true", help="List all strategies")
    rpt_parser.add_argument("--db", default="output/mtc.db", help="Database path")

    # --- iterate ---
    iter_parser = subparsers.add_parser("iterate", help="Create new strategy version")
    iter_parser.add_argument("strategy", help="Path to strategy YAML file")
    iter_parser.add_argument("--params", help="Parameter updates: 'key=val,key2=val2'")
    iter_parser.add_argument("--version", help="Explicit version string")
    iter_parser.add_argument("--generate", action="store_true", help="Also generate PowerLanguage code")
    iter_parser.add_argument("--backtest", action="store_true", help="Also run backtest")
    iter_parser.add_argument("--data", help="Data file for backtest")
    iter_parser.add_argument("--capital", type=float, default=1_000_000, help="Initial capital")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "generate": cmd_generate,
        "backtest": cmd_backtest,
        "optimize": cmd_optimize,
        "report": cmd_report,
        "iterate": cmd_iterate,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
