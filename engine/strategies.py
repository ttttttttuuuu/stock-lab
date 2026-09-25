"""Trading strategies.

Each strategy maps a DataFrame (with indicators precomputed) to a signal
Series: +1 = bullish (buy weekly CALL), -1 = bearish (buy weekly PUT),
0 = flat. Signals are evaluated at close of day t and acted on at the
close of day t (same-bar fill approximation).

The ensemble combines all base strategies by majority vote.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind


# Production parameters come from data/production_params.json (via
# engine.production) so the weekly evolution job can promote better combos
# without code changes. Promoted 2026-09-21 from the param-opt grid search.
from . import production as _prod

_p = _prod.all_strategy_params()
PARAMS = {
    "sma_fast": _p["sma_cross"]["fast"], "sma_slow": _p["sma_cross"]["slow"],
    "rsi_period": _p["rsi_reversion"]["period"],
    "rsi_oversold": _p["rsi_reversion"]["oversold"],
    "rsi_overbought": _p["rsi_reversion"]["overbought"],
    "macd_fast": _p["macd_trend"]["fast"], "macd_slow": _p["macd_trend"]["slow"],
    "macd_signal": _p["macd_trend"]["signal"],
    "bb_n": _p["bb_breakout"]["n"], "bb_k": _p["bb_breakout"]["k"],
    "st_period": _p["supertrend"]["period"], "st_mult": _p["supertrend"]["mult"],
    "ut_mult": _p["ut_bot"]["mult"], "ut_atr_period": _p["ut_bot"]["atr_period"],
    "ttm_n": _p["ttm_squeeze"]["n"], "ttm_mult_kc": _p["ttm_squeeze"]["mult_kc"],
    "wt_ch_len": _p["wavetrend"]["ch_len"], "wt_avg_len": _p["wavetrend"]["avg_len"],
    "wt_ob": _p["wavetrend"].get("overbought", 53.0),
    "wt_os": _p["wavetrend"].get("oversold", -53.0),
    "nt_anchor": _p["natural_trade"]["anchor"],
    "nt_vol_mult": _p["natural_trade"]["vol_mult"],
    "nt_trend_ma": _p["natural_trade"]["trend_ma"],
}


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Add all indicator columns once."""
    out = df.copy()
    close = out["close"]
    out["sma_fast"] = ind.sma(close, PARAMS["sma_fast"])
    out["sma_slow"] = ind.sma(close, PARAMS["sma_slow"])
    out["rsi"] = ind.rsi(close, PARAMS["rsi_period"])
    macd_line, signal_line, hist = ind.macd(
        close, PARAMS["macd_fast"], PARAMS["macd_slow"], PARAMS["macd_signal"])
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist
    mid, upper, lower, pct_b = ind.bollinger(close, PARAMS["bb_n"], PARAMS["bb_k"])
    out["bb_mid"] = mid
    out["bb_upper"] = upper
    out["bb_lower"] = lower
    out["bb_pctb"] = pct_b
    out["hv20"] = ind.historical_volatility(close, 20)
    # TradingView community favorites (stock-lab strategies)
    out["st_dir"], out["st_line"] = ind.supertrend(
        out, PARAMS["st_period"], PARAMS["st_mult"])
    out["ut_stop"] = ind.ut_bot_stop(out, PARAMS["ut_mult"], PARAMS["ut_atr_period"])
    out["ttm_mom"], out["ttm_sqz"] = ind.ttm_squeeze(
        out, n=PARAMS["ttm_n"], mult_kc=PARAMS["ttm_mult_kc"])
    out["wt1"], out["wt2"] = ind.wavetrend(
        out, PARAMS["wt_ch_len"], PARAMS["wt_avg_len"])
    return out


def sig_sma_cross(df: pd.DataFrame) -> pd.Series:
    """Trend following: fast/slow SMA cross. In position while fast > slow."""
    s = pd.Series(0, index=df.index)
    s[df["sma_fast"] > df["sma_slow"]] = 1
    s[df["sma_fast"] < df["sma_slow"]] = -1
    s[df["sma_slow"].isna()] = 0
    return s


