"""Grid-search the exit structure (take-profit / stop-loss) per strategy.

Entry signals always use the production default strategy params; only the
exit rules vary. This isolates the effect of the exit structure itself.

Usage: python -m engine.exit_optimize [--symbols AAPL,MSFT] [--years 2]
                                      [--no-sync]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import storage
from .nasdaq import fetch_history
from .param_strategies import DEFAULT_PARAMS, PARAM_SIGNALS
from .universe import STOCK_SYMBOLS as DEFAULT_SYMBOLS
from .stock_backtest import (MAX_HOLD_DAYS, compute_metrics, exits_for,
                             run_stock_backtest)

ROOT = Path(__file__).resolve().parent.parent

# exit structures to compare; must contain every strategy's production exit
EXIT_GRID = [
    {"take_profit": 0.10, "stop_loss": -0.05},   # global default
    {"take_profit": 0.06, "stop_loss": -0.03},   # tight both (higher win rate)
    {"take_profit": 0.08, "stop_loss": -0.04},   # moderately tight
    {"take_profit": 0.15, "stop_loss": -0.07},   # wide both (trend friendly)
    {"take_profit": 0.10, "stop_loss": -0.03},   # tight stop, normal target
    {"take_profit": 0.05, "stop_loss": -0.05},   # symmetric tight
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--years", type=float, default=2.0)
    ap.add_argument("--no-sync", action="store_true")
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    storage.init_db()
    run_at = datetime.now(timezone.utc).isoformat()
    n_runs = 0

    with storage.get_conn() as conn:
        storage.reset_exit_runs(conn)
        for sym in symbols:
            print(f"[fetch] {sym} ...", flush=True)
            df = fetch_history(sym, years=args.years)
            storage.upsert_prices(conn, sym, df)
            for name, fn in PARAM_SIGNALS.items():
                sig = fn(df, **DEFAULT_PARAMS[name])
                prod_tp, prod_sl = exits_for(name)
                best = None
                for ex in EXIT_GRID:
                    trades = run_stock_backtest(
                        df, sig, sym, name,
                        stop_loss=ex["stop_loss"],
                        take_profit=ex["take_profit"],
                        max_hold_days=MAX_HOLD_DAYS)
                    metrics = compute_metrics(trades)
                    is_default = (ex["take_profit"], ex["stop_loss"]) == (prod_tp, prod_sl)
                    storage.save_exit_run(
                        conn, run_at, sym, name, ex["take_profit"],
                        ex["stop_loss"], MAX_HOLD_DAYS, is_default, metrics)
                    n_runs += 1
                    pnl = metrics.get("total_pnl", 0)
                    if best is None or pnl > best[1]:
                        best = (ex, pnl)
                print(f"  {name:15s} best=tp{best[0]['take_profit']:.0%}/"
                      f"sl{best[0]['stop_loss']:.0%} pnl={best[1]}", flush=True)

    out = {
        "run_at": run_at,
        "symbols": symbols,
        "years": args.years,
        "combos": n_runs,
    }
    (ROOT / "data" / "exit_opt_summary.json").write_text(json.dumps(out, indent=2))
    print(f"\nDone. {n_runs} exit combos across {len(symbols)} symbols x "
          f"{len(PARAM_SIGNALS)} strategies.")

    if not args.no_sync and storage.supabase_enabled():
        print("Syncing to Supabase ...")
        print(storage.sync_to_supabase())


if __name__ == "__main__":
    main()
