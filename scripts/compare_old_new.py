"""Old vs new Top10 comparison after the dual-window re-selection.

For each OLD pair (snapshot), computes the hypothetical PnL of having
kept trading it from the switch date forward (signal replay on cached
bars). Compares against the NEW pairs' actual live ledger PnL over the
same period.

Run a few days after re-selection:  python scripts/compare_old_new.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import production, strategies  # noqa: E402
from engine.intraday import fetch_intraday  # noqa: E402
from engine.stock_backtest import compute_metrics, run_stock_backtest  # noqa: E402

HOLD_BARS = 7 * 10

snap = json.loads((ROOT / "data/old_top10_1h_snapshot.json").read_text())
state = json.loads((ROOT / "data/stock_paper_1h_positions.json").read_text())
switch = state.get("selected_on")
if not switch or switch <= snap["snapshot_date"]:
    sys.exit(f"re-selection hasn't happened yet (selected_on={switch}); "
             f"run this after the next full selection")

wl = set(production.watchlist())
print(f"切换日: {switch} | 旧组合快照: {snap['snapshot_date']}\n")

# hypothetical old-pair performance since switch
print("== 旧组合：如果继续持有 ==")
old_total = 0
for p in snap["pairs"]:
    sym, name = p["symbol"], p["strategy"]
    if name in wl:
        continue
    df = strategies.prepare(fetch_intraday(sym, "1h", use_cache=True,
                                           max_age_days=2))
    dates = df["date"].astype(str)
    mask = dates >= switch
    if mask.sum() < 5:
        print(f"  {sym}×{name}: 切换后数据不足")
        continue
    sig = strategies.STOCK_STRATEGIES[name](df)
    trades = run_stock_backtest(df[mask].reset_index(drop=True),
                                sig[mask].reset_index(drop=True),
                                sym, name, max_hold_days=HOLD_BARS)
    m = compute_metrics(trades)
    pnl = m.get("total_pnl", 0)
    old_total += pnl
    print(f"  {sym:5} {name:12} 假设盈亏 {pnl:>8.2f}  ({m.get('trades',0)} 笔)")
print(f"  {'合计':<18}{old_total:>8.2f}\n")

# actual new-pair live performance since switch
print("== 新组合：实盘账本 ==")
import sqlite3
conn = sqlite3.connect(ROOT / "data/trader.db")
rows = conn.execute(
    "SELECT symbol, strategy, SUM(pnl) FROM stock_paper_intra_trades "
    "WHERE timeframe='1h' AND exit_date >= ? GROUP BY 1,2", (switch,)).fetchall()
new_total = sum(r[2] for r in rows)
unreal = sum(p["unrealized_pnl"] or 0 for p in state["positions"])
for r in rows:
    print(f"  {r[0]:5} {r[1]:12} 已实现 {r[2]:>8.2f}")
print(f"  浮盈（当前持仓）: {unreal:.2f}")
print(f"  合计: {new_total + unreal:.2f}\n")
print(f"== 结论: 新组合 {'跑赢' if new_total + unreal > old_total else '跑输'} "
      f"旧组合 {abs(new_total + unreal - old_total):.2f} 美元 ==")
