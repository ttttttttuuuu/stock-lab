"""Experiment: run the strategy matrix on intraday bars (15m / 1h / 4h).

Same strategies (production params), same stock backtest engine, same $100
notional per trade. Exits use each strategy's production tp/sl; the time
stop is expressed in bars per timeframe (~10 trading days).

Results go to data/intraday_summary.json + a per-timeframe CSV for
comparison against the daily matrix. Experiment only — not synced to
Supabase and not shown in the frontend yet.

Usage: python -m engine.run_intraday_backtest [--timeframes 15m,1h,4h]
                                              [--symbols AAPL,MSFT]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import strategies
from .intraday import TIMEFRAMES, RateLimited, fetch_intraday
from .run_backtest import DEFAULT_SYMBOLS
from .stock_backtest import compute_metrics, run_stock_backtest

ROOT = Path(__file__).resolve().parent.parent

MAX_RATE_LIMIT_PAUSES = 12        # 12 x 10 min = wait up to ~2h for unblock
RATE_LIMIT_SLEEP_S = 600


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframes", default="15m,1h,4h")
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    args = ap.parse_args()
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    run_at = datetime.now(timezone.utc).isoformat()
    results = []
    pauses = 0
    for tf in timeframes:
        cfg = TIMEFRAMES[tf]
        for sym in symbols:
            while True:
                try:
                    df = fetch_intraday(sym, tf)
                    break
                except RateLimited as e:
                    pauses += 1
                    if pauses > MAX_RATE_LIMIT_PAUSES:
                        print(f"[{tf}] {sym}: still rate-limited after "
                              f"{MAX_RATE_LIMIT_PAUSES} pauses ({e}) — saving "
                              f"partial results; rerun later (cache keeps "
                              f"finished symbols)", flush=True)
                        _write(out_path(), run_at, timeframes, symbols, results)
                        return
                    print(f"[{tf}] {sym}: rate-limited, pause 10 min "
                          f"({pauses}/{MAX_RATE_LIMIT_PAUSES})...", flush=True)
                    time.sleep(RATE_LIMIT_SLEEP_S)
                except Exception as e:  # noqa: BLE001 - skip symbols w/o data
                    print(f"[{tf}] {sym}: fetch failed: {e}", flush=True)
                    df = None
                    break
            if df is None:
                continue
            df = strategies.prepare(df)
            for name, fn in strategies.STOCK_STRATEGIES.items():
                sig = fn(df)
                trades = run_stock_backtest(df, sig, sym, name,
                                            max_hold_days=cfg["hold_bars"])
                m = compute_metrics(trades)
                results.append({"timeframe": tf, "symbol": sym,
                                "strategy": name, "bars": len(df), **m})
            print(f"[{tf}] {sym} done ({len(df)} bars)", flush=True)

    _write(out_path(), run_at, timeframes, symbols, results)
    print(f"\nDone. {len(results)} timeframe-strategy-symbol combos.")


def out_path() -> Path:
    return ROOT / "data" / "intraday_summary.json"


def _write(path: Path, run_at: str, timeframes: list[str],
           symbols: list[str], results: list[dict]):
    path.write_text(json.dumps({
        "run_at": run_at,
        "timeframes": timeframes,
        "symbols": symbols,
        "results": results,
    }))


if __name__ == "__main__":
    main()
