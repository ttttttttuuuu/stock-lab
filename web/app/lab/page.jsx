"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowUpDown, FlaskConical, RotateCw, Trophy, Search } from "lucide-react";
import { loadStockLab, loadStockPaper, loadProductionParams, invalidatePrefix, IS_STATIC } from "../../lib/data";
import { INTERVAL_LABEL } from "../../lib/stratLabels";
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

const COLUMNS = [
  { key: "symbol", label: "股票" },
  { key: "strategy", label: "策略" },
  { key: "trades", label: "笔数", num: true },
  { key: "win_rate", label: "胜率", num: true },
  { key: "avg_pnl", label: "均盈亏", num: true },
  { key: "profit_factor", label: "盈亏比", num: true },
  { key: "max_drawdown", label: "最大回撤", num: true },
  { key: "total_pnl", label: "总盈亏", num: true },
];

export default function StockLab() {
  const [data, setData] = useState(null);
  const [paper, setPaper] = useState(null);
  const [prod, setProd] = useState(null);
  const [error, setError] = useState(null);
  const [strategy, setStrategy] = useState("all");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("total_pnl");
  const [sortDir, setSortDir] = useState(-1);
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
  // visitor triggers the engine (fetch prices -> backtest -> sync DB) and
  // polls until done; everyone else just reads the DB.
  useEffect(() => {
    if (!data || IS_STATIC) return undefined;
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
          invalidatePrefix("stocklab");
          invalidatePrefix("stpair");
          invalidatePrefix("prices");
          invalidatePrefix("stockpaper");
          const d = await loadStockLab();
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
  }, [data?.run_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const pairs = useMemo(() => {
    if (!data) return [];
    let rows = data.pairs.filter((p) => p.trades > 0);
    if (strategy !== "all") rows = rows.filter((p) => p.strategy === strategy);
    if (query.trim()) {
      const q = query.trim().toUpperCase();
      rows = rows.filter((p) => p.symbol.includes(q));
    }
    const col = COLUMNS.find((c) => c.key === sortKey);
    rows = [...rows].sort((a, b) => {
      const av = a[sortKey] ?? (col?.num ? -Infinity : "");
      const bv = b[sortKey] ?? (col?.num ? -Infinity : "");
      return (av > bv ? 1 : av < bv ? -1 : 0) * sortDir;
    });
    return rows;
  }, [data, strategy, query, sortKey, sortDir]);

  if (error)
    return <div className="panel"><h2>数据加载失败</h2><p className="muted">{error}</p></div>;
  if (!data) return <Skeleton variant="dashboard" />;

  const wl = new Set(prod?.watchlist || []);
  const eligible = data.pairs.filter((p) => p.trades > 0 && !wl.has(p.strategy));
  const top10 = eligible.slice(0, 10);
  const top20 = eligible.slice(0, 20);
  const strategies = [...new Set(data.pairs.map((p) => p.strategy))];
  const symbols = new Set(data.pairs.map((p) => p.symbol)).size;
  const toggleSort = (key) => {
    if (sortKey === key) setSortDir((d) => -d);
    else { setSortKey(key); setSortDir(key === "symbol" || key === "strategy" ? 1 : -1); }
  };

  return (
    <>
      <h1>策略</h1>
      <p className="subtitle">
        10 策略（含 4 个 TradingView 热门候选）× {symbols} 只股票 · 股价回测（非期权）· 每笔 $100 名义本金 ·
        策略级止盈止损 / 最长持有 10 个交易日
      </p>
      <p style={{ margin: "-12px 0 20px", display: "flex", gap: 10, flexWrap: "wrap" }}>
        <Link href="/lab/optimize" className="btn">
          <FlaskConical size={13} aria-hidden="true" /> 参数寻优：网格搜索最优参数
        </Link>
        {!IS_STATIC && (
          <button className="btn" onClick={startEvolve} disabled={evolveRunning}>
            <RotateCw size={13} aria-hidden="true" /> 进化更新
          </button>
        )}
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
          <span className="label">有效配对</span>
          <strong>{data.pairs.filter((p) => p.trades > 0).length}</strong>
        </div>
        <div className="stat-item">
          <span className="label">策略</span>
          <strong>{strategies.length}</strong>
        </div>
        <div className="stat-item">
          <span className="label">股票</span>
          <strong>{symbols}</strong>
        </div>
        <div className="stat-item">
          <span className="label">回测时间</span>
          <strong style={{ fontSize: 14 }}>
            {data.run_at ? new Date(data.run_at).toLocaleString("zh-CN", { hour12: false }) : "—"}
          </strong>
        </div>
      </div>

      <div className="panel">
        <h2><Trophy size={15} style={{ verticalAlign: "-2px", marginRight: 6 }} aria-hidden="true" />
          Top 10 策略 × 股票配对</h2>
        <p className="hint">按总盈亏排序 · 点击查看完整交易明细与 K 线标注</p>
        <div className="pair-grid">
          {top10.map((p, i) => (
            <Link key={`${p.strategy}-${p.symbol}`} href={`/lab/pair?strategy=${p.strategy}&symbol=${p.symbol}`}
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
          <h2>Top20 实盘验证（股票纸面 · $100/笔）</h2>
          <p className="hint">
            选股 → 验证 → 跟踪闭环：Top 配对的信号每日自动开平仓，规则与回测完全一致（策略级止盈止损 / 最长持有 10 个交易日）
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
                        <Link href={`/lab/pair?strategy=${p.strategy}&symbol=${p.symbol}`} className="sym-link">
                          <strong>{p.symbol}</strong>
                        </Link>{" "}
                        <span className="badge backtest">{STRAT_LABELS[p.strategy] || p.strategy}</span>
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
        <h2>全部配对排行</h2>
        <div className="filters" style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)} aria-label="按策略筛选">
            <option value="all">全部策略</option>
            {strategies.map((s) => (
              <option key={s} value={s}>{STRAT_LABELS[s] || s}</option>
            ))}
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Search size={14} aria-hidden="true" />
            <input value={query} onChange={(e) => setQuery(e.target.value)}
                   placeholder="搜索股票代码…" aria-label="搜索股票代码" />
          </label>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                {COLUMNS.map((c) => (
                  <th key={c.key} onClick={() => toggleSort(c.key)}
                      style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}
                      aria-sort={sortKey === c.key ? (sortDir === 1 ? "ascending" : "descending") : undefined}>
                    {c.label} <ArrowUpDown size={11} style={{ verticalAlign: "-1px", opacity: sortKey === c.key ? 1 : 0.35 }} aria-hidden="true" />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pairs.map((p, i) => (
                <tr key={`${p.strategy}-${p.symbol}`}>
                  <td className="muted">{i + 1}</td>
                  <td>
                    <Link href={`/lab/pair?strategy=${p.strategy}&symbol=${p.symbol}`} className="sym-link">
                      <strong>{p.symbol}</strong>
                    </Link>
                  </td>
                  <td><span className="badge backtest">{STRAT_LABELS[p.strategy] || p.strategy}</span>{" "}
                      <span className="badge flat">{INTERVAL_LABEL}</span>
                      {wl.has(p.strategy) && (
                        <span className="badge flat" style={{ marginLeft: 4 }}
                              title="观察名单：全窗口表现不达标且重寻优未通过守卫，已移出 Top 配对选拔">
                          观察中
                        </span>
                      )}
                  </td>
                  <td>{p.trades}</td>
                  <td>{fmt(p.win_rate, 1)}%</td>
                  <td className={p.avg_pnl >= 0 ? "pos" : "neg"}>${fmt(p.avg_pnl)}</td>
                  <td>{fmt(p.profit_factor)}</td>
                  <td className="neg">${fmt(p.max_drawdown)}</td>
                  <td className={p.total_pnl >= 0 ? "pos" : "neg"}><strong>${fmt(p.total_pnl)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          共 {pairs.length} 个配对 · 空头交易为模拟卖空（未计借券成本）· 点击股票代码进入详情
        </p>
      </div>
    </>
  );
}
