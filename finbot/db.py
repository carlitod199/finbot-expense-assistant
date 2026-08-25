# -*- coding: utf-8 -*-
"""Persistence layer (SQLite).

Two tables:
  - budgets: editable configuration (month x category x amount), seeded from
    config/budgets.py on first boot.
  - transactions: one row per recorded expense.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime

from config.budgets import CATEGORIES, MONTHLY_BUDGETS

# Path to the database file (overridable via env var, useful when deploying).
DB_PATH = os.environ.get("FINBOT_DB", os.path.join(os.getcwd(), "finbot.db"))

_conn: sqlite3.Connection | None = None


def connect() -> sqlite3.Connection:
    """Return the process-wide SQLite connection, opening it on first use."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
    return _conn


def init_db() -> None:
    """Create the tables (if needed) and seed the budgets."""
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS budgets (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            month    TEXT NOT NULL,
            category TEXT NOT NULL,
            amount   REAL NOT NULL,
            UNIQUE(month, category)
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            spent_on    TEXT NOT NULL,          -- YYYY-MM-DD
            category    TEXT NOT NULL,
            amount      REAL NOT NULL,
            description TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trans_date ON transactions(spent_on);
        CREATE INDEX IF NOT EXISTS idx_trans_cat  ON transactions(category);
        """
    )
    # Seed: never overwrites months that already exist (INSERT OR IGNORE).
    for month, categories in MONTHLY_BUDGETS.items():
        for category, amount in categories.items():
            conn.execute(
                "INSERT OR IGNORE INTO budgets (month, category, amount) VALUES (?, ?, ?)",
                (month, category, float(amount)),
            )
    conn.commit()


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def record_transaction(day: date, category: str, amount: float, description: str) -> int:
    """Insert one expense and return its row id."""
    conn = connect()
    cur = conn.execute(
        "INSERT INTO transactions (spent_on, category, amount, description, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            day.isoformat(),
            category,
            float(amount),
            description,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def month_configured(month: str) -> bool:
    """True if at least one budget row exists for the month."""
    conn = connect()
    row = conn.execute(
        "SELECT 1 FROM budgets WHERE month = ? LIMIT 1", (month,)
    ).fetchone()
    return row is not None


def budgets_for_month(month: str) -> dict[str, float]:
    """Return {category: amount} for the month. If the month is not in the
    database, fall back to the 7 default categories with a budget of 0 (this
    avoids KeyErrors in the reports)."""
    conn = connect()
    rows = conn.execute(
        "SELECT category, amount FROM budgets WHERE month = ? ORDER BY id", (month,)
    ).fetchall()
    if rows:
        return {r["category"]: r["amount"] for r in rows}
    return {c: 0.0 for c in CATEGORIES}


def category_spend_for_month(category: str, month: str) -> float:
    """Total spent in one category during the given month."""
    conn = connect()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM transactions "
        "WHERE category = ? AND substr(spent_on, 1, 7) = ?",
        (category, month),
    ).fetchone()
    return float(row["total"])


def spend_by_category_for_month(month: str) -> dict[str, float]:
    """Total spent per category during the given month."""
    conn = connect()
    rows = conn.execute(
        "SELECT category, COALESCE(SUM(amount), 0) AS total FROM transactions "
        "WHERE substr(spent_on, 1, 7) = ? GROUP BY category",
        (month,),
    ).fetchall()
    return {r["category"]: float(r["total"]) for r in rows}


def total_spend_for_month(month: str) -> float:
    """Total spent in the month, counting only the 7 variable categories."""
    conn = connect()
    placeholders = ",".join("?" for _ in CATEGORIES)
    row = conn.execute(
        f"SELECT COALESCE(SUM(amount), 0) AS total FROM transactions "
        f"WHERE substr(spent_on, 1, 7) = ? AND category IN ({placeholders})",
        (month, *CATEGORIES),
    ).fetchone()
    return float(row["total"])


def total_spend_in_range(start: date, end: date) -> float:
    """Total spent (7 categories) between start and end, inclusive."""
    conn = connect()
    placeholders = ",".join("?" for _ in CATEGORIES)
    row = conn.execute(
        f"SELECT COALESCE(SUM(amount), 0) AS total FROM transactions "
        f"WHERE spent_on BETWEEN ? AND ? AND category IN ({placeholders})",
        (start.isoformat(), end.isoformat(), *CATEGORIES),
    ).fetchone()
    return float(row["total"])