def sig_rsi_reversion(df: pd.DataFrame) -> pd.Series:
    """Mean reversion: RSI below oversold expect bounce (call),
    above overbought expect fade (put)."""
    s = pd.Series(0, index=df.index)
    s[df["rsi"] < PARAMS["rsi_oversold"]] = 1
    s[df["rsi"] > PARAMS["rsi_overbought"]] = -1
    return s


def sig_macd(df: pd.DataFrame) -> pd.Series:
    """MACD histogram sign with confirmation (hist same sign 2 days)."""
    h = df["macd_hist"]
    s = pd.Series(0, index=df.index)
    bull = (h > 0) & (h.shift(1) > 0)
    bear = (h < 0) & (h.shift(1) < 0)
    s[bull.fillna(False)] = 1
    s[bear.fillna(False)] = -1
    return s


def sig_bollinger_breakout(df: pd.DataFrame) -> pd.Series:
    """Volatility breakout: close above upper band -> momentum call,
    close below lower band -> momentum put. Back inside bands -> flat."""
    s = pd.Series(0, index=df.index)
    s[df["close"] > df["bb_upper"]] = 1
    s[df["close"] < df["bb_lower"]] = -1
    return s


BASE_STRATEGIES = {
    "sma_cross": sig_sma_cross,
    "rsi_reversion": sig_rsi_reversion,
    "macd_trend": sig_macd,
    "bb_breakout": sig_bollinger_breakout,
}


def sig_ensemble(df: pd.DataFrame) -> pd.Series:
    """Majority vote of base strategies; ties (0 net) stay flat."""
    votes = pd.DataFrame({name: fn(df) for name, fn in BASE_STRATEGIES.items()})
    total = votes.sum(axis=1)
    s = pd.Series(0, index=df.index)
    s[total >= 2] = 1
    s[total <= -2] = -1
    return s


# Weights derived from 2y/50-symbol backtest profit factors (pf - 1):
# rsi 1.45, sma 1.32, bb 1.27, macd 1.23. RSI carries the most weight.
# NOTE: fitted on the same backtest window -> its backtest is in-sample;
# paper trading is the honest out-of-sample test.
ENSEMBLE_WEIGHTS = {
    "sma_cross": 0.32,
    "rsi_reversion": 0.45,
    "macd_trend": 0.23,
    "bb_breakout": 0.27,
}
ENSEMBLE_THRESHOLD = sum(ENSEMBLE_WEIGHTS.values()) / 2  # 0.635


def sig_ensemble_weighted(df: pd.DataFrame) -> pd.Series:
    """Weighted vote: score = sum(weight * signal); act when |score| >=
    half the total weight (i.e. a weighted majority agrees)."""
    score = pd.Series(0.0, index=df.index)
    for name, w in ENSEMBLE_WEIGHTS.items():
        score = score + BASE_STRATEGIES[name](df) * w
    s = pd.Series(0, index=df.index)
    s[score >= ENSEMBLE_THRESHOLD] = 1
    s[score <= -ENSEMBLE_THRESHOLD] = -1
    return s


ALL_STRATEGIES = {**BASE_STRATEGIES, "ensemble": sig_ensemble,
                  "ensemble_weighted": sig_ensemble_weighted}


# ---------------- TradingView community strategies (stock lab first) ----------------
# These join the stock-lab matrix only. Once a strategy proves itself on
# live stock paper trades it can be promoted into the options book.

def sig_supertrend(df: pd.DataFrame) -> pd.Series:
    """SuperTrend: in-market long while uptrend, short while downtrend."""
    s = df["st_dir"].copy()
    s[df["st_line"].isna()] = 0
    return s.astype(int)


