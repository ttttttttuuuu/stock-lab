"""Backtest engine: weekly options, $100 per trade, simulated via Black-Scholes.

Rules
-----
- Signal +1 -> buy weekly ATM CALL; -1 -> buy weekly ATM PUT (DTE ~7 days).
- Position size: exactly $100 of premium per trade (fractional contracts
  allowed in simulation; note this in the UI).
- Exit on: signal change/flip, stop-loss -50%, take-profit +100%,
  or time stop after 5 trading days.
- Fills at same-day close (close-to-close approximation).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import pandas as pd

from .options_sim import bs_price, pick_weekly_contract

TRADE_BUDGET = 100.0          # USD per trade
STOP_LOSS = -0.50             # -50% of premium
TAKE_PROFIT = 1.00            # +100% of premium
MAX_HOLD_DAYS = 5             # trading days
DTE_AT_ENTRY = 7              # calendar days


@dataclass
class Trade:
    symbol: str
    strategy: str
    kind: str                    # call / put
    strike: float
    entry_date: str
    entry_underlying: float
    entry_price: float           # option premium per share
    qty: float                   # fractional contracts
    iv_entry: float
    exit_date: str = ""
    exit_underlying: float = 0.0
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    hold_days: int = 0


def _option_price(row, strike, kind, dte_cal_days):
    sigma = row["hv20"] if pd.notna(row["hv20"]) else 0.30
    return bs_price(row["close"], strike, dte_cal_days / 365.0, sigma, kind)


def run_backtest(df: pd.DataFrame, signals: pd.Series, symbol: str,
                 strategy: str) -> list[Trade]:
    trades: list[Trade] = []
    pos: Trade | None = None
    dte_left = 0
    days_held = 0

    for i in range(len(df)):
        row = df.iloc[i]
        sig = int(signals.iloc[i])
        date_str = row["date"].strftime("%Y-%m-%d")

        if pos is not None:
            dte_left -= 1
            days_held += 1
            price = _option_price(row, pos.strike, pos.kind, max(dte_left, 0))
            ret = price / pos.entry_price - 1 if pos.entry_price > 0 else -1
            exit_reason = None
            if sig != 0 and ((sig > 0) != (pos.kind == "call")):
                exit_reason = "signal_flip"
            elif sig == 0:
                exit_reason = "signal_off"
            elif ret <= STOP_LOSS:
                exit_reason = "stop_loss"
            elif ret >= TAKE_PROFIT:
                exit_reason = "take_profit"
            elif days_held >= MAX_HOLD_DAYS or dte_left <= 0:
                exit_reason = "time_stop"
            elif i == len(df) - 1:
                exit_reason = "end_of_data"

            if exit_reason:
                pos.exit_date = date_str
                pos.exit_underlying = round(float(row["close"]), 2)
                pos.exit_price = round(price, 4)
                pos.exit_reason = exit_reason
                pos.pnl = round((price - pos.entry_price) * 100 * pos.qty, 2)
                pos.pnl_pct = round(ret * 100, 2)
                pos.hold_days = days_held
                trades.append(pos)
                pos = None
                if exit_reason != "signal_flip":
                    continue  # do not re-enter same bar unless flip

        if pos is None and sig != 0 and pd.notna(row["hv20"]):
            kind = "call" if sig > 0 else "put"
            strike, dte = pick_weekly_contract(float(row["close"]), DTE_AT_ENTRY)
            entry_price = _option_price(row, strike, kind, dte)
            if entry_price <= 0.01:
                continue
            qty = TRADE_BUDGET / (entry_price * 100)
            pos = Trade(
                symbol=symbol,
                strategy=strategy,
                kind=kind,
                strike=strike,
                entry_date=date_str,
                entry_underlying=round(float(row["close"]), 2),
                entry_price=round(entry_price, 4),
                qty=round(qty, 4),
                iv_entry=round(float(row["hv20"]), 4),
            )
            dte_left = dte
            days_held = 0

    return trades


def compute_metrics(trades: list[Trade]) -> dict:
    if not trades:
        return {"trades": 0}
    pnls = pd.Series([t.pnl for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    equity = pnls.cumsum()
    peak = equity.cummax()
    max_dd = float((equity - peak).min())
    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())
    return {
        "trades": len(trades),
        "wins": int(len(wins)),
        "win_rate": round(len(wins) / len(trades) * 100, 1),
        "total_pnl": round(float(pnls.sum()), 2),
        "avg_pnl": round(float(pnls.mean()), 2),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "max_drawdown": round(max_dd, 2),
        "capital_deployed": round(len(trades) * TRADE_BUDGET, 2),
        "return_on_capital_pct": round(float(pnls.sum()) / (len(trades) * TRADE_BUDGET) * 100, 2),
        "avg_hold_days": round(sum(t.hold_days for t in trades) / len(trades), 1),
        "exit_reasons": pd.Series([t.exit_reason for t in trades]).value_counts().to_dict(),
    }


def trades_to_dicts(trades: list[Trade]) -> list[dict]:
    return [asdict(t) for t in trades]
