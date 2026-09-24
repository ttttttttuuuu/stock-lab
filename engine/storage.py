"""Storage layer: local SQLite (always) + optional Supabase sync via REST.

Supabase is enabled when SUPABASE_URL and SUPABASE_SERVICE_KEY (or anon key)
are present in the environment or a .env file at the project root.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "trader.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# load .env if present
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    metrics TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    source TEXT NOT NULL DEFAULT 'backtest',   -- backtest | paper | live
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    kind TEXT NOT NULL,
    strike REAL,
    entry_date TEXT,
    entry_underlying REAL,
    entry_price REAL,
    qty REAL,
    iv_entry REAL,
    exit_date TEXT,
    exit_underlying REAL,
    exit_price REAL,
    exit_reason TEXT,
    pnl REAL,
    pnl_pct REAL,
    hold_days INTEGER
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    signal INTEGER NOT NULL,
    close REAL,
    details TEXT
);
CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS paper_positions (
    symbol TEXT PRIMARY KEY,
    data TEXT NOT NULL               -- JSON of the open position
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    date TEXT PRIMARY KEY,           -- one row per day
    realized REAL,
    unrealized REAL,
    total REAL,                      -- realized + unrealized
    positions_count INTEGER,
    marked_at TEXT
);
CREATE TABLE IF NOT EXISTS strategy_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    strategy TEXT NOT NULL,
    level TEXT NOT NULL,             -- insufficient | ok | watch | critical
    reasons TEXT,                    -- JSON array of human-readable reasons
    n INTEGER,                       -- closed paper trades at evaluation time
    win_rate REAL,
    avg_pnl REAL
);
CREATE TABLE IF NOT EXISTS stock_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    metrics TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    side TEXT NOT NULL,              -- long | short
    entry_date TEXT,
    entry_price REAL,
    shares REAL,
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl REAL,
    pnl_pct REAL,
    hold_days INTEGER
);
CREATE TABLE IF NOT EXISTS stock_paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    side TEXT NOT NULL,              -- long | short
    entry_date TEXT,
    entry_price REAL,
    shares REAL,
    exit_date TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl REAL,
    pnl_pct REAL,
    hold_days INTEGER
);
CREATE TABLE IF NOT EXISTS stock_paper_positions (
    key TEXT PRIMARY KEY,            -- "symbol|strategy"
    data TEXT NOT NULL               -- JSON of the open position
);
CREATE TABLE IF NOT EXISTS param_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    params TEXT NOT NULL,            -- JSON of the param combo
    is_default INTEGER NOT NULL DEFAULT 0,
    metrics TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exit_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    take_profit REAL NOT NULL,
    stop_loss REAL NOT NULL,
    max_hold_days INTEGER NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    metrics TEXT NOT NULL
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def save_run(conn: sqlite3.Connection, run_at: str, symbol: str,
             strategy: str, metrics: dict) -> int:
    cur = conn.execute(
        "INSERT INTO backtest_runs (run_at, symbol, strategy, metrics) VALUES (?,?,?,?)",
        (run_at, symbol, strategy, json.dumps(metrics)),
    )
    return cur.lastrowid


def save_trades(conn: sqlite3.Connection, run_id: int, trades: list[dict],
                source: str = "backtest"):
    cols = ["symbol", "strategy", "kind", "strike", "entry_date",
            "entry_underlying", "entry_price", "qty", "iv_entry", "exit_date",
            "exit_underlying", "exit_price", "exit_reason", "pnl", "pnl_pct",
            "hold_days"]
    conn.executemany(
        f"INSERT INTO trades (run_id, source, {','.join(cols)}) "
        f"VALUES (?,?,{','.join('?' * len(cols))})",
        [[run_id, source] + [t.get(c) for c in cols] for t in trades],
    )


def upsert_prices(conn: sqlite3.Connection, symbol: str, df):
    conn.executemany(
        "INSERT OR REPLACE INTO prices (symbol,date,open,high,low,close,volume) "
        "VALUES (?,?,?,?,?,?,?)",
        [
            (symbol, r["date"].strftime("%Y-%m-%d"), r["open"], r["high"],
             r["low"], r["close"], r["volume"])
            for _, r in df.iterrows()
        ],
    )


def save_signal(conn: sqlite3.Connection, created_at: str, symbol: str,
                strategy: str, signal: int, close: float, details: dict):
    conn.execute(
        "INSERT INTO signals (created_at, symbol, strategy, signal, close, details) "
        "VALUES (?,?,?,?,?,?)",
        (created_at, symbol, strategy, signal, close, json.dumps(details)),
    )


def save_paper_positions(conn: sqlite3.Connection, positions: list[dict]):
    """Replace the open paper-position set (keyed by symbol + strategy —
    multiple strategies can hold the same symbol at once)."""
    conn.execute("DELETE FROM paper_positions")
    conn.executemany(
        "INSERT INTO paper_positions (symbol, data) VALUES (?,?)",
        [(f"{p['symbol']}|{p.get('strategy', 'ensemble')}", json.dumps(p))
         for p in positions],
    )


def save_equity_snapshot(conn: sqlite3.Connection, day: str, realized: float,
                         unrealized: float, positions_count: int,
                         marked_at: str):
    """Upsert one daily equity snapshot (realized + unrealized)."""
    conn.execute(
        "INSERT OR REPLACE INTO equity_snapshots "
        "(date, realized, unrealized, total, positions_count, marked_at) "
        "VALUES (?,?,?,?,?,?)",
        (day, round(realized, 2), round(unrealized, 2),
         round(realized + unrealized, 2), positions_count, marked_at),
    )


def save_strategy_alerts(conn: sqlite3.Connection, created_at: str,
                         alerts: dict):
    """Log one deviation-alert evaluation per strategy (append-only)."""
    conn.executemany(
        "INSERT INTO strategy_alerts "
        "(created_at, strategy, level, reasons, n, win_rate, avg_pnl) "
        "VALUES (?,?,?,?,?,?,?)",
        [(created_at, strat, a["level"], json.dumps(a["reasons"]),
          (a.get("actual") or {}).get("n"),
          (a.get("actual") or {}).get("win_rate"),
          (a.get("actual") or {}).get("avg_pnl"))
         for strat, a in alerts.items()],
    )


def reset_stock_lab(conn: sqlite3.Connection):
    """Full-refresh semantics: each stock-lab run replaces all prior rows."""
    conn.execute("DELETE FROM stock_runs")
    conn.execute("DELETE FROM stock_trades")


def save_stock_run(conn: sqlite3.Connection, run_at: str, symbol: str,
                   strategy: str, metrics: dict) -> int:
    cur = conn.execute(
        "INSERT INTO stock_runs (run_at, symbol, strategy, metrics) VALUES (?,?,?,?)",
        (run_at, symbol, strategy, json.dumps(metrics)),
    )
    return cur.lastrowid


def save_stock_trades(conn: sqlite3.Connection, run_id: int, trades: list[dict]):
    cols = ["symbol", "strategy", "side", "entry_date", "entry_price",
            "shares", "exit_date", "exit_price", "exit_reason", "pnl",
            "pnl_pct", "hold_days"]
    conn.executemany(
        f"INSERT INTO stock_trades (run_id, {','.join(cols)}) "
        f"VALUES (?,{','.join('?' * len(cols))})",
        [[run_id] + [t.get(c) for c in cols] for t in trades],
    )


def save_stock_paper_trades(conn: sqlite3.Connection, trades: list[dict]):
    cols = ["symbol", "strategy", "side", "entry_date", "entry_price",
            "shares", "exit_date", "exit_price", "exit_reason", "pnl",
            "pnl_pct", "hold_days"]
    conn.executemany(
        f"INSERT INTO stock_paper_trades ({','.join(cols)}) "
        f"VALUES ({','.join('?' * len(cols))})",
        [[t.get(c) for c in cols] for t in trades],
    )


def save_stock_paper_positions(conn: sqlite3.Connection, positions: list[dict]):
    """Replace the open stock-paper set (keyed by symbol|strategy)."""
    conn.execute("DELETE FROM stock_paper_positions")
    conn.executemany(
        "INSERT INTO stock_paper_positions (key, data) VALUES (?,?)",
        [(p["key"], json.dumps(p)) for p in positions],
    )


def reset_param_runs(conn: sqlite3.Connection):
    """Full-refresh semantics: each optimization run replaces all rows."""
    conn.execute("DELETE FROM param_runs")


def save_param_run(conn: sqlite3.Connection, run_at: str, symbol: str,
                   strategy: str, params: dict, is_default: bool,
                   metrics: dict) -> int:
    cur = conn.execute(
        "INSERT INTO param_runs (run_at, symbol, strategy, params, is_default, metrics)"
        " VALUES (?,?,?,?,?,?)",
        (run_at, symbol, strategy, json.dumps(params), 1 if is_default else 0,
         json.dumps(metrics)),
    )
    return cur.lastrowid


def reset_exit_runs(conn: sqlite3.Connection):
    """Full-refresh semantics: each exit-grid run replaces all rows."""
    conn.execute("DELETE FROM exit_runs")


def save_exit_run(conn: sqlite3.Connection, run_at: str, symbol: str,
                  strategy: str, take_profit: float, stop_loss: float,
                  max_hold_days: int, is_default: bool, metrics: dict) -> int:
    cur = conn.execute(
        "INSERT INTO exit_runs (run_at, symbol, strategy, take_profit, stop_loss,"
        " max_hold_days, is_default, metrics) VALUES (?,?,?,?,?,?,?,?)",
        (run_at, symbol, strategy, take_profit, stop_loss, max_hold_days,
         1 if is_default else 0, json.dumps(metrics)),
    )
    return cur.lastrowid


# ---------------- Supabase sync (optional) ----------------

def supabase_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _sb(table: str, rows: list[dict]):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=rows, timeout=60)
            r.raise_for_status()
            return
        except Exception as e:  # noqa: BLE001 - retry transient timeouts
            last_err = e
    raise last_err


def _sb_delete_all(table: str):
    url = f"{SUPABASE_URL}/rest/v1/{table}?id=gt.0"
    if table in ("prices", "paper_positions"):  # no id column
        url = f"{SUPABASE_URL}/rest/v1/{table}?symbol=neq.__none__"
    elif table == "stock_paper_positions":      # keyed by "key"
        url = f"{SUPABASE_URL}/rest/v1/{table}?key=neq.__none__"
    elif table == "equity_snapshots":
        url = f"{SUPABASE_URL}/rest/v1/{table}?date=gte.1970-01-01"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Prefer": "return=minimal",
    }
    r = requests.delete(url, headers=headers, timeout=30)
    r.raise_for_status()


# columns that are jsonb in Supabase — values must be sent as JSON
# objects/arrays, not pre-serialized strings
JSONB_COLUMNS = {"backtest_runs": {"metrics"}, "signals": {"details"},
                 "paper_positions": {"data"}, "strategy_alerts": {"reasons"},
                 "stock_runs": {"metrics"},
                 "stock_paper_positions": {"data"},
                 "param_runs": {"params", "metrics"},
                 "exit_runs": {"metrics"}}


def sync_to_supabase():
    """Full-refresh push of local tables to Supabase (schema.sql required).

    Deletes remote rows then re-inserts in batches, so re-runs never
    accumulate duplicates. Tables are small (<5 MB) so this is cheap.
    """
    if not supabase_enabled():
        return {"enabled": False}
    conn = get_conn()
    out = {}
    for table in ("backtest_runs", "trades", "signals", "prices",
                  "paper_positions", "equity_snapshots", "strategy_alerts",
                  "stock_runs", "stock_trades",
                  "stock_paper_positions", "stock_paper_trades",
                  "param_runs", "exit_runs"):
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        cols = [d[0] for d in conn.execute(f"SELECT * FROM {table} LIMIT 1").description]
        dicts = [dict(zip(cols, r)) for r in rows]
        jsonb_cols = JSONB_COLUMNS.get(table, set())
        for d in dicts:
            d.pop("id", None)
            for c in jsonb_cols:
                if isinstance(d.get(c), str):
                    d[c] = json.loads(d[c])
        try:
            _sb_delete_all(table)
            if dicts:
                for i in range(0, len(dicts), 500):
                    _sb(table, dicts[i:i + 500])
            out[table] = len(dicts)
        except Exception as e:  # noqa: BLE001 - tolerate missing tables etc.
            out[table] = f"ERROR: {e}"
    return {"enabled": True, "synced": out}
