"""Grid-search strategy parameters across the stock universe.

For every (strategy, symbol, param-combo) the raw OHLCV frame is turned
into signals by engine.param_strategies (defaults = production params),
traded by the same stock backtest engine, and persisted to param_runs.

Usage: python -m engine.param_optimize [--symbols AAPL,MSFT] [--years 2]
                                       [--strategies supertrend,ut_bot]
                                       [--no-sync]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import storage
from .nasdaq import fetch_history
from .param_strategies import DEFAULT_PARAMS, PARAM_GRIDS, PARAM_SIGNALS
from .universe import STOCK_SYMBOLS as DEFAULT_SYMBOLS
from .stock_backtest import compute_metrics, run_stock_backtest

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--years", type=float, default=2.0)
    ap.add_argument("--strategies",
                    default=",".join(PARAM_GRIDS.keys()))
    ap.add_argument("--no-sync", action="store_true")
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    strat_names = [s.strip() for s in args.strategies.split(",") if s.strip()]
    for name in strat_names:
        if name not in PARAM_GRIDS:
            raise SystemExit(f"unknown strategy for optimization: {name}")

    storage.init_db()
    run_at = datetime.now(timezone.utc).isoformat()
    n_runs = 0
    full_run = set(strat_names) == set(PARAM_GRIDS.keys())

    with storage.get_conn() as conn:
        prev_run_at = None
        if full_run:
            storage.reset_param_runs(conn)
        else:
            # partial run: replace only the selected strategies, then carry
            # the rest forward so "latest run_at" readers still see them
            prev_run_at = conn.execute(
                "SELECT MAX(run_at) FROM param_runs").fetchone()[0]
            storage.reset_param_runs(conn, strat_names)
        for sym in symbols:
            print(f"[fetch] {sym} ...", flush=True)
            df = fetch_history(sym, years=args.years)
            storage.upsert_prices(conn, sym, df)
            for name in strat_names:
                fn = PARAM_SIGNALS[name]
                default = DEFAULT_PARAMS[name]
                best = None
                for params in PARAM_GRIDS[name]:
                    sig = fn(df, **params)
                    trades = run_stock_backtest(df, sig, sym, name)
                    metrics = compute_metrics(trades)
                    is_default = params == default
                    storage.save_param_run(conn, run_at, sym, name, params,
                                           is_default, metrics)
                    n_runs += 1
                    pnl = metrics.get("total_pnl", 0)
                    if best is None or pnl > best[1]:
                        best = (params, pnl)
                print(f"  {name:15s} best={json.dumps(best[0])} "
                      f"pnl={best[1]} (default "
                      f"{json.dumps(default)})", flush=True)

        if not full_run and prev_run_at:
            carried = storage.carry_forward_param_runs(
                conn, prev_run_at, run_at, strat_names)
            print(f"carried forward {carried} rows from previous batch "
                  f"({prev_run_at})")

    out = {
        "run_at": run_at,
        "symbols": symbols,
        "years": args.years,
        "strategies": strat_names,
        "combos": n_runs,
    }
    (ROOT / "data" / "param_opt_summary.json").write_text(
        json.dumps(out, indent=2))
    print(f"\nDone. {n_runs} param combos across {len(symbols)} symbols x "
          f"{len(strat_names)} strategies.")

    if not args.no_sync and storage.supabase_enabled():
        print("Syncing to Supabase ...")
        print(storage.sync_to_supabase())


if __name__ == "__main__":
    main()
