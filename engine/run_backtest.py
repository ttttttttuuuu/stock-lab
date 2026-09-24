"""Run the full multi-symbol x multi-strategy backtest and persist results.

Usage: python -m engine.run_backtest [--symbols AAPL,MSFT] [--years 2]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import storage, strategies
from .backtest import compute_metrics, run_backtest, trades_to_dicts
from .nasdaq import fetch_history

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SYMBOLS = [
    # mega tech
    "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "AMZN", "META", "GOOGL", "AVGO", "NFLX",
    # tech / semis
    "ORCL", "CRM", "ADBE", "INTC", "MU", "CSCO", "QCOM", "TXN", "ARM", "DELL",
    # high-beta / retail favorites
    "PLTR", "SMCI", "COIN", "MSTR", "HOOD", "SOFI", "SNAP", "UBER", "SHOP", "PYPL",
    # consumer / industrial / financial / energy
    "F", "GM", "BA", "DIS", "NKE", "SBUX", "MCD", "WMT", "JPM", "BAC",
    "XOM", "CVX", "PFE", "BABA", "NIO", "RIVN", "LCID",
    # index ETFs
    "SPY", "QQQ", "IWM",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--years", type=float, default=2.0)
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    storage.init_db()
    run_at = datetime.now(timezone.utc).isoformat()
    all_metrics = []
    trade_counts = 0

    with storage.get_conn() as conn:
        for sym in symbols:
            print(f"[fetch] {sym} ...", flush=True)
            df = fetch_history(sym, years=args.years)
            storage.upsert_prices(conn, sym, df)
            df = strategies.prepare(df)
            for name, fn in strategies.ALL_STRATEGIES.items():
                sig = fn(df)
                trades = run_backtest(df, sig, sym, name)
                metrics = compute_metrics(trades)
                run_id = storage.save_run(conn, run_at, sym, name, metrics)
                storage.save_trades(conn, run_id, trades_to_dicts(trades))
                trade_counts += len(trades)
                all_metrics.append({"symbol": sym, "strategy": name, **metrics})
                print(f"  {name:15s} trades={metrics.get('trades', 0):3d} "
                      f"pnl={metrics.get('total_pnl', 0)}", flush=True)

    # aggregated leaderboard for the frontend
    out = {
        "run_at": run_at,
        "symbols": symbols,
        "years": args.years,
        "results": all_metrics,
    }
    (ROOT / "data" / "backtest_summary.json").write_text(json.dumps(out, indent=2))
    print(f"\nDone. {len(all_metrics)} strategy-symbol combos, {trade_counts} trades.")

    if storage.supabase_enabled():
        print("Syncing to Supabase ...")
        print(storage.sync_to_supabase())


if __name__ == "__main__":
    main()
