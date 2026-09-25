"""Train / validation / live split analysis for the tracked 1h Top10 pairs.

Windows:
  train      2024-09-25 .. 2026-06-30  (selection knowledge cut-off)
  validation 2026-07-01 .. 2026-09-19  (capital-sim window, out-of-sample)
  live       2026-09-21 .. now         (real paper forward trading)

Run: python scripts/analyze_train_live.py
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import strategies  # noqa: E402
from engine.intraday import fetch_intraday  # noqa: E402
from engine.stock_backtest import compute_metrics, run_stock_backtest  # noqa: E402

TRAIN_END = "2026-06-30"
VAL_END = "2026-09-19"
HOLD_BARS = 7 * 10

state = json.loads((ROOT / "data/stock_paper_1h_positions.json").read_text())
pairs = state["pairs"]

conn = sqlite3.connect(ROOT / "data/trader.db")
live_closed = conn.execute(
    "SELECT symbol, strategy, pnl FROM stock_paper_intra_trades "
    "WHERE timeframe='1h'").fetchall()

frames = {}
for sym in sorted({p["symbol"] for p in pairs}):
    df = strategies.prepare(fetch_intraday(sym, "1h", use_cache=True))
    frames[sym] = df

rows = []
for p in pairs:
    sym, name = p["symbol"], p["strategy"]
    df = frames[sym]
    sig = strategies.STOCK_STRATEGIES[name](df)
    dates = df["date"].astype(str)

    tr_mask = dates <= TRAIN_END
    val_mask = (dates > TRAIN_END) & (dates <= VAL_END)

    tr = run_stock_backtest(df[tr_mask].reset_index(drop=True),
                            sig[tr_mask].reset_index(drop=True),
                            sym, name, max_hold_days=HOLD_BARS)
    va = run_stock_backtest(df[val_mask].reset_index(drop=True),
                            sig[val_mask].reset_index(drop=True),
                            sym, name, max_hold_days=HOLD_BARS)
    mt, mv = compute_metrics(tr), compute_metrics(va)

    lc = [t[2] for t in live_closed if t[0] == sym and t[1] == name]
    pos = next((x for x in state["positions"] if x["key"] == f"{sym}|{name}"), None)
    live_pnl = sum(lc) + (pos["unrealized_pnl"] if pos else 0)

    rows.append({
        "pair": f"{sym}×{name}",
        "train_pnl": mt.get("total_pnl", 0), "train_wr": mt.get("win_rate", 0),
        "train_n": mt.get("trades", 0),
        "val_pnl": mv.get("total_pnl", 0), "val_wr": mv.get("win_rate", 0),
        "val_n": mv.get("trades", 0),
        "live_pnl": round(live_pnl, 2),
        "live_status": ("持仓中" if pos else "空仓"),
    })

print(f"{'配对':<22}{'训练PnL':>9}{'胜率':>7}{'笔数':>5}"
      f"{'验证PnL':>9}{'胜率':>7}{'笔数':>5}{'实盘PnL':>9}  状态")
print("-" * 88)
tot = [0, 0, 0]
for r in sorted(rows, key=lambda x: -x["val_pnl"]):
    print(f"{r['pair']:<22}{r['train_pnl']:>9.2f}{r['train_wr']:>6.1f}%{r['train_n']:>5}"
          f"{r['val_pnl']:>9.2f}{r['val_wr']:>6.1f}%{r['val_n']:>5}{r['live_pnl']:>9.2f}"
          f"  {r['live_status']}")
    tot[0] += r["train_pnl"]; tot[1] += r["val_pnl"]; tot[2] += r["live_pnl"]
print("-" * 88)
print(f"{'合计':<22}{tot[0]:>9.2f}{'':>12}{tot[1]:>9.2f}{'':>12}{tot[2]:>9.2f}")
print(f"\n训练期 {len(df[dates <= TRAIN_END])} bars | 验证期 {len(df[val_mask])} bars"
      f" | 实盘自 2026-09-21 起")
