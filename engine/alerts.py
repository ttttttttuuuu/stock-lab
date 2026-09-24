"""Live-vs-backtest deviation alerts — mirrors web/lib/reviewStats.js.

A strategy with enough closed paper trades that significantly underperforms
its 2-year backtest baseline gets flagged. daily_signals skips NEW opens for
CRITICAL strategies (existing positions are still managed to exit); every
evaluation is logged to the strategy_alerts table for the dashboard.

Keep the thresholds in sync with web/lib/reviewStats.js.
"""
from __future__ import annotations

MIN_SAMPLE = 5
WIN_RATE_CRIT_PP = -15.0
WIN_RATE_WATCH_PP = -8.0

LEVELS = ("insufficient", "ok", "watch", "critical")


def _stats(pnls: list[float]) -> dict | None:
    if not pnls:
        return None
    wins = [p for p in pnls if p > 0]
    return {
        "n": len(pnls),
        "win_rate": round(len(wins) / len(pnls) * 100, 1),
        "avg_pnl": round(sum(pnls) / len(pnls), 2),
        "total_pnl": round(sum(pnls), 2),
    }


def evaluate_one(actual: dict | None, baseline: dict) -> dict:
    """Same rules as reviewStats.js alertLevel()."""
    if not actual or actual["n"] < MIN_SAMPLE:
        return {"level": "insufficient", "reasons": []}
    d_win = round(actual["win_rate"] - baseline["win_rate"], 1)
    reasons = []
    if d_win <= WIN_RATE_CRIT_PP:
        reasons.append(f"胜率偏离 {d_win}pp（阈值 {WIN_RATE_CRIT_PP}pp）")
    if baseline["avg_pnl"] > 0 and actual["avg_pnl"] < 0:
        reasons.append(
            f"均盈亏由正转负（回测 ${baseline['avg_pnl']} → 实际 ${actual['avg_pnl']}）")
    if reasons:
        return {"level": "critical", "reasons": reasons, "d_win": d_win}

    watch = []
    if d_win <= WIN_RATE_WATCH_PP:
        watch.append(f"胜率偏离 {d_win}pp")
    if baseline["avg_pnl"] > 0 and actual["avg_pnl"] < baseline["avg_pnl"] * 0.5:
        watch.append(f"均盈亏不及回测一半（${actual['avg_pnl']} vs ${baseline['avg_pnl']}）")
    if watch:
        return {"level": "watch", "reasons": watch, "d_win": d_win}
    return {"level": "ok", "reasons": [], "d_win": d_win}


def evaluate_from_db(conn) -> dict[str, dict]:
    """Evaluate every strategy: backtest baseline vs closed paper trades.

    Returns {strategy: {level, reasons, actual, baseline}}.
    """
    bt_rows = conn.execute(
        "SELECT strategy, pnl FROM trades WHERE source='backtest'").fetchall()
    paper_rows = conn.execute(
        "SELECT strategy, pnl FROM trades "
        "WHERE source='paper' AND exit_date IS NOT NULL").fetchall()

    bt: dict[str, list[float]] = {}
    for s, p in bt_rows:
        bt.setdefault(s, []).append(p)
    live: dict[str, list[float]] = {}
    for s, p in paper_rows:
        live.setdefault(s, []).append(p)

    out = {}
    for strat, pnls in bt.items():
        baseline = _stats(pnls)
        actual = _stats(live.get(strat, []))
        verdict = evaluate_one(actual, baseline)
        out[strat] = {**verdict, "actual": actual, "baseline": baseline}
    return out


def paused_strategies(alerts: dict[str, dict]) -> set[str]:
    """Strategies that must not open new positions."""
    return {s for s, a in alerts.items() if a["level"] == "critical"}
