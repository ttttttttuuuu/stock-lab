"""Export the Futu SIMULATE account snapshot to web/public/data/futu_sim.json.

Only works on the machine running OpenD (127.0.0.1:11111) — i.e. the owner's
Mac, never the cloud. On any failure writes {available: false, error} so the
frontend can render an offline state instead of nothing.

Usage: python -m engine.futu_export
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "data" / "futu_sim.json"
MIRROR_FILE = ROOT / "data" / "futu_mirror.json"

ORDER_COLS = ["order_id", "code", "stock_name", "trd_side", "order_type",
              "qty", "price", "order_status", "dealt_qty", "dealt_avg_price",
              "create_time", "updated_time"]


def main():
    now = datetime.now(timezone.utc).isoformat()
    mirror = []
    if MIRROR_FILE.exists():
        mirror = json.loads(MIRROR_FILE.read_text()).get("orders", [])

    payload = {"available": False, "updated_at": now, "mirror": mirror}
    try:
        import futu
        from .broker_futu import FutuBroker

        b = FutuBroker(simulate=True)
        try:
            acct = b.account()
            positions = b.positions()
            ret, orders = b.trd.order_list_query(acc_id=b.acc_id,
                                                 trd_env=b.env)
            order_list = []
            if ret == futu.RET_OK:
                for _, r in orders.iterrows():
                    order_list.append({
                        c: (str(r[c]) if c in ("order_id", "code",
                                               "stock_name", "trd_side",
                                               "order_type", "order_status",
                                               "create_time", "updated_time")
                            else float(r[c]) if r[c] == r[c] else None)
                        for c in ORDER_COLS if c in orders.columns
                    })
            payload.update(available=True, acc_id=b.acc_id, account=acct,
                           positions=positions, orders=order_list)
        finally:
            b.close()
        print(f"[futu-export] 账户 {payload['acc_id']} "
              f"总资产 {acct.get('total_assets')} 持仓 {len(positions)} "
              f"订单 {len(order_list)}")
    except Exception as e:  # noqa: BLE001 - OpenD 离线等情况都要落盘
        payload["error"] = str(e)[:300]
        print(f"[futu-export] OpenD 不可用: {e}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
