"use client";

import { Fragment, useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
  ReferenceLine,
} from "recharts";
import Link from "next/link";

import { loadOverview, loadSignalsData } from "../../lib/data";
import { evaluateStrategies } from "../../lib/reviewStats";
import { STRAT_LABELS } from "../../lib/stratLabels";
import Skeleton from "../../components/Skeleton";

const COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ec4899", "#38bdf8", "#a78bfa"];

const fmt = (n) =>
  n == null ? "—" : n.toLocaleString("en-US", { maximumFractionDigits: 2 });

export default function OptionsOverview() {
  const [data, setData] = useState(null);
  const [sigData, setSigData] = useState(null);
  const [error, setError] = useState(null);
  const [sortDir, setSortDir] = useState("asc"); // worst positions first

  useEffect(() => {
    loadOverview().then(setData).catch((e) => setError(String(e)));
    loadSignalsData().then(setSigData).catch(() => {}); // focus panel degrades gracefully
  }, []);

  if (error)
    return <div className="panel"><h2>数据加载失败</h2><p className="muted">{error}</p></div>;
  if (!data) return <Skeleton variant="dashboard" />;

  const { leaderboard, curves, heatmap, totals, paper_account: pa } = data;
  const strategies = totals.strategies;
  const symbols = totals.symbols;

  const sortedPositions = pa
    ? [...pa.positions].sort((a, b) => {
        const d = (a.unrealized_pnl ?? 0) - (b.unrealized_pnl ?? 0);
        return sortDir === "asc" ? d : -d;
      })
    : [];

  // ---- per-strategy exposure (nominal premium deployed) ----
  const exposure = pa
    ? Object.values(
        pa.positions.reduce((m, p) => {
          const k = p.strategy || "ensemble";
          const e = m[k] || (m[k] = {
            strategy: k, count: 0, cost: 0, value: 0, calls: 0, puts: 0,
          });
          e.count += 1;
          e.cost += p.entry_price * 100 * p.qty;
          e.value += (p.last_mark ?? p.entry_price) * 100 * p.qty;
          if (p.kind === "call") e.calls += 1; else e.puts += 1;
          return m;
        }, {})
      )
        .map((e) => ({ ...e, unrealized: e.value - e.cost }))
        .sort((a, b) => b.cost - a.cost)
    : [];
  const maxCost = Math.max(...exposure.map((e) => e.cost), 1);

  const exposurePanel = pa && exposure.length > 0 && (
    <div className="panel">
      <h2>策略风险敞口（名义权利金）</h2>
      <p className="hint">
        每个策略独立的 $100/笔 账本 · 合计 ${fmt(exposure.reduce((a, e) => a + e.cost, 0))} 在仓
      </p>
      <div>
        {exposure.map((e) => (
          <div key={e.strategy} className="expo-row">
            <div className="expo-label">
              <strong>{STRAT_LABELS[e.strategy] || e.strategy}</strong>
              <span className="muted" style={{ fontSize: 11 }}>
                {e.count} 笔 · <span className="pos">{e.calls}C</span>
                {" / "}<span className="neg">{e.puts}P</span>
              </span>
            </div>
            <div className="expo-bar-track" role="img"
                 aria-label={`${e.strategy} 敞口 $${fmt(e.cost)}`}>
              <div className="expo-bar-fill"
                   style={{ width: `${(e.cost / maxCost) * 100}%` }} />
            </div>
            <div className="expo-nums">
              <span className="num">${fmt(e.cost)}</span>
              <span className={`num ${e.unrealized >= 0 ? "pos" : "neg"}`}>
                {e.unrealized >= 0 ? "+" : ""}${fmt(e.unrealized)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );

  // ---- today focus ----
  const sigCounts = sigData
    ? sigData.signals.reduce(
        (m, s) => {
          if (s.signal > 0) m.call += 1;
          else if (s.signal < 0) m.put += 1;
          else m.flat += 1;
          return m;
        },
        { call: 0, put: 0, flat: 0 })
    : null;
  const topLosers = pa ? sortedPositions.filter((p) => (p.unrealized_pnl ?? 0) < 0).slice(0, 5) : [];
  const nearExpiry = pa
    ? pa.positions.filter((p) => (p.dte_left ?? 99) <= 3)
        .sort((a, b) => (a.dte_left ?? 0) - (b.dte_left ?? 0))
    : [];

  // live-vs-backtest deviation alerts (shared rules with /review)
  const stratAlerts = evaluateStrategies(leaderboard, data.paper_trades || []);
  const alertByStrat = Object.fromEntries(stratAlerts.map((e) => [e.strategy, e.alert]));
  const crits = stratAlerts.filter((e) => e.alert.level === "critical");
  const watches = stratAlerts.filter((e) => e.alert.level === "watch");

  const paperPanel = pa && (
    <div className="panel">
      <h2>
        纸面账户{" "}
        <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>
          {pa.marked_at
            ? `· 报价截至 ${pa.marked_at.slice(0, 16).replace("T", " ")} UTC`
            : "· 等待首次每日任务"}
        </span>
      </h2>
      <div className="cards" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="label">Open Positions</div>
          <div className="value">{pa.positions.length}</div>
        </div>
        <div className="card">
          <div className="label">Cost Basis</div>
          <div className="value">${fmt(pa.cost)}</div>
        </div>
        <div className="card">
          <div className="label">Market Value</div>
          <div className="value">${fmt(pa.value)}</div>
        </div>
        <div className="card">
          <div className="label">Unrealized P&amp;L</div>
          <div className={`value ${pa.unrealized >= 0 ? "pos" : "neg"}`}>
            ${fmt(pa.unrealized)}
          </div>
        </div>
        <div className="card">
          <div className="label">Realized P&amp;L</div>
          <div className={`value ${pa.realized >= 0 ? "pos" : "neg"}`}>
            ${fmt(pa.realized)}
          </div>
        </div>
      </div>
      {pa.equity && pa.equity.length > 1 && (
        <div style={{ width: "100%", height: 220, marginBottom: 16 }}>
          <ResponsiveContainer>
            <LineChart data={pa.equity} margin={{ top: 4, right: 12, bottom: 0, left: 4 }}>
              <XAxis dataKey="date" tick={{ fill: "#8b93a5", fontSize: 11 }}
                     tickFormatter={(d) => d.slice(5)} minTickGap={40} />
              <YAxis tick={{ fill: "#8b93a5", fontSize: 11 }} width={64}
                     tickFormatter={(v) => `$${v}`} />
              <Tooltip
                contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 8 }}
                labelStyle={{ color: "#8b93a5" }}
                formatter={(v, name, item) => [
                  `$${fmt(v)}${item?.payload?.unrealized ? " (含浮盈)" : ""}`,
                  "累计盈亏",
                ]}
              />
              <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="4 4" />
              <Line dataKey="pnl" dot={{ r: 3, fill: "#f59e0b" }} isAnimationActive={false}
                    stroke={pa.equity[pa.equity.length - 1].pnl >= 0 ? "#22c55e" : "#ef4444"}
                    strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {pa.positions.length > 0 && (
        <div className="table-wrap" style={{ maxHeight: 320 }}>
          <table>
            <thead>
              <tr>
                <th>Symbol</th><th>Type</th><th className="num">Strike</th>
                <th>Expiry</th><th className="num">Entry</th>
                <th className="num">Mark</th><th>Quote</th>
                <th className="num"
                    style={{ cursor: "pointer", userSelect: "none" }}
                    title="Click to sort"
                    onClick={() => setSortDir(sortDir === "asc" ? "desc" : "asc")}>
                  Unrealized {sortDir === "asc" ? "▲" : "▼"}
                </th><th className="num">%</th>
              </tr>
            </thead>
            <tbody>
              {sortedPositions.map((p) => (
                <tr key={`${p.symbol}|${p.strategy || "ensemble"}`}>
                  <td>
                    <strong>{p.symbol}</strong>{" "}
                    <span className="muted" style={{ fontSize: 11 }}>
                      {p.strategy || "ensemble"}
                    </span>
                  </td>
                  <td><span className={`badge ${p.kind}`}>{p.kind}</span></td>
                  <td className="num">{fmt(p.strike)}</td>
                  <td className="mono">{p.expiry || "sim"}</td>
                  <td className="num">{fmt(p.entry_price)}</td>
                  <td className="num">{fmt(p.last_mark ?? p.entry_price)}</td>
                  <td>
                    <span className={`badge ${p.last_mark_source === "chain" ? "call" : "flat"}`}>
                      {p.last_mark_source || p.price_source || "—"}
                    </span>
                  </td>
                  <td className={`num ${(p.unrealized_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                    {p.unrealized_pnl != null ? `$${fmt(p.unrealized_pnl)}` : "—"}
                  </td>
                  <td className={`num ${(p.unrealized_pct ?? 0) >= 0 ? "pos" : "neg"}`}>
                    {p.unrealized_pct != null ? `${fmt(p.unrealized_pct)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  // ---- today focus panel ----
  const focusPanel = pa && (sigCounts || topLosers.length || nearExpiry.length) && (
    <div className="panel">
      <h2>今日焦点</h2>
      <div className="focus-grid">
        {sigCounts && (
          <div>
            <div className="label" style={{ marginBottom: 8 }}>最新信号分布</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <span className="badge call">CALL × {sigCounts.call}</span>
              <span className="badge put">PUT × {sigCounts.put}</span>
              <span className="badge flat">FLAT × {sigCounts.flat}</span>
            </div>
          </div>
        )}
        {topLosers.length > 0 && (
          <div>
            <div className="label" style={{ marginBottom: 8 }}>浮亏最多</div>
            {topLosers.map((p) => (
              <div key={`${p.symbol}|${p.strategy}`} className="focus-row">
                <strong>{p.symbol}</strong>
                <span className="muted" style={{ fontSize: 11 }}>{p.strategy || "ensemble"}</span>
                <span className={`badge ${p.kind}`}>{p.kind}</span>
                <span className="neg num" style={{ marginLeft: "auto" }}>
                  ${fmt(p.unrealized_pnl)}
                </span>
              </div>
            ))}
          </div>
        )}
        {nearExpiry.length > 0 && (
          <div>
            <div className="label" style={{ marginBottom: 8 }}>临近到期（≤3 个交易日）</div>
            {nearExpiry.map((p) => (
              <div key={`${p.symbol}|${p.strategy}`} className="focus-row">
                <strong>{p.symbol}</strong>
                <span className="muted" style={{ fontSize: 11 }}>{p.strategy || "ensemble"}</span>
                <span className={`badge ${p.kind}`}>{p.kind}</span>
                <span className="badge paper" style={{ marginLeft: "auto" }}>
                  DTE {p.dte_left}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  // merge curves into one series array for recharts
  const dateMap = {};
  strategies.forEach((s) => {
    (curves[s] || []).forEach((p) => {
      dateMap[p.date] = dateMap[p.date] || { date: p.date };
      dateMap[p.date][s] = p.pnl;
    });
  });
  const chartData = Object.values(dateMap).sort((a, b) =>
    a.date.localeCompare(b.date)
  );

  const allPnl = Object.values(heatmap).flatMap((r) => Object.values(r));
  const maxAbs = Math.max(...allPnl.map(Math.abs), 1);
  const heatColor = (v) => {
    if (v == null) return "transparent";
    const a = Math.min(Math.abs(v) / maxAbs, 1) * 0.55;
    return v >= 0 ? `rgba(34,197,94,${a})` : `rgba(239,68,68,${a})`;
  };

  return (
    <>
      <h1>期权账本</h1>
      <p className="subtitle">
        周期权纸面交易 · 每笔 $100 · 回测 2 年 BS 模拟 · 实盘按真实期权链报价结算
      </p>

      <div className="refresh-banner" role="status">
        <span className="pulse-dot" aria-hidden="true" />
        期权账本处于数据积累期：每日信号任务照常运行，平仓样本足够后统计结论才有意义。当前主线为
        <Link href="/" style={{ color: "var(--accent)", margin: "0 4px" }}>美股股票交易</Link>。
      </div>

      {(crits.length > 0 || watches.length > 0) && (
        <div className={`alert-banner ${crits.length ? "" : "watch"}`}>
          <h2>
            {crits.length
              ? `${crits.length} 个策略纸面战绩显著偏离回测基线`
              : `${watches.length} 个策略出现偏离迹象`}
          </h2>
          <p className="muted">
            {[...crits, ...watches]
              .map((e) => `${e.strategy}：${e.alert.reasons.join("；")}`)
              .join(" ｜ ")}
            {" · "}
            <Link href="/review" style={{ color: "var(--accent)" }}>
              查看复盘详情 →
            </Link>
          </p>
        </div>
      )}

      {paperPanel}

      {exposurePanel}

      {focusPanel}

      <div className="cards">
        <div className="card">
          <div className="label">Total P&amp;L (all strategies)</div>
          <div className={`value ${totals.total_pnl >= 0 ? "pos" : "neg"}`}>
            ${fmt(totals.total_pnl)}
          </div>
        </div>
        <div className="card">
          <div className="label">Backtest Trades</div>
          <div className="value">{fmt(totals.backtest_trades)}</div>
        </div>
        <div className="card">
          <div className="label">Symbols</div>
          <div className="value">{symbols.length}</div>
        </div>
        <div className="card">
          <div className="label">Strategies</div>
          <div className="value">{strategies.length}</div>
        </div>
        <div className="card">
          <div className="label">Paper Trades</div>
          <div className="value">{totals.paper_trades}</div>
        </div>
      </div>

      <div className="panel">
        <h2>策略排行（回测 2 年汇总 + 实盘状态）</h2>
        <table>
          <thead>
            <tr>
              <th>#</th><th>Strategy</th><th className="num">Trades</th>
              <th className="num">Win Rate</th><th className="num">Total P&amp;L</th>
              <th className="num">Avg P&amp;L</th><th className="num">Profit Factor</th>
              <th>实盘状态</th>
            </tr>
          </thead>
          <tbody>
            {leaderboard.map((r, i) => {
              const al = alertByStrat[r.strategy];
              return (
                <tr key={r.strategy}>
                  <td className="muted">{i + 1}</td>
                  <td>{STRAT_LABELS[r.strategy] || r.strategy}</td>
                  <td className="num">{r.trades}</td>
                  <td className="num">{r.win_rate}%</td>
                  <td className={`num ${r.total_pnl >= 0 ? "pos" : "neg"}`}>
                    ${fmt(r.total_pnl)}
                  </td>
                  <td className={`num ${r.avg_pnl >= 0 ? "pos" : "neg"}`}>
                    ${fmt(r.avg_pnl)}
                  </td>
                  <td className="num">{r.profit_factor ?? "∞"}</td>
                  <td>
                    {al && (
                      <span className={`badge alert-${al.level}`}
                            title={al.reasons.join("；") || undefined}>
                        {al.label}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>回测累计盈亏（按策略）</h2>
        <div style={{ width: "100%", height: 360 }}>
          <ResponsiveContainer>
            <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
              <XAxis dataKey="date" tick={{ fill: "#8b93a5", fontSize: 11 }}
                     tickFormatter={(d) => d.slice(2, 7)} minTickGap={60} />
              <YAxis tick={{ fill: "#8b93a5", fontSize: 11 }}
                     tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} width={56} />
              <Tooltip
                contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 8 }}
                labelStyle={{ color: "#8b93a5" }}
                formatter={(v, name) => [`$${fmt(v)}`, STRAT_LABELS[name] || name]}
              />
              <Legend formatter={(v) => STRAT_LABELS[v] || v} />
              {strategies.map((s, i) => (
                <Line key={s} dataKey={s} stroke={COLORS[i % COLORS.length]}
                      dot={false} isAnimationActive={false}
                      strokeWidth={s === "ensemble" ? 2.5 : 1.5} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="panel">
        <h2>标的 × 策略 盈亏热力图（回测）</h2>
        <div
          className="heat"
          style={{ gridTemplateColumns: `90px repeat(${strategies.length}, 1fr)` }}
        >
          <div className="heat-cell heat-head"></div>
          {strategies.map((s) => (
            <div key={s} className="heat-cell heat-head">{STRAT_LABELS[s] || s}</div>
          ))}
          {symbols.map((sym) => (
            <Fragment key={sym}>
              <div className="heat-cell heat-head" style={{ textAlign: "left" }}>
                {sym}
              </div>
              {strategies.map((s) => {
                const v = heatmap[sym]?.[s];
                return (
                  <div key={`${sym}-${s}`} className="heat-cell"
                       style={{ background: heatColor(v) }}>
                    {v == null ? "—" : fmt(v)}
                  </div>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>
    </>
  );
}
