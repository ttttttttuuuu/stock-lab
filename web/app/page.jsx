"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { FlaskConical, RotateCw, Trophy, TrendingUp } from "lucide-react";
import { loadStockLab, loadStockPaper, loadProductionParams, invalidatePrefix } from "../lib/data";
import { STRAT_LABELS, INTERVAL_LABEL } from "../lib/stratLabels";
import Skeleton from "../components/Skeleton";

const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });

export default function StockDashboard() {
  const [data, setData] = useState(null);
  const [paper, setPaper] = useState(null);
  const [prod, setProd] = useState(null);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [evolveRunning, setEvolveRunning] = useState(false);
  const [evolveStale, setEvolveStale] = useState(false);
  const [evolveRunAt, setEvolveRunAt] = useState(null);

  useEffect(() => {
    loadStockLab().then(setData).catch((e) => setError(String(e)));
    loadStockPaper().then(setPaper).catch(() => {}); // panel degrades gracefully
    loadProductionParams().then(setProd).catch(() => {}); // watchlist degrades to none
    // evolution freshness: remind when the last full evolution wasn't today
    fetch("/api/evolve/refresh").then((r) => r.json()).then((s) => {
      setEvolveRunning(!!s.running);
      setEvolveRunAt(s.run_at || null);
      const d = s.run_at ? new Date(s.run_at) : null;
      const now = new Date();
      const fresh = d && d.getFullYear() === now.getFullYear()
        && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
      setEvolveStale(!fresh);
    }).catch(() => {}); // API unavailable (static hosting) — hide reminder
  }, []);

  // poll while an evolution run is in progress, then reload everything
  useEffect(() => {
    if (!evolveRunning) return undefined;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const s = await (await fetch("/api/evolve/refresh")).json();
        if (!s.running) {
          clearInterval(timer);
          ["stocklab", "stpair", "prices", "stockpaper", "paramopt", "exitopt", "prodparams"]
            .forEach(invalidatePrefix);
          const d = await loadStockLab();
          const p = await loadStockPaper().catch(() => null);
          const pr = await loadProductionParams().catch(() => null);
          if (!cancelled) {
            setData(d); if (p) setPaper(p); if (pr) setProd(pr);
            setEvolveRunning(false); setEvolveStale(false);
            setEvolveRunAt(s.run_at || null);
          }
        }
      } catch {
        clearInterval(timer);
        if (!cancelled) setEvolveRunning(false);
      }
    }, 15000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [evolveRunning]);

  const startEvolve = async () => {
    setEvolveRunning(true);
    try {
      const r = await (await fetch("/api/evolve/refresh?force=1", { method: "POST" })).json();
      if (r.status !== "started" && r.status !== "running") setEvolveRunning(false);
    } catch {
      setEvolveRunning(false);
    }
  };

  // Lazy daily refresh: if the matrix wasn't computed today, the first
  // visitor triggers the engine and polls until done; everyone else reads DB.
  useEffect(() => {
    if (!data) return undefined;
    const runAt = data.run_at ? new Date(data.run_at) : null;
    const now = new Date();
    const fresh = runAt
      && runAt.getFullYear() === now.getFullYear()
      && runAt.getMonth() === now.getMonth()
      && runAt.getDate() === now.getDate();
    if (fresh) return undefined;

    let cancelled = false;
    let failures = 0;
    setRefreshing(true);
    fetch("/api/stock-lab/refresh", { method: "POST" }).catch(() => {});
    const timer = setInterval(async () => {
      try {
        const s = await (await fetch("/api/stock-lab/refresh")).json();
        if (!s.running) {
          clearInterval(timer);
          ["stocklab", "stpair", "prices", "stockpaper"].forEach(invalidatePrefix);
          const d = await loadStockLab();
          const p = await loadStockPaper().catch(() => null);
          if (!cancelled) { setData(d); if (p) setPaper(p); setRefreshing(false); }
        }
      } catch {
        if (++failures >= 2) {
          clearInterval(timer);
          if (!cancelled) setRefreshing(false);
        }
      }
    }, 15000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [data?.run_at]); // eslint-disable-line react-hooks/exhaustive-deps

  // per-strategy rollup across all symbols
  const stratRollup = useMemo(() => {
    if (!data) return [];
    const byStrat = {};
    data.pairs.forEach((p) => {
      if (!p.trades) return;
      const e = byStrat[p.strategy] || (byStrat[p.strategy] = {
        strategy: p.strategy, trades: 0, winSum: 0, total_pnl: 0,
      });
      e.trades += p.trades;
      e.winSum += (p.win_rate || 0) * p.trades;
      e.total_pnl += p.total_pnl || 0;
    });
    return Object.values(byStrat)
      .map((e) => ({
        ...e,
        win_rate: e.trades ? Math.round((e.winSum / e.trades) * 10) / 10 : 0,
        total_pnl: Math.round(e.total_pnl * 100) / 100,
      }))
      .sort((a, b) => b.total_pnl - a.total_pnl);
  }, [data]);

  if (error)
    return <div className="panel"><h2>数据加载失败</h2><p className="muted">{error}</p></div>;
  if (!data) return <Skeleton variant="dashboard" />;

  const wl = new Set(prod?.watchlist || []);
  const active = data.pairs.filter((p) => p.trades > 0);
  const eligible = active.filter((p) => !wl.has(p.strategy));
  const top10 = eligible.slice(0, 10);
  const top20 = eligible.slice(0, 20);
  const backtestTotal = Math.round(active.reduce((a, p) => a + (p.total_pnl || 0), 0) * 100) / 100;
  const symbols = new Set(data.pairs.map((p) => p.symbol)).size;

  const spOpen = paper?.positions?.length ?? 0;
  const spUnrealized = paper
    ? paper.positions.reduce((a, p) => a + (p.unrealized_pnl ?? 0), 0) : 0;
  const spRealized = paper
    ? paper.closed_trades.reduce((a, t) => a + (t.pnl || 0), 0) : 0;
  const spTotal = spRealized + spUnrealized;

  return (
    <>
      <h1>仪表盘</h1>
      <p className="subtitle">
        美股短线 · 每笔 $100 名义本金 · {stratRollup.length} 策略 × {symbols} 只股票 ·
        日线信号 · 2 年回测 + Top20 实时纸面验证
      </p>
      <p style={{ margin: "-12px 0 20px", display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Link href="/lab/optimize" className="btn">
          <FlaskConical size={13} aria-hidden="true" /> 参数寻优
        </Link>
        <button className="btn" onClick={startEvolve} disabled={evolveRunning}>
          <RotateCw size={13} aria-hidden="true" /> 进化更新
        </button>
        <Link href="/lab" className="btn">
          <TrendingUp size={13} aria-hidden="true" /> 选股实验室
        </Link>
      </p>

      {refreshing && (
        <div className="refresh-banner" role="status">
          <span className="pulse-dot" aria-hidden="true" />
          数据不是今天的，正在后台拉取最新股价并重跑回测（约 1–2 分钟），完成后自动刷新…
        </div>
      )}

      {evolveRunning && (
        <div className="refresh-banner" role="status">
          <span className="pulse-dot" aria-hidden="true" />
          正在进化更新：全量补抓价格 → 重跑参数 + 出场网格 → 样本外守卫晋升 → 重跑回测（约 15–20 分钟），完成后自动刷新…
        </div>
      )}

      {!evolveRunning && evolveStale && (
        <div className="refresh-banner" role="status" style={{ justifyContent: "space-between" }}>
          <span>
            ⚠️ 策略参数数据不是最新的（上次进化：{evolveRunAt ? new Date(evolveRunAt).toLocaleString("zh-CN", { hour12: false }) : "从未"}）。
            进化更新会把价格从最后数据日补抓到今天，并重跑全部寻优与晋升判断。
          </span>
          <button className="btn primary" onClick={startEvolve} style={{ flexShrink: 0 }}>
            <RotateCw size={13} aria-hidden="true" /> 立即进化更新
          </button>
        </div>
      )}

      <div className="stat-strip">
        <div className="stat-item">
          <span className="label">回测总盈亏（全矩阵）</span>
          <strong className={backtestTotal >= 0 ? "pos" : "neg"}>
            {backtestTotal >= 0 ? "+" : ""}${fmt(backtestTotal)}
          </strong>
        </div>
        <div className="stat-item">
          <span className="label">验证账本 · 在仓</span>
          <strong>{spOpen}</strong>
        </div>
        <div className="stat-item">
          <span className="label">验证账本 · 浮盈</span>
          <strong className={spUnrealized >= 0 ? "pos" : "neg"}>
            {spUnrealized >= 0 ? "+" : ""}${fmt(Math.round(spUnrealized * 100) / 100)}
          </strong>
        </div>
        <div className="stat-item">
          <span className="label">验证账本 · 已实现</span>
          <strong className={spRealized >= 0 ? "pos" : "neg"}>
            {spRealized >= 0 ? "+" : ""}${fmt(Math.round(spRealized * 100) / 100)}
          </strong>
        </div>
        <div className="stat-item">
          <span className="label">验证账本 · 合计</span>
          <strong className={spTotal >= 0 ? "pos" : "neg"}>
            {spTotal >= 0 ? "+" : ""}${fmt(Math.round(spTotal * 100) / 100)}
          </strong>
        </div>
      </div>

      <div className="panel">
        <h2><Trophy size={15} style={{ verticalAlign: "-2px", marginRight: 6 }} aria-hidden="true" />
          Top 10 策略 × 股票配对</h2>
        <p className="hint">按 2 年回测总盈亏排序 · 点击查看完整交易明细与 K 线标注</p>
        <div className="pair-grid">
          {top10.map((p, i) => (
            <Link key={`${p.strategy}-${p.symbol}`} href={`/lab/${p.strategy}/${p.symbol}`}
                  className="pair-card" aria-label={`第${i + 1}名 ${p.symbol} ${STRAT_LABELS[p.strategy] || p.strategy}`}>
              <span className={`rank-badge ${i < 3 ? "top" : ""}`}>{i + 1}</span>
              <div className="pair-head">
                <strong>{p.symbol}</strong>
                <span className="badge backtest">{STRAT_LABELS[p.strategy] || p.strategy}</span>
                <span className="badge flat">{INTERVAL_LABEL}</span>
              </div>
              <div className={`pair-pnl ${p.total_pnl >= 0 ? "pos" : "neg"}`}>
                ${fmt(p.total_pnl)}
              </div>
              <div className="pair-meta">
                <span>胜率 {fmt(p.win_rate, 1)}%</span>
                <span>{p.trades} 笔</span>
                <span>PF {fmt(p.profit_factor)}</span>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {paper && (paper.positions.length > 0 || paper.closed_trades.length > 0) && (
        <div className="panel">
          <h2>Top20 实盘验证账本（股票纸面 · $100/笔）</h2>
          <p className="hint">
            信号每日自动开平仓，规则与回测完全一致（策略级止盈止损 / 最长持有 10 个交易日）
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th><th>配对</th>
                  <th className="num">回测总盈亏</th>
                  <th>实盘状态</th>
                  <th className="num">浮盈</th>
                  <th className="num">已实现</th>
                  <th className="num">实盘合计</th>
                </tr>
              </thead>
              <tbody>
                {top20.map((p, i) => {
                  const key = `${p.symbol}|${p.strategy}`;
                  const pos = paper.positions.find((x) => x.key === key);
                  const closedN = paper.closed_trades.filter(
                    (t) => t.symbol === p.symbol && t.strategy === p.strategy);
                  const realized = closedN.reduce((a, t) => a + (t.pnl || 0), 0);
                  const unrealized = pos?.unrealized_pnl ?? 0;
                  const liveTotal = realized + unrealized;
                  return (
                    <tr key={key}>
                      <td className="muted">{i + 1}</td>
                      <td>
                        <Link href={`/lab/${p.strategy}/${p.symbol}`} className="sym-link">
                          <strong>{p.symbol}</strong>
                        </Link>{" "}
                        <span className="badge backtest">{STRAT_LABELS[p.strategy] || p.strategy}</span>{" "}
                        <span className="badge flat">{INTERVAL_LABEL}</span>
                      </td>
                      <td className={`num ${p.total_pnl >= 0 ? "pos" : "neg"}`}>
                        ${fmt(p.total_pnl)}
                      </td>
                      <td>
                        {pos ? (
                          <>
                            <span className={`badge ${pos.side === "long" ? "call" : "put"}`}>
                              {pos.side === "long" ? "多" : "空"}
                            </span>{" "}
                            <span className="muted" style={{ fontSize: 11 }}>
                              @ ${fmt(pos.entry_price)} · {pos.entry_date}
                            </span>
                          </>
                        ) : (
                          <span className="badge flat">观望</span>
                        )}
                      </td>
                      <td className={`num ${unrealized >= 0 ? "pos" : "neg"}`}>
                        {pos ? `${unrealized >= 0 ? "+" : ""}$${fmt(unrealized)}` : "—"}
                      </td>
                      <td className={`num ${realized >= 0 ? "pos" : "neg"}`}>
                        {closedN.length
                          ? `${realized >= 0 ? "+" : ""}$${fmt(realized)} (${closedN.length}笔)`
                          : "—"}
                      </td>
                      <td className={`num ${liveTotal >= 0 ? "pos" : "neg"}`}>
                        <strong>
                          {pos || closedN.length
                            ? `${liveTotal >= 0 ? "+" : ""}$${fmt(liveTotal)}`
                            : "—"}
                        </strong>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="panel">
        <h2>策略排行（回测 2 年 · 全股票汇总）</h2>
        <table>
          <thead>
            <tr>
              <th>#</th><th>策略</th><th className="num">交易笔数</th>
              <th className="num">胜率</th><th className="num">总盈亏</th>
            </tr>
          </thead>
          <tbody>
            {stratRollup.map((r, i) => (
              <tr key={r.strategy}>
                <td className="muted">{i + 1}</td>
                <td>
                  {STRAT_LABELS[r.strategy] || r.strategy}
                  {wl.has(r.strategy) && (
                    <span className="badge flat" style={{ marginLeft: 6 }}
                          title="观察名单：全窗口表现不达标且重寻优未通过守卫，已移出 Top 配对选拔">
                      观察中
                    </span>
                  )}
                </td>
                <td className="num">{r.trades}</td>
                <td className="num">{r.win_rate}%</td>
                <td className={`num ${r.total_pnl >= 0 ? "pos" : "neg"}`}>
                  <strong>${fmt(r.total_pnl)}</strong>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>期权账本（数据积累中）</h2>
        <p className="hint">
          周期权纸面账本每日照常运行并积累真实链上报价样本，平仓样本足够后再评估策略有效性。
          {" "}<Link href="/options" style={{ color: "var(--accent)" }}>查看期权仪表盘 →</Link>
        </p>
      </div>
    </>
  );
}
