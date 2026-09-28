"""把纸面账本的开平仓事件镜像成富途模拟盘订单。

Gate: 环境变量 BROKER=futu_sim 才启用（默认关，云端/本地日常跑不受影响）。
安全边界:
- 只连本机 OpenD 的 SIMULATE 环境（broker_futu 已硬禁用 REAL）
- 只镜像多头（纸面账本允许做空，富途美股模拟卖空未接线，遇到直接跳过）
- 整股 sizing: FUTU_MIRROR_BUDGET（默认 $500）// 价格，<1 股跳过并记录原因
- 幂等: data/futu_mirror.json 以 动作|配对|入场时间 为事件键；
  失败（如非交易时段下单被拒）保留 failed 状态，下次运行自动重试

注意：1h 纸面账本的信号本身按 bar 收盘复盘、滞后约一天记账，镜像单
只是"信号出现后的下一个可下单时刻"成交，用于验证真实成交价与滑点，
不代表可复现纸面账本的精确入场价。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIRROR_FILE = ROOT / "data" / "futu_mirror.json"
BUDGET = float(os.environ.get("FUTU_MIRROR_BUDGET", "500"))


def enabled() -> bool:
    return os.environ.get("BROKER") == "futu_sim"


def _load() -> dict:
    if MIRROR_FILE.exists():
        return json.loads(MIRROR_FILE.read_text())
    return {"orders": []}


def _save(state: dict):
    MIRROR_FILE.parent.mkdir(parents=True, exist_ok=True)
    MIRROR_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def _event_key(action: str, pair_key: str, ts: str) -> str:
    return f"{action}|{pair_key}|{ts}"


def _find(state: dict, event: str) -> dict | None:
    for o in state["orders"]:
        if o["event"] == event:
            return o
    return None


def mirror(opens: list[dict], closes: list[dict]):
    """opens: intraday_paper 新开的 position dicts；
    closes: 刚平仓的 trade dicts（含 entry_date 用于配对开仓单）。"""
    if not enabled() or (not opens and not closes):
        return
    from .broker_futu import BrokerError, FutuBroker

    state = _load()
    now = datetime.now(timezone.utc).isoformat()
    broker = FutuBroker(simulate=True)
    try:
        from . import futu_book
        # 先同步上一轮挂单的真实成交，重建虚拟账本（ sizing 要用账面现金）
        futu_book.sync_fills(broker, state)
        book = futu_book.rebuild(state)
        acct = broker.account()
        print(f"[futu-mirror] 沙盒现金 {acct.get('cash')} | "
              f"虚拟账本现金 {book['cash']}/{book['start_capital']}", flush=True)

        for pos in opens:
            ev = _event_key("open", pos["key"], pos["entry_ts"])
            rec = _find(state, ev)
            if rec and rec["status"] in ("submitted", "skipped",
                                         "filled", "cancelled"):
                continue
            if rec is None:
                rec = {"event": ev, "action": "open",
                       "symbol": pos["symbol"], "strategy": pos["strategy"],
                       "paper_side": pos["side"],
                       "paper_price": pos["entry_price"], "time": now}
                state["orders"].append(rec)
            if pos["side"] != "long":
                rec.update(status="skipped",
                           reason="做空不镜像（富途美股模拟卖空未接线）")
            else:
                # sizing 受虚拟现金约束：资金不足的信号直接跳过
                spend = min(BUDGET, book["cash"])
                qty = int(spend / float(pos["entry_price"]))
                if qty < 1:
                    rec.update(status="skipped",
                               reason=f"虚拟现金不足（余 ${book['cash']:.0f}，"
                                      f"买不起 1 股 @ {pos['entry_price']}）")
                else:
                    try:
                        res = broker.place_stock_order(
                            pos["symbol"], "BUY", qty=qty, price=None)
                        rec.update(status="submitted", qty=qty,
                                   order_id=res.order_id, time=now)
                        book["cash"] -= qty * float(pos["entry_price"])
                        print(f"[futu-mirror] BUY {pos['symbol']} x{qty} "
                              f"order_id={res.order_id}", flush=True)
                    except BrokerError as e:
                        rec.update(status="failed", error=str(e), time=now)
                        print(f"[futu-mirror] open {pos['symbol']} 失败: {e}",
                              flush=True)
            _save(state)

        for t in closes:
            pair_key = f"{t['symbol']}|{t['strategy']}"
            ev = _event_key("close", pair_key, t["exit_date"])
            rec = _find(state, ev)
            if rec and rec["status"] in ("submitted", "skipped",
                                         "filled", "cancelled"):
                continue
            open_rec = _find(state, _event_key("open", pair_key,
                                               t["entry_date"]))
            if rec is None:
                rec = {"event": ev, "action": "close",
                       "symbol": t["symbol"], "strategy": t["strategy"],
                       "paper_side": t["side"],
                       "paper_price": t["exit_price"],
                       "exit_reason": t["exit_reason"],
                       "open_event": _event_key("open", pair_key,
                                                t["entry_date"]),
                       "time": now}
                state["orders"].append(rec)
            if t["side"] != "long" or not open_rec \
                    or open_rec["status"] not in ("submitted", "filled"):
                rec.update(status="skipped",
                           reason="无对应的已镜像开仓单（做空或未成交）")
            else:
                qty = open_rec.get("fill_qty") or open_rec.get("qty", 0)
                try:
                    res = broker.place_stock_order(
                        t["symbol"], "SELL", qty=qty, price=None)
                    rec.update(status="submitted", qty=qty,
                               order_id=res.order_id, time=now)
                    print(f"[futu-mirror] SELL {t['symbol']} x{qty} "
                          f"order_id={res.order_id}", flush=True)
                except BrokerError as e:
                    rec.update(status="failed", error=str(e), time=now)
                    print(f"[futu-mirror] close {t['symbol']} 失败: {e}",
                          flush=True)
            _save(state)

        futu_book.save(state)  # 重放重建 data/futu_book.json
    finally:
        broker.close()
