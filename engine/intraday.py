"""Free intraday US market data.

Primary source: Polygon.io aggregates API (free key in POLYGON_API_KEY,
5 calls/min, split-adjusted). Fallback: Yahoo Finance v8 chart API (no key,
but aggressively rate-limits by IP — raises RateLimited so callers can back
off at the job level).

- 15m bars: last ~60 days
- 1h bars:  last ~729 days (regular session only)
- 4h bars:  aggregated from 1h within each trading day

Results are cached as CSV under data/cache (same-day freshness), same
convention as engine.nasdaq for daily bars.

NOTE: Yahoo fallback prices are NOT split/dividend adjusted; Polygon are.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# load .env if present (same convention as engine.storage)
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

POLYGON_KEY = os.environ.get("POLYGON_API_KEY")
POLYGON_MIN_INTERVAL_S = 12.5     # free plan: 5 calls/min
_last_polygon_call = 0.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 "
                  "Safari/537.36",
    "Accept": "application/json",
}

# timeframe -> fetch/aggregation config (bars kept to the regular session:
# bar start within 09:00–15:59 ET; the 09:00 hourly bar holds the open)
TIMEFRAMES = {
    "15m": {"interval": "15m", "days": 59, "hold_bars": 27 * 10},
    "1h": {"interval": "60m", "days": 729, "hold_bars": 7 * 10},
    "4h": {"interval": "60m", "days": 729, "hold_bars": 20, "chunk": 4},
}


class RateLimited(Exception):
    """The data source is throttling us right now."""


def _polygon_get(url: str, params: dict | None) -> dict:
    """One Polygon call with free-plan pacing (5/min) and 429 backoff."""
    global _last_polygon_call
    for attempt in range(4):
        wait = POLYGON_MIN_INTERVAL_S - (time.time() - _last_polygon_call)
        if wait > 0:
            time.sleep(wait)
        _last_polygon_call = time.time()
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(15 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RateLimited("polygon: still 429 after retries")


def _fetch_polygon(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """Polygon v2 aggregates with cursor pagination (free plan pages at
    ~1k bars regardless of limit), then regular-session filtering."""
    mult, span = (15, "minute") if interval == "15m" else (60, "minute")
    end = date.today()
    start = end - timedelta(days=days)
    url = (f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/"
           f"{mult}/{span}/{start}/{end}")
    params = {"adjusted": "true", "sort": "asc", "limit": 50000,
              "apiKey": POLYGON_KEY}
    bars = []
    while True:
        j = _polygon_get(url, params)
        bars.extend(j.get("results") or [])
        nxt = j.get("next_url")
        if not nxt:
            break
        url, params = nxt, {"apiKey": POLYGON_KEY}   # cursor auth still needed
    if not bars:
        raise RuntimeError(f"polygon: no intraday data for {symbol}")
    df = pd.DataFrame({
        "date": pd.to_datetime([b["t"] for b in bars], unit="ms", utc=True)
                    .tz_convert("America/New_York"),
        "open": [b["o"] for b in bars],
        "high": [b["h"] for b in bars],
        "low": [b["l"] for b in bars],
        "close": [b["c"] for b in bars],
        "volume": [b["v"] for b in bars],
    }).dropna(subset=["close"])
    # regular session only. 15m bars align to the clock so start at 09:30;
    # hourly bars align to clock hours, so the 09:00 bar carries the open.
    session_start = "09:30" if interval == "15m" else "09:00"
    t = df["date"].dt.time
    df = df[(t >= datetime.strptime(session_start, "%H:%M").time())
            & (t < datetime.strptime("16:00", "%H:%M").time())]
    return df.reset_index(drop=True)


def _fetch_raw(symbol: str, interval: str, days: int) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    params = {
        "interval": interval,
        "period1": int((now - timedelta(days=days)).timestamp()),
        "period2": int(now.timestamp()),
        "includePrePost": "false",
    }
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            r = requests.get(f"https://{host}/v8/finance/chart/{symbol}",
                             params=params, headers=HEADERS, timeout=30)
        except requests.RequestException:
            continue
        if r.status_code == 429 or not r.text.lstrip().startswith("{"):
            raise RateLimited(f"{host} throttled (status {r.status_code})")
        if r.status_code != 200:
            continue
        payload = r.json().get("chart", {})
        if payload.get("error"):
            raise RuntimeError(f"yahoo chart error: {payload['error']}")
        result = (payload.get("result") or [None])[0]
        if not result or not result.get("timestamp"):
            raise RuntimeError(f"no intraday data for {symbol}")
        q = result["indicators"]["quote"][0]
        df = pd.DataFrame({
            "date": pd.to_datetime(result["timestamp"], unit="s", utc=True)
                        .tz_convert("America/New_York"),
            "open": q["open"], "high": q["high"], "low": q["low"],
            "close": q["close"], "volume": q["volume"],
        })
        return df.dropna(subset=["close"]).reset_index(drop=True)
    raise RateLimited("both yahoo hosts unreachable")


def _chunk_bars(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Aggregate every n consecutive bars within each trading day
    (keeps the tz-aware datetime dtype — no .values round-trip)."""
    day = df["date"].dt.date
    grp = df.groupby(day).cumcount() // n
    return df.groupby([day, grp]).agg(
        date=("date", "first"), open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum")).reset_index(drop=True)


def fetch_intraday(symbol: str, timeframe: str,
                   use_cache: bool = True) -> pd.DataFrame:
    """Intraday OHLCV for `symbol` at `timeframe` (15m/1h/4h), ascending."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"unknown timeframe: {timeframe}")
    cfg = TIMEFRAMES[timeframe]
    symbol = symbol.upper()
    cache = CACHE_DIR / f"intra_{symbol}_{timeframe}.csv"
    today = date.today().isoformat()
    if use_cache and cache.exists():
        marker = cache.with_suffix(".day")
        if marker.exists() and marker.read_text().strip() == today:
            df = pd.read_csv(cache)
            # mixed EDT/EST offsets make read_csv fall back to strings —
            # parse explicitly as UTC then convert to ET
            df["date"] = (pd.to_datetime(df["date"], format="ISO8601",
                                         utc=True)
                          .dt.tz_convert("America/New_York"))
            return df

    if cfg.get("chunk"):
        # 4h derives from the (cached) 1h bars — no extra API calls
        df = _chunk_bars(fetch_intraday(symbol, "1h", use_cache),
                         cfg["chunk"])
    elif POLYGON_KEY:
        df = _fetch_polygon(symbol, cfg["interval"], cfg["days"])
    else:
        df = _fetch_raw(symbol, cfg["interval"], cfg["days"])
    df.to_csv(cache, index=False)
    cache.with_suffix(".day").write_text(today)
    time.sleep(0.4)  # be polite
    return df
