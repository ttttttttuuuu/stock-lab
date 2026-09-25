"""Parameter-aware strategy signals + grids for hyperparameter search.

Unlike strategies.py (which reads precomputed indicator columns from
prepare()), each function here computes its own indicators from the raw
OHLCV frame using the given params. Defaults reproduce the production
strategies exactly, so the default combo of every grid is a like-for-like
baseline.

Signals follow the same convention: +1 long / -1 short / 0 flat, evaluated
at bar close with no look-ahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind


def sig_sma_cross_p(df: pd.DataFrame, fast: int = 5, slow: int = 30) -> pd.Series:
    f = ind.sma(df["close"], fast)
    s = ind.sma(df["close"], slow)
    out = pd.Series(0, index=df.index)
    out[f > s] = 1
    out[f < s] = -1
    out[s.isna()] = 0
    return out


def sig_rsi_p(df: pd.DataFrame, period: int = 7, oversold: int = 35,
              overbought: int = 65) -> pd.Series:
    r = ind.rsi(df["close"], period)
    out = pd.Series(0, index=df.index)
    out[r < oversold] = 1
    out[r > overbought] = -1
    return out


def sig_macd_p(df: pd.DataFrame, fast: int = 19, slow: int = 39,
               signal: int = 9) -> pd.Series:
    _, _, hist = ind.macd(df["close"], fast, slow, signal)
    out = pd.Series(0, index=df.index)
    bull = (hist > 0) & (hist.shift(1) > 0)
    bear = (hist < 0) & (hist.shift(1) < 0)
    out[bull.fillna(False)] = 1
    out[bear.fillna(False)] = -1
    return out


def sig_bb_p(df: pd.DataFrame, n: int = 10, k: float = 2.0) -> pd.Series:
    _, upper, lower, _ = ind.bollinger(df["close"], n, k)
    out = pd.Series(0, index=df.index)
    out[df["close"] > upper] = 1
    out[df["close"] < lower] = -1
    return out


def sig_supertrend_p(df: pd.DataFrame, period: int = 20,
                     mult: float = 3.0) -> pd.Series:
    direction, line = ind.supertrend(df, period, mult)
    out = direction.copy()
    out[line.isna()] = 0
    return out.astype(int)


def sig_ut_bot_p(df: pd.DataFrame, mult: float = 3.0,
                 atr_period: int = 14) -> pd.Series:
    stop = ind.ut_bot_stop(df, mult, atr_period)
    out = pd.Series(0, index=df.index)
    valid = stop.notna()
    out[valid & (df["close"] > stop)] = 1
    out[valid & (df["close"] < stop)] = -1
    return out


def sig_ttm_p(df: pd.DataFrame, n: int = 15, mult_kc: float = 2.0) -> pd.Series:
    mom, sqz = ind.ttm_squeeze(df, n=n, mult_kc=mult_kc)
    out = pd.Series(0, index=df.index)
    valid = mom.notna()
    out[valid & ~sqz.fillna(False) & (mom > 0)] = 1
    out[valid & ~sqz.fillna(False) & (mom < 0)] = -1
    return out


def sig_wavetrend_p(df: pd.DataFrame, ch_len: int = 14,
                    avg_len: int = 21, overbought: float = 53.0,
                    oversold: float = -53.0) -> pd.Series:
    wt1s, wt2s = ind.wavetrend(df, ch_len, avg_len)
    wt1, wt2 = wt1s.to_numpy(), wt2s.to_numpy()
    out = np.zeros(len(df), dtype=int)
    state = 0
    for i in range(1, len(df)):
        if not (np.isfinite(wt1[i]) and np.isfinite(wt2[i])
                and np.isfinite(wt1[i - 1]) and np.isfinite(wt2[i - 1])):
            out[i] = state
            continue
        cross_up = wt1[i - 1] <= wt2[i - 1] and wt1[i] > wt2[i]
        cross_dn = wt1[i - 1] >= wt2[i - 1] and wt1[i] < wt2[i]
        if cross_up and wt1[i] < oversold:
            state = 1
        elif cross_dn and wt1[i] > overbought:
            state = -1
        elif state == 1 and cross_dn:
            state = 0
        elif state == -1 and cross_up:
            state = 0
        out[i] = state
    return pd.Series(out, index=df.index)


def sig_natural_trade_p(df: pd.DataFrame, anchor: int = 40,
                        vol_mult: float = 1.5, trend_ma: int = 30) -> pd.Series:
    """自然交易理论（量化版）：fib 引力区回撤 + 量能确认 + 趋势过滤。

    Defaults reproduce the production strategy exactly.
    """
    high_n = df["high"].rolling(anchor).max().to_numpy()
    low_n = df["low"].rolling(anchor).min().to_numpy()
    trend = df["close"].rolling(trend_ma).mean().to_numpy()
    vol_ma = df["volume"].rolling(20).mean().to_numpy()
    c = df["close"].to_numpy()
    o = df["open"].to_numpy()
    lo = df["low"].to_numpy()
    hi = df["high"].to_numpy()
    vol = df["volume"].to_numpy()

    out = np.zeros(len(df), dtype=int)
    state = 0
    for i in range(len(df)):
        rng = high_n[i] - low_n[i]
        if not (np.isfinite(rng) and np.isfinite(trend[i])
                and np.isfinite(vol_ma[i]) and rng > 0):
            out[i] = state
            continue
        gz_lo, gz_hi = high_n[i] - 0.618 * rng, high_n[i] - 0.382 * rng
        sz_lo, sz_hi = low_n[i] + 0.382 * rng, low_n[i] + 0.618 * rng
        vol_ok = vol[i] >= vol_ma[i] * vol_mult
        if state == 1 and c[i] < gz_lo:
            state = 0
        elif state == -1 and c[i] > sz_hi:
            state = 0
        if state == 0 and vol_ok:
            if (c[i] > trend[i] and lo[i] <= gz_hi
                    and gz_lo <= c[i] <= gz_hi and c[i] > o[i]):
                state = 1
            elif (c[i] < trend[i] and hi[i] >= sz_lo
                    and sz_lo <= c[i] <= sz_hi and c[i] < o[i]):
                state = -1
        out[i] = state
    return pd.Series(out, index=df.index)


PARAM_SIGNALS = {
    "sma_cross": sig_sma_cross_p,
    "rsi_reversion": sig_rsi_p,
    "macd_trend": sig_macd_p,
    "bb_breakout": sig_bb_p,
    "supertrend": sig_supertrend_p,
    "ut_bot": sig_ut_bot_p,
    "ttm_squeeze": sig_ttm_p,
    "wavetrend": sig_wavetrend_p,
    "natural_trade": sig_natural_trade_p,
}

# default combo = current production parameters (baseline row in the grid),
# sourced from data/production_params.json via engine.production so weekly
# evolution promotions are picked up automatically.
from . import production as _prod  # noqa: E402

DEFAULT_PARAMS = _prod.all_strategy_params()

# explicit combo lists (handles constraints like fast < slow cleanly);
# the default combo is always included
PARAM_GRIDS = {
    "sma_cross": [
        {"fast": 5, "slow": 20}, {"fast": 5, "slow": 30},
        {"fast": 5, "slow": 50}, {"fast": 10, "slow": 20},
        {"fast": 10, "slow": 30}, {"fast": 10, "slow": 50},
        {"fast": 20, "slow": 50}, {"fast": 20, "slow": 100},
    ],
    "rsi_reversion": [
        {"period": 7, "oversold": 25, "overbought": 75},
        {"period": 7, "oversold": 30, "overbought": 70},
        {"period": 7, "oversold": 35, "overbought": 65},
        {"period": 14, "oversold": 25, "overbought": 75},
        {"period": 14, "oversold": 30, "overbought": 70},
        {"period": 14, "oversold": 35, "overbought": 65},
        {"period": 21, "oversold": 25, "overbought": 75},
        {"period": 21, "oversold": 30, "overbought": 70},
        {"period": 21, "oversold": 35, "overbought": 65},
    ],
    "macd_trend": [
        {"fast": 8, "slow": 21, "signal": 5},
        {"fast": 12, "slow": 26, "signal": 9},
        {"fast": 19, "slow": 39, "signal": 9},
        {"fast": 5, "slow": 35, "signal": 5},
    ],
    "bb_breakout": [
        {"n": 10, "k": 1.5}, {"n": 10, "k": 2.0}, {"n": 10, "k": 2.5},
        {"n": 20, "k": 1.5}, {"n": 20, "k": 2.0}, {"n": 20, "k": 2.5},
        {"n": 30, "k": 1.5}, {"n": 30, "k": 2.0}, {"n": 30, "k": 2.5},
    ],
    "supertrend": [
        {"period": 7, "mult": 2.0}, {"period": 7, "mult": 3.0},
        {"period": 7, "mult": 4.0}, {"period": 10, "mult": 2.0},
        {"period": 10, "mult": 3.0}, {"period": 10, "mult": 4.0},
        {"period": 14, "mult": 2.0}, {"period": 14, "mult": 3.0},
        {"period": 14, "mult": 4.0}, {"period": 20, "mult": 2.0},
        {"period": 20, "mult": 3.0}, {"period": 20, "mult": 4.0},
    ],
    "ut_bot": [
        {"mult": 1.0, "atr_period": 5}, {"mult": 1.0, "atr_period": 10},
        {"mult": 1.0, "atr_period": 14}, {"mult": 2.0, "atr_period": 5},
        {"mult": 2.0, "atr_period": 10}, {"mult": 2.0, "atr_period": 14},
        {"mult": 3.0, "atr_period": 5}, {"mult": 3.0, "atr_period": 10},
        {"mult": 3.0, "atr_period": 14},
    ],
    "ttm_squeeze": [
        {"n": 15, "mult_kc": 1.0}, {"n": 15, "mult_kc": 1.5},
        {"n": 15, "mult_kc": 2.0}, {"n": 20, "mult_kc": 1.0},
        {"n": 20, "mult_kc": 1.5}, {"n": 20, "mult_kc": 2.0},
        {"n": 25, "mult_kc": 1.0}, {"n": 25, "mult_kc": 1.5},
        {"n": 25, "mult_kc": 2.0},
    ],
    "wavetrend": [
        {"ch_len": 7, "avg_len": 14}, {"ch_len": 7, "avg_len": 21},
        {"ch_len": 7, "avg_len": 28}, {"ch_len": 10, "avg_len": 14},
        {"ch_len": 10, "avg_len": 21}, {"ch_len": 10, "avg_len": 28},
        {"ch_len": 14, "avg_len": 14}, {"ch_len": 14, "avg_len": 21},
        {"ch_len": 14, "avg_len": 28},
    ],
    "natural_trade": [
        {"anchor": 30, "vol_mult": 1.2, "trend_ma": 20},
        {"anchor": 30, "vol_mult": 1.2, "trend_ma": 30},
        {"anchor": 30, "vol_mult": 1.5, "trend_ma": 20},
        {"anchor": 30, "vol_mult": 1.5, "trend_ma": 30},
        {"anchor": 40, "vol_mult": 1.2, "trend_ma": 20},
        {"anchor": 40, "vol_mult": 1.2, "trend_ma": 30},
        {"anchor": 40, "vol_mult": 1.5, "trend_ma": 20},
        {"anchor": 40, "vol_mult": 1.5, "trend_ma": 30},
        {"anchor": 60, "vol_mult": 1.2, "trend_ma": 20},
        {"anchor": 60, "vol_mult": 1.2, "trend_ma": 30},
        {"anchor": 60, "vol_mult": 1.5, "trend_ma": 20},
        {"anchor": 60, "vol_mult": 1.5, "trend_ma": 30},
    ],
}

# sanity: every default must be present in its grid
for _name, _default in DEFAULT_PARAMS.items():
    assert _default in PARAM_GRIDS[_name], f"default missing from grid: {_name}"
