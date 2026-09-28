"""策略专属虚拟账本 —— 把富途模拟盘当执行沙盒，自己记一本小本金账。

背景：富途模拟账户资金由平台设定（~$217k），与真实交易计划（$100-500/
笔）完全脱节。本模块维护一本虚拟本金账（默认 $3,000，FUTU_BOOK_CAPITAL
可改），只统计策略镜像单的真实成交：

- 买入按 dealt_avg_price（真实成交均价）扣虚拟现金，现金不足 1 股则该
  信号跳过不下单（资金约束即真实约束）
- 卖出按真实成交价回款，得出已实现盈亏
- 账本 = f(镜像事件日志)，可从头重放重建，天然幂等

Usage: python -m engine.futu_book   # 重放重建 data/futu_book.json
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIRROR_FILE = ROOT / "data" / "futu_mirror.json"
BOOK_FILE = ROOT / "data" / "futu_book.json"
START_CAPITAL = float(os.environ.get("FUTU_BOOK_CAPITAL", "3000"))

CANCELLED = {"CANCELLED_ALL", "CANCELLED_PART", "DISABLED", "FAILED",
             "DELETED", "CANCELLED"}
TERMINAL = {"filled", "cancelled", "skipped"}


def load_mirror() -> dict:
    if MIRROR_FILE.exists():
        return json.loads(MIRROR_FILE.read_text())
    return {"orders": []}


def save_mirror(state: dict):
    MIRROR_FILE.parent.mkdir(parents=True, exist_ok=True)
    MIRROR_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def sync_fills(broker, state: dict) -> int:
    """把镜像日志里 submitted 的订单同步为 filled/cancelled（含真实成交价）。
    返回新成交的笔数。"""
    import futu
    pending = [o for o in state["orders"]
               if o["status"] == "submitted" and o.get("order_id")]
    if not pending:
        return 0
    ret, orders = broker.trd.order_list_query(acc_id=broker.acc_id,
                                              trd_env=broker.env)
    if ret != futu.RET_OK:
        return 0
    by_id = {str(r["order_id"]): r for _, r in orders.iterrows()}
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for o in pending:
        r = by_id.get(str(o["order_id"]))
        if r is None:
            continue
        st = str(r["order_status"])
        if st == "FILLED_ALL":
            o.update(status="filled",
                     fill_price=round(float(r["dealt_avg_price"]), 4),
                     fill_qty=float(r["dealt_qty"]),
                     fill_time=str(r.get("updated_time") or now))
            n += 1
            print(f"[futu-book] 成交 {o['action']} {o['symbol']} "
                  f"x{o['fill_qty']} @ {o['fill_price']}", flush=True)
        elif st in CANCELLED:
            o.update(status="cancelled")
    return n


def rebuild(state: dict) -> dict:
    """从镜像事件日志重放整本账。买入占用现金，卖出回款并结算盈亏。"""
    cash = START_CAPITAL
    positions: dict[str, dict] = {}   # open event key -> position
    closed: list[dict] = []
    fills = [o for o in state["orders"] if o.get("status") == "filled"]
    fills.sort(key=lambda o: o.get("fill_time") or o["time"])
    for o in fills:
        if o["action"] == "open":
            cost = round(o["fill_qty"] * o["fill_price"], 2)
            cash -= cost
            positions[o["event"]] = {
                "key": o["event"].split("|", 1)[1].rsplit("|", 1)[0],
                "symbol": o["symbol"], "strategy": o["strategy"],
                "qty": o["fill_qty"], "cost_price": o["fill_price"],
                "cost": cost, "open_time": o.get("fill_time") or o["time"],
            }
        else:
            # 优先用下单时记录的关联，否则按 symbol 先进先出配对
            open_ev = o.get("open_event")
            if open_ev not in positions:
                open_ev = next(
                    (k for k, p in positions.items()
                     if p["symbol"] == o["symbol"]), None)
            if open_ev is None:
                continue
            p = positions.pop(open_ev)
            proceeds = round(o["fill_qty"] * o["fill_price"], 2)
            cash += proceeds
            closed.append({
                "symbol": p["symbol"], "strategy": p["strategy"],
                "qty": p["qty"], "cost_price": p["cost_price"],
                "exit_price": o["fill_price"], "pnl": round(proceeds - p["cost"], 2),
                "open_time": p["open_time"],
                "close_time": o.get("fill_time") or o["time"],
                "exit_reason": o.get("exit_reason"),
            })
    return {
        "start_capital": START_CAPITAL,
        "cash": round(cash, 2),
        "positions": list(positions.values()),
        "closed": closed,
        "realized_pnl": round(sum(c["pnl"] for c in closed), 2),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def save(state: dict) -> dict:
    book = rebuild(state)
    BOOK_FILE.write_text(json.dumps(book, indent=2, ensure_ascii=False))
    return book


if __name__ == "__main__":
    book = save(load_mirror())
    print(f"虚拟账本: 现金 {book['cash']} / {book['start_capital']}，"
          f"持仓 {len(book['positions'])}，已实现 {book['realized_pnl']}")
