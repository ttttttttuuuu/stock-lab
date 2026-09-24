"""Export SQLite results to static JSON consumed by the Next.js frontend.

Usage: python -m engine.export_web
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from . import storage

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "data"
OUT.mkdir(parents=True, exist_ok=True)


def rows_to_dicts(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def main():
    conn = storage.get_conn()

    # ---- production params (incl. watchlist) — read by the frontend to
    # mark/filter probation strategies in both Supabase and local mode ----
    prod_file = ROOT / "data" / "production_params.json"
    if prod_file.exists():
        (OUT / "production_params.json").write_text(prod_file.read_text())

    # ---- all trades ----
    trades = rows_to_dicts(conn, "SELECT * FROM trades ORDER BY entry_date")
    (OUT / "trades.json").write_text(json.dumps(trades))

    # ---- per strategy-symbol metrics (latest run) ----
    runs = rows_to_dicts(conn, """
        SELECT r.* FROM backtest_runs r
        JOIN (SELECT MAX(run_at) m FROM backtest_runs) t ON r.run_at = t.m
    """)
    for r in runs:
        r["metrics"] = json.loads(r["metrics"])
    (OUT / "runs.json").write_text(json.dumps(runs))

    # ---- strategy leaderboard (aggregate across symbols) ----
    bt = [t for t in trades if t["source"] == "backtest"]
    by_strat = defaultdict(list)
    for t in bt:
        by_strat[t["strategy"]].append(t)
    leaderboard = []
    for strat, ts in by_strat.items():
        pnl = pd.Series([t["pnl"] for t in ts])
        wins = pnl[pnl > 0]
        leaderboard.append({
            "strategy": strat,
            "trades": len(ts),
            "win_rate": round(len(wins) / len(ts) * 100, 1),
            "total_pnl": round(float(pnl.sum()), 2),
            "avg_pnl": round(float(pnl.mean()), 2),
            "profit_factor": round(float(wins.sum() / -pnl[pnl <= 0].sum()), 2)
                             if (pnl <= 0).any() and pnl[pnl <= 0].sum() != 0 else None,
        })
    leaderboard.sort(key=lambda x: x["total_pnl"], reverse=True)

    # ---- equity curves per strategy (cumulative pnl by exit date) ----
    curves = {}
    for strat, ts in by_strat.items():
        daily = defaultdict(float)
        for t in ts:
            daily[t["exit_date"]] += t["pnl"]
        cum, pts = 0.0, []
        for d in sorted(daily):
            cum += daily[d]
            pts.append({"date": d, "pnl": round(cum, 2)})
        curves[strat] = pts

    # ---- heatmap: symbol x strategy total pnl ----
    heat = defaultdict(dict)
    for t in bt:
        heat[t["symbol"]][t["strategy"]] = round(
            heat[t["symbol"]].get(t["strategy"], 0) + t["pnl"], 2)

    # ---- latest signals ----
    signals = rows_to_dicts(conn, """
        SELECT s.* FROM signals s
        JOIN (SELECT symbol, strategy, MAX(created_at) m FROM signals GROUP BY symbol, strategy) t
          ON s.symbol=t.symbol AND s.strategy=t.strategy AND s.created_at=t.m
    """)
    for s in signals:
        s["details"] = json.loads(s["details"]) if s.get("details") else {}

    # ---- paper positions ----
    state_file = ROOT / "data" / "paper_positions.json"
    paper = json.loads(state_file.read_text()) if state_file.exists() else {"positions": []}
    paper_trades = [t for t in trades if t["source"] == "paper"]

    # ---- paper account summary ----
    positions = paper["positions"]
    cost = sum(p["entry_price"] * 100 * p["qty"] for p in positions)
    value = sum(p.get("last_mark", p["entry_price"]) * 100 * p["qty"]
                for p in positions)
    realized = round(sum(t["pnl"] for t in paper_trades), 2)
    unrealized = round(value - cost, 2)

    # equity curve: prefer daily snapshots (full history), fall back to
    # realized exits + current unrealized
    snaps = rows_to_dicts(conn,
                          "SELECT * FROM equity_snapshots ORDER BY date")
    entries = [p["entry_date"] for p in positions] + [t["entry_date"] for t in paper_trades]
    if snaps:
        equity = [{"date": s["date"], "pnl": s["total"]} for s in snaps]
        if entries and equity and equity[0]["date"] > min(entries):
            equity.insert(0, {"date": min(entries), "pnl": 0.0})
        if positions and equity:
            equity[-1]["unrealized"] = True
    else:
        daily = defaultdict(float)
        for t in paper_trades:
            daily[t["exit_date"]] += t["pnl"]
        cum, equity = 0.0, []
        for d in sorted(daily):
            cum += daily[d]
            equity.append({"date": d, "pnl": round(cum, 2)})
        if entries:
            first = min(entries)
            if not equity or equity[0]["date"] > first:
                equity.insert(0, {"date": first, "pnl": 0.0})
        if positions:
            mark_day = (positions[0].get("marked_at") or "")[:10]
            if mark_day:
                equity.append({"date": mark_day, "pnl": round(cum + unrealized, 2),
                               "unrealized": True})
    paper_account = {
        "positions": positions,
        "cost": round(cost, 2),
        "value": round(value, 2),
        "unrealized": unrealized,
        "realized": realized,
        "equity": equity,
        "marked_at": positions[0].get("marked_at") if positions else None,
    }

    overview = {
        "leaderboard": leaderboard,
        "curves": curves,
        "heatmap": heat,
        "paper_account": paper_account,
        # closed paper trades (source=paper rows are only written on close);
        # lets the dashboard compute deviation alerts without the big payload
        "paper_trades": paper_trades,
        "totals": {
            "backtest_trades": len(bt),
            "paper_trades": len(paper_trades),
            "symbols": sorted({t["symbol"] for t in bt}),
            "strategies": sorted(by_strat.keys()),
            "total_pnl": round(sum(t["pnl"] for t in bt), 2),
        },
    }
    (OUT / "overview.json").write_text(json.dumps(overview))
    (OUT / "signals.json").write_text(json.dumps({
        "signals": signals, "paper_positions": paper["positions"],
        "paper_trades": paper_trades,
    }))

    # ---- stock lab: strategy x symbol stock-price backtest ----
    n_pairs = 0
    try:
        stock_runs = rows_to_dicts(conn, """
            SELECT r.* FROM stock_runs r
            JOIN (SELECT MAX(run_at) m FROM stock_runs) t ON r.run_at = t.m
        """)
        pairs = []
        for r in stock_runs:
            m = json.loads(r["metrics"])
            pairs.append({"symbol": r["symbol"], "strategy": r["strategy"], **m})
        pairs.sort(key=lambda x: x.get("total_pnl", 0), reverse=True)
        (OUT / "stock_lab.json").write_text(json.dumps({
            "run_at": stock_runs[0]["run_at"] if stock_runs else None,
            "pairs": pairs,
        }))
        n_pairs = len(pairs)

        # per-pair trade lists for detail pages
        sdir = OUT / "stock_trades"
        sdir.mkdir(exist_ok=True)
        for f in sdir.glob("*.json"):
            f.unlink()
        for r in stock_runs:
            ts = rows_to_dicts(conn, """
                SELECT symbol, strategy, side, entry_date, entry_price, shares,
                       exit_date, exit_price, exit_reason, pnl, pnl_pct, hold_days
                FROM stock_trades WHERE run_id=? ORDER BY entry_date
            """, (r["id"],))
            (sdir / f"{r['strategy']}__{r['symbol']}.json").write_text(
                json.dumps(ts))

        # per-symbol daily OHLCV for candlestick charts
        pdir = OUT / "prices"
        pdir.mkdir(exist_ok=True)
        for f in pdir.glob("*.json"):
            f.unlink()
        syms = [row[0] for row in
                conn.execute("SELECT DISTINCT symbol FROM prices")]
        for sym in syms:
            rows = rows_to_dicts(conn, """
                SELECT date, open, high, low, close, volume FROM prices
                WHERE symbol=? ORDER BY date
            """, (sym,))
            (pdir / f"{sym}.json").write_text(json.dumps(rows))

        # stock paper verification book (top pairs, live)
        sp_positions = rows_to_dicts(conn, "SELECT * FROM stock_paper_positions")
        for p in sp_positions:
            p["data"] = json.loads(p["data"]) if isinstance(p.get("data"), str) else p.get("data")
        sp_trades = rows_to_dicts(conn,
            "SELECT * FROM stock_paper_trades ORDER BY entry_date")
        (OUT / "stock_paper.json").write_text(json.dumps({
            "positions": [p["data"] for p in sp_positions],
            "closed_trades": sp_trades,
        }))
    except Exception as e:  # noqa: BLE001 - tables may not exist on old DBs
        print(f"stock lab export skipped: {e}")

    # ---- parameter optimization grid results ----
    n_param = 0
    try:
        param_rows = rows_to_dicts(conn, """
            SELECT r.* FROM param_runs r
            JOIN (SELECT MAX(run_at) m FROM param_runs) t ON r.run_at = t.m
        """)
        if param_rows:
            for r in param_rows:
                r["params"] = json.loads(r["params"])
                r["metrics"] = json.loads(r["metrics"])

            # strategy-level: aggregate each param combo across symbols
            by_combo = defaultdict(list)
            for r in param_rows:
                key = (r["strategy"], json.dumps(r["params"], sort_keys=True))
                by_combo[key].append(r)
            strat_grid = defaultdict(list)
            for (strat, pjson), rows in by_combo.items():
                trades_n = sum(r["metrics"].get("trades", 0) for r in rows)
                wins_n = sum(r["metrics"].get("wins", 0) for r in rows)
                gross_win = sum(r["metrics"].get("avg_win", 0)
                                * r["metrics"].get("wins", 0) for r in rows)
                gross_loss = sum(-r["metrics"].get("avg_loss", 0)
                                 * (r["metrics"].get("trades", 0)
                                    - r["metrics"].get("wins", 0)) for r in rows)
                total_pnl = round(sum(r["metrics"].get("total_pnl", 0)
                                      for r in rows), 2)
                strat_grid[strat].append({
                    "params": json.loads(pjson),
                    "is_default": bool(rows[0]["is_default"]),
                    "symbols": len(rows),
                    "trades": trades_n,
                    "win_rate": round(wins_n / trades_n * 100, 1) if trades_n else 0,
                    "total_pnl": total_pnl,
                    "avg_pnl": round(total_pnl / trades_n, 2) if trades_n else 0,
                    "profit_factor": round(gross_win / gross_loss, 2)
                                     if gross_loss > 0 else None,
                })
            for strat in strat_grid:
                strat_grid[strat].sort(key=lambda x: x["total_pnl"],
                                       reverse=True)

            # pair-level: default vs best per (symbol, strategy)
            by_pair = defaultdict(list)
            for r in param_rows:
                by_pair[(r["symbol"], r["strategy"])].append(r)
            pairs_opt = []
            for (sym, strat), rows in by_pair.items():
                rows_sorted = sorted(
                    rows, key=lambda r: r["metrics"].get("total_pnl", 0),
                    reverse=True)
                best = rows_sorted[0]
                dflt = next((r for r in rows if r["is_default"]), None)
                if not dflt:
                    continue
                d_pnl = dflt["metrics"].get("total_pnl", 0)
                b_pnl = best["metrics"].get("total_pnl", 0)
                pairs_opt.append({
                    "symbol": sym,
                    "strategy": strat,
                    "default_params": dflt["params"],
                    "default_pnl": d_pnl,
                    "default_win_rate": dflt["metrics"].get("win_rate", 0),
                    "default_trades": dflt["metrics"].get("trades", 0),
                    "best_params": best["params"],
                    "best_pnl": b_pnl,
                    "best_win_rate": best["metrics"].get("win_rate", 0),
                    "best_trades": best["metrics"].get("trades", 0),
                    "delta": round(b_pnl - d_pnl, 2),
                })
            pairs_opt.sort(key=lambda x: x["delta"], reverse=True)

            (OUT / "param_opt.json").write_text(json.dumps({
                "run_at": param_rows[0]["run_at"],
                "strategies": strat_grid,
                "pairs": pairs_opt,
            }))
            n_param = len(param_rows)
    except Exception as e:  # noqa: BLE001 - table may not exist on old DBs
        print(f"param opt export skipped: {e}")

    # ---- exit-structure grid results ----
    n_exit = 0
    try:
        exit_rows = rows_to_dicts(conn, """
            SELECT r.* FROM exit_runs r
            JOIN (SELECT MAX(run_at) m FROM exit_runs) t ON r.run_at = t.m
        """)
        if exit_rows:
            for r in exit_rows:
                r["metrics"] = json.loads(r["metrics"])

            def agg_exit(rows):
                trades_n = sum(r["metrics"].get("trades", 0) for r in rows)
                wins_n = sum(r["metrics"].get("wins", 0) for r in rows)
                gross_win = sum(r["metrics"].get("avg_win", 0)
                                * r["metrics"].get("wins", 0) for r in rows)
                gross_loss = sum(-r["metrics"].get("avg_loss", 0)
                                 * (r["metrics"].get("trades", 0)
                                    - r["metrics"].get("wins", 0)) for r in rows)
                total_pnl = round(sum(r["metrics"].get("total_pnl", 0)
                                      for r in rows), 2)
                first = rows[0]
                return {
                    "take_profit": first["take_profit"],
                    "stop_loss": first["stop_loss"],
                    "is_default": bool(first["is_default"]),
                    "trades": trades_n,
                    "win_rate": round(wins_n / trades_n * 100, 1) if trades_n else 0,
                    "total_pnl": total_pnl,
                    "avg_pnl": round(total_pnl / trades_n, 2) if trades_n else 0,
                    "profit_factor": round(gross_win / gross_loss, 2)
                                     if gross_loss > 0 else None,
                }

            by_exit = defaultdict(list)
            for r in exit_rows:
                by_exit[(r["take_profit"], r["stop_loss"])].append(r)
            global_exit = [agg_exit(rows) for rows in by_exit.values()]
            # production exits differ per strategy — the highlight is only
            # meaningful in the per-strategy view, not the global aggregate
            for g in global_exit:
                g["is_default"] = False
            global_exit.sort(key=lambda x: x["total_pnl"], reverse=True)

            by_strat_exit = defaultdict(lambda: defaultdict(list))
            for r in exit_rows:
                by_strat_exit[r["strategy"]][(r["take_profit"],
                                              r["stop_loss"])].append(r)
            strat_exit = {}
            for strat, exits in by_strat_exit.items():
                strat_exit[strat] = [agg_exit(rows) for rows in exits.values()]
                strat_exit[strat].sort(key=lambda x: x["total_pnl"],
                                       reverse=True)

            (OUT / "exit_opt.json").write_text(json.dumps({
                "run_at": exit_rows[0]["run_at"],
                "global": global_exit,
                "strategies": strat_exit,
            }))
            n_exit = len(exit_rows)
    except Exception as e:  # noqa: BLE001 - table may not exist on old DBs
        print(f"exit opt export skipped: {e}")

    print(f"exported: {len(trades)} trades, {len(runs)} runs, "
          f"{len(signals)} signals, {n_pairs} stock pairs, "
          f"{n_param} param runs, {n_exit} exit runs -> {OUT}")


if __name__ == "__main__":
    main()