def sig_ut_bot(df: pd.DataFrame) -> pd.Series:
    """UT Bot (ATR trailing stop): long above the stop, short below."""
    s = pd.Series(0, index=df.index)
    valid = df["ut_stop"].notna()
    s[valid & (df["close"] > df["ut_stop"])] = 1
    s[valid & (df["close"] < df["ut_stop"])] = -1
    return s


def sig_ttm_squeeze(df: pd.DataFrame) -> pd.Series:
    """Squeeze Momentum (LazyBear): ride the momentum sign; flat while the
    squeeze is still on (compressed volatility = no edge)."""
    s = pd.Series(0, index=df.index)
    valid = df["ttm_mom"].notna()
    s[valid & ~df["ttm_sqz"].fillna(False) & (df["ttm_mom"] > 0)] = 1
    s[valid & ~df["ttm_sqz"].fillna(False) & (df["ttm_mom"] < 0)] = -1
    return s


def sig_wavetrend(df: pd.DataFrame) -> pd.Series:
    """WaveTrend: long after a bullish wt1/wt2 cross in oversold,
    short after a bearish cross in overbought; hold until reverse."""
    ob, os_ = PARAMS["wt_ob"], PARAMS["wt_os"]
    wt1, wt2 = df["wt1"].to_numpy(), df["wt2"].to_numpy()
    out = np.zeros(len(df), dtype=int)
    state = 0
    for i in range(1, len(df)):
        if not (np.isfinite(wt1[i]) and np.isfinite(wt2[i])
                and np.isfinite(wt1[i - 1]) and np.isfinite(wt2[i - 1])):
            out[i] = state
            continue
        cross_up = wt1[i - 1] <= wt2[i - 1] and wt1[i] > wt2[i]
        cross_dn = wt1[i - 1] >= wt2[i - 1] and wt1[i] < wt2[i]
        if cross_up and wt1[i] < os_:
            state = 1
        elif cross_dn and wt1[i] > ob:
            state = -1
        elif state == 1 and cross_dn:
            state = 0
        elif state == -1 and cross_up:
            state = 0
        out[i] = state
    return pd.Series(out, index=df.index)


def sig_natural_trade(df: pd.DataFrame) -> pd.Series:
    """自然交易理论（龚有柴）量化版 —— fib 空间 + 量能 + fib 时间：

    fib 空间：锚定波段（anchor 根 K 的最高/最低）的 0.382–0.618 回撤区
        是"引力区"，回踩引力区后大概率延续原趋势；
    量能：入场 K 线成交量 >= vol_mult × 20 均量（能量确认）；
    fib 时间：锚定窗口长度即时间要素；
    趋势过滤：收盘价在趋势均线上方才做多，下方才做空。

    多头：上升趋势 + 盘中回踩引力区 + 收阳线 + 放量 → 入场；
        收盘跌破 0.618 位（引力失效）→ 离场。
    空头：镜像。
    """
    anchor = int(PARAMS["nt_anchor"])
    vol_mult = float(PARAMS["nt_vol_mult"])
    ma_n = int(PARAMS["nt_trend_ma"])

    high_n = df["high"].rolling(anchor).max().to_numpy()
    low_n = df["low"].rolling(anchor).min().to_numpy()
    trend = df["close"].rolling(ma_n).mean().to_numpy()
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
        # gravity zones
        gz_lo, gz_hi = high_n[i] - 0.618 * rng, high_n[i] - 0.382 * rng
        sz_lo, sz_hi = low_n[i] + 0.382 * rng, low_n[i] + 0.618 * rng
        vol_ok = vol[i] >= vol_ma[i] * vol_mult

        if state == 1 and c[i] < gz_lo:      # 0.618 引力失效
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


TV_STRATEGIES = {
    "supertrend": sig_supertrend,
    "ut_bot": sig_ut_bot,
    "ttm_squeeze": sig_ttm_squeeze,
    "wavetrend": sig_wavetrend,
    "natural_trade": sig_natural_trade,
}

# stock-lab universe = original 6 + TradingView candidates
STOCK_STRATEGIES = {**ALL_STRATEGIES, **TV_STRATEGIES}
