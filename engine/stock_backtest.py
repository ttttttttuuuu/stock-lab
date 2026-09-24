"""Stock-level backtest: strategy signals traded on the underlying stock.

Unlike engine/backtest.py (weekly options via Black-Scholes), this simulates
trading the stock itself — long on +1, short on -1 — so results are directly
verifiable against price history and usable for strategy × symbol screening.

Rules
-----
- Signal +1 -> long the stock; -1 -> short the stock (same-bar close fill).
- Position size: exactly $100 notional per trade (fractional shares).
- Exit on: signal flip/off, stop-loss -5%, take-profit +10%,
  or time stop after 10 trading days.
- Short selling is simulated without borrow cost; noted in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

TRADE_BUDGET = 100.0          # USD notional per trade
STOP_LOSS = -0.05             # -5% adverse move
TAKE_PROFIT = 0.10            # +10% favourable move
MAX_HOLD_DAYS = 10            # trading days

# Per-strategy exit structures come from data/production_params.json (via
# engine.production) so the weekly evolution job can promote better combos
# without code changes. Promoted 2026-09-22 from the exit-grid search.
# Strategies without an override use the global default +10% / -5%.
from . import production as _prod  # noqa: E402


def exits_for(strategy: str) -> tuple[float, float]:
    """(take_profit, stop_loss) for a strategy — per-strategy override or
    the global default."""
    return _prod.strategy_exit(strategy)


@dataclass
class StockTrade:
    symbol: str
    strategy: str
    side: str                    # long / short
    entry_date: str
    entry_price: float
    shares: float                # fractional
    exit_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    hold_days: int = 0


def run_stock_backtest(df: pd.DataFrame, signals: pd.Series, symbol: str,
                       strategy: str, stop_loss: float | None = None,
                       take_profit: float | None = None,
                       max_hold_days: int = MAX_HOLD_DAYS) -> list[StockTrade]:
    if take_profit is None or stop_loss is None:
        take_profit, stop_loss = exits_for(strategy)
    trades: list[StockTrade] = []
    pos: StockTrade | None = None
    days_held = 0

    for i in range(len(df)):
        row = df.iloc[i]
        sig = int(signals.iloc[i])
        date_str = row["date"].strftime("%Y-%m-%d")
        close = float(row["close"])

        if pos is not None:
            days_held += 1
            direction = 1 if pos.side == "long" else -1
            ret = (close / pos.entry_price - 1) * direction
            exit_reason = None
            if sig != 0 and ((sig > 0) != (pos.side == "long")):
                exit_reason = "signal_flip"
            elif sig == 0:
                exit_reason = "signal_off"
            elif ret <= stop_loss:
                exit_reason = "stop_loss"
            elif ret >= take_profit:
                exit_reason = "take_profit"
            elif days_held >= max_hold_days:
                exit_reason = "time_stop"
            elif i == len(df) - 1:
                exit_reason = "end_of_data"

            if exit_reason:
                pos.exit_date = date_str
                pos.exit_price = round(close, 4)
                pos.exit_reason = exit_reason
                pos.pnl = round(ret * TRADE_BUDGET, 2)
                pos.pnl_pct = round(ret * 100, 2)
                pos.hold_days = days_held
                trades.append(pos)
                pos = None
                if exit_reason != "signal_flip":
                    continue  # do not re-enter same bar unless flip

        if pos is None and sig != 0:
            side = "long" if sig > 0 else "short"
            pos = StockTrade(
                symbol=symbol,
                strategy=strategy,
                side=side,
                entry_date=date_str,
                entry_price=round(close, 4),
                shares=round(TRADE_BUDGET / close, 6),
            )
            days_held = 0

    return trades


def compute_metrics(trades: list[StockTrade]) -> dict:
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
    # annualised Sharpe on per-trade returns is meaningless; use daily marks
    # approximated from trade returns / hold days instead — keep it simple:
    # report per-trade stats only.
    longs = [t for t in trades if t.side == "long"]
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
        "long_ratio": round(len(longs) / len(trades) * 100, 1),
        "avg_hold_days": round(sum(t.hold_days for t in trades) / len(trades), 1),
        "exit_reasons": pd.Series([t.exit_reason for t in trades]).value_counts().to_dict(),
    }


def trades_to_dicts(trades: list[StockTrade]) -> list[dict]:
    return [asdict(t) for t in trades]
