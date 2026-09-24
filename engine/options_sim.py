"""Black-Scholes option pricing used to simulate weekly option trades.

Free historical option prices do not exist, so the backtest prices a
hypothetical ATM weekly contract from the underlying price + 20-day
historical volatility (as IV proxy) + a constant risk-free rate.
"""
from __future__ import annotations

import math

from scipy.stats import norm

RISK_FREE = 0.045  # ~1M T-bill proxy
TRADING_DAYS = 252


def bs_price(S: float, K: float, T_years: float, sigma: float, kind: str,
             r: float = RISK_FREE) -> float:
    """Black-Scholes price for a European call/put."""
    if T_years <= 0:
        return max(0.0, S - K) if kind == "call" else max(0.0, K - S)
    sigma = max(sigma, 0.05)  # floor IV proxy
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T_years) / (sigma * math.sqrt(T_years))
    d2 = d1 - sigma * math.sqrt(T_years)
    if kind == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T_years) * norm.cdf(d2)
    return K * math.exp(-r * T_years) * norm.cdf(-d2) - S * norm.cdf(-d1)


def pick_weekly_contract(S: float, dte_days: int = 7) -> tuple[float, int]:
    """Pick ATM strike (rounded to nearest $2.5/$5 style step) and DTE."""
    step = 1.0 if S < 50 else (2.5 if S < 200 else 5.0)
    strike = round(S / step) * step
    return strike, dte_days
