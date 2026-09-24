"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, BarChart, Bar, Cell, LineChart, Line, Legend,
} from "recharts";

import { loadTrades, loadOverview } from "../../lib/data";
import { tradeStats, evaluateStrategies } from "../../lib/reviewStats";
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

const REASON_LABELS = {
  stop_loss: "止损",
  take_profit: "止盈",
  time_stop: "到期/限时",
  signal_flip: "信号反转",
  signal_off: "信号消失",
  end_of_data: "数据截止",
};

const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });
const pct = (n, d = 1) => (n == null ? "—" : `${fmt(n, d)}%`);
const reasonBase = (r) => (r || "").split("(")[0] || "unknown";

const COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ec4899", "#38bdf8", "#a78bfa"];

export default function Review() {
  const [trades, setTrades] = useState(null);
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([loadTrades(), loadOverview()])
      .then(([t, o]) => { setTrades(t); setOverview(o); })
      .catch((e) => setError(String(e)));
  }, []);

  const closed = useMemo(
    () => (trades || []).filter((t) => t.source === "paper" && t.exit_date),
    [trades]);

  const overall = useMemo(() => tradeStats(closed), [closed]);

  const evaluated = useMemo(
    () => (overview ? evaluateStrategies(overview.leaderboard || [], closed) : []),
    [overview, closed]);

  const cumCurve = useMemo(() => {
    const daily = {};
    closed.forEach((t) => (daily[t.exit_date] = (daily[t.exit_date] || 0) + t.pnl));
    let cum = 0;
    return Object.keys(daily).sort()
      .map((d) => ({ date: d, pnl: Math.round((cum += daily[d]) * 100) / 100 }));
  }, [closed]);

  const reasonRows = useMemo(() => {
    const m = {};
    closed.forEach((t) => {
      const k = reasonBase(t.exit_reason);
      m[k] = m[k] || { n: 0, pnl: 0 };
      m[k].n += 1;
      m[k].pnl += t.pnl;
    });
    return Object.entries(m)
      .map(([k, v]) => ({ reason: k, n: v.n, pnl: Math.round(v.pnl * 100) / 100 }))
      .sort((a, b) => b.n - a.n);
  }, [closed]);

  // per-strategy cumulative realized P&L, merged into one dated series
  const stratCurves = useMemo(() => {
    const daily = {};
    closed.forEach((t) => {
      daily[t.strategy] = daily[t.strategy] || {};
      daily[t.strategy][t.exit_date] =
        (daily[t.strategy][t.exit_date] || 0) + t.pnl;
    });
    const cum = {};
    const dateMap = {};
    Object.entries(daily).forEach(([s, days]) => {
      cum[s] = 0;
      Object.keys(days).sort().forEach((d) => {
        cum[s] += days[d];
        dateMap[d] = dateMap[d] || { date: d };
        dateMap[d][s] = Math.round(cum[s] * 100) / 100;
      });
    });
    return Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date));
  }, [closed]);

  const liveStrategies = useMemo(
    () => [...new Set(closed.map((t) => t.strategy))].sort(),
    [closed]);

  // live leaderboard: realized (closed) + unrealized (open) per strategy,
  // ranked by total — meaningful even before first closes
  const liveBoard = useMemo(() => {
    if (!overview) return [];
    const byStrat = {};
    const ensure = (s) => (byStrat[s] = byStrat[s] || {
      strategy: s, closedN: 0, wins: 0, realized: 0, openN: 0, unrealized: 0,
    });
    closed.forEach((t) => {
      const e = ensure(t.strategy);
      e.closedN += 1;
      e.realized += t.pnl;
      if (t.pnl > 0) e.wins += 1;
    });
    (overview.paper_account?.positions || []).forEach((p) => {
      const e = ensure(p.strategy || "ensemble");
      e.openN += 1;
      e.unrealized += p.unrealized_pnl ?? 0;
    });
    const alertMap = Object.fromEntries(evaluated.map((e) => [e.strategy, e.alert]));
    return Object.values(byStrat)
      .map((e) => ({
        ...e,
        total: Math.round((e.realized + e.unrealized) * 100) / 100,
        winRate: e.closedN ? (e.wins / e.closedN) * 100 : null,
        alert: alertMap[e.strategy],
      }))
      .sort((a, b) => b.total - a.total);
  }, [overview, closed, evaluated]);

  if (error)
    return <div className="panel"><h2>数据加载失败</h2><p className="muted">{error}</p></div>;
  if (!trades || !overview) return <Skeleton variant="dashboard" />;

  const openCount = overview.paper_account?.positions?.length ?? 0;

  return (
    <>
      <h1>复盘 Review</h1>
      <p className="subtitle">
        纸面交易实际战绩 vs 回测预期 · 已平仓 {closed.length} 笔 · 持仓中 {openCount} 笔
      </p>

      {(() => {
        const crits = evaluated.filter((e) => e.alert.level === "critical");
        const watches = evaluated.filter((e) => e.alert.level === "watch");
        if (!crits.length && !watches.length) return null;
        return (
          <div className={`alert-banner ${crits.length ? "" : "watch"}`}>
            <h2>
              {crits.length
                ? `⚠ ${crits.length} 个策略显著偏离回测基线，建议重点复核（交易仍继续）`
                : `${watches.length} 个策略出现偏离迹象，持续观察`}
            </h2>
            <p className="muted">
              {[...crits, ...watches]
                .map((e) => `${STRAT_LABELS[e.strategy] || e.strategy}：${e.alert.reasons.join("；")}`)
                .join(" ｜ ")}
            </p>
          </div>
        );
      })()}

      {liveBoard.length > 0 && (
        <div className="panel" style={{ marginBottom: 18 }}>
          <h2>策略纸面排行（实时 · 已实现 + 浮盈）</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Strategy</th>
                  <th className="num">已平仓</th><th className="num">胜率</th>
                  <th className="num">已实现</th>
                  <th className="num">持仓中</th><th className="num">浮盈</th>
                  <th className="num">合计</th><th>状态</th>
                </tr>
              </thead>
              <tbody>
                {liveBoard.map((e, i) => (
                  <tr key={e.strategy}>
                    <td>
                      <span className={`rank-badge ${i < 3 ? "top" : ""}`}
                            style={{ position: "static" }}>{i + 1}</span>
                    </td>
                    <td><strong>{STRAT_LABELS[e.strategy] || e.strategy}</strong></td>
                    <td className="num">{e.closedN}</td>
                    <td className="num">{e.winRate == null ? "—" : pct(e.winRate)}</td>
                    <td className={`num ${e.realized >= 0 ? "pos" : "neg"}`}>
                      ${fmt(Math.round(e.realized * 100) / 100)}
                    </td>
                    <td className="num">{e.openN}</td>
                    <td className={`num ${e.unrealized >= 0 ? "pos" : "neg"}`}>
                      {e.unrealized >= 0 ? "+" : ""}${fmt(Math.round(e.unrealized * 100) / 100)}
                    </td>
                    <td className={`num ${e.total >= 0 ? "pos" : "neg"}`}>
                      <strong>${fmt(e.total)}</strong>
                    </td>
                    <td>
                      {e.alert && (
                        <span className={`badge alert-${e.alert.level}`}
                              title={e.alert.reasons.join("；") || undefined}>
                          {e.alert.label}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
            合计 = 已实现盈亏 + 当前浮盈（按最新标记价）。浮盈随每日报价变动，最终以平仓为准。
          </p>
        </div>
      )}

      {closed.length === 0 && (
        <div className="panel" style={{ marginBottom: 18 }}>
          <h2>还没有已平仓的纸面交易</h2>
          <p className="muted" style={{ lineHeight: 1.8 }}>
            当前 {openCount} 笔持仓全部于 2026-09-25 到期。每日任务（05:40）会按实时报价标记浮盈，
            触发止损 / 止盈 / 到期时自动平仓并写入记录，此页随即填充实际数据。
            下方先展示各策略的回测基线，作为平仓后的对照基准。
          </p>
        </div>
      )}

      {overall && (
        <>
          <div className="cards" style={{ marginBottom: 18 }}>
            <div className="card">
              <div className="label">Closed Trades</div>
              <div className="value">{overall.n}</div>
            </div>
            <div className="card">
              <div className="label">Realized P&amp;L</div>
              <div className={`value ${overall.total_pnl >= 0 ? "pos" : "neg"}`}>
                ${fmt(overall.total_pnl)}
              </div>
            </div>
            <div className="card">
              <div className="label">Win Rate</div>
              <div className="value">{pct(overall.win_rate)}</div>
            </div>
            <div className="card">
              <div className="label">Avg P&amp;L / Trade</div>
              <div className={`value ${overall.avg_pnl >= 0 ? "pos" : "neg"}`}>
                ${fmt(overall.avg_pnl)}
              </div>
            </div>
            <div className="card">
              <div className="label">Profit Factor</div>
              <div className="value">{fmt(overall.profit_factor)}</div>
            </div>
            <div className="card">
              <div className="label">Avg Hold Days</div>
              <div className="value">{fmt(overall.avg_days, 1)}</div>
            </div>
          </div>

          {cumCurve.length > 1 && (
            <div className="panel" style={{ marginBottom: 18 }}>
              <h2>累计已实现盈亏</h2>
              <div style={{ width: "100%", height: 200 }}>
                <ResponsiveContainer>
                  <AreaChart data={cumCurve} margin={{ top: 4, right: 12, bottom: 0, left: 4 }}>
                    <XAxis dataKey="date" tick={{ fill: "#8b93a5", fontSize: 11 }}
                           tickFormatter={(d) => d.slice(5)} minTickGap={40} />
                    <YAxis tick={{ fill: "#8b93a5", fontSize: 11 }} width={64}
                           tickFormatter={(v) => `$${v}`} />
                    <Tooltip
                      contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 8 }}
                      labelStyle={{ color: "#8b93a5" }}
                      formatter={(v) => [`$${fmt(v)}`, "累计盈亏"]} />
                    <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="4 4" />
                    <Area dataKey="pnl" isAnimationActive={false}
                          stroke={cumCurve[cumCurve.length - 1].pnl >= 0 ? "#22c55e" : "#ef4444"}
                          fill={cumCurve[cumCurve.length - 1].pnl >= 0 ? "#22c55e33" : "#ef444433"}
                          strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {stratCurves.length > 0 && liveStrategies.length > 0 && (
            <div className="panel" style={{ marginBottom: 18 }}>
              <h2>按策略：累计已实现盈亏</h2>
              <div style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <LineChart data={stratCurves} margin={{ top: 4, right: 12, bottom: 0, left: 4 }}>
                    <XAxis dataKey="date" tick={{ fill: "#8b93a5", fontSize: 11 }}
                           tickFormatter={(d) => d.slice(5)} minTickGap={40} />
                    <YAxis tick={{ fill: "#8b93a5", fontSize: 11 }} width={64}
                           tickFormatter={(v) => `$${v}`} />
                    <Tooltip
                      contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 8 }}
                      labelStyle={{ color: "#8b93a5" }}
                      formatter={(v, name) => [`$${fmt(v)}`, STRAT_LABELS[name] || name]} />
                    <Legend formatter={(v) => STRAT_LABELS[v] || v}
                            wrapperStyle={{ fontSize: 12 }} />
                    <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="4 4" />
                    {liveStrategies.map((s, i) => (
                      <Line key={s} dataKey={s} connectNulls isAnimationActive={false}
                            stroke={COLORS[i % COLORS.length]} strokeWidth={2}
                            dot={{ r: 3, fill: COLORS[i % COLORS.length] }} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </>
      )}

      <div className="panel" style={{ marginBottom: 18 }}>
        <h2>按策略：实际 vs 回测预期</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th rowSpan={2}>Strategy</th>
                <th colSpan={4} style={{ textAlign: "center", borderBottom: "1px solid var(--border)" }}>
                  回测（2 年基线）
                </th>
                <th colSpan={4} style={{ textAlign: "center", borderBottom: "1px solid var(--border)" }}>
                  纸面实盘
                </th>
                <th colSpan={2} style={{ textAlign: "center", borderBottom: "1px solid var(--border)" }}>
                  偏差
                </th>
                <th rowSpan={2}>状态</th>
              </tr>
              <tr>
                <th className="num">笔数</th><th className="num">胜率</th>
                <th className="num">均盈亏</th><th className="num">PF</th>
                <th className="num">笔数</th><th className="num">胜率</th>
                <th className="num">均盈亏</th><th className="num">总盈亏</th>
                <th className="num">Δ胜率</th><th className="num">Δ均盈亏</th>
              </tr>
            </thead>
            <tbody>
              {evaluated.map(({ strategy: sKey, baseline: b, actual: a, alert }) => {
                const dWin = a ? Math.round((a.win_rate - b.win_rate) * 10) / 10 : null;
                const dAvg = a ? Math.round((a.avg_pnl - b.avg_pnl) * 100) / 100 : null;
                return (
                  <tr key={sKey}>
                    <td><strong>{STRAT_LABELS[sKey] || sKey}</strong></td>
                    <td className="num muted">{fmt(b.trades, 0)}</td>
                    <td className="num muted">{pct(b.win_rate)}</td>
                    <td className="num muted">${fmt(b.avg_pnl)}</td>
                    <td className="num muted">{fmt(b.profit_factor)}</td>
                    {a ? (
                      <>
                        <td className="num">{a.n}</td>
                        <td className="num">{pct(a.win_rate)}</td>
                        <td className={`num ${a.avg_pnl >= 0 ? "pos" : "neg"}`}>${fmt(a.avg_pnl)}</td>
                        <td className={`num ${a.total_pnl >= 0 ? "pos" : "neg"}`}>${fmt(a.total_pnl)}</td>
                        <td className={`num ${dWin >= 0 ? "pos" : "neg"}`}>
                          {dWin >= 0 ? "+" : ""}{fmt(dWin, 1)}pp
                        </td>
                        <td className={`num ${dAvg >= 0 ? "pos" : "neg"}`}>
                          {dAvg >= 0 ? "+" : ""}${fmt(dAvg)}
                        </td>
                      </>
                    ) : (
                      <td className="num muted" colSpan={6} style={{ textAlign: "center" }}>
                        等待首笔平仓
                      </td>
                    )}
                    <td>
                      <span className={`badge alert-${alert.level}`}
                            title={alert.reasons.join("；") || undefined}>
                        {alert.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          偏差 = 纸面实盘 − 回测。状态判定需 ≥5 笔样本：胜率低于基线 8pp 记「观察」，
          低于 15pp 或均盈亏由正转标记「⚠ 显著偏离」。告警仅提示、不暂停交易；样本量小时偏差波动大，建议累计 30+ 笔后再做最终结论。
        </p>
      </div>

      {reasonRows.length > 0 && (
        <div className="panel" style={{ marginBottom: 18 }}>
          <h2>平仓原因分布</h2>
          <div style={{ width: "100%", height: 180 }}>
            <ResponsiveContainer>
              <BarChart data={reasonRows} margin={{ top: 4, right: 12, bottom: 0, left: 4 }}>
                <XAxis dataKey="reason" tick={{ fill: "#8b93a5", fontSize: 11 }}
                       tickFormatter={(r) => REASON_LABELS[r] || r} />
                <YAxis tick={{ fill: "#8b93a5", fontSize: 11 }} width={40} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 8 }}
                  labelStyle={{ color: "#8b93a5" }}
                  formatter={(v, name) =>
                    name === "pnl" ? [`$${fmt(v)}`, "合计盈亏"] : [v, "笔数"]}
                  labelFormatter={(r) => REASON_LABELS[r] || r} />
                <Bar dataKey="n" isAnimationActive={false} radius={[4, 4, 0, 0]}>
                  {reasonRows.map((r) => (
                    <Cell key={r.reason} fill={r.pnl >= 0 ? "#22c55e" : "#ef4444"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {closed.length > 0 && (
        <div className="panel">
          <h2>平仓明细（最近 {Math.min(closed.length, 50)} 笔）</h2>
          <div className="table-wrap" style={{ maxHeight: 420 }}>
            <table>
              <thead>
                <tr>
                  <th>Symbol</th><th>Strategy</th><th>Type</th>
                  <th className="num">Strike</th><th>Entry</th>
                  <th className="num">Entry Premium</th><th>Exit</th>
                  <th className="num">Exit Premium</th><th>Reason</th>
                  <th className="num">Days</th>
                  <th className="num">P&amp;L</th><th className="num">%</th>
                </tr>
              </thead>
              <tbody>
                {[...closed].sort((a, b) => b.exit_date.localeCompare(a.exit_date))
                  .slice(0, 50).map((t) => (
                    <tr key={t.id}>
                      <td><strong>{t.symbol}</strong></td>
                      <td className="muted">{STRAT_LABELS[t.strategy] || t.strategy}</td>
                      <td><span className={`badge ${t.kind}`}>{t.kind}</span></td>
                      <td className="num">{fmt(t.strike)}</td>
                      <td className="mono">{t.entry_date}</td>
                      <td className="num">{fmt(t.entry_price)}</td>
                      <td className="mono">{t.exit_date}</td>
                      <td className="num">{fmt(t.exit_price)}</td>
                      <td className="muted">{REASON_LABELS[reasonBase(t.exit_reason)] || t.exit_reason}</td>
                      <td className="num">{t.hold_days}</td>
                      <td className={`num ${t.pnl >= 0 ? "pos" : "neg"}`}>${fmt(t.pnl)}</td>
                      <td className={`num ${t.pnl_pct >= 0 ? "pos" : "neg"}`}>{pct(t.pnl_pct)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
