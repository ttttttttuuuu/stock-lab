"""Futu HK US-stock real trading costs (official schedule, verified 2026-10-27).

Source: https://support.futunn.com/topic814 (美股融资融券账户模拟交易规则)
- commission: $0.0049/share, min $0.99/order, capped at 0.5% of trade amount
- platform fee: $0.005/share, min $1.00/order, capped at 0.5%
- settlement fee: $0.003/share
- SEC compliance fee (sell only): amount * 0.000008, min $0.01
- FINRA TAF (sell only): $0.000166/share, min $0.01, max $8.30

Short borrow is NOT in the fee schedule (stock-specific): modelled as an
annualized rate on short market value, actual days held / 365.
Slippage is a separate assumption in basis points per side.
"""
from __future__ import annotations

from datetime import datetime

COMMISSION_PER_SHARE = 0.0049
COMMISSION_MIN = 0.99
PLATFORM_PER_SHARE = 0.005
PLATFORM_MIN = 1.00
SETTLEMENT_PER_SHARE = 0.003
SEC_RATE = 0.000008
SEC_MIN = 0.01
TAF_PER_SHARE = 0.000166
TAF_MIN = 0.01
TAF_MAX = 8.30
FEE_CAP_PCT = 0.005  # commission and platform each capped at 0.5% of amount

# Futu advertises $0 commission for US fractional-share (<1 share) orders;
# whether the platform fee is also waived is UNVERIFIED — only used when
# fractional_free=True is explicitly requested as a what-if scenario.
FRACTIONAL_FREE_ASSUMPTION = "unverified: commission+platform waived for <1 share orders"


def order_fees(shares: float, price: float, side: str,
               fractional_free: bool = False) -> float:
    """Total fees of ONE order. side = 'buy' | 'sell'."""
    amount = shares * price
    if fractional_free and shares < 1:
        commission = platform = 0.0
    else:
        commission = min(max(COMMISSION_PER_SHARE * shares, COMMISSION_MIN),
                         amount * FEE_CAP_PCT)
        platform = min(max(PLATFORM_PER_SHARE * shares, PLATFORM_MIN),
                       amount * FEE_CAP_PCT)
    fees = commission + platform + SETTLEMENT_PER_SHARE * shares
    if side == "sell":
        fees += max(amount * SEC_RATE, SEC_MIN)
        fees += min(max(TAF_PER_SHARE * shares, TAF_MIN), TAF_MAX)
    return fees


def _days(entry: str, exit_: str) -> float:
    fmt = "%Y-%m-%d" if len(entry) == 10 else None
    if fmt:
        return (datetime.strptime(exit_[:10], fmt)
                - datetime.strptime(entry[:10], fmt)).days
    return (datetime.fromisoformat(exit_)
            - datetime.fromisoformat(entry)).total_seconds() / 86400


def trade_net(t: dict, notional: float, slippage_bps: float = 5.0,
              borrow_annual: float = 0.05,
              fractional_free: bool = False) -> dict:
    """Recompute one paper trade at `notional` with real Futu costs.

    t: closed trade dict with entry_price/exit_price/side/pnl_pct/dates.
    Returns {gross, fees, borrow, slippage, net}.
    """
    shares = notional / t["entry_price"]
    short = t["side"] == "short"
    fees = (order_fees(shares, t["entry_price"], "sell" if short else "buy",
                       fractional_free)
            + order_fees(shares, t["exit_price"], "buy" if short else "sell",
                         fractional_free))
    gross = notional * t["pnl_pct"] / 100
    borrow = (notional * borrow_annual * max(_days(t["entry_date"], t["exit_date"]), 0) / 365
              if short else 0.0)
    slippage = notional * slippage_bps / 10000 * 2
    return {"gross": gross, "fees": fees, "borrow": borrow,
            "slippage": slippage, "net": gross - fees - borrow - slippage}
