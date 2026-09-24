"""Technical indicators used by the strategies (classic trader toolset)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    std = close.rolling(n).std()
    upper = mid + k * std
    lower = mid - k * std
    pct_b = (close - lower) / (upper - lower)
    return mid, upper, lower, pct_b


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def historical_volatility(close: pd.Series, n: int = 20) -> pd.Series:
    """Annualized historical volatility from log returns."""
    ret = np.log(close / close.shift())
    return ret.rolling(n).std() * np.sqrt(252)


# ---------------- TradingView community favorites ----------------

def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0):
    """SuperTrend (KivancOzbilgic). Returns (direction, st_line).
    direction: +1 uptrend / -1 downtrend. No repainting (bar-close logic)."""
    hl2 = (df["high"] + df["low"]) / 2
    a = atr(df, period)
    upper = (hl2 + mult * a).to_numpy(dtype=float, copy=True)
    lower = (hl2 - mult * a).to_numpy(dtype=float, copy=True)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)
    direction = np.ones(n, dtype=int)
    st = np.full(n, np.nan)

    for i in range(1, n):
        if not (np.isfinite(upper[i]) and np.isfinite(lower[i])):
            upper[i], lower[i] = upper[i - 1], lower[i - 1]
            direction[i] = direction[i - 1]
            st[i] = st[i - 1]
            continue
        # bands ratchet: upper only tightens in an uptrend of volatility, etc.
        if not (upper[i] < upper[i - 1] or close[i - 1] > upper[i - 1]):
            upper[i] = upper[i - 1]
        if not (lower[i] > lower[i - 1] or close[i - 1] < lower[i - 1]):
            lower[i] = lower[i - 1]
        if close[i] > upper[i - 1]:
            direction[i] = 1
        elif close[i] < lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        st[i] = lower[i] if direction[i] == 1 else upper[i]
    return (pd.Series(direction, index=df.index),
            pd.Series(st, index=df.index))


def ut_bot_stop(df: pd.DataFrame, mult: float = 2.0, atr_period: int = 10):
    """UT Bot Alerts (QuantNomad) ATR trailing stop. Returns the stop line;
    price above it = bullish, below = bearish."""
    src = df["close"].to_numpy(dtype=float)
    nloss = (mult * atr(df, atr_period)).to_numpy(dtype=float, copy=True)
    n = len(df)
    stop = np.full(n, np.nan)
    stop[0] = src[0]
    for i in range(1, n):
        prev = stop[i - 1]
        if not np.isfinite(nloss[i]):
            stop[i] = prev
        elif src[i] > prev and src[i - 1] > prev:
            stop[i] = max(prev, src[i] - nloss[i])
        elif src[i] < prev and src[i - 1] < prev:
            stop[i] = min(prev, src[i] + nloss[i])
        else:
            stop[i] = src[i] - nloss[i] if src[i] > prev else src[i] + nloss[i]
    return pd.Series(stop, index=df.index)


def _linreg_last(s: pd.Series, n: int) -> pd.Series:
    """Pine-style linreg(source, n, 0): fitted line value at the last bar."""
    x = np.arange(n, dtype=float)

    def _fit(w):
        k = np.polyfit(x, w, 1)
        return k[0] * (n - 1) + k[1]

    return s.rolling(n).apply(_fit, raw=True)


def ttm_squeeze(df: pd.DataFrame, n: int = 20, mult_bb: float = 2.0,
                mult_kc: float = 1.5):
    """Squeeze Momentum (LazyBear). Returns (momentum, squeeze_on).
    momentum = linreg of de-meaned close; squeeze_on = BB inside KC."""
    close = df["close"]
    basis = sma(close, n)
    dev = mult_bb * close.rolling(n).std(ddof=0)
    upper_bb, lower_bb = basis + dev, basis - dev
    tr = pd.concat(
        [df["high"] - df["low"],
         (df["high"] - df["close"].shift()).abs(),
         (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    rangema = sma(tr, n)
    upper_kc = basis + rangema * mult_kc
    lower_kc = basis - rangema * mult_kc
    squeeze_on = (lower_bb > lower_kc) & (upper_bb < upper_kc)
    midline = ((df["high"].rolling(n).max() + df["low"].rolling(n).min()) / 2
               + basis) / 2
    momentum = _linreg_last(close - midline, n)
    return momentum, squeeze_on


def wavetrend(df: pd.DataFrame, ch_len: int = 10, avg_len: int = 21,
              sig_len: int = 4):
    """WaveTrend Oscillator (LazyBear). Returns (wt1, wt2)."""
    ap = (df["high"] + df["low"] + df["close"]) / 3
    esa = ema(ap, ch_len)
    d = ema((ap - esa).abs(), ch_len)
    ci = (ap - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ema(ci, avg_len)
    wt2 = sma(wt1, sig_len)
    return wt1, wt2
