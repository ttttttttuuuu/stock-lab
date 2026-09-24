"""Free US market data via Nasdaq public API (no key required).

- Daily OHLCV history: /api/quote/{sym}/historical
- Options chain:       /api/quote/{sym}/option-chain

Results are cached as CSV/JSON under data/cache to be polite with rate limits.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

BASE = "https://api.nasdaq.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_session = requests.Session()
_session.headers.update(HEADERS)


def _get(path: str, params: dict, retries: int = 3) -> dict:
    last_err = None
    for attempt in range(retries):
        try:
            r = _session.get(f"{BASE}{path}", params=params, timeout=20)
            r.raise_for_status()
            payload = r.json()
            if payload.get("data") is not None:
                return payload["data"]
            last_err = f"empty data: {str(payload)[:200]}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Nasdaq API failed for {path}: {last_err}")


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    if s in ("", "--", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_history(symbol: str, years: float = 2.0, use_cache: bool = True) -> pd.DataFrame:
    """Daily OHLCV for `symbol`, ascending by date. Cached per day + window —
    the cache marker records both the fetch date and the years window, so a
    1-year daily-job cache never silently serves a 2-year backtest."""
    symbol = symbol.upper()
    cache = CACHE_DIR / f"hist_{symbol}.csv"
    today = date.today().isoformat()
    if use_cache and cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"])
        # serve cache when it is from today AND covers at least the
        # requested window (a 2y cache may serve a 1y request)
        marker = cache.with_suffix(".day")
        if marker.exists():
            try:
                mdate, myears = marker.read_text().strip().rsplit("|", 1)
                if mdate == today and float(myears) >= years:
                    return df
            except ValueError:
                pass  # legacy/odd marker -> refetch
    end = date.today()
    start = end - timedelta(days=int(365.25 * years) + 10)
    data = None
    for assetclass in ("stocks", "etf"):  # SPY/QQQ etc. are ETFs
        try:
            data = _get(
                f"/quote/{symbol}/historical",
                {
                    "assetclass": assetclass,
                    "fromdate": start.isoformat(),
                    "todate": end.isoformat(),
                    "limit": 9999,
                },
            )
            break
        except RuntimeError:
            continue
    if data is None:
        raise RuntimeError(f"Nasdaq API failed for {symbol} (stocks & etf)")
    rows = data["tradesTable"]["rows"]
    recs = []
    for r in rows:
        recs.append(
            {
                "date": pd.to_datetime(r["date"], format="%m/%d/%Y"),
                "open": _num(r["open"]),
                "high": _num(r["high"]),
                "low": _num(r["low"]),
                "close": _num(r["close"]),
                "volume": _num(r["volume"]),
            }
        )
    df = (
        pd.DataFrame(recs)
        .dropna(subset=["close"])
        .sort_values("date")
        .reset_index(drop=True)
    )
    df.to_csv(cache, index=False)
    cache.with_suffix(".day").write_text(f"{today}|{years}")
    time.sleep(0.4)  # be polite
    return df


def fetch_quote(symbol: str) -> dict:
    data = None
    for assetclass in ("stocks", "etf"):
        try:
            data = _get(f"/quote/{symbol.upper()}/info", {"assetclass": assetclass})
            break
        except RuntimeError:
            continue
    if data is None:
        raise RuntimeError(f"quote failed for {symbol}")
    p = data["primaryData"]
    return {
        "symbol": symbol.upper(),
        "price": _num(p["lastSalePrice"]),
        "net_change": _num(p["netChange"]),
        "pct_change": _num(str(p["percentageChange"]).replace("%", "")),
        "timestamp": p.get("lastTradeTimestamp"),
    }


def fetch_option_chain(symbol: str, max_dte: int = 14) -> pd.DataFrame:
    """Near-term option chain (calls & puts) for `symbol`."""
    symbol = symbol.upper()
    today = date.today()
    data = None
    for assetclass in ("stocks", "etf"):
        try:
            data = _get(
                f"/quote/{symbol}/option-chain",
                {
                    "assetclass": assetclass,
                    "fromdate": today.isoformat(),
                    "todate": (today + timedelta(days=max_dte)).isoformat(),
                    "limit": 5000,
                },
            )
            break
        except RuntimeError:
            continue
    if data is None:
        raise RuntimeError(f"option chain failed for {symbol}")
    rows = data["table"]["rows"]
    recs = []
    expiry = None
    for r in rows:
        if r.get("expirygroup"):
            expiry = r["expirygroup"]
            continue
        if not r.get("strike"):
            continue
        recs.append(
            {
                "expiry": expiry,
                "strike": _num(r["strike"]),
                "c_bid": _num(r.get("c_Bid")),
                "c_ask": _num(r.get("c_Ask")),
                "c_last": _num(r.get("c_Last")),
                "c_oi": _num(r.get("c_Openinterest")),
                "p_bid": _num(r.get("p_Bid")),
                "p_ask": _num(r.get("p_Ask")),
                "p_last": _num(r.get("p_Last")),
                "p_oi": _num(r.get("p_Openinterest")),
            }
        )
    df = pd.DataFrame(recs)
    if not df.empty:
        df["expiry"] = pd.to_datetime(df["expiry"])
    (CACHE_DIR / f"chain_{symbol}.json").write_text(
        json.dumps({"asof": today.isoformat(), "rows": df.to_dict("records")}, default=str)
    )
    time.sleep(0.4)
    return df


if __name__ == "__main__":
    df = fetch_history("AAPL", years=2, use_cache=False)
    print(df.tail(3))
    print("rows:", len(df))
