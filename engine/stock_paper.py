"""Live paper verification of the top stock-lab pairs (stocks, not options).

Closes the loop: 选股 (stock lab backtest) -> 验证 (this live paper book)
-> 跟踪 (lab page panel). Takes the top N strategy×symbol pairs by backtest
total P&L and runs a live $100-notional paper book for each, mirroring
engine/stock_backtest.py rules exactly:

- signal +1 -> long, -1 -> short (fractional shares, $100 notional)
- exit on signal flip/off, stop -5%, TP +10%, or 10-trading-day time stop
- marks at the latest daily close; idempotent within a day

Runs after engine.daily_signals in the signals refresh chain.

Usage: python -m engine.stock_paper [--top 10]
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import storage, strategies
from .nasdaq import fetch_history
from .stock_backtest import (MAX_HOLD_DAYS, exits_for,
                             TRADE_BUDGET)

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "data" / "stock_paper_positions.json"
MIN_BACKTEST_TRADES = 10  # ignore tiny-sample pairs when picking the top N

# Live-performance veto: a pair whose OWN closed paper trades over the
# rolling window are consistently losing stops getting NEW entries.
# - entry-only: open positions are still managed to a natural exit
# - self-healing: once the bad record ages out of the window the pair
#   can be selected again (no permanent bans)
VETO_WINDOW_DAYS = 45
VETO_MIN_TRADES = 3
VETO_MAX_PNL = -15.0  # USD on $100-notional trades
EQUITY_FILES = (ROOT / "data" / "stock_paper_equity.json",
                ROOT / "web" / "public" / "data" / "stock_paper_equity.json")


def live_veto(conn) -> set[str]:
    """Pair keys ("SYM|strategy") vetoed by their recent live record."""
    cutoff = (date.today() - timedelta(days=VETO_WINDOW_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT symbol, strategy, pnl FROM stock_paper_trades"
        " WHERE exit_date >= ?", (cutoff,)).fetchall()
    agg: dict[str, list] = {}
    for sym, strat, pnl in rows:
        a = agg.setdefault(f"{sym}|{strat}", [0, 0.0])
        a[0] += 1
        a[1] += pnl or 0.0
    veto = {k for k, (n, total) in agg.items()
            if n >= VETO_MIN_TRADES and total <= VETO_MAX_PNL}
    if veto:
        print(f"[stock-paper] live veto (new entries blocked): {sorted(veto)}",
              flush=True)
    return veto


def write_equity_snapshot(realized: float, unrealized: float,
                          n_positions: int, day: str):
    """One equity point per day (idempotent re-runs) for the long-term
    profitability curve — the primary 'are we steadily making money' metric."""
    hist = []
    if EQUITY_FILES[0].exists():
        hist = json.loads(EQUITY_FILES[0].read_text())
    hist = [h for h in hist if h.get("date") != day]
    hist.append({"date": day, "realized": round(realized, 2),
                 "unrealized": round(unrealized, 2),
                 "total": round(realized + unrealized, 2),
                 "positions": n_positions})
    hist.sort(key=lambda h: h["date"])
    text = json.dumps(hist, ensure_ascii=False)
    for path in EQUITY_FILES:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"positions": []}


def top_pairs(conn, top_n: int, exclude: set[str] | None = None) -> list[dict]:
    """Top N pairs from the latest stock-lab run, by backtest total P&L.

    Strategies on the production watchlist (probation) are excluded — they
    keep appearing in the full lab ranking but can't enter the live book.
    `exclude` holds live-vetoed pair keys ("SYM|strategy")."""
    from . import production  # local import: avoid cycles at module load
    wl = set(production.watchlist())
    rows = conn.execute(
        """
        SELECT r.symbol, r.strategy, r.metrics FROM stock_runs r
        JOIN (SELECT MAX(run_at) m FROM stock_runs) t ON r.run_at = t.m
        """
    ).fetchall()
    pairs = []
    for sym, strat, metrics_json in rows:
        if strat in wl or (exclude and f"{sym}|{strat}" in exclude):
            continue
        m = json.loads(metrics_json)
        if m.get("trades", 0) >= MIN_BACKTEST_TRADES:
            pairs.append({"symbol": sym, "strategy": strat, **m})
    pairs.sort(key=lambda p: p.get("total_pnl", 0), reverse=True)
    return pairs[:top_n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--no-sync", action="store_true",
                    help="skip Supabase sync (a later step in the chain syncs)")
    args = ap.parse_args()

    storage.init_db()
    now = datetime.now(timezone.utc).isoformat()
    state = load_state()
    closed: list[dict] = []

    with storage.get_conn() as conn:
        vetoed = live_veto(conn)
        pairs = top_pairs(conn, args.top, exclude=vetoed)
        print(f"[stock-paper] verifying top {len(pairs)} pairs: "
              + ", ".join(f"{p['symbol']}×{p['strategy']}" for p in pairs),
              flush=True)
        # entry-only veto: keep vetoed pairs' OPEN positions in the loop so
        # they exit by the normal rules instead of being force-closed as
        # stragglers; manage_only blocks any new entry below.
        selected = {f"{p['symbol']}|{p['strategy']}" for p in pairs}
        for open_pos in state["positions"]:
            if open_pos["key"] in vetoed and open_pos["key"] not in selected:
                sym, strat = open_pos["key"].split("|")
                pairs.append({"symbol": sym, "strategy": strat,
                              "manage_only": True})

        # cache per symbol so pairs sharing a symbol fetch once
        frames = {}
        for pair in pairs:
            sym, strat = pair["symbol"], pair["strategy"]
            key = f"{sym}|{strat}"
            if sym not in frames:
                frames[sym] = strategies.prepare(fetch_history(sym, years=1))
            df = frames[sym]
            sig = int(strategies.STOCK_STRATEGIES[strat](df).iloc[-1])
            last = df.iloc[-1]
            date_str = last["date"].strftime("%Y-%m-%d")
            close = float(last["close"])

            pos = next((p for p in state["positions"] if p["key"] == key), None)

            if pos:
                # age once per new trading day only (idempotent re-runs)
                if pos.get("last_mark_date") != date_str:
                    pos["days_held"] += 1
                direction = 1 if pos["side"] == "long" else -1
                ret = (close / pos["entry_price"] - 1) * direction
                pos["last_mark"] = round(close, 4)
                pos["unrealized_pnl"] = round(ret * TRADE_BUDGET, 2)
                pos["unrealized_pct"] = round(ret * 100, 2)
                pos["marked_at"] = now
                pos["last_mark_date"] = date_str

                reason = None
                tp, sl = exits_for(strat)
                if sig != 0 and ((sig > 0) != (pos["side"] == "long")):
                    reason = "signal_flip"
                elif sig == 0:
                    reason = "signal_off"
                elif ret <= sl:
                    reason = "stop_loss"
                elif ret >= tp:
                    reason = "take_profit"
                elif pos["days_held"] >= MAX_HOLD_DAYS:
                    reason = "time_stop"
                if reason:
                    closed.append({
                        "symbol": sym, "strategy": strat, "side": pos["side"],
                        "entry_date": pos["entry_date"],
                        "entry_price": pos["entry_price"],
                        "shares": pos["shares"],
                        "exit_date": date_str, "exit_price": round(close, 4),
                        "exit_reason": reason,
                        "pnl": round(ret * TRADE_BUDGET, 2),
                        "pnl_pct": round(ret * 100, 2),
                        "hold_days": pos["days_held"],
                    })
                    state["positions"].remove(pos)
                    pos = None
                    print(f"  [close] {key} {reason} pnl={closed[-1]['pnl']}",
                          flush=True)

            if pos is None and sig != 0 and not pair.get("manage_only"):
                side = "long" if sig > 0 else "short"
                state["positions"].append({
                    "key": key, "symbol": sym, "strategy": strat, "side": side,
                    "entry_date": date_str, "entry_price": round(close, 4),
                    "shares": round(TRADE_BUDGET / close, 6),
                    "days_held": 0, "last_mark_date": date_str,
                    "last_mark": round(close, 4), "unrealized_pnl": 0.0,
                    "unrealized_pct": 0.0, "marked_at": now,
                    "backtest_pnl": pair.get("total_pnl"),
                })
                print(f"  [open] {key} {side} @ {close:.2f}", flush=True)

        # drop positions whose pair fell out of the top N? No — let them
        # close naturally by the rules above; the key lookup above simply
        # won't update them anymore, so force-close stragglers at mark:
        active_keys = {f"{p['symbol']}|{p['strategy']}" for p in pairs}
        stragglers = [p for p in state["positions"]
                      if p["key"] not in active_keys]
        for p in stragglers:
            sym = p["symbol"]
            if sym not in frames:
                try:
                    frames[sym] = strategies.prepare(fetch_history(sym, years=1))
                except Exception as e:  # noqa: BLE001
                    print(f"  [warn] cannot mark straggler {p['key']}: {e}",
                          flush=True)
                    continue
            close = float(frames[sym].iloc[-1]["close"])
            date_str = frames[sym].iloc[-1]["date"].strftime("%Y-%m-%d")
            direction = 1 if p["side"] == "long" else -1
            ret = close / p["entry_price"] - 1
            pnl = round(ret * direction * TRADE_BUDGET, 2)
            closed.append({
                "symbol": sym, "strategy": p["strategy"], "side": p["side"],
                "entry_date": p["entry_date"], "entry_price": p["entry_price"],
                "shares": p["shares"], "exit_date": date_str,
                "exit_price": round(close, 4), "exit_reason": "dropped_from_top",
                "pnl": pnl, "pnl_pct": round(ret * direction * 100, 2),
                "hold_days": p["days_held"],
            })
            state["positions"].remove(p)
            print(f"  [close] {p['key']} dropped_from_top pnl={pnl}", flush=True)

        if closed:
            storage.save_stock_paper_trades(conn, closed)
        storage.save_stock_paper_positions(conn, state["positions"])

        # long-term equity history (realized from the full trades table,
        # unrealized from current marks) — one point per day
        realized = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM stock_paper_trades"
        ).fetchone()[0]
        unrealized = sum(p.get("unrealized_pnl") or 0.0
                         for p in state["positions"])
        write_equity_snapshot(realized, unrealized,
                              len(state["positions"]), now[:10])

    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"\n[stock-paper] open: {len(state['positions'])} | "
          f"closed today: {len(closed)}")

    if not args.no_sync and storage.supabase_enabled():
        print(storage.sync_to_supabase())


if __name__ == "__main__":
    main()
