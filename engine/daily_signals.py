"""Daily job: refresh prices, compute the latest signal per symbol/strategy,
and (paper mode) open/close weekly option paper trades.

Paper trading uses REAL option-chain quotes from the Nasdaq API:
entry at the contract's ask, exit marked at the bid. Black-Scholes is
only a fallback when the chain is unavailable (and for the backtest,
where historical chains do not exist for free).

Usage: python -m engine.daily_signals [--symbols AAPL,MSFT]
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from . import alerts as alerts_mod
from . import storage, strategies
from .backtest import (DTE_AT_ENTRY, MAX_HOLD_DAYS, STOP_LOSS, TAKE_PROFIT,
                       TRADE_BUDGET, Trade, trades_to_dicts)
from .nasdaq import fetch_history, fetch_option_chain
from .options_sim import bs_price, pick_weekly_contract

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "AMZN", "META", "GOOGL", "AVGO", "NFLX",
    "ORCL", "CRM", "ADBE", "INTC", "MU", "CSCO", "QCOM", "TXN", "ARM", "DELL",
    "PLTR", "SMCI", "COIN", "MSTR", "HOOD", "SOFI", "SNAP", "UBER", "SHOP", "PYPL",
    "F", "GM", "BA", "DIS", "NKE", "SBUX", "MCD", "WMT", "JPM", "BAC",
    "XOM", "CVX", "PFE", "BABA", "NIO", "RIVN", "LCID",
    "SPY", "QQQ", "IWM",
]
STATE_FILE = ROOT / "data" / "paper_positions.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"positions": []}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------------- real option-chain helpers ----------------

def _chain_prices(row, prefix: str):
    """Usable entry/exit prices for a chain row.
    Priority: mid(bid,ask) -> ask/bid -> last trade. Returns (entry, exit)."""
    bid, ask, last = row[f"{prefix}_bid"], row[f"{prefix}_ask"], row[f"{prefix}_last"]
    mid = None
    if pd.notna(bid) and pd.notna(ask) and bid > 0 and ask > 0:
        mid = (bid + ask) / 2
    entry = mid or (ask if pd.notna(ask) and ask > 0 else None) \
        or (last if pd.notna(last) and last > 0 else None)
    exit_ = mid or (bid if pd.notna(bid) and bid > 0 else None) \
        or (last if pd.notna(last) and last > 0 else None)
    return entry, exit_


def pick_from_chain(chain: pd.DataFrame, spot: float, kind: str,
                    target_dte: int = DTE_AT_ENTRY):
    """Pick the real contract: expiry closest to target_dte (>= 3 days),
    strike nearest spot, with any usable quote. Returns dict or None."""
    if chain is None or chain.empty:
        return None
    today = pd.Timestamp(date.today())
    c = chain.copy()
    c["dte"] = (c["expiry"] - today).dt.days
    c = c[c["dte"] >= 3]
    if c.empty:
        return None
    best_dte = min(c["dte"].unique(), key=lambda d: abs(d - target_dte))
    c = c[c["dte"] == best_dte]
    prefix = "c" if kind == "call" else "p"
    priced = []
    for _, row in c.iterrows():
        entry, exit_ = _chain_prices(row, prefix)
        if entry and entry > 0.01:
            priced.append((row, entry, exit_))
    if not priced:
        return None
    priced.sort(key=lambda t: abs(t[0]["strike"] - spot))
    row, entry, exit_ = priced[0]
    return {
        "strike": float(row["strike"]),
        "expiry": row["expiry"].strftime("%Y-%m-%d"),
        "dte": int(best_dte),
        "ask": float(entry),
        "bid": float(exit_) if exit_ else None,
    }


def mark_from_chain(chain: pd.DataFrame, kind: str, strike: float,
                    expiry: str) -> float | None:
    """Current exit-side price for an open contract; None if not found."""
    if chain is None or chain.empty:
        return None
    rows = chain[(chain["strike"] == strike)
                 & (chain["expiry"] == pd.Timestamp(expiry))]
    if rows.empty:
        return None
    prefix = "c" if kind == "call" else "p"
    _, exit_ = _chain_prices(rows.iloc[0], prefix)
    return float(exit_) if exit_ else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--no-sync", action="store_true",
                    help="skip Supabase sync (a later step in the chain syncs)")
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    storage.init_db()
    now = datetime.now(timezone.utc).isoformat()
    state = load_state()
    closed_trades: list[Trade] = []
    new_signals = []

    with storage.get_conn() as conn:
        # deviation alerts: logged for the dashboard and printed here, but
        # trading continues for every strategy — alerts are advisory only
        strat_alerts = alerts_mod.evaluate_from_db(conn)
        storage.save_strategy_alerts(conn, now, strat_alerts)
        crits = [s for s, a in strat_alerts.items() if a["level"] == "critical"]
        for s in sorted(crits):
            print(f"[alert] {s} CRITICAL (advisory only, trading continues): "
                  f"{'; '.join(strat_alerts[s]['reasons'])}", flush=True)

        for sym in symbols:
            print(f"[daily] {sym}", flush=True)
            df = strategies.prepare(fetch_history(sym, years=1))
            storage.upsert_prices(conn, sym, df)
            last = df.iloc[-1]
            date_str = last["date"].strftime("%Y-%m-%d")
            spot = float(last["close"])

            # lazily fetched real option chain for this symbol
            chain: pd.DataFrame | None = None
            chain_tried = False

            def get_chain():
                nonlocal chain, chain_tried
                if not chain_tried:
                    chain_tried = True
                    try:
                        chain = fetch_option_chain(sym, max_dte=16)
                    except Exception as e:  # noqa: BLE001
                        print(f"  [warn] option chain unavailable for {sym}: {e}")
                        chain = None
                return chain

            for name, fn in strategies.ALL_STRATEGIES.items():
                sig = int(fn(df).iloc[-1])
                storage.save_signal(conn, now, sym, name, sig, spot,
                                    {"rsi": round(float(last["rsi"]), 1),
                                     "hv20": round(float(last["hv20"]), 4)})
                new_signals.append({"symbol": sym, "strategy": name,
                                    "signal": sig, "close": spot})

                # --- paper position management ---
                # Every strategy runs its own independent $100 book:
                # positions are keyed by (symbol, strategy), so multiple
                # strategies can hold the same symbol simultaneously.
                open_pos = next((p for p in state["positions"]
                                 if p["symbol"] == sym
                                 and p.get("strategy", "ensemble") == name), None)

                if open_pos:
                    # age the position once per new trading day only —
                    # re-running the job on the same data must not
                    # double-count days held or burn DTE
                    if open_pos.get("last_mark_date") != date_str:
                        open_pos["dte_left"] -= 1
                        open_pos["days_held"] += 1
                    # mark with real bid first, BS fallback
                    real_bid = mark_from_chain(get_chain(), open_pos["kind"],
                                               open_pos["strike"],
                                               open_pos.get("expiry", ""))
                    if real_bid is not None:
                        price = real_bid
                        mark_src = "chain"
                    else:
                        price = bs_price(spot, open_pos["strike"],
                                         max(open_pos["dte_left"], 0) / 365.0,
                                         float(last["hv20"]), open_pos["kind"])
                        mark_src = "bs"
                    ret = price / open_pos["entry_price"] - 1
                    # persist the mark so the dashboard can show live P&L
                    open_pos["last_mark"] = round(price, 4)
                    open_pos["last_mark_source"] = mark_src
                    open_pos["unrealized_pnl"] = round(
                        (price - open_pos["entry_price"]) * 100 * open_pos["qty"], 2)
                    open_pos["unrealized_pct"] = round(ret * 100, 2)
                    open_pos["marked_at"] = now
                    open_pos["last_mark_date"] = date_str
                    reason = None
                    if sig != 0 and ((sig > 0) != (open_pos["kind"] == "call")):
                        reason = "signal_flip"
                    elif sig == 0:
                        reason = "signal_off"
                    elif ret <= STOP_LOSS:
                        reason = "stop_loss"
                    elif ret >= TAKE_PROFIT:
                        reason = "take_profit"
                    elif open_pos["days_held"] >= MAX_HOLD_DAYS or open_pos["dte_left"] <= 0:
                        reason = "time_stop"
                    if reason:
                        t = Trade(symbol=sym, strategy=open_pos.get("strategy", name),
                                  kind=open_pos["kind"], strike=open_pos["strike"],
                                  entry_date=open_pos["entry_date"],
                                  entry_underlying=open_pos["entry_underlying"],
                                  entry_price=open_pos["entry_price"],
                                  qty=open_pos["qty"], iv_entry=open_pos["iv_entry"],
                                  exit_date=date_str,
                                  exit_underlying=round(spot, 2),
                                  exit_price=round(price, 4),
                                  exit_reason=f"{reason}({mark_src})",
                                  pnl=round((price - open_pos["entry_price"]) * 100 * open_pos["qty"], 2),
                                  pnl_pct=round(ret * 100, 2),
                                  hold_days=open_pos["days_held"])
                        closed_trades.append(t)
                        state["positions"].remove(open_pos)
                        open_pos = None
                        if reason != "signal_flip":
                            continue

                if open_pos is None and sig != 0:
                    kind = "call" if sig > 0 else "put"
                    contract = pick_from_chain(get_chain(), spot, kind)
                    if contract:  # real chain entry at ask
                        entry = contract["ask"]
                        strike, dte = contract["strike"], contract["dte"]
                        expiry, src = contract["expiry"], "chain"
                    else:  # BS fallback
                        strike, dte = pick_weekly_contract(spot, DTE_AT_ENTRY)
                        entry = bs_price(spot, strike, dte / 365.0,
                                         float(last["hv20"]), kind)
                        expiry, src = "", "bs"
                    if entry > 0.01:
                        state["positions"].append({
                            "symbol": sym, "strategy": name, "kind": kind,
                            "strike": strike,
                            "expiry": expiry, "price_source": src,
                            "entry_date": date_str,
                            "entry_underlying": round(spot, 2),
                            "entry_price": round(entry, 4),
                            "qty": round(TRADE_BUDGET / (entry * 100), 4),
                            "iv_entry": round(float(last["hv20"]), 4),
                            "dte_left": dte, "days_held": 0,
                            "last_mark_date": date_str,
                        })
                        print(f"  [paper open] {sym} {name} {kind} {strike} "
                              f"exp={expiry or 'sim'} @ {entry:.2f} ({src})",
                              flush=True)

        if closed_trades:
            storage.save_trades(conn, None, trades_to_dicts(closed_trades),
                                source="paper")
        storage.save_paper_positions(conn, state["positions"])

        # --- daily equity snapshot ---
        realized = conn.execute(
            "SELECT COALESCE(SUM(pnl),0) FROM trades WHERE source='paper'"
        ).fetchone()[0]
        unrealized = sum(
            (p.get("last_mark", p["entry_price"]) - p["entry_price"]) * 100 * p["qty"]
            for p in state["positions"]
        )
        storage.save_equity_snapshot(
            conn, date.today().isoformat(), realized, unrealized,
            len(state["positions"]), now)

    save_state(state)
    actionable = [s for s in new_signals if s["signal"] != 0]
    by_strat = {}
    for s in actionable:
        by_strat[s["strategy"]] = by_strat.get(s["strategy"], 0) + 1

    # freshness marker for the web lazy-refresh API
    (ROOT / "data" / "signals_summary.json").write_text(json.dumps({
        "run_at": now,
        "signals": len(new_signals),
        "paper_open": len(state["positions"]),
        "paper_closed": len(closed_trades),
    }, indent=2))

    print(f"\nSignals saved: {len(new_signals)} | paper closed: {len(closed_trades)} "
          f"| paper open: {len(state['positions'])}"
          + (f" | alerts critical: {', '.join(sorted(crits))}" if crits else ""))
    print("actionable signals by strategy: "
          + (", ".join(f"{k}={v}" for k, v in sorted(by_strat.items())) or "none"))

    if not args.no_sync and storage.supabase_enabled():
        print(storage.sync_to_supabase())


if __name__ == "__main__":
    main()
