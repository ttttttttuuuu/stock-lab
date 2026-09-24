"""Futu (富途牛牛) broker adapter — STUB, not wired in yet.

Roadmap for live trading (deferred per project plan):
1. Install OpenD (Futu gateway) locally and log in with a Futu account.
2. `pip install futu-api` (moomoo API for US markets).
3. Implement the interface below against futu's OpenSecTradeContext
   (trd_env=TrdEnv.SIMULATE first for paper, then REAL).
4. daily_signals.py will call place_order() instead of only recording
   paper positions, gated by env var BROKER=futu.

Interface contract (keep stable so the engine does not change):
"""
from __future__ import annotations


class FutuBroker:
    def __init__(self, host: str = "127.0.0.1", port: int = 11111,
                 simulate: bool = True):
        self.host = host
        self.port = port
        self.simulate = simulate
        raise NotImplementedError(
            "Futu integration is deferred. Install OpenD + futu-api first."
        )

    def get_option_chain(self, symbol: str, expiry: str):
        """Return near-term option chain for symbol/expiry."""
        raise NotImplementedError

    def place_order(self, option_code: str, qty: int, side: str,
                    price: float | None = None):
        """side: 'BUY' to open, 'SELL' to close. Returns order id."""
        raise NotImplementedError

    def positions(self):
        """Current option positions."""
        raise NotImplementedError
