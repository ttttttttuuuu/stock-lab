"use client";

import { Fragment, useEffect, useState } from "react";
import { loadSignalsData, invalidatePrefix, IS_STATIC } from "../../lib/data";
import Skeleton from "../../components/Skeleton";

const STRAT_LABELS = {
  sma_cross: "SMA Cross 5/30",
  rsi_reversion: "RSI Mean Reversion",
  macd_trend: "MACD Trend",
  bb_breakout: "Bollinger Breakout",
  ensemble: "Ensemble (vote)",
  ensemble_weighted: "Ensemble Weighted",
  supertrend: "SuperTrend 20/3",
  ut_bot: "UT Bot (ATR)",
  ttm_squeeze: "TTM Squeeze",
  wavetrend: "WaveTrend",
};

const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });

function SigBadge({ s }) {
  if (s > 0) return <span className="badge call">CALL</span>;
  if (s < 0) return <span className="badge put">PUT</span>;
  return <span className="badge flat">FLAT</span>;
}

export default function Signals() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    loadSignalsData().then(setData).catch((e) => setError(String(e)));
  }, []);

  // Lazy daily refresh: if signals weren't computed today, the first
  // visitor triggers the daily engine (prices -> signals -> paper trades
  // -> sync) and polls until done; everyone else just reads the DB.
  useEffect(() => {
    if (!data || IS_STATIC) return undefined;
    const latest = data.signals?.[0]?.created_at
      ? new Date(data.signals[0].created_at) : null;
    const now = new Date();
    const fresh = latest
      && latest.getFullYear() === now.getFullYear()
      && latest.getMonth() === now.getMonth()
      && latest.getDate() === now.getDate();
    if (fresh) return undefined;

    let cancelled = false;
    let failures = 0;
    setRefreshing(true);
    fetch("/api/signals/refresh", { method: "POST" }).catch(() => {});
    const timer = setInterval(async () => {
      try {
        const s = await (await fetch("/api/signals/refresh")).json();
        if (!s.running) {
          clearInterval(timer);
          invalidatePrefix("signals");
          invalidatePrefix("overview");
          invalidatePrefix("trades");
          invalidatePrefix("stockpaper");
          const d = await loadSignalsData();
          if (!cancelled) { setData(d); setRefreshing(false); }
        }
      } catch {
        // API route unavailable (e.g. static hosting) — stop quietly
        if (++failures >= 2) {
          clearInterval(timer);
          if (!cancelled) setRefreshing(false);
        }
      }
    }, 15000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [data?.signals?.[0]?.created_at]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error)
    return <div className="panel"><h2>数据加载失败</h2><p className="muted">{error}</p></div>;
  if (!data) return <Skeleton variant="table" rows={14} />

  const { signals, paper_positions, paper_trades } = data;
  const symbols = [...new Set(signals.map((s) => s.symbol))].sort();
  const strategies = [...new Set(signals.map((s) => s.strategy))].sort();
  const byKey = {};
  signals.forEach((s) => { byKey[`${s.symbol}|${s.strategy}`] = s; });
  const asof = signals[0]?.created_at?.slice(0, 16).replace("T", " ");

  // group open positions by strategy
  const posByStrat = {};
  paper_positions.forEach((p) => {
    const k = p.strategy || "ensemble";
    (posByStrat[k] = posByStrat[k] || []).push(p);
  });
  Object.values(posByStrat).forEach((arr) =>
    arr.sort((a, b) => a.symbol.localeCompare(b.symbol)));
  const stratGroups = Object.entries(posByStrat)
    .sort(([a], [b]) => (STRAT_LABELS[a] || a).localeCompare(STRAT_LABELS[b] || b));

  return (
    <>
      <h1>Daily Signals &amp; Paper Trading</h1>
      <p className="subtitle">
        Latest close signals from the daily job {asof ? `· updated ${asof} UTC` : ""} ·
        every strategy runs its own $100 paper book
      </p>

      {refreshing && (
        <div className="refresh-banner" role="status">
          <span className="pulse-dot" aria-hidden="true" />
          信号不是今天的，正在后台拉取最新价格、重算信号并更新纸面持仓（约 1–2 分钟），完成后自动刷新…
        </div>
      )}

      <div className="panel">
        <h2>Open Paper Positions ({paper_positions.length})</h2>
        {paper_positions.length === 0 ? (
          <p className="muted">No open paper positions.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th><th>Type</th><th className="num">Strike</th>
                <th>Expiry</th><th>Quote</th>
                <th>Entry Date</th><th className="num">Underlying</th>
                <th className="num">Premium</th><th className="num">Qty</th>
                <th className="num">DTE Left</th>
              </tr>
            </thead>
            <tbody>
              {stratGroups.map(([strat, positions]) => {
                const groupCost = positions.reduce(
                  (a, p) => a + p.entry_price * 100 * p.qty, 0);
                return (
                  <Fragment key={strat}>
                    <tr className="group-row">
                      <td colSpan={10}>
                        {STRAT_LABELS[strat] || strat}
                        <span className="muted" style={{ fontWeight: 400 }}>
                          {" "}· {positions.length} 笔 · 权利金合计 ${fmt(groupCost)}
                        </span>
                      </td>
                    </tr>
                    {positions.map((p) => (
                      <tr key={`${p.symbol}|${p.strategy || "ensemble"}`}>
                        <td><strong>{p.symbol}</strong></td>
                        <td><span className={`badge ${p.kind}`}>{p.kind}</span></td>
                        <td className="num">{fmt(p.strike)}</td>
                        <td className="mono">{p.expiry || "sim"}</td>
                        <td>
                          <span className={`badge ${p.price_source === "chain" ? "call" : "flat"}`}>
                            {p.price_source === "chain" ? "real" : "bs"}
                          </span>
                        </td>
                        <td className="mono">{p.entry_date}</td>
                        <td className="num">{fmt(p.entry_underlying)}</td>
                        <td className="num">{fmt(p.entry_price)}</td>
                        <td className="num">{fmt(p.qty)}</td>
                        <td className="num">{p.dte_left}</td>
                      </tr>
                    ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h2>Signal Matrix (latest close)</h2>
        <table>
          <thead>
            <tr>
              <th>Symbol</th><th className="num">Close</th><th className="num">RSI7</th>
              {strategies.map((s) => <th key={s}>{STRAT_LABELS[s] || s}</th>)}
            </tr>
          </thead>
          <tbody>
            {symbols.map((sym) => {
              const any = byKey[`${sym}|${strategies[0]}`];
              return (
                <tr key={sym}>
                  <td><strong>{sym}</strong></td>
                  <td className="num">{fmt(any?.close)}</td>
                  <td className="num">{any?.details?.rsi ?? "—"}</td>
                  {strategies.map((s) => (
                    <td key={s}><SigBadge s={byKey[`${sym}|${s}`]?.signal ?? 0} /></td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>Closed Paper Trades ({paper_trades.length})</h2>
        {paper_trades.length === 0 ? (
          <p className="muted">No closed paper trades yet — the daily job records them here.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th><th>Strategy</th><th>Type</th><th className="num">Strike</th>
                <th>Entry</th><th>Exit</th><th>Reason</th>
                <th className="num">P&amp;L</th><th className="num">%</th>
              </tr>
            </thead>
            <tbody>
              {paper_trades.map((t) => (
                <tr key={t.id}>
                  <td><strong>{t.symbol}</strong></td>
                  <td className="muted">{STRAT_LABELS[t.strategy] || t.strategy}</td>
                  <td><span className={`badge ${t.kind}`}>{t.kind}</span></td>
                  <td className="num">{fmt(t.strike)}</td>
                  <td className="mono">{t.entry_date}</td>
                  <td className="mono">{t.exit_date}</td>
                  <td className="muted">{t.exit_reason}</td>
                  <td className={`num ${t.pnl >= 0 ? "pos" : "neg"}`}>${fmt(t.pnl)}</td>
                  <td className={`num ${t.pnl_pct >= 0 ? "pos" : "neg"}`}>{fmt(t.pnl_pct, 1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
