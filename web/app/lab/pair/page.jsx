"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { loadPrices, loadStockPairTrades } from "../../../lib/data";
import { STRAT_LABELS, INTERVAL_LABEL } from "../../../lib/stratLabels";
import Skeleton from "../../../components/Skeleton";
import StockChart from "../../../components/StockChart";

const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });

const EXIT_LABELS = {
  signal_flip: "信号反转",
  signal_off: "信号消失",
  stop_loss: "止损",
  take_profit: "止盈",
  time_stop: "时间止损",
};

function PairDetail() {
  const sp = useSearchParams();
  const strategy = sp.get("strategy") || "";
  const symbol = sp.get("symbol") || "";
  const [trades, setTrades] = useState(null);
  const [candles, setCandles] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!strategy || !symbol) return;
    Promise.all([loadStockPairTrades(strategy, symbol), loadPrices(symbol)])
      .then(([t, c]) => { setTrades(t); setCandles(c); })
      .catch((e) => setError(String(e)));
  }, [strategy, symbol]);

  const analysis = useMemo(() => {
    if (!trades || !trades.length) return null;
    const wins = trades.filter((t) => t.pnl > 0);
    const grossWin = wins.reduce((a, t) => a + t.pnl, 0);
    const grossLoss = -trades.filter((t) => t.pnl <= 0).reduce((a, t) => a + t.pnl, 0);
    let cum = 0, peak = 0, maxDd = 0;
    const equity = trades.map((t, i) => {
      cum += t.pnl; peak = Math.max(peak, cum);
      maxDd = Math.min(maxDd, cum - peak);
      return { i: i + 1, date: t.exit_date, pnl: Math.round(cum * 100) / 100 };
    });
    const longs = trades.filter((t) => t.side === "long");
    const shorts = trades.filter((t) => t.side === "short");
    const sideStats = (list) => ({
      n: list.length,
      pnl: Math.round(list.reduce((a, t) => a + t.pnl, 0) * 100) / 100,
      win: list.length
        ? Math.round((list.filter((t) => t.pnl > 0).length / list.length) * 1000) / 10
        : 0,
    });
    const byReason = Object.entries(
      trades.reduce((m, t) => {
        const k = t.exit_reason || "other";
        (m[k] = m[k] || { n: 0, pnl: 0 });
        m[k].n += 1; m[k].pnl += t.pnl;
        return m;
      }, {})
    ).map(([reason, v]) => ({
      reason, n: v.n, pnl: Math.round(v.pnl * 100) / 100,
    })).sort((a, b) => b.n - a.n);
    const best = trades.reduce((a, t) => (t.pnl > a.pnl ? t : a));
    const worst = trades.reduce((a, t) => (t.pnl < a.pnl ? t : a));
    return {
      trades: trades.length,
      win_rate: (wins.length / trades.length) * 100,
      total_pnl: trades.reduce((a, t) => a + t.pnl, 0),
      profit_factor: grossLoss > 0 ? grossWin / grossLoss : null,
      max_drawdown: maxDd,
      avg_hold: trades.reduce((a, t) => a + (t.hold_days || 0), 0) / trades.length,
      avg_win: wins.length ? grossWin / wins.length : 0,
      avg_loss: trades.length - wins.length
        ? -grossLoss / (trades.length - wins.length) : 0,
      equity, best, worst,
      longs: sideStats(longs), shorts: sideStats(shorts), byReason,
    };
  }, [trades]);

  if (!strategy || !symbol)
    return <div className="panel"><h2>缺少参数</h2><p className="muted">请从策略页面进入配对详情。</p></div>;
  if (error)
    return <div className="panel"><h2>数据加载失败</h2><p className="muted">{error}</p></div>;
  if (!trades || !candles) return <Skeleton variant="chart" />;

  // running cumulative P&L per trade row
  let run = 0;
  const rows = trades.map((t) => {
    run = Math.round((run + t.pnl) * 100) / 100;
    return { ...t, cum: run };
  });

  return (
    <>
      <Link href="/lab" className="back-link">
        <ArrowLeft size={14} style={{ verticalAlign: "-2px" }} aria-hidden="true" /> 返回策略
      </Link>
      <h1>{symbol}{" "}
        <span className="badge backtest" style={{ fontSize: 13 }}>
          {STRAT_LABELS[strategy] || strategy}
        </span>{" "}
        <span className="badge flat" style={{ fontSize: 13 }}>{INTERVAL_LABEL}</span>
      </h1>
      <p className="subtitle">
        股价回测 · 每笔 $100 名义本金 · 多头/空头 · 策略级止盈止损 / 最长持有 10 个交易日
      </p>

      {analysis && (
        <>
          <div className="stat-strip">
            <div className="stat-item">
              <span className="label">最终累计盈亏</span>
              <strong className={analysis.total_pnl >= 0 ? "pos" : "neg"}>
                {analysis.total_pnl >= 0 ? "+" : ""}${fmt(analysis.total_pnl)}
              </strong>
            </div>
            <div className="stat-item">
              <span className="label">笔数</span>
              <strong>{analysis.trades}</strong>
            </div>
            <div className="stat-item">
              <span className="label">胜率</span>
              <strong>{fmt(analysis.win_rate, 1)}%</strong>
            </div>
            <div className="stat-item">
              <span className="label">盈亏比</span>
              <strong>{fmt(analysis.profit_factor)}</strong>
            </div>
            <div className="stat-item">
              <span className="label">最大回撤</span>
              <strong className="neg">${fmt(analysis.max_drawdown)}</strong>
            </div>
            <div className="stat-item">
              <span className="label">平均持有</span>
              <strong>{fmt(analysis.avg_hold, 1)} 天</strong>
            </div>
          </div>

          <div className="panel">
            <h2>权益曲线（按平仓累计）</h2>
            <div style={{ width: "100%", height: 240 }}>
              <ResponsiveContainer>
                <LineChart data={analysis.equity} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
                  <XAxis dataKey="date" tick={{ fill: "#8b93a5", fontSize: 11 }}
                         tickFormatter={(d) => d.slice(2, 7)} minTickGap={50} />
                  <YAxis tick={{ fill: "#8b93a5", fontSize: 11 }} width={64}
                         tickFormatter={(v) => `$${v}`} />
                  <Tooltip
                    contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 8 }}
                    labelStyle={{ color: "#8b93a5" }}
                    formatter={(v) => [`$${fmt(v)}`, "累计盈亏"]}
                  />
                  <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="4 4" />
                  <Line dataKey="pnl" dot={false} isAnimationActive={false}
                        stroke={analysis.total_pnl >= 0 ? "#22c55e" : "#ef4444"}
                        strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="cards">
            <div className="card">
              <div className="label">多头（{analysis.longs.n} 笔 · 胜率 {analysis.longs.win}%）</div>
              <div className={`value ${analysis.longs.pnl >= 0 ? "pos" : "neg"}`}>
                {analysis.longs.pnl >= 0 ? "+" : ""}${fmt(analysis.longs.pnl)}
              </div>
            </div>
            <div className="card">
              <div className="label">空头（{analysis.shorts.n} 笔 · 胜率 {analysis.shorts.win}%）</div>
              <div className={`value ${analysis.shorts.pnl >= 0 ? "pos" : "neg"}`}>
                {analysis.shorts.pnl >= 0 ? "+" : ""}${fmt(analysis.shorts.pnl)}
              </div>
            </div>
            <div className="card">
              <div className="label">平均盈利 / 平均亏损</div>
              <div className="value" style={{ fontSize: 18 }}>
                <span className="pos">+${fmt(analysis.avg_win)}</span>
                {" / "}
                <span className="neg">${fmt(analysis.avg_loss)}</span>
              </div>
            </div>
            <div className="card">
              <div className="label">最佳一笔（{analysis.best.exit_date}）</div>
              <div className="value pos">+${fmt(analysis.best.pnl)}</div>
            </div>
            <div className="card">
              <div className="label">最差一笔（{analysis.worst.exit_date}）</div>
              <div className="value neg">${fmt(analysis.worst.pnl)}</div>
            </div>
          </div>

          <div className="panel">
            <h2>出场原因分布</h2>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {analysis.byReason.map((r) => (
                <span key={r.reason} className="badge flat" style={{ fontSize: 12 }}>
                  {EXIT_LABELS[r.reason] || r.reason} × {r.n}
                  {" · "}
                  <span className={r.pnl >= 0 ? "pos" : "neg"}>
                    {r.pnl >= 0 ? "+" : ""}${fmt(r.pnl)}
                  </span>
                </span>
              ))}
            </div>
          </div>
        </>
      )}

      <div className="panel">
        <h2>K 线与交易标注</h2>
        <p className="hint">
          ▲ 绿色 = 做多开仓 / 平仓 · ▼ 红色 = 做空开仓 / 平仓 · 平仓标记上的数字为该笔盈亏（$）
        </p>
        {candles.length
          ? <StockChart candles={candles} trades={trades} />
          : <p className="muted">无价格数据</p>}
      </div>

      <div className="panel">
        <h2>交易明细（{trades.length} 笔）</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th><th>方向</th><th>开仓日</th><th>开仓价</th>
                <th>平仓日</th><th>平仓价</th><th>持有</th><th>盈亏 %</th>
                <th>盈亏 $</th><th>累计 $</th><th>平仓原因</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t, i) => (
                <tr key={i}>
                  <td className="muted">{i + 1}</td>
                  <td>
                    <span className={`badge ${t.side === "long" ? "call" : "put"}`}>
                      {t.side === "long" ? "多" : "空"}
                    </span>
                  </td>
                  <td>{t.entry_date}</td>
                  <td>${fmt(t.entry_price)}</td>
                  <td>{t.exit_date}</td>
                  <td>${fmt(t.exit_price)}</td>
                  <td>{t.hold_days} 天</td>
                  <td className={t.pnl_pct >= 0 ? "pos" : "neg"}>
                    {t.pnl_pct > 0 ? "+" : ""}{fmt(t.pnl_pct)}%
                  </td>
                  <td className={t.pnl >= 0 ? "pos" : "neg"}>
                    <strong>{t.pnl > 0 ? "+" : ""}${fmt(t.pnl)}</strong>
                  </td>
                  <td className={t.cum >= 0 ? "pos" : "neg"}>
                    {t.cum >= 0 ? "+" : ""}${fmt(t.cum)}
                  </td>
                  <td className="muted">{EXIT_LABELS[t.exit_reason] || t.exit_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

export default function PairPage() {
  return (
    <Suspense fallback={<Skeleton variant="chart" />}>
      <PairDetail />
    </Suspense>
  );
}
