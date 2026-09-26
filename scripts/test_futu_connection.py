"""Futu OpenD smoke test — SIMULATE env only.

Run after: pip install futu-api, OpenD running and logged in locally.

    python scripts/test_futu_connection.py            # read-only checks
    python scripts/test_futu_connection.py --order    # + one tiny simulate
                                                      # order (AAPL, 1 share,
                                                      # far-from-market limit,
                                                      # then cancelled)

No credentials are read or printed; the script only talks to local OpenD.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.broker_futu import BrokerError, FutuBroker  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", action="store_true",
                    help="place + cancel one harmless simulate order")
    args = ap.parse_args()

    b = FutuBroker(simulate=True)
    print(f"连接 OpenD {b.host}:{b.port}（模拟环境）...")

    try:
        acc = b.account()
        print("✓ 模拟账户:", {k: v for k, v in acc.items() if v is not None})
    except BrokerError as e:
        sys.exit(f"✗ 账户查询失败：{e}\n"
                 "  请确认 OpenD 已启动并登录富途账户。")

    try:
        q = b.quote("AAPL")
        print(f"✓ AAPL 行情: last={q['last_price']} "
              f"更新时间={q['update_time']}")
    except BrokerError as e:
        print(f"✗ 行情查询失败（可能缺行情权限，LV1 即可）: {e}")

    try:
        pos = b.positions()
        print(f"✓ 模拟持仓 {len(pos)} 个",
              f"（示例: {pos[0]['code']} x{pos[0]['qty']}）" if pos else "")
    except BrokerError as e:
        print(f"✗ 持仓查询失败: {e}")

    if args.order:
        try:
            # 远离市价的限价单，挂在模拟盘也不会成交，随后撤单
            low = round((b.quote("AAPL")["last_price"] or 100) * 0.5, 2)
            od = b.place_stock_order("AAPL", "BUY", qty=1, price=low)
            print(f"✓ 模拟挂单成功: {od.code} BUY 1 @ {low} "
                  f"order_id={od.order_id}")
            futu = b._futu  # noqa: SLF001 - smoke test only
            ret, data = b.trd.cancel_order(
                order_id=od.order_id, trd_env=b.env)
            print("✓ 撤单:", "成功" if ret == futu.RET_OK else f"失败 {data}")
        except BrokerError as e:
            print(f"✗ 模拟下单失败（若提示未解锁，设置 FUTU_TRADE_PWD 环境变量后重试）: {e}")

    b.close()
    print("\n冒烟测试完成。")


if __name__ == "__main__":
    main()
