"""SQLite database for strategy and backtest tracking."""

import sqlite3
import json
from pathlib import Path
from datetime import datetime


DEFAULT_DB_PATH = "output/mtc.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    yaml_hash TEXT,
    config_yaml TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER REFERENCES strategies(id),
    params_json TEXT,
    data_file TEXT,
    data_range TEXT,
    timeframe TEXT,
    total_trades INTEGER,
    win_rate REAL,
    profit_factor REAL,
    sharpe_ratio REAL,
    sortino_ratio REAL,
    max_drawdown REAL,
    max_drawdown_pct REAL,
    net_profit REAL,
    gross_profit REAL,
    gross_loss REAL,
    avg_trade REAL,
    calmar_ratio REAL,
    run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_id INTEGER REFERENCES backtests(id),
    direction TEXT,
    entry_time TEXT,
    entry_price REAL,
    exit_time TEXT,
    exit_price REAL,
    pnl REAL,
    bars_held INTEGER,
    exit_reason TEXT,
    contracts INTEGER DEFAULT 1
);
"""


class TrackerDB:
    """SQLite tracker for strategies and backtests."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- Strategy operations ---

    def save_strategy(self, name: str, version: str, config_yaml: str,
                      yaml_hash: str = "") -> int:
        """Insert or get existing strategy. Returns strategy_id."""
        cursor = self.conn.execute(
            "SELECT id FROM strategies WHERE name = ? AND version = ?",
            (name, version),
        )
        row = cursor.fetchone()
        if row:
            return row["id"]

        cursor = self.conn.execute(
            "INSERT INTO strategies (name, version, yaml_hash, config_yaml) VALUES (?, ?, ?, ?)",
            (name, version, yaml_hash, config_yaml),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_strategy(self, name: str, version: str = None) -> dict | None:
        """Get strategy by name (and optionally version). Returns latest if no version."""
        if version:
            cursor = self.conn.execute(
                "SELECT * FROM strategies WHERE name = ? AND version = ?",
                (name, version),
            )
        else:
            cursor = self.conn.execute(
                "SELECT * FROM strategies WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                (name,),
            )
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_strategies(self) -> list[dict]:
        """List all strategies."""
        cursor = self.conn.execute(
            "SELECT id, name, version, created_at FROM strategies ORDER BY created_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]

    # --- Backtest operations ---

    def save_backtest(self, strategy_id: int, params: dict, metrics,
                      data_file: str = "", data_range: str = "",
                      timeframe: str = "", trades: list[dict] = None) -> int:
        """Save a backtest result. Returns backtest_id."""
        cursor = self.conn.execute(
            """INSERT INTO backtests
            (strategy_id, params_json, data_file, data_range, timeframe,
             total_trades, win_rate, profit_factor, sharpe_ratio, sortino_ratio,
             max_drawdown, max_drawdown_pct, net_profit, gross_profit, gross_loss,
             avg_trade, calmar_ratio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                strategy_id,
                json.dumps(params),
                data_file,
                data_range,
                timeframe,
                metrics.total_trades,
                metrics.win_rate,
                metrics.profit_factor,
                metrics.sharpe_ratio,
                metrics.sortino_ratio,
                metrics.max_drawdown,
                metrics.max_drawdown_pct,
                metrics.net_profit,
                metrics.gross_profit,
                metrics.gross_loss,
                metrics.avg_trade,
                metrics.calmar_ratio,
            ),
        )
        backtest_id = cursor.lastrowid

        # Save individual trades
        if trades:
            for trade in trades:
                self.conn.execute(
                    """INSERT INTO trades
                    (backtest_id, direction, entry_time, entry_price,
                     exit_time, exit_price, pnl, bars_held, exit_reason, contracts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        backtest_id,
                        trade.get("direction"),
                        trade.get("entry_time"),
                        trade.get("entry_price"),
                        trade.get("exit_time"),
                        trade.get("exit_price"),
                        trade.get("pnl"),
                        trade.get("bars_held"),
                        trade.get("exit_reason"),
                        trade.get("contracts", 1),
                    ),
                )

        self.conn.commit()
        return backtest_id

    def get_top_backtests(self, strategy_name: str = None, metric: str = "sharpe_ratio",
                          limit: int = 10) -> list[dict]:
        """Query top backtests, optionally filtered by strategy name."""
        if strategy_name:
            cursor = self.conn.execute(
                f"""SELECT b.*, s.name as strategy_name, s.version
                FROM backtests b
                JOIN strategies s ON b.strategy_id = s.id
                WHERE s.name = ?
                ORDER BY b.{metric} DESC
                LIMIT ?""",
                (strategy_name, limit),
            )
        else:
            cursor = self.conn.execute(
                f"""SELECT b.*, s.name as strategy_name, s.version
                FROM backtests b
                JOIN strategies s ON b.strategy_id = s.id
                ORDER BY b.{metric} DESC
                LIMIT ?""",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]

    def get_backtest_trades(self, backtest_id: int) -> list[dict]:
        """Get all trades for a backtest."""
        cursor = self.conn.execute(
            "SELECT * FROM trades WHERE backtest_id = ? ORDER BY entry_time",
            (backtest_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
