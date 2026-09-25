"""Live paper verification of the recommended 1h Top10 portfolio.

The 1h timeframe won the capital simulation (+18.7% over ~3 months, 9/10
winning legs); this module tracks whether that holds live. Mirrors
engine/stock_paper.py but on hourly bars:

- pair selection: top N by full-window 1h PnL (cached bars, production
  params/exits), watchlist strategies excluded, min-trades filter
- $100 notional per pair, fractional shares, long/short
- exits: signal flip/off, strategy tp/sl, time stop in 1h bars (~10 days)
- evaluated once per day after close (signals on the latest 1h bars);
  idempotent within a day
- persists to SQLite (stock_paper_intra_* tables) and exports
  web/public/data/stock_paper_1h.json for the frontend

Usage: python -m engine.intraday_paper [--timeframe 1h] [--top 10]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import production, storage, strategies
from .intraday import TIMEFRAMES, fetch_intraday
from .stock_backtest import TRADE_BUDGET, exits_for

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "data" / "stock_paper_1h_positions.json"
MIN_VAL_TRADES = 8
VAL_WINDOW_DAYS = 90  # recent regime window for pair ranking


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"positions": [], "pairs": [], "selected_on": None, "eval_ts": {}}


def ensure_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_paper_intra_positions (
            key TEXT PRIMARY KEY,
            timeframe TEXT NOT NULL,
            data TEXT NOT NULL
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_paper_intra_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timeframe TEXT NOT NULL,
            symbol TEXT NOT NULL,
            strategy TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_date TEXT, entry_price REAL, shares REAL,
            exit_date TEXT, exit_price REAL, exit_reason TEXT,
            pnl REAL, pnl_pct REAL, hold_bars INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")


def top_pairs(frames: dict, sigs: dict, tf: str, top_n: int) -> list[dict]:
    """Dual-window selection (regime-aware):
    - train window: everything older than VAL_WINDOW_DAYS — must be
      profitable (long-term viability filter)
    - validation window: the last VAL_WINDOW_DAYS — ranking metric
      (recent regime strength)
    Full-window PnL ranking kept stale pairs whose edge had decayed;
    this drops them within a week.
    """
    from datetime import date, timedelta
    from .stock_backtest import compute_metrics, run_stock_backtest
    wl = set(production.watchlist())
    hold = TIMEFRAMES[tf]["hold_bars"]
    train_end = (date.today() - timedelta(days=VAL_WINDOW_DAYS)).isoformat()
    rows = []
    for sym, df in frames.items():
        dates = df["date"].astype(str)
        tr_mask = dates <= train_end
        va_mask = dates > train_end
        dtr = df[tr_mask].reset_index(drop=True)
        dva = df[va_mask].reset_index(drop=True)
        if len(dtr) < 50 or len(dva) < 20:
            continue
        for name in strategies.STOCK_STRATEGIES:
            if name in wl:
                continue
            sig = sigs[(sym, name)]
            tr = run_stock_backtest(dtr, sig[tr_mask].reset_index(drop=True),
                                    sym, name, max_hold_days=hold)
            mt = compute_metrics(tr)
            if mt.get("total_pnl", 0) <= 0:
                continue  # no long-term edge — skip
            va = run_stock_backtest(dva, sig[va_mask].reset_index(drop=True),
                                    sym, name, max_hold_days=hold)
            mv = compute_metrics(va)
            if mv.get("trades", 0) >= MIN_VAL_TRADES:
                rows.append({"symbol": sym, "strategy": name, **mv,
                             "train_pnl": mt.get("total_pnl", 0)})
    rows.sort(key=lambda r: r.get("total_pnl", 0), reverse=True)
    return rows[:top_n]


def export_web(payload: dict):
    out = ROOT / "web" / "public" / "data" / "stock_paper_1h.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1h", choices=list(TIMEFRAMES))
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--mark-only", action="store_true",
                    help="hourly mode: skip full-universe re-selection, only "
                         "refresh the tracked pairs' symbols with fresh bars")
    args = ap.parse_args()
    tf = args.timeframe
    hold = TIMEFRAMES[tf]["hold_bars"]

    storage.init_db()
    now = datetime.now(timezone.utc).isoformat()
    state = load_state()

    wl = set(production.watchlist())
    from .run_backtest import DEFAULT_SYMBOLS as INTRA_SYMBOLS

    # selection cadence: full-universe Top10 re-selection at most weekly —
    # daily runs only refresh the tracked pairs' symbols (Polygon free tier
    # is slow; 50 symbols ≈ over an hour, 12 symbols ≈ 15 min)
    from datetime import date as _date
    sel_on = state.get("selected_on")
    sel_age = (_date.today() - _date.fromisoformat(sel_on)).days if sel_on else 999
    if args.mark_only or (state.get("pairs") and sel_age < 7):
        pairs = state["pairs"]
        did_full = False
        symbols = sorted({p["symbol"] for p in pairs}
                         | {p["symbol"] for p in state["positions"]})
        fresh = args.mark_only  # hourly mode bypasses the same-day cache
        print(f"[{tf}-paper] tracked-only: {len(symbols)} symbols "
              f"(selection age {sel_age}d, fresh={fresh})", flush=True)
    else:
        symbols = sorted(set(INTRA_SYMBOLS)
                         | {p["symbol"] for p in state["positions"]})
        did_full = True
        fresh = False
        print(f"[{tf}-paper] full selection over {len(symbols)} symbols ...",
              flush=True)

    frames, sigs = {}, {}
    for sym in symbols:
        try:
            df = strategies.prepare(fetch_intraday(sym, tf, use_cache=not fresh))
        except Exception as e:  # noqa: BLE001 - skip symbols w/o data
            print(f"  [warn] {sym}: {e}", flush=True)
            continue
        if fresh:
            import time
            time.sleep(0.6)  # be gentle with the free-tier rate limit
        frames[sym] = df
        for name in strategies.STOCK_STRATEGIES:
            if name not in wl:
                sigs[(sym, name)] = strategies.STOCK_STRATEGIES[name](df)

    if did_full:
        old_pairs = state.get("pairs") or []
        pairs = top_pairs(frames, sigs, tf, args.top)
        state["pairs"] = [{"symbol": p["symbol"], "strategy": p["strategy"],
                           "backtest_pnl": p.get("total_pnl")} for p in pairs]
        state["selected_on"] = now[:10]
        gen_changed = bool(old_pairs) and {
            (p["symbol"], p["strategy"]) for p in pairs
        } != {(p["symbol"], p["strategy"]) for p in old_pairs}
        print(f"[{tf}-paper] verifying top {len(pairs)}: "
              + ", ".join(f"{p['symbol']}×{p['strategy']}" for p in pairs),
              flush=True)
    else:
        old_pairs = state.get("pairs") or []
        gen_changed = False

    closed: list[dict] = []
    top_keys = {f"{p['symbol']}|{p['strategy']}" for p in pairs}
    active_keys = set(top_keys)
    # positions whose pair dropped out keep getting marked/closed by the rules
    for pos in state["positions"]:
        active_keys.add(pos["key"])
    eval_ts = state.setdefault("eval_ts", {})

    # Free-tier intraday data lands with ~1 day lag, but each daily run gets
    # the FULL previous session at once — so instead of evaluating only the
    # latest bar, replay every unseen bar in order and apply the rules
    # bar-by-bar. Decisions are then identical to true hourly evaluation,
    # just booked a day late. Idempotent: already-seen bars are skipped.
    for key in sorted(active_keys):
        sym, strat = key.split("|")
        df = frames.get(sym)
        if df is None or (sym, strat) not in sigs:
            continue
        ts = df["date"].astype(str).reset_index(drop=True)
        sig_vals = sigs[(sym, strat)].reset_index(drop=True).to_numpy()
        closes = df["close"].to_numpy()
        n = len(df)
        last_i = n - 1
        tp, sl = exits_for(strat)
        pos = next((p for p in state["positions"] if p["key"] == key), None)

        if pos:
            anchor_ts = pos.get("last_mark_ts") or pos["entry_ts"]
            m = ts[ts == anchor_ts].index
            anchor_i = int(m[0]) if len(m) else 0
        else:
            anchor_ts = eval_ts.get(key)
            m = ts[ts == anchor_ts].index if anchor_ts else []
            if len(m):
                anchor_i = int(m[0])
            else:
                # no history: replay only the latest session (~7 bars) so a
                # pair can still catch a signal that fired mid-session, but
                # never opens on weeks-old bars
                anchor_i = max(0, last_i - 8)

        entry_i = None
        if pos:
            m2 = ts[ts == pos["entry_ts"]].index
            entry_i = int(m2[0]) if len(m2) else 0

        for i in range(anchor_i + 1, n):
            bar_ts = ts.iloc[i]
            close = float(closes[i])
            s = int(sig_vals[i])
            if pos:
                direction = 1 if pos["side"] == "long" else -1
                ret = (close / pos["entry_price"] - 1) * direction
                pos["bars_held"] = i - entry_i
                pos["last_mark"] = round(close, 4)
                pos["unrealized_pnl"] = round(ret * TRADE_BUDGET, 2)
                pos["unrealized_pct"] = round(ret * 100, 2)
                pos["marked_at"] = now
                pos["last_mark_ts"] = bar_ts

                reason = None
                if s != 0 and ((s > 0) != (pos["side"] == "long")):
                    reason = "signal_flip"
                elif s == 0:
                    reason = "signal_off"
                elif ret <= sl:
                    reason = "stop_loss"
                elif ret >= tp:
                    reason = "take_profit"
                elif pos["bars_held"] >= hold:
                    reason = "time_stop"
                elif i == last_i and key not in top_keys:
                    reason = "dropped_from_top"
                if reason:
                    closed.append({
                        "symbol": sym, "strategy": strat, "side": pos["side"],
                        "entry_date": pos["entry_ts"],
                        "entry_price": pos["entry_price"],
                        "shares": pos["shares"], "exit_date": bar_ts,
                        "exit_price": round(close, 4), "exit_reason": reason,
                        "pnl": round(ret * TRADE_BUDGET, 2),
                        "pnl_pct": round(ret * 100, 2),
                        "hold_bars": pos["bars_held"],
                    })
                    state["positions"].remove(pos)
                    pos = None
                    entry_i = None
                    print(f"  [close] {key} {reason} @ {bar_ts} "
                          f"pnl={closed[-1]['pnl']}", flush=True)
            elif key in top_keys and s != 0:
                side = "long" if s > 0 else "short"
                pos = {
                    "key": key, "symbol": sym, "strategy": strat, "side": side,
                    "entry_ts": bar_ts, "entry_price": round(close, 4),
                    "shares": round(TRADE_BUDGET / close, 6),
                    "bars_held": 0, "last_mark_ts": bar_ts,
                    "last_mark": round(close, 4), "unrealized_pnl": 0.0,
                    "unrealized_pct": 0.0, "marked_at": now,
                }
                state["positions"].append(pos)
                entry_i = i
                print(f"  [open] {key} {side} @ {close:.2f} @ {bar_ts}",
                      flush=True)

        eval_ts[key] = ts.iloc[last_i]

    with storage.get_conn() as conn:
        ensure_tables(conn)
        for t in closed:
            conn.execute(
                """INSERT INTO stock_paper_intra_trades
                   (timeframe, symbol, strategy, side, entry_date, entry_price,
                    shares, exit_date, exit_price, exit_reason, pnl, pnl_pct,
                    hold_bars)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tf, t["symbol"], t["strategy"], t["side"], t["entry_date"],
                 t["entry_price"], t["shares"], t["exit_date"], t["exit_price"],
                 t["exit_reason"], t["pnl"], t["pnl_pct"], t["hold_bars"]))
        conn.execute("DELETE FROM stock_paper_intra_positions WHERE timeframe=?",
                     (tf,))
        for p in state["positions"]:
            conn.execute(
                "INSERT INTO stock_paper_intra_positions (key, timeframe, data)"
                " VALUES (?,?,?)",
                (p["key"], tf, json.dumps(p, ensure_ascii=False)))

        # ---- portfolio generations: close the outgoing generation when a
        # full re-selection changed the Top10 lineup ----
        if gen_changed:
            today = now[:10]
            gens = state.setdefault("generations", [])
            start = state.get("gen_start")
            if not start:
                # bootstrap: earliest book activity
                row = conn.execute(
                    "SELECT MIN(entry_date) FROM stock_paper_intra_trades"
                    " WHERE timeframe=?", (tf,)).fetchone()
                start = (row[0] or today)[:10]
                if state["positions"]:
                    start = min(start, min(p["entry_ts"]
                                           for p in state["positions"])[:10])
            r = conn.execute(
                """SELECT COALESCE(SUM(pnl),0), COUNT(*)
                   FROM stock_paper_intra_trades
                   WHERE timeframe=? AND exit_date >= ? AND exit_date < ?""",
                (tf, start, today)).fetchone()
            gens.append({"id": len(gens) + 1, "start": start, "end": today,
                         "pairs": old_pairs,
                         "realized_pnl": round(r[0], 2), "trades": r[1]})
            state["gen_start"] = today
            print(f"[gen] 第 {len(gens)} 代结束: {start} ~ {today} "
                  f"已实现 {r[0]:.2f} ({r[1]} 笔)", flush=True)

    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    with storage.get_conn() as conn:
        rows = conn.execute(
            """SELECT symbol, strategy, side, entry_date, entry_price, shares,
                      exit_date, exit_price, exit_reason, pnl, pnl_pct,
                      hold_bars
               FROM stock_paper_intra_trades WHERE timeframe=?
               ORDER BY exit_date""", (tf,)).fetchall()
        cols = ["symbol", "strategy", "side", "entry_date", "entry_price",
                "shares", "exit_date", "exit_price", "exit_reason", "pnl",
                "pnl_pct", "hold_bars"]
        all_closed = [dict(zip(cols, r)) for r in rows]
        # current (open) generation with live realized stats
        cur_start = state.get("gen_start")
        if not cur_start:
            row = conn.execute(
                "SELECT MIN(entry_date) FROM stock_paper_intra_trades"
                " WHERE timeframe=?", (tf,)).fetchone()
            cur_start = (row[0] or now)[:10]
            if state["positions"]:
                cur_start = min(cur_start, min(p["entry_ts"]
                                               for p in state["positions"])[:10])
        r = conn.execute(
            """SELECT COALESCE(SUM(pnl),0), COUNT(*)
               FROM stock_paper_intra_trades
               WHERE timeframe=? AND exit_date >= ?""",
            (tf, cur_start)).fetchone()
        generations = list(state.get("generations", [])) + [{
            "id": len(state.get("generations", [])) + 1,
            "start": cur_start, "end": None,
            "pairs": [{"symbol": p["symbol"], "strategy": p["strategy"],
                       "backtest_pnl": p.get("total_pnl",
                                             p.get("backtest_pnl"))}
                      for p in pairs],
            "realized_pnl": round(r[0], 2), "trades": r[1],
            "current": True,
        }]
    export_web({
        "timeframe": tf, "updated_at": now,
        "positions": state["positions"], "closed_trades": all_closed,
        "pairs": [{"symbol": p["symbol"], "strategy": p["strategy"],
                   "backtest_pnl": p.get("total_pnl", p.get("backtest_pnl"))}
                  for p in pairs],
        "generations": generations,
    })
    print(f"\n[{tf}-paper] open: {len(state['positions'])} | "
          f"closed today: {len(closed)}")


if __name__ == "__main__":
    main()
