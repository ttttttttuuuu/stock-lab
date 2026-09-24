"""Aggressive re-optimization for watchlist strategies (offline analysis).

Unlike engine.param_optimize this does NOT touch the param_runs table — it
is a focused experiment for strategies that keep losing money (currently
wavetrend and rsi_reversion). Grids are wider than production, including
WaveTrend's overbought/oversold cross thresholds.

Verdict per strategy (same double guard as engine.weekly_evolve):
  - guard A: candidate full-window PnL beats current by max($50, 10%)
  - guard B: candidate also beats current on the held-out last 126 bars
PROMOTE  -> write the new params into production_params.json
DEMOTE   -> add the strategy to production watchlist (excluded from
            Top-pair selection and the live paper book)

Usage: python -m engine.watchlist_optimize [--years 2] [--tail 126] [--apply]
Without --apply it only prints the report (dry run).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import production
from .nasdaq import fetch_history
from .param_strategies import PARAM_SIGNALS
from .stock_backtest import compute_metrics, run_stock_backtest
from .universe import STOCK_SYMBOLS

ROOT = Path(__file__).resolve().parent.parent

# wider than the production grids; includes the previously hard-coded
# WaveTrend +/-53 cross thresholds
AGGRESSIVE_GRIDS = {
    "rsi_reversion": [
        {"period": p, "oversold": os_, "overbought": ob}
        for p in (5, 7, 10, 14, 21)
        for os_, ob in ((20, 80), (25, 75), (30, 70), (35, 65), (40, 60))
    ],
    "wavetrend": [
        {"ch_len": c, "avg_len": a, "overbought": ob, "oversold": -ob}
        for c in (7, 10, 14, 21)
        for a in (14, 21, 28, 35)
        for ob in (45.0, 53.0, 60.0)
    ],
}

MIN_IMPROVE_PCT = 0.10
MIN_IMPROVE_ABS = 50.0


def aggregate(frames, strategy: str, params: dict, exits, tail: int = 0) -> float:
    """Total PnL of one combo across the universe (tail>0 = last N bars)."""
    fn = PARAM_SIGNALS[strategy]
    total = 0.0
    for df in frames.values():
        sig = fn(df, **params)
        if tail:
            df_w = df.tail(tail).reset_index(drop=True)
            sig = sig.tail(tail).reset_index(drop=True)
        else:
            df_w = df
        tp, sl = exits
        trades = run_stock_backtest(df_w, sig, "", strategy,
                                    stop_loss=sl, take_profit=tp)
        total += compute_metrics(trades).get("total_pnl", 0)
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=2.0)
    ap.add_argument("--tail", type=int, default=126)
    ap.add_argument("--apply", action="store_true",
                    help="write verdicts into production_params.json")
    args = ap.parse_args()

    prod_params = production.all_strategy_params()
    prod_exits = production.all_strategy_exits()
    print(f"[watchlist-opt] loading {len(STOCK_SYMBOLS)} symbols ...", flush=True)
    frames = {sym: fetch_history(sym, years=args.years) for sym in STOCK_SYMBOLS}

    lines = [f"# Watchlist Re-optimization — "
             f"{datetime.now(timezone.utc).isoformat()[:16]}Z", ""]
    verdicts = {}

    for strat, grid in AGGRESSIVE_GRIDS.items():
        cur = dict(prod_params[strat])
        # current default may lack the new threshold keys — normalize through
        # the signal signature defaults by evaluating as-is
        exits = prod_exits.get(strat, production.GLOBAL_DEFAULT_EXIT)
        cur_full = aggregate(frames, strat, cur, exits)
        cur_tail = aggregate(frames, strat, cur, exits, tail=args.tail)
        print(f"\n[{strat}] current {json.dumps(cur)} "
              f"full={cur_full:.2f} tail={cur_tail:.2f}", flush=True)

        results = []
        for params in grid:
            full = aggregate(frames, strat, params, exits)
            results.append((full, params))
            print(f"  {json.dumps(params):60s} full={full:9.2f}", flush=True)
        results.sort(key=lambda r: r[0], reverse=True)

        # walk-forward check only for combos that pass guard A
        verdict = None
        for full, params in results:
            better = full - cur_full
            if better < max(MIN_IMPROVE_ABS, MIN_IMPROVE_PCT * abs(cur_full)):
                break  # sorted: nobody below can pass either
            tail_c = aggregate(frames, strat, params, exits, tail=args.tail)
            tag = "PASS" if tail_c > cur_tail else "fail-tail"
            print(f"  [guard] {json.dumps(params)} full={full:.2f} "
                  f"tail={tail_c:.2f} vs cur tail={cur_tail:.2f} -> {tag}",
                  flush=True)
            if tail_c > cur_tail:
                verdict = ("PROMOTE", params, full, tail_c)
                break
            if verdict is None:
                verdict = ("REJECTED", params, full, tail_c)

        if verdict and verdict[0] == "PROMOTE":
            _, params, full, tail_c = verdict
            verdicts[strat] = {"action": "PROMOTE", "params": params,
                               "full": full, "tail": tail_c,
                               "cur_full": cur_full, "cur_tail": cur_tail}
            lines.append(f"- **{strat}**: PROMOTE `{json.dumps(params)}` "
                         f"(full {cur_full:.0f}->{full:.0f}, "
                         f"tail {cur_tail:.0f}->{tail_c:.0f})")
        else:
            best_full, best_params = results[0]
            verdicts[strat] = {"action": "DEMOTE", "best_params": best_params,
                               "best_full": best_full,
                               "cur_full": cur_full, "cur_tail": cur_tail}
            lines.append(f"- **{strat}**: DEMOTE — no combo passed the double "
                         f"guard (best `{json.dumps(best_params)}` "
                         f"full={best_full:.0f} vs current {cur_full:.0f}, "
                         f"and/or tail not better)")

    report = ROOT / "logs" / f"watchlist_optimize_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M')}.md"
    report.write_text("\n".join(lines) + "\n")
    print(f"\n[watchlist-opt] report -> {report}")

    if args.apply:
        now = datetime.now(timezone.utc).isoformat()
        wl = production.watchlist()
        changed = False
        for strat, v in verdicts.items():
            if v["action"] == "PROMOTE":
                prod_params[strat] = v["params"]
                if strat in wl:
                    wl.remove(strat)
                changed = True
            else:
                if strat not in wl:
                    wl.append(strat)
                changed = True
        if changed:
            production.save(prod_params, prod_exits, now,
                            note="watchlist re-optimization", watchlist=wl)
            print(f"[watchlist-opt] applied. watchlist = {wl}")
    else:
        print("[watchlist-opt] dry run — re-run with --apply to write verdicts")


if __name__ == "__main__":
    main()
