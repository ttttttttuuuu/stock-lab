"use client";

import { useEffect, useMemo, useState } from "react";
import { loadTrades } from "../../lib/data";
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
const PAGE_SIZE = 100;

export default function Trades() {
  const [trades, setTrades] = useState(null);
  const [error, setError] = useState(null);
  const [symbol, setSymbol] = useState("all");
  const [strategy, setStrategy] = useState("all");
  const [kind, setKind] = useState("all");
  const [result, setResult] = useState("all");
  const [source, setSource] = useState("all");
  const [page, setPage] = useState(0);

  useEffect(() => {
    loadTrades().then(setTrades).catch((e) => setError(String(e)));
  }, []);

  const filtered = useMemo(() => {
    if (!trades) return [];
    return trades.filter((t) =>
      (symbol === "all" || t.symbol === symbol) &&
      (strategy === "all" || t.strategy === strategy) &&
      (kind === "all" || t.kind === kind) &&
      (source === "all" || t.source === source) &&
      (result === "all" || (result === "win" ? t.pnl > 0 : t.pnl <= 0))
    );
  }, [trades, symbol, strategy, kind, result, source]);

  useEffect(() => setPage(0), [symbol, strategy, kind, result, source]);

  if (error)
    return <div className="panel"><h2>数据加载失败</h2><p className="muted">{error}</p></div>;
  if (!trades) return <Skeleton variant="table" rows={14} />

  const symbols = [...new Set(trades.map((t) => t.symbol))].sort();
  const strategies = [...new Set(trades.map((t) => t.strategy))].sort();
  const pages = Math.ceil(filtered.length / PAGE_SIZE);
  const shown = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const sumPnl = filtered.reduce((a, t) => a + (t.pnl || 0), 0);
  const wins = filtered.filter((t) => t.pnl > 0).length;
  const winRate = filtered.length ? (wins / filtered.length) * 100 : null;

  return (
    <>
      <h1>交易明细</h1>
      <p className="subtitle">
        全部模拟成交记录 · 回测 + 纸面
      </p>

      <div className="stat-strip">
        <div className="stat-item">
          <span className="label">笔数</span>
          <strong>{filtered.length.toLocaleString()}</strong>
        </div>
        <div className="stat-item">
          <span className="label">胜率</span>
          <strong>{winRate == null ? "—" : `${winRate.toFixed(1)}%`}</strong>
        </div>
        <div className="stat-item">
          <span className="label">合计盈亏</span>
          <strong className={sumPnl >= 0 ? "pos" : "neg"}>${fmt(sumPnl)}</strong>
        </div>
        <div className="stat-item">
          <span className="label">平均每笔</span>
          <strong className={sumPnl >= 0 ? "pos" : "neg"}>
            ${fmt(filtered.length ? sumPnl / filtered.length : 0)}
          </strong>
        </div>
      </div>

      <div className="filters">
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="all">All sources</option>
          <option value="backtest">Backtest</option>
          <option value="paper">Paper</option>
        </select>
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          <option value="all">All symbols</option>
          {symbols.map((s) => <option key={s}>{s}</option>)}
        </select>
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
          <option value="all">All strategies</option>
          {strategies.map((s) => (
            <option key={s} value={s}>{STRAT_LABELS[s] || s}</option>
          ))}
        </select>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="all">Call + Put</option>
          <option value="call">Call</option>
          <option value="put">Put</option>
        </select>
        <select value={result} onChange={(e) => setResult(e.target.value)}>
          <option value="all">Win + Loss</option>
          <option value="win">Wins</option>
          <option value="loss">Losses</option>
        </select>
      </div>

      <div className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Source</th><th>Symbol</th><th>Strategy</th><th>Type</th>
                <th className="num">Strike</th><th>Entry</th>
                <th className="num">Underlying</th><th className="num">Premium</th>
                <th className="num">Qty</th><th>Exit</th>
                <th className="num">Exit Premium</th><th>Reason</th>
                <th className="num">Days</th>
                <th className="num">P&amp;L</th><th className="num">%</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((t) => (
                <tr key={t.id}>
                  <td><span className={`badge ${t.source}`}>{t.source}</span></td>
                  <td><strong>{t.symbol}</strong></td>
                  <td className="muted">{STRAT_LABELS[t.strategy] || t.strategy}</td>
                  <td><span className={`badge ${t.kind}`}>{t.kind}</span></td>
                  <td className="num">{fmt(t.strike)}</td>
                  <td className="mono">{t.entry_date}</td>
                  <td className="num">{fmt(t.entry_underlying)}</td>
                  <td className="num">{fmt(t.entry_price)}</td>
                  <td className="num">{fmt(t.qty)}</td>
                  <td className="mono">{t.exit_date}</td>
                  <td className="num">{fmt(t.exit_price)}</td>
                  <td className="muted">{t.exit_reason}</td>
                  <td className="num">{t.hold_days}</td>
                  <td className={`num ${t.pnl >= 0 ? "pos" : "neg"}`}>${fmt(t.pnl)}</td>
                  <td className={`num ${t.pnl_pct >= 0 ? "pos" : "neg"}`}>{fmt(t.pnl_pct, 1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {pages > 1 && (
          <div style={{ display: "flex", gap: 10, marginTop: 14, alignItems: "center" }}>
            <button className="filters" style={{ all: "unset", cursor: "pointer", padding: "6px 12px", background: "var(--panel-2)", borderRadius: 8 }}
                    disabled={page === 0} onClick={() => setPage(page - 1)}>← Prev</button>
            <span className="muted">Page {page + 1} / {pages}</span>
            <button style={{ all: "unset", cursor: "pointer", padding: "6px 12px", background: "var(--panel-2)", borderRadius: 8 }}
                    disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next →</button>
          </div>
        )}
      </div>
    </>
  );
}
