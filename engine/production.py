"""Production strategy parameters — single source of truth.

Values live in data/production_params.json so the weekly evolution job can
promote better combos without code changes. Code defaults below are the
fallback when the file is missing (and document the lineage).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROD_FILE = ROOT / "data" / "production_params.json"

# fallback = current production values (promoted 2026-09-21/22 grid searches)
DEFAULT_STRATEGY_PARAMS = {
    "sma_cross": {"fast": 5, "slow": 30},
    "rsi_reversion": {"period": 7, "oversold": 35, "overbought": 65},
    "macd_trend": {"fast": 19, "slow": 39, "signal": 9},
    "bb_breakout": {"n": 10, "k": 2.0},
    "supertrend": {"period": 20, "mult": 3.0},
    "ut_bot": {"mult": 3.0, "atr_period": 14},
    "ttm_squeeze": {"n": 15, "mult_kc": 2.0},
    "wavetrend": {"ch_len": 14, "avg_len": 21},
    "natural_trade": {"anchor": 40, "vol_mult": 1.5, "trend_ma": 30},
}

DEFAULT_STRATEGY_EXITS = {          # strategy -> (take_profit, stop_loss)
    "ut_bot": (0.15, -0.07),
    "ttm_squeeze": (0.15, -0.07),
    "supertrend": (0.08, -0.04),
    "natural_trade": (0.08, -0.04),
    "bb_breakout": (0.08, -0.04),
    "macd_trend": (0.06, -0.03),
    "rsi_reversion": (0.05, -0.05),
}

GLOBAL_DEFAULT_EXIT = (0.10, -0.05)


def _load() -> dict:
    try:
        return json.loads(PROD_FILE.read_text())
    except Exception:  # noqa: BLE001 - missing/corrupt file -> code defaults
        return {}


def all_strategy_params() -> dict:
    """param_strategies-style param dicts for every optimizable strategy."""
    stored = _load().get("strategy_params", {})
    out = {}
    for name, default in DEFAULT_STRATEGY_PARAMS.items():
        merged = dict(default)
        merged.update(stored.get(name, {}))
        out[name] = merged
    return out


def strategy_params(name: str) -> dict:
    return all_strategy_params()[name]


def strategy_exit(name: str) -> tuple[float, float]:
    """(take_profit, stop_loss): per-strategy override or global default."""
    stored = _load().get("strategy_exits", {})
    if name in stored:
        tp, sl = stored[name]
        return (float(tp), float(sl))
    return DEFAULT_STRATEGY_EXITS.get(name, GLOBAL_DEFAULT_EXIT)


def all_strategy_exits() -> dict:
    stored = _load().get("strategy_exits", {})
    out = {k: tuple(v) for k, v in DEFAULT_STRATEGY_EXITS.items()}
    for k, v in stored.items():
        out[k] = (float(v[0]), float(v[1]))
    return out


def watchlist() -> list[str]:
    """Strategies on probation: excluded from Top-pair selection and the
    live paper book, but still computed/shown in the full ranking."""
    return list(_load().get("watchlist", []))


def save(strategy_params: dict, strategy_exits: dict, updated_at: str,
         note: str = "", watchlist: list | None = None):
    """Persist a new production parameter set (full document).

    `watchlist=None` preserves the existing list so weekly evolution
    promotions never silently clear a probation."""
    doc = {
        "updated_at": updated_at,
        "note": note,
        "strategy_params": strategy_params,
        "strategy_exits": {k: [float(v[0]), float(v[1])]
                           for k, v in strategy_exits.items()},
        "watchlist": _load().get("watchlist", []) if watchlist is None
                     else list(watchlist),
    }
    PROD_FILE.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
