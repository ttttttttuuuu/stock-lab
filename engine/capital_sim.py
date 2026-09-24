"""Capital simulation: "what if I started executing on day X with $1000?"

Strictly no look-ahead: pair/strategy selection uses ONLY the train window
(data before the split date); the test window (split -> today) is then traded
flat-start with current production params/exits, $100 per pair.

Scenarios per timeframe:
  A) Top10 portfolio  — top 10 pairs by train PnL, $100 each ($1000 total)
  B) Single best pair — top 1 pair by train PnL, $1000 (10x scale)
  C) Single strategy  — best strategy by train aggregate PnL, spread $100
                        over its top 10 symbols by train PnL
  D) Hindsight max    — best TEST-window pair x $1000 (God's view, NOT
                        executable; shown only as an upper bound)

Timeframes & splits:
  1d / 1h / 4h: train = start..2026-06-30, test = 2026-07-01..today
  15m: only ~40 trading days exist; train = ..2026-08-31, test = 09-01..today

Usage: python -m engine.capital_sim [--timeframes 1d,1h,4h,15m]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import production, strategies
from .intraday import TIMEFRAMES, fetch_intraday
from .nasdaq import fetch_history
from .run_backtest import DEFAULT_SYMBOLS as INTRADAY_SYMBOLS
from .stock_backtest import MAX_HOLD_DAYS, compute_metrics, run_stock_backtest
from .universe import STOCK_SYMBOLS

ROOT = Path(__file__).resolve().parent.parent
TRADE_BUDGET = 100.0
MIN_TRAIN_TRADES = 3          # ignore noise pairs when ranking
TOP_N = 10

TF_CONFIG = {
    "1d": {"split": "2026-07-01", "hold": MAX_HOLD_DAYS, "kind": "daily"},
    "1h": {"split": "2026-07-01", "hold": TIMEFRAMES["1h"]["hold_bars"], "kind": "intra"},
    "4h": {"split": "2026-07-01", "hold": TIMEFRAMES["4h"]["hold_bars"], "kind": "intra"},
    "15m": {"split": "2026-09-01", "hold": TIMEFRAMES["15m"]["hold_bars"], "kind": "intra"},
}


def load_frames(tf: str) -> dict:
    cfg = TF_CONFIG[tf]
    symbols = STOCK_SYMBOLS if cfg["kind"] == "daily" else INTRADAY_SYMBOLS
    frames = {}
    for sym in symbols:
        try:
            df = (fetch_history(sym, years=2) if cfg["kind"] == "daily"
                  else fetch_intraday(sym, tf))
            frames[sym] = strategies.prepare(df)
        except Exception as e:  # noqa: BLE001 - skip symbols w/o data
            print(f"  [{tf}] {sym}: load failed: {e}", flush=True)
    return frames


def split_frame(df, sig, split: str):
    """Split by date; signals were computed on the FULL frame first so
    indicators keep their warmup (same methodology as weekly_evolve tail)."""
    ts = pd.to_datetime(df["date"], utc=True)
    boundary = pd.Timestamp(split, tz="UTC")
    train_m = (ts < boundary).to_numpy()
    test_m = ~train_m
    cols = df.reset_index(drop=True)
    s = sig.reset_index(drop=True)
    return (cols[train_m].reset_index(drop=True), s[train_m].reset_index(drop=True),
            cols[test_m].reset_index(drop=True), s[test_m].reset_index(drop=True),
            str(ts[train_m].max())[:10] if train_m.any() else None,
            str(ts[test_m].min())[:10] if test_m.any() else None,
            str(ts[test_m].max())[:10] if test_m.any() else None)


def run_tf(tf: str, watchlist: set) -> dict:
    cfg = TF_CONFIG[tf]
    print(f"\n[{tf}] split={cfg['split']} hold={cfg['hold']} — loading frames...",
          flush=True)
    frames = load_frames(tf)
    print(f"[{tf}] {len(frames)} symbols loaded", flush=True)

    train_rows, test_cache = [], {}
    te_start_all, te_end_all = None, None
    for sym, df in frames.items():
        for name, fn in strategies.STOCK_STRATEGIES.items():
            if name in watchlist:
                continue
            sig = fn(df)
            dtr, str_, dte, ste, tr_end, te_start, te_end = split_frame(
                df, sig, cfg["split"])
            if len(dtr) < 50 or len(dte) < 5:
                continue
            if te_start and (te_start_all is None or te_start < te_start_all):
                te_start_all = te_start
            if te_end and (te_end_all is None or te_end > te_end_all):
                te_end_all = te_end
            tr = run_stock_backtest(dtr, str_, sym, name,
                                    max_hold_days=cfg["hold"])
            tm = compute_metrics(tr)
            if tm.get("trades", 0) >= MIN_TRAIN_TRADES:
                train_rows.append({"symbol": sym, "strategy": name,
                                   "train_pnl": tm["total_pnl"],
                                   "train_trades": tm["trades"],
                                   "train_win_rate": tm.get("win_rate", 0)})
            te = run_stock_backtest(dte, ste, sym, name,
                                    max_hold_days=cfg["hold"])
            test_cache[(sym, name)] = te
        print(f"  [{tf}] {sym} done", flush=True)

    train_rows.sort(key=lambda r: r["train_pnl"], reverse=True)
    top_pairs = train_rows[:TOP_N]

    def test_metrics(sym, strat):
        ts = test_cache.get((sym, strat), [])
        m = compute_metrics(ts)
        return {"trades": m.get("trades", 0), "pnl": m.get("total_pnl", 0),
                "win_rate": m.get("win_rate", 0)}

    # A) Top10 portfolio, $100 each
    port_pairs = []
    all_test_trades = []
    for r in top_pairs:
        tm = test_metrics(r["symbol"], r["strategy"])
        port_pairs.append({**r, "test_trades": tm["trades"],
                           "test_pnl": tm["pnl"], "test_win_rate": tm["win_rate"]})
        all_test_trades.extend(test_cache.get((r["symbol"], r["strategy"]), []))
    port_total = sum(p["test_pnl"] for p in port_pairs)

    def equity_curve(trades):
        daily = {}
        for t in trades:
            daily[t.exit_date] = daily.get(t.exit_date, 0) + t.pnl
        cum = 0.0
        return [{"date": d, "pnl": round(cum := cum + v, 2)}
                for d, v in sorted(daily.items())]

    # B) single best pair by train, $1000
    best = top_pairs[0] if top_pairs else None
    single_pair = None
    if best:
        tm = test_metrics(best["symbol"], best["strategy"])
        single_pair = {**best, "test_trades": tm["trades"],
                       "test_pnl_x10": round(tm["pnl"] * 10, 2),
                       "equity": [{"date": p["date"], "pnl": round(p["pnl"] * 10, 2)}
                                  for p in equity_curve(
                                      test_cache.get((best["symbol"],
                                                      best["strategy"]), []))]}

    # C) single strategy: best train aggregate, $100 x its top-10 symbols
    by_strat = {}
    for r in train_rows:
        by_strat.setdefault(r["strategy"], 0.0)
        by_strat[r["strategy"]] += r["train_pnl"]
    best_strat = max(by_strat, key=by_strat.get) if by_strat else None
    single_strat = None
    if best_strat:
        legs = [r for r in train_rows if r["strategy"] == best_strat][:TOP_N]
        leg_rows = []
        for r in legs:
            tm = test_metrics(r["symbol"], r["strategy"])
            leg_rows.append({"symbol": r["symbol"], "train_pnl": r["train_pnl"],
                             "test_pnl": tm["pnl"], "test_trades": tm["trades"]})
        single_strat = {"strategy": best_strat,
                        "train_total": round(by_strat[best_strat], 2),
                        "legs": leg_rows,
                        "test_total": round(sum(l["test_pnl"] for l in leg_rows), 2)}

    # D) hindsight max over ALL pairs (not executable)
    hind = None
    for (sym, strat), ts in test_cache.items():
        pnl = compute_metrics(ts).get("total_pnl", 0)
        if hind is None or pnl > hind["test_pnl"]:
            hind = {"symbol": sym, "strategy": strat, "test_pnl": round(pnl, 2)}

    return {
        "timeframe": tf, "split": cfg["split"],
        "test_window": f"{te_start_all} -> {te_end_all}",
        "portfolio_top10": {"pairs": port_pairs,
                            "test_total": round(port_total, 2),
                            "winning_legs": sum(1 for p in port_pairs
                                              if p["test_pnl"] > 0),
                            "equity": equity_curve(all_test_trades)},
        "single_pair": single_pair,
        "single_strategy": single_strat,
        "hindsight_max": hind,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframes", default="1d,1h,4h,15m")
    args = ap.parse_args()
    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    watchlist = set(production.watchlist())

    out_path = ROOT / "data" / "capital_sim.json"
    # merge with existing results so a daily 1d-only refresh never wipes the
    # intraday sections (those rerun on demand / with evolution)
    existing = {}
    if out_path.exists():
        try:
            old = json.loads(out_path.read_text())
            existing = {r["timeframe"]: r for r in old.get("results", [])}
        except Exception:  # noqa: BLE001 - corrupt file -> start fresh
            existing = {}

    out = {"run_at": datetime.now(timezone.utc).isoformat(),
           "budget_per_pair": TRADE_BUDGET, "capital": TRADE_BUDGET * TOP_N,
           "watchlist_excluded": sorted(watchlist), "results": []}
    for tf in tfs:
        existing[tf] = run_tf(tf, watchlist)
    order = {"1d": 0, "1h": 1, "4h": 2, "15m": 3}
    out["results"] = [existing[k] for k in
                      sorted(existing, key=lambda k: order.get(k, 9))]
    # recommended = timeframe whose Top10 portfolio did best out-of-sample
    best_a = max(out["results"], key=lambda r: r["portfolio_top10"]["test_total"])
    out["recommended"] = best_a["timeframe"]

    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    web_out = ROOT / "web" / "public" / "data" / "capital_sim.json"
    web_out.parent.mkdir(parents=True, exist_ok=True)
    web_out.write_text(json.dumps(out, ensure_ascii=False))

    lines = [f"# 资金模拟报告 — {out['run_at'][:16]}Z",
             "",
             f"本金 $1000 · 每股对 $100 · 选择窗口严格只用 split 之前的数据 · "
             f"观察名单策略已排除: {', '.join(sorted(watchlist)) or '无'}",
             ""]
    for r in out["results"]:
        lines.append(f"## {r['timeframe']}（split {r['split']}，测试窗 {r['test_window']}）")
        a = r["portfolio_top10"]["test_total"]
        b = r["single_pair"]["test_pnl_x10"] if r["single_pair"] else None
        c = r["single_strategy"]["test_total"] if r["single_strategy"] else None
        d = r["hindsight_max"]["test_pnl"] * 10 if r["hindsight_max"] else None
        lines.append(f"- A Top10 组合: **${a:+.2f}**")
        if b is not None:
            sp = r["single_pair"]
            lines.append(f"- B 单一配对满仓 ({sp['symbol']}×{sp['strategy']}): **${b:+.2f}**")
        if c is not None:
            lines.append(f"- C 单策略分散 ({r['single_strategy']['strategy']}): **${c:+.2f}**")
        if d is not None:
            hm = r["hindsight_max"]
            lines.append(f"- D 上帝视角上限 ({hm['symbol']}×{hm['strategy']}): ${d:+.2f}（不可实盘）")
        lines.append("")
    report = ROOT / "logs" / f"capital_sim_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M')}.md"
    report.write_text("\n".join(lines) + "\n")
    print(f"\n[capital-sim] report -> {report}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
