"""Broker-style accounting for the real-cost candidate paper account."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

from .futu_costs import order_fees

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "web" / "public" / "data" / "real_book.json"

INITIAL_CASH = 3000.0
NOTIONAL = 1000.0
SLIPPAGE_BPS = 5.0
BORROW_ANNUAL = 0.05


def _elapsed_days(start: str, end: str) -> float:
    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    try:
        return max((parse(end) - parse(start)).total_seconds() / 86400, 0.0)
    except ValueError:
        return max((datetime.strptime(end[:10], "%Y-%m-%d")
                    - datetime.strptime(start[:10], "%Y-%m-%d")).days, 0)


def _execution(raw_price: float, shares: float, order_side: str,
               slippage_bps: float = SLIPPAGE_BPS) -> tuple[float, float, float]:
    direction = 1 if order_side == "buy" else -1
    fill = raw_price * (1 + direction * slippage_bps / 10000)
    return fill, order_fees(shares, fill, order_side), abs(fill - raw_price) * shares


def _borrow(pos: dict, end: str, borrow_annual: float = BORROW_ANNUAL) -> float:
    if pos["side"] != "short":
        return 0.0
    days = _elapsed_days(pos["entry_date"], end)
    return pos["entry_price"] * pos["shares"] * borrow_annual * days / 365


def open_position(cash: float, symbol: str, strategy: str, side: str,
                  price: float, timestamp: str, notional: float = NOTIONAL,
                  slippage_bps: float = SLIPPAGE_BPS):
    """Open at a slipped close-price fill. Long allows fractions; short does not."""
    shares = notional / price
    if side == "short":
        shares = math.floor(shares)
        if shares < 1:
            return cash, None
    order_side = "buy" if side == "long" else "sell"
    fill, fees, slippage = _execution(price, shares, order_side, slippage_bps)
    cash_flow = -fill * shares - fees if side == "long" else fill * shares - fees
    pos = {
        "key": f"{symbol}|{strategy}", "symbol": symbol, "strategy": strategy,
        "side": side, "entry_date": timestamp, "entry_price": price,
        "entry_fill": fill, "shares": shares, "entry_fees": fees,
        "entry_slippage": slippage, "last_mark": price,
        "last_mark_ts": timestamp, "bars_held": 0,
    }
    return cash + cash_flow, pos


def close_position(cash: float, pos: dict, price: float, timestamp: str,
                   reason: str, slippage_bps: float = SLIPPAGE_BPS,
                   borrow_annual: float = BORROW_ANNUAL):
    order_side = "sell" if pos["side"] == "long" else "buy"
    fill, exit_fees, exit_slippage = _execution(
        price, pos["shares"], order_side, slippage_bps)
    borrow = _borrow(pos, timestamp, borrow_annual)
    cash_flow = (fill * pos["shares"] - exit_fees - borrow
                 if pos["side"] == "long"
                 else -fill * pos["shares"] - exit_fees - borrow)
    direction = 1 if pos["side"] == "long" else -1
    gross = (price - pos["entry_price"]) * pos["shares"] * direction
    fees = pos["entry_fees"] + exit_fees
    slippage = pos["entry_slippage"] + exit_slippage
    net = gross - fees - slippage - borrow
    trade = {
        "symbol": pos["symbol"], "strategy": pos["strategy"], "side": pos["side"],
        "entry_date": pos["entry_date"], "entry_price": pos["entry_price"],
        "shares": pos["shares"], "exit_date": timestamp, "exit_price": price,
        "exit_reason": reason, "pnl": gross,
        "pnl_pct": gross / (pos["entry_price"] * pos["shares"]) * 100,
        "hold_days": _elapsed_days(pos["entry_date"], timestamp),
        "fees": fees, "slippage": slippage, "borrow": borrow, "pnl_net": net,
    }
    return cash + cash_flow, trade


def account_mark(cash: float, positions: list[dict], prices: dict[str, float],
                 timestamp: str) -> dict:
    """Liquidation equity: exit costs and borrow are included in every mark."""
    equity = cash
    unrealized = 0.0
    for pos in positions:
        price = prices.get(pos["symbol"], pos.get("last_mark", pos["entry_price"]))
        order_side = "sell" if pos["side"] == "long" else "buy"
        fill, exit_fees, exit_slippage = _execution(price, pos["shares"], order_side)
        borrow = _borrow(pos, timestamp)
        liquidation = (fill * pos["shares"] - exit_fees - borrow
                       if pos["side"] == "long"
                       else -fill * pos["shares"] - exit_fees - borrow)
        equity += liquidation
        direction = 1 if pos["side"] == "long" else -1
        gross = (price - pos["entry_price"]) * pos["shares"] * direction
        unrealized += gross - pos["entry_fees"] - pos["entry_slippage"] - exit_fees - exit_slippage - borrow
    return {"cash": cash, "equity": equity, "unrealized": unrealized}


def advance_pair(state: dict, key: str, timestamps: list[str], signals: list[int],
                 closes: list[float], top_keys: set[str], hold_bars: int,
                 take_profit: float, stop_loss: float) -> dict:
    """Replay unseen bars once; outgoing positions exit naturally, never forced."""
    symbol, strategy = key.split("|", 1)
    actions = {"opened": [], "closed": []}
    pos = next((p for p in state["positions"] if p["key"] == key), None)
    anchor_ts = (pos.get("last_mark_ts") or pos["entry_date"]) if pos else state["eval_ts"].get(key)
    anchor_i = timestamps.index(anchor_ts) if anchor_ts in timestamps else (
        0 if pos else max(0, len(timestamps) - 9))
    entry_i = timestamps.index(pos["entry_date"]) if pos and pos["entry_date"] in timestamps else 0

    for i in range(anchor_i + 1, len(timestamps)):
        timestamp, price, signal = timestamps[i], float(closes[i]), int(signals[i])
        if pos:
            direction = 1 if pos["side"] == "long" else -1
            ret = (price / pos["entry_price"] - 1) * direction
            pos["bars_held"] = i - entry_i
            pos["last_mark"] = price
            pos["last_mark_ts"] = timestamp
            reason = None
            if signal != 0 and ((signal > 0) != (pos["side"] == "long")):
                reason = "signal_flip"
            elif signal == 0:
                reason = "signal_off"
            elif ret <= stop_loss:
                reason = "stop_loss"
            elif ret >= take_profit:
                reason = "take_profit"
            elif pos["bars_held"] >= hold_bars:
                reason = "time_stop"
            if reason:
                state["cash"], trade = close_position(
                    state["cash"], pos, price, timestamp, reason)
                actions["closed"].append(trade)
                state["positions"].remove(pos)
                pos = None
                if reason != "signal_flip":
                    continue
        if pos is None and key in top_keys and signal != 0:
            side = "long" if signal > 0 else "short"
            state["cash"], pos = open_position(
                state["cash"], symbol, strategy, side, price, timestamp)
            if pos is not None:
                state["positions"].append(pos)
                actions["opened"].append(dict(pos))
                entry_i = i
    state["eval_ts"][key] = timestamps[-1]
    return actions


def diversified(rows: list[dict], top_n: int = 3) -> list[dict]:
    selected, seen = [], set()
    for row in sorted(rows, key=lambda r: r["total_pnl"], reverse=True):
        if row["symbol"] in seen:
            continue
        selected.append(row)
        seen.add(row["symbol"])
        if len(selected) == top_n:
            break
    return selected


def _net_trades(trades: list[dict]) -> list[dict]:
    out = []
    for t in trades:
        _, pos = open_position(0.0, t.get("symbol", "TEST"),
                               t.get("strategy", "candidate"), t["side"],
                               t["entry_price"], t["entry_date"])
        if pos is None:
            continue
        _, closed = close_position(0.0, pos, t["exit_price"], t["exit_date"],
                                   t.get("exit_reason", "backtest"))
        out.append(closed)
    return out


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0, "total_pnl": 0.0}
    pnls = [t["pnl_net"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    equity = peak = drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return {
        "trades": len(trades), "wins": len(wins),
        "win_rate": len(wins) / len(trades) * 100,
        "total_pnl": sum(pnls), "avg_pnl": sum(pnls) / len(pnls),
        "profit_factor": sum(wins) / -sum(losses) if losses and sum(losses) else None,
        "max_drawdown": drawdown,
    }


def score_candidate(train_trades: list[dict], validation_trades: list[dict]):
    train = _metrics(_net_trades(train_trades))
    if train["total_pnl"] <= 0:
        return None
    validation = _metrics(_net_trades(validation_trades))
    if validation["trades"] < 8:
        return None
    return {**validation, "train_pnl": train["total_pnl"]}


def select_pairs(frames: dict, sigs: dict, strategy_names: list[str], tf: str,
                 top_n: int = 3, exclude: set[str] | None = None,
                 as_of: str | None = None) -> list[dict]:
    """Train must be net-profitable; last-90-day net PnL ranks validation."""
    from datetime import date, timedelta
    from .intraday import TIMEFRAMES
    from .stock_backtest import run_stock_backtest, trades_to_dicts

    cutoff = ((date.fromisoformat(as_of) if as_of else date.today())
              - timedelta(days=90)).isoformat()
    rows = []
    for symbol, df in frames.items():
        dates = df["date"].astype(str)
        train_mask = dates <= cutoff
        validation_mask = dates > cutoff
        train_df = df[train_mask].reset_index(drop=True)
        validation_df = df[validation_mask].reset_index(drop=True)
        if len(train_df) < 50 or len(validation_df) < 20:
            continue
        for strategy in strategy_names:
            key = f"{symbol}|{strategy}"
            if exclude and key in exclude:
                continue
            signal = sigs[(symbol, strategy)]
            train = run_stock_backtest(
                train_df, signal[train_mask].reset_index(drop=True), symbol,
                strategy, max_hold_days=TIMEFRAMES[tf]["hold_bars"])
            validation = run_stock_backtest(
                validation_df, signal[validation_mask].reset_index(drop=True),
                symbol, strategy, max_hold_days=TIMEFRAMES[tf]["hold_bars"])
            score = score_candidate(trades_to_dicts(train), trades_to_dicts(validation))
            if score:
                rows.append({"symbol": symbol, "strategy": strategy, **score})
    return diversified(rows, top_n)


def _default_state(now: str) -> dict:
    return {"cash": INITIAL_CASH, "positions": [], "pairs": [],
            "selected_on": None, "eval_ts": {}, "started_at": now}


def _load_state(conn, now: str) -> dict:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='real_book_meta'").fetchone()
    if not exists:
        return _default_state(now)
    row = conn.execute("SELECT data FROM real_book_meta WHERE key='account'").fetchone()
    return json.loads(row[0]) if row else _default_state(now)


def _live_veto(conn, tf: str) -> set[str]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='real_book_trades'").fetchone()
    if not exists:
        return set()
    cutoff = date.fromordinal(date.today().toordinal() - 45).isoformat()
    rows = conn.execute(
        "SELECT symbol, strategy, pnl_net FROM real_book_trades WHERE exit_date >= ?",
        (cutoff,)).fetchall()
    agg: dict[str, list] = {}
    for symbol, strategy, pnl in rows:
        item = agg.setdefault(f"{symbol}|{strategy}", [0, 0.0])
        item[0] += 1
        item[1] += pnl or 0.0
    return {key for key, (count, pnl) in agg.items()
            if count >= 3 and pnl <= -15.0}


def _payload(conn, state: dict, mark: dict, now: str) -> dict:
    rows = conn.execute("SELECT * FROM real_book_trades ORDER BY exit_date").fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM real_book_trades LIMIT 1").description]
    trades = [dict(zip(cols, row)) for row in rows]
    metrics = _metrics(trades)
    equity_rows = conn.execute(
        "SELECT * FROM real_book_equity ORDER BY date").fetchall()
    equity_cols = [d[0] for d in conn.execute("SELECT * FROM real_book_equity LIMIT 1").description]
    equity = [dict(zip(equity_cols, row)) for row in equity_rows]
    return {
        "timeframe": "1h", "updated_at": now, "started_at": state["started_at"],
        "initial_cash": INITIAL_CASH, "notional": NOTIONAL,
        "sample_status": "accumulating" if not trades else "active",
        "account": {**mark, "realized": sum(t["pnl_net"] or 0 for t in trades)},
        "metrics": metrics, "pairs": state["pairs"], "positions": state["positions"],
        "closed_trades": trades, "equity": equity,
        "assumptions": {
            "slippage_bps_per_side": SLIPPAGE_BPS,
            "short_borrow_annual": BORROW_ANNUAL,
            "fees": "Futu HK US-stock fee schedule",
            "note": "Paper account; no fabricated history before first run",
        },
    }


def _persist_and_export(conn, state: dict, closed: list[dict], mark: dict, now: str):
    columns = ["symbol", "strategy", "side", "entry_date", "entry_price", "shares",
               "exit_date", "exit_price", "exit_reason", "pnl", "pnl_pct",
               "hold_days", "fees", "slippage", "borrow", "pnl_net"]
    conn.executemany(
        f"INSERT INTO real_book_trades ({','.join(columns)}) VALUES ({','.join('?' * len(columns))})",
        [[trade.get(c) for c in columns] for trade in closed])
    conn.execute("DELETE FROM real_book_positions")
    conn.executemany(
        "INSERT INTO real_book_positions (key, data) VALUES (?,?)",
        [(p["key"], json.dumps(p, ensure_ascii=False)) for p in state["positions"]])
    conn.execute("INSERT OR REPLACE INTO real_book_meta (key, data) VALUES ('account', ?)",
                 (json.dumps(state, ensure_ascii=False),))
    realized = conn.execute("SELECT COALESCE(SUM(pnl_net),0) FROM real_book_trades").fetchone()[0]
    conn.execute(
        "INSERT OR REPLACE INTO real_book_equity "
        "(date, equity, cash, realized, unrealized, positions_count, marked_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (now[:10], mark["equity"], mark["cash"], realized, mark["unrealized"],
         len(state["positions"]), now))
    payload = _payload(conn, state, mark, now)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False))
    return payload


def main():
    parser = argparse.ArgumentParser(description="Real-cost 1h candidate paper account")
    parser.add_argument("--dry-run", action="store_true",
                        help="select and replay without writing DB, state, or frontend JSON")
    args = parser.parse_args()

    from . import production, storage, strategies
    from .intraday import TIMEFRAMES, fetch_intraday
    from .run_backtest import DEFAULT_SYMBOLS
    from .stock_backtest import exits_for

    now = datetime.now(timezone.utc).isoformat()
    if not args.dry_run:
        storage.init_db()
    with storage.get_conn() as conn:
        state = _load_state(conn, now)
        vetoed = _live_veto(conn, "1h")

    selected_on = state.get("selected_on")
    selection_age = (date.today() - date.fromisoformat(selected_on)).days if selected_on else 999
    full_selection = not state.get("pairs") or selection_age >= 7
    symbols = set(DEFAULT_SYMBOLS if full_selection else
                  [p["symbol"] for p in state["pairs"]])
    symbols.update(p["symbol"] for p in state["positions"])
    watchlist = set(production.watchlist())
    strategy_names = [name for name in strategies.STOCK_STRATEGIES if name not in watchlist]
    frames, sigs = {}, {}
    for symbol in sorted(symbols):
        try:
            df = strategies.prepare(fetch_intraday(symbol, "1h", use_cache=True))
        except Exception as exc:  # data gaps must not block the other pairs
            print(f"[real-book] {symbol}: {exc}", flush=True)
            continue
        frames[symbol] = df
        for strategy in strategy_names:
            sigs[(symbol, strategy)] = strategies.STOCK_STRATEGIES[strategy](df)

    if full_selection:
        state["pairs"] = select_pairs(frames, sigs, strategy_names, "1h", 3,
                                      exclude=vetoed)
        state["selected_on"] = now[:10]
    top_keys = {f"{p['symbol']}|{p['strategy']}" for p in state["pairs"]}
    active_keys = top_keys | {p["key"] for p in state["positions"]}
    opened, closed = [], []
    for key in sorted(active_keys):
        symbol, strategy = key.split("|", 1)
        if symbol not in frames:
            continue
        df = frames[symbol]
        tp, sl = exits_for(strategy)
        actions = advance_pair(
            state, key, df["date"].astype(str).tolist(),
            sigs[(symbol, strategy)].tolist(), df["close"].tolist(), top_keys,
            TIMEFRAMES["1h"]["hold_bars"], tp, sl)
        opened.extend(actions["opened"])
        closed.extend(actions["closed"])

    prices = {p["symbol"]: p.get("last_mark", p["entry_price"]) for p in state["positions"]}
    for pos in state["positions"]:
        pos["unrealized_net"] = account_mark(
            0.0, [pos], {pos["symbol"]: prices[pos["symbol"]]}, now)["unrealized"]
        pos["marked_at"] = now
    mark = account_mark(state["cash"], state["positions"], prices, now)

    print("[real-book] pairs: " + ", ".join(
        f"{p['symbol']}×{p['strategy']} (${p['total_pnl']:.2f} validation net)"
        for p in state["pairs"]), flush=True)
    print(f"[real-book] opened={len(opened)} closed={len(closed)} "
          f"equity=${mark['equity']:.2f} cash=${mark['cash']:.2f}", flush=True)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "pairs": state["pairs"],
                          "opened": opened, "closed": closed, "account": mark},
                         ensure_ascii=False, indent=2))
        return
    with storage.get_conn() as conn:
        _persist_and_export(conn, state, closed, mark, now)


if __name__ == "__main__":
    main()
