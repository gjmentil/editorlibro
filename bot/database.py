"""SQLite database for trade history and price data."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


class Database:
    def __init__(self, path: str = "trading_bot.db"):
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._init_tables()

    def close(self):
        self._conn.close()

    def _init_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL,
                filled_price REAL,
                fee REAL DEFAULT 0,
                status TEXT NOT NULL,
                strategy TEXT,
                signal_data TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                price REAL NOT NULL,
                bid REAL,
                ask REAL,
                volume REAL,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                symbol TEXT,
                trades_count INTEGER DEFAULT 0,
                total_pnl REAL DEFAULT 0,
                total_fees REAL DEFAULT 0,
                win_count INTEGER DEFAULT 0,
                loss_count INTEGER DEFAULT 0,
                UNIQUE(date, symbol)
            );

            CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at);
            CREATE INDEX IF NOT EXISTS idx_prices_symbol_time ON prices(symbol, recorded_at);
        """)
        self._conn.commit()

    def record_trade(self, order_id: str, symbol: str, side: str, order_type: str,
                     quantity: float, price: float | None, status: str,
                     strategy: str | None = None, signal_data: dict | None = None):
        self._conn.execute(
            """INSERT OR REPLACE INTO trades
               (order_id, symbol, side, order_type, quantity, price, status, strategy, signal_data, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (order_id, symbol, side, order_type, quantity, price, status,
             strategy, json.dumps(signal_data) if signal_data else None),
        )
        self._conn.commit()

    def update_trade(self, order_id: str, status: str, filled_price: float | None = None, fee: float = 0):
        self._conn.execute(
            """UPDATE trades SET status=?, filled_price=?, fee=?, updated_at=datetime('now')
               WHERE order_id=?""",
            (status, filled_price, fee, order_id),
        )
        self._conn.commit()

    def record_price(self, symbol: str, price: float, bid: float | None = None,
                     ask: float | None = None, volume: float | None = None):
        self._conn.execute(
            "INSERT INTO prices (symbol, price, bid, ask, volume) VALUES (?, ?, ?, ?, ?)",
            (symbol, price, bid, ask, volume),
        )
        self._conn.commit()

    def get_price_history(self, symbol: str, limit: int = 200) -> list[float]:
        rows = self._conn.execute(
            "SELECT price FROM prices WHERE symbol=? ORDER BY recorded_at DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return [r["price"] for r in reversed(rows)]

    def get_recent_trades(self, symbol: str | None = None, limit: int = 50) -> list[dict]:
        if symbol:
            rows = self._conn.execute(
                "SELECT * FROM trades WHERE symbol=? ORDER BY created_at DESC LIMIT ?",
                (symbol, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_daily_pnl(self, date: str | None = None) -> dict:
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        trades = self._conn.execute(
            "SELECT * FROM trades WHERE date(created_at)=? AND status='FILLED'",
            (date,),
        ).fetchall()

        total_pnl = 0.0
        total_fees = 0.0
        buy_count = 0
        sell_count = 0

        for t in trades:
            total_fees += t["fee"] or 0
            if t["side"] == "SELL" and t["filled_price"]:
                total_pnl += t["filled_price"] * t["quantity"]
                sell_count += 1
            elif t["side"] == "BUY" and t["filled_price"]:
                total_pnl -= t["filled_price"] * t["quantity"]
                buy_count += 1

        return {
            "date": date,
            "trades": len(trades),
            "buys": buy_count,
            "sells": sell_count,
            "pnl": round(total_pnl, 2),
            "fees": round(total_fees, 2),
        }

    def get_trades_today_count(self) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE date(created_at)=?", (today,)
        ).fetchone()
        return row["cnt"]

    def get_daily_loss(self) -> float:
        today = datetime.now().strftime("%Y-%m-%d")
        row = self._conn.execute(
            """SELECT COALESCE(SUM(CASE WHEN side='SELL' THEN filled_price * quantity
                ELSE -filled_price * quantity END), 0) as pnl
               FROM trades WHERE date(created_at)=? AND status='FILLED'""",
            (today,),
        ).fetchone()
        return row["pnl"]
