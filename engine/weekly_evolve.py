"""Weekly strategy evolution: re-run the param + exit grids, then promote
better combos into data/production_params.json — but only when they pass
BOTH guards:

  A) full-window aggregate PnL beats current production by >= 10% (and $50)
  B) walk-forward check: on the held-out last ~6 months (126 trading days),
     the candidate also beats current production

Guard B is the anti-overfitting gate: a combo that only wins in-sample does
not get promoted. All decisions are logged to logs/weekly_evolve_*.md.

Usage: python -m engine.weekly_evolve [--years 2] [--tail 126]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import production, storage
from .nasdaq import fetch_history
from .param_strategies import PARAM_SIGNALS
from .run_backtest import DEFAULT_SYMBOLS
from .stock_backtest import run_stock_backtest

ROOT = Path(__file__).resolve().parent.parent
MIN_IMPROVE_PCT = 0.10      # guard A: relative improvement threshold
MIN_IMPROVE_ABS = 50.0      # guard A: absolute improvement threshold (USD)


def run_module(name: str, *extra: str):
    print(f"[step] python -m {name} {' '.join(extra)}", flush=True)
    r = subprocess.run([sys.executable, "-m", name, *extra], cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"{name} failed with code {r.returncode}")


def latest_rows(conn, table: str) -> list[dict]:
    cur = conn.execute(
        f"SELECT * FROM {table} r JOIN (SELECT MAX(run_at) m FROM {table}) t"
        " ON r.run_at = t.m")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def tail_pnl(frames, strategy: str, params: dict, exits, tail: int) -> float:
    """Aggregate PnL of one param/exit combo on the held-out tail window."""
    fn = PARAM_SIGNALS[strategy]
    total = 0.0
    for df in frames.values():
        sig = fn(df, **params)
        trades = run_stock_backtest(df.tail(tail).reset_index(drop=True),
                                    sig.tail(tail).reset_index(drop=True),
                                    "", strategy,
                                    take_profit=exits[0], stop_loss=exits[1])
        total += sum(t.pnl for t in trades)
    return round(total, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=2.0)
    ap.add_argument("--tail", type=int, default=126)
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    now = datetime.now(timezone.utc).isoformat()

    # 1) refresh both grids (no sync yet)
    run_module("engine.param_optimize", "--no-sync", "--years", str(args.years))
    run_module("engine.exit_optimize", "--no-sync", "--years", str(args.years))

    # 2) aggregate grids per strategy
    conn = storage.get_conn()
    param_rows = latest_rows(conn, "param_runs")
    exit_rows = latest_rows(conn, "exit_runs")

    agg_p = defaultdict(lambda: defaultdict(float))   # strategy -> pjson -> pnl
    cur_p = {}                                        # strategy -> current pnl
    for r in param_rows:
        params = json.loads(r["params"])
        m = json.loads(r["metrics"])
        agg_p[r["strategy"]][json.dumps(params, sort_keys=True)] += \
            m.get("total_pnl", 0)
        if r["is_default"]:
            cur_p[r["strategy"]] = cur_p.get(r["strategy"], 0) + m.get("total_pnl", 0)

    agg_e = defaultdict(lambda: defaultdict(float))   # strategy -> "tp|sl" -> pnl
    cur_e = {}
    for r in exit_rows:
        m = json.loads(r["metrics"])
        key = f"{r['take_profit']}|{r['stop_loss']}"
        agg_e[r["strategy"]][key] += m.get("total_pnl", 0)
        if r["is_default"]:
            cur_e[r["strategy"]] = cur_e.get(r["strategy"], 0) + m.get("total_pnl", 0)

    prod_params = production.all_strategy_params()
    prod_exits = {s: production.strategy_exit(s) for s in PARAM_SIGNALS}

    # 3) preload frames once for walk-forward validation
    frames = {sym: fetch_history(sym, years=args.years) for sym in symbols}

    verdicts = []
    new_params = {k: dict(v) for k, v in prod_params.items()}
    new_exits = dict(prod_exits)
    promotions = 0

    for strat in sorted(PARAM_SIGNALS):
        # ---- params candidate ----
        best_pjson = max(agg_p[strat], key=agg_p[strat].get)
        cand_params = json.loads(best_pjson)
        cand_pnl = agg_p[strat][best_pjson]
        base_pnl = cur_p.get(strat, 0)
        verdict_p = "keep"
        if cand_params != prod_params[strat]:
            better = cand_pnl - base_pnl
            guard_a = better >= max(MIN_IMPROVE_ABS,
                                    abs(base_pnl) * MIN_IMPROVE_PCT)
            if guard_a:
                tail_c = tail_pnl(frames, strat, cand_params,
                                  prod_exits[strat], args.tail)
                tail_b = tail_pnl(frames, strat, prod_params[strat],
                                  prod_exits[strat], args.tail)
                if tail_c > tail_b:
                    new_params[strat] = cand_params
                    verdict_p = f"PROMOTE (full {base_pnl:.0f}->{cand_pnl:.0f}, tail {tail_b:.0f}->{tail_c:.0f})"
                    promotions += 1
                else:
                    verdict_p = f"rejected by walk-forward (tail {tail_b:.0f} vs {tail_c:.0f})"
            else:
                verdict_p = f"rejected by margin (+{better:.0f} < threshold)"
        verdicts.append(f"- **{strat}** params: {verdict_p} "
                        f"(candidate `{best_pjson}` ${cand_pnl:.0f} vs current ${base_pnl:.0f})")

        # ---- exit candidate ----
        best_ekey = max(agg_e[strat], key=agg_e[strat].get)
        tp, sl = (float(x) for x in best_ekey.split("|"))
        cand_epnl = agg_e[strat][best_ekey]
        base_epnl = cur_e.get(strat, 0)
        verdict_e = "keep"
        if (tp, sl) != tuple(prod_exits[strat]):
            better = cand_epnl - base_epnl
            guard_a = better >= max(MIN_IMPROVE_ABS,
                                    abs(base_epnl) * MIN_IMPROVE_PCT)
            if guard_a:
                tail_c = tail_pnl(frames, strat, new_params[strat],
                                  (tp, sl), args.tail)
                tail_b = tail_pnl(frames, strat, new_params[strat],
                                  prod_exits[strat], args.tail)
                if tail_c > tail_b:
                    new_exits[strat] = (tp, sl)
                    verdict_e = f"PROMOTE (full {base_epnl:.0f}->{cand_epnl:.0f}, tail {tail_b:.0f}->{tail_c:.0f})"
                    promotions += 1
                else:
                    verdict_e = f"rejected by walk-forward (tail {tail_b:.0f} vs {tail_c:.0f})"
            else:
                verdict_e = f"rejected by margin (+{better:.0f} < threshold)"
        verdicts.append(f"- **{strat}** exits: {verdict_e} "
                        f"(candidate tp{tp:.0%}/sl{sl:.0%} ${cand_epnl:.0f} vs current ${base_epnl:.0f})")

    # 4) persist + rerun if anything changed
    if promotions:
        production.save(new_params, new_exits, now,
                        note=f"weekly evolve {now[:10]}: {promotions} promotion(s)")
        print(f"[evolve] {promotions} promotion(s) applied, rerunning matrix...",
              flush=True)
        run_module("engine.run_stock_backtest")      # self-syncs
    else:
        print("[evolve] no promotions this week", flush=True)
        run_module("engine.sync")
    run_module("engine.export_web")

    # 5) report
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    stamp = now[:16].replace(":", "").replace("-", "")
    report = logs / f"weekly_evolve_{stamp}.md"
    report.write_text(
        f"# Weekly Evolution — {now[:16]}Z\n\n"
        f"promotions: **{promotions}**\n\n" + "\n".join(verdicts) + "\n",
        encoding="utf-8")
    (ROOT / "data" / "weekly_evolve_summary.json").write_text(json.dumps({
        "run_at": now,
        "promotions": promotions,
        "report": str(report.relative_to(ROOT)),
    }, indent=2))
    print(f"[evolve] report -> {report}", flush=True)
    print(f"EVOLVE_SUMMARY promotions={promotions}", flush=True)


if __name__ == "__main__":
    main()
