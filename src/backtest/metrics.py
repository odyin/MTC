"""Backtest performance metrics calculation."""

import numpy as np
import pandas as pd
from dataclasses import dataclass, asdict


@dataclass
class BacktestMetrics:
    """Summary metrics for a backtest run."""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    net_profit: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    avg_trade: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    avg_bars_in_trade: float
    max_consecutive_wins: int
    max_consecutive_losses: int

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            "=" * 50,
            "           BACKTEST RESULTS",
            "=" * 50,
            f"  Total Trades:        {self.total_trades}",
            f"  Win Rate:            {self.win_rate:.1%}",
            f"  Net Profit:          {self.net_profit:,.0f}",
            f"  Profit Factor:       {self.profit_factor:.2f}",
            f"  Avg Trade:           {self.avg_trade:,.0f}",
            f"  Avg Win:             {self.avg_win:,.0f}",
            f"  Avg Loss:            {self.avg_loss:,.0f}",
            f"  Largest Win:         {self.largest_win:,.0f}",
            f"  Largest Loss:        {self.largest_loss:,.0f}",
            f"  Max Drawdown:        {self.max_drawdown:,.0f} ({self.max_drawdown_pct:.1%})",
            f"  Sharpe Ratio:        {self.sharpe_ratio:.3f}",
            f"  Sortino Ratio:       {self.sortino_ratio:.3f}",
            f"  Calmar Ratio:        {self.calmar_ratio:.3f}",
            f"  Max Consec Wins:     {self.max_consecutive_wins}",
            f"  Max Consec Losses:   {self.max_consecutive_losses}",
            "=" * 50,
        ]
        return "\n".join(lines)


def calculate_metrics(
    trades: list[dict],
    initial_capital: float = 1_000_000,
    annual_bars: int = 252,
) -> BacktestMetrics:
    """Calculate performance metrics from a list of trade dicts.

    Each trade dict must have: 'pnl', 'bars_held'
    """
    if not trades:
        return BacktestMetrics(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0, net_profit=0, gross_profit=0, gross_loss=0,
            profit_factor=0, avg_trade=0, avg_win=0, avg_loss=0,
            largest_win=0, largest_loss=0, max_drawdown=0, max_drawdown_pct=0,
            sharpe_ratio=0, sortino_ratio=0, calmar_ratio=0,
            avg_bars_in_trade=0, max_consecutive_wins=0, max_consecutive_losses=0,
        )

    pnls = np.array([t["pnl"] for t in trades])
    bars_held = np.array([t.get("bars_held", 1) for t in trades])

    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    total_trades = len(pnls)
    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0

    gross_profit = float(wins.sum()) if len(wins) > 0 else 0.0
    gross_loss = float(abs(losses.sum())) if len(losses) > 0 else 0.0
    net_profit = float(pnls.sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    avg_trade = float(pnls.mean())
    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0
    largest_win = float(wins.max()) if len(wins) > 0 else 0.0
    largest_loss = float(losses.min()) if len(losses) > 0 else 0.0

    # Equity curve & drawdown
    equity = np.cumsum(pnls) + initial_capital
    running_max = np.maximum.accumulate(equity)
    drawdowns = equity - running_max
    max_drawdown = float(abs(drawdowns.min())) if len(drawdowns) > 0 else 0.0
    max_dd_idx = np.argmin(drawdowns) if len(drawdowns) > 0 else 0
    max_drawdown_pct = max_drawdown / running_max[max_dd_idx] if running_max[max_dd_idx] > 0 else 0

    # Sharpe ratio (annualized, using trade returns)
    returns = pnls / initial_capital
    sharpe_ratio = 0.0
    if len(returns) > 1 and returns.std() > 0:
        sharpe_ratio = float(returns.mean() / returns.std() * np.sqrt(annual_bars))

    # Sortino ratio
    downside = returns[returns < 0]
    sortino_ratio = 0.0
    if len(downside) > 1 and downside.std() > 0:
        sortino_ratio = float(returns.mean() / downside.std() * np.sqrt(annual_bars))

    # Calmar ratio
    annual_return = net_profit / max(1, total_trades) * annual_bars
    calmar_ratio = annual_return / max_drawdown if max_drawdown > 0 else 0.0

    # Consecutive wins/losses
    max_consec_wins = _max_consecutive(pnls > 0)
    max_consec_losses = _max_consecutive(pnls < 0)

    avg_bars = float(bars_held.mean()) if len(bars_held) > 0 else 0.0

    return BacktestMetrics(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        net_profit=net_profit,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        avg_trade=avg_trade,
        avg_win=avg_win,
        avg_loss=avg_loss,
        largest_win=largest_win,
        largest_loss=largest_loss,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        calmar_ratio=calmar_ratio,
        avg_bars_in_trade=avg_bars,
        max_consecutive_wins=max_consec_wins,
        max_consecutive_losses=max_consec_losses,
    )


def _max_consecutive(mask: np.ndarray) -> int:
    """Count the maximum consecutive True values in a boolean array."""
    if len(mask) == 0:
        return 0
    max_run = 0
    current_run = 0
    for val in mask:
        if val:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0
    return max_run
