"""Genetic algorithm parameter optimizer."""

import random
from pathlib import Path

import yaml
import numpy as np

from src.backtest.engine import BacktestEngine, BacktestResult
from src.optimizer.grid import extract_param_ranges


def _create_individual(ranges: dict[str, list]) -> dict:
    """Create a random individual (parameter set)."""
    return {name: random.choice(values) for name, values in ranges.items()}


def _evaluate(config: dict, params: dict, data_path: str,
              metric: str, initial_capital: float) -> float:
    """Evaluate fitness of an individual."""
    engine = BacktestEngine(config, params)
    result = engine.run(data_path=data_path, initial_capital=initial_capital)
    return getattr(result.metrics, metric, 0)


def _tournament_select(population: list[tuple[dict, float]], tournament_size: int) -> dict:
    """Tournament selection."""
    competitors = random.sample(population, min(tournament_size, len(population)))
    winner = max(competitors, key=lambda x: x[1])
    return winner[0].copy()


def _crossover(parent1: dict, parent2: dict) -> tuple[dict, dict]:
    """Single-point crossover."""
    keys = list(parent1.keys())
    if len(keys) <= 1:
        return parent1.copy(), parent2.copy()

    point = random.randint(1, len(keys) - 1)
    child1 = {}
    child2 = {}
    for i, key in enumerate(keys):
        if i < point:
            child1[key] = parent1[key]
            child2[key] = parent2[key]
        else:
            child1[key] = parent2[key]
            child2[key] = parent1[key]
    return child1, child2


def _mutate(individual: dict, ranges: dict[str, list], mutation_rate: float) -> dict:
    """Random mutation."""
    mutated = individual.copy()
    for key in mutated:
        if random.random() < mutation_rate:
            mutated[key] = random.choice(ranges[key])
    return mutated


def genetic_optimize(
    config: dict,
    data_path: str | Path,
    metric: str = "sharpe_ratio",
    population_size: int = 50,
    generations: int = 100,
    crossover_rate: float = 0.8,
    mutation_rate: float = 0.1,
    tournament_size: int = 3,
    elite_count: int = 2,
    initial_capital: float = 1_000_000,
    verbose: bool = True,
) -> list[tuple[dict, float]]:
    """Run genetic algorithm optimization.

    Returns list of (params, fitness) tuples for final population, sorted descending.
    """
    ranges = extract_param_ranges(config)
    if not ranges:
        raise ValueError("No optimizable parameters found")

    data_path = str(data_path)

    # Initialize population
    population = []
    for _ in range(population_size):
        individual = _create_individual(ranges)
        fitness = _evaluate(config, individual, data_path, metric, initial_capital)
        population.append((individual, fitness))

    best_ever = max(population, key=lambda x: x[1])

    for gen in range(generations):
        # Sort by fitness
        population.sort(key=lambda x: x[1], reverse=True)

        # Elitism: keep top individuals
        next_gen = list(population[:elite_count])

        # Generate rest of next generation
        while len(next_gen) < population_size:
            parent1 = _tournament_select(population, tournament_size)
            parent2 = _tournament_select(population, tournament_size)

            if random.random() < crossover_rate:
                child1, child2 = _crossover(parent1, parent2)
            else:
                child1, child2 = parent1.copy(), parent2.copy()

            child1 = _mutate(child1, ranges, mutation_rate)
            child2 = _mutate(child2, ranges, mutation_rate)

            f1 = _evaluate(config, child1, data_path, metric, initial_capital)
            f2 = _evaluate(config, child2, data_path, metric, initial_capital)

            next_gen.append((child1, f1))
            if len(next_gen) < population_size:
                next_gen.append((child2, f2))

        population = next_gen
        current_best = max(population, key=lambda x: x[1])

        if current_best[1] > best_ever[1]:
            best_ever = current_best

        if verbose and (gen + 1) % 10 == 0:
            print(f"  Gen {gen + 1}/{generations} | Best: {current_best[1]:.4f} | "
                  f"All-time best: {best_ever[1]:.4f}")

    population.sort(key=lambda x: x[1], reverse=True)
    return population


def genetic_optimize_from_yaml(
    strategy_path: str | Path,
    data_path: str | Path,
    **kwargs,
) -> list[tuple[dict, float]]:
    """Convenience: load YAML and run genetic optimization."""
    with open(strategy_path) as f:
        config = yaml.safe_load(f)
    return genetic_optimize(config, data_path, **kwargs)
