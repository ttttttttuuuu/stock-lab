"""Re-rank ALL 1h pairs by validation-window (2026-07-01..09-19) PnL,
using today's full-universe cache. Compares against the current Top10
(selected on full-window PnL).

Run: python scripts/analyze_val_rank.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import production, strategies  # noqa: E402
from engine.intraday import fetch_intraday  # noqa: E402
from engine.run_backtest import DEFAULT_SYMBOLS  # noqa: E402
from engine.stock_backtest import compute_metrics, run_stock_backtest  # noqa: E402

TRAIN_END = "2026-06-30"
VAL_END = "2026-09-19"
HOLD_BARS = 7 * 10
MIN_VAL_TRADES = 8

wl = set(production.watchlist())
state = json.loads((ROOT / "data/stock_paper_1h_positions.json").read_text())
current = {f"{p['symbol']}×{p['strategy']}" for p in state["pairs"]}

rows = []
for sym in sorted(DEFAULT_SYMBOLS):
    try:
        df = strategies.prepare(fetch_intraday(sym, "1h", use_cache=True,
                                               max_age_days=2))
    except Exception as e:  # noqa: BLE001
        print(f"  [skip] {sym}: {e}")
        continue
    dates = df["date"].astype(str)
    tr_mask = dates <= TRAIN_END
    val_mask = (dates > TRAIN_END) & (dates <= VAL_END)
    dtr, dva = df[tr_mask].reset_index(drop=True), df[val_mask].reset_index(drop=True)
    for name, fn in strategies.STOCK_STRATEGIES.items():
        if name in wl:
            continue
        sig = fn(df)
        va = run_stock_backtest(dva, sig[val_mask].reset_index(drop=True),
                                sym, name, max_hold_days=HOLD_BARS)
        mv = compute_metrics(va)
        if mv.get("trades", 0) < MIN_VAL_TRADES:
            continue
        tr = run_stock_backtest(dtr, sig[tr_mask].reset_index(drop=True),
                                sym, name, max_hold_days=HOLD_BARS)
        mt = compute_metrics(tr)
        rows.append({
            "pair": f"{sym}×{name}",
            "val_pnl": mv.get("total_pnl", 0), "val_wr": mv.get("win_rate", 0),
            "val_n": mv.get("trades", 0),
            "train_pnl": mt.get("total_pnl", 0),
            "current": f"{sym}×{name}" in current,
        })

rows.sort(key=lambda r: -r["val_pnl"])
print(f"{'排名':<4}{'配对':<22}{'验证PnL':>9}{'胜率':>7}{'笔数':>5}{'训练PnL':>9}  备注")
print("-" * 70)
for i, r in enumerate(rows[:15], 1):
    tag = "当前Top10" if r["current"] else ("训练期亏损!" if r["train_pnl"] < 0 else "新面孔")
    print(f"{i:<4}{r['pair']:<22}{r['val_pnl']:>9.2f}{r['val_wr']:>6.1f}%{r['val_n']:>5}"
          f"{r['train_pnl']:>9.2f}  {tag}")
out = rows[:15]
(ROOT / "data/val_rank_1h.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
