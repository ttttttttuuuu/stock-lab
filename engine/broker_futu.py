"""Futu (富途牛牛) broker adapter — SIMULATE-ONLY by design.

Safety contract (do not weaken without an explicit owner decision):
- This adapter talks to OpenD only for TrdEnv.SIMULATE. Real-money trading
  (TrdEnv.REAL) is refused at construction unless FUTU_ALLOW_REAL=1 is set,
  and even then this class never unlocks trading — the real environment
  must be unlocked manually in the Futu app / OpenD every session.
- No credentials in code or git. OpenD login happens outside this repo;
  the trade-unlock password is read from env FUTU_TRADE_PWD only when the
  simulate account requires it, and is never logged.
- OpenD must stay bound to 127.0.0.1 (default). Pointing this adapter at a
  remote OpenD should only happen over an SSH tunnel.

Usage:
    broker = FutuBroker()                    # simulate env
    broker.account()                         # buying power etc.
    broker.quote("AAPL")                     # latest snapshot price
    broker.place_stock_order("AAPL", "BUY", qty=1, price=305.0)
    broker.positions()

Requires: pip install futu-api  +  OpenD running and logged in locally.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

OPEND_HOST = os.environ.get("FUTU_OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.environ.get("FUTU_OPEND_PORT", "11111"))


class BrokerError(RuntimeError):
    pass


def _futu():
    try:
        import futu  # noqa: PLC0415 - optional dependency, lazy import
        return futu
    except ImportError as e:
        raise BrokerError(
            "futu-api 未安装：pip install futu-api，并启动本机 OpenD 网关"
        ) from e


def us_code(symbol: str) -> str:
    """AAPL -> US.AAPL (Futu market prefix)."""
    s = symbol.strip().upper()
    return s if "." in s else f"US.{s}"


@dataclass
class OrderResult:
    order_id: str
    code: str
    side: str
    qty: float
    price: float | None
    raw: dict


class FutuBroker:
    def __init__(self, host: str = OPEND_HOST, port: int = OPEND_PORT,
                 simulate: bool = True):
        futu = _futu()
        if not simulate and os.environ.get("FUTU_ALLOW_REAL") != "1":
            raise BrokerError(
                "真实交易环境被硬禁用：需要 FUTU_ALLOW_REAL=1 且人工在 "
                "OpenD 解锁。当前项目阶段只允许模拟盘。")
        self._futu = futu
        self.env = futu.TrdEnv.SIMULATE if simulate else futu.TrdEnv.REAL
        self.host, self.port = host, port
        self._trd = None
        self._unlocked = False

    # ---- connections -----------------------------------------------------
    def _quote_ctx(self):
        return self._futu.OpenQuoteContext(host=self.host, port=self.port)

    @property
    def trd(self):
        if self._trd is None:
            self._trd = self._futu.OpenSecTradeContext(
                host=self.host, port=self.port,
                filter_trdmarket=self._futu.TrdMarket.US,
                security_firm=self._futu.SecurityFirm.FUTUSECURITIES)
        return self._trd

    def close(self):
        if self._trd is not None:
            self._trd.close()
            self._trd = None

    # ---- account / quotes ------------------------------------------------
    def account(self) -> dict:
        ret, data = self.trd.accinfo_query(trd_env=self.env)
        if ret != self._futu.RET_OK:
            raise BrokerError(f"accinfo_query failed: {data}")
        row = data.iloc[0].to_dict()
        return {k: row.get(k) for k in
                ("total_assets", "cash", "market_val", "frozen_cash",
                 "available_funds", "currency")}

    def quote(self, symbol: str) -> dict:
        ctx = self._quote_ctx()
        try:
            ret, data = ctx.get_market_snapshot([us_code(symbol)])
            if ret != self._futu.RET_OK:
                raise BrokerError(f"get_market_snapshot {symbol}: {data}")
            row = data.iloc[0].to_dict()
            return {
                "code": row.get("code"),
                "last_price": row.get("last_price"),
                "open": row.get("open_price"),
                "high": row.get("high_price"),
                "low": row.get("low_price"),
                "prev_close": row.get("prev_close_price"),
                "volume": row.get("volume"),
                "update_time": row.get("update_time"),
            }
        finally:
            ctx.close()

    def positions(self) -> list[dict]:
        ret, data = self.trd.position_list_query(trd_env=self.env)
        if ret != self._futu.RET_OK:
            raise BrokerError(f"position_list_query failed: {data}")
        out = []
        for _, r in data.iterrows():
            out.append({
                "code": r.get("code"),
                "qty": float(r.get("qty", 0)),
                "cost_price": r.get("cost_price"),
                "market_val": r.get("market_val"),
                "pl_val": r.get("pl_val"),
                "pl_ratio": r.get("pl_ratio"),
            })
        return out

    # ---- orders ----------------------------------------------------------
    def _ensure_unlocked(self):
        """Simulate accounts may still require unlock_trade; the password
        comes from env only. Never called for REAL (manual unlock only)."""
        if self._unlocked:
            return
        pwd = os.environ.get("FUTU_TRADE_PWD")
        if not pwd:
            return  # many simulate setups need no unlock; try and see
        ret, data = self.trd.unlock_trade(password=pwd, trd_env=self.env)
        if ret == self._futu.RET_OK:
            self._unlocked = True
        # failure surfaces on the first order with a clear broker error

    def place_stock_order(self, symbol: str, side: str, qty: float,
                          price: float | None = None) -> OrderResult:
        """side: 'BUY' or 'SELL'. qty is floored to whole shares (Futu US
        stock API does not accept fractional qty on most routes); callers
        must size positions accordingly. price=None -> market order."""
        self._ensure_unlocked()
        futu = self._futu
        side_map = {"BUY": futu.TrdSide.BUY, "SELL": futu.TrdSide.SELL}
        if side.upper() not in side_map:
            raise BrokerError(f"side must be BUY/SELL, got {side!r}")
        whole = int(qty)
        if whole < 1:
            raise BrokerError(
                f"qty {qty} < 1 股：富途美股 API 多数路由不支持碎股，"
                f"请提高单笔本金或改用整股 sizing")
        kwargs = dict(
            qty=whole, code=us_code(symbol), trd_side=side_map[side.upper()],
            trd_env=self.env)
        if price is None:
            kwargs["order_type"] = futu.OrderType.MARKET
        else:
            kwargs["price"] = float(price)
            kwargs["order_type"] = futu.OrderType.NORMAL
        ret, data = self.trd.place_order(**kwargs)
        if ret != futu.RET_OK:
            raise BrokerError(f"place_order failed: {data}")
        row = data.iloc[0].to_dict()
        return OrderResult(
            order_id=str(row.get("order_id", "")),
            code=row.get("code", us_code(symbol)),
            side=side.upper(), qty=whole, price=price, raw=row)
