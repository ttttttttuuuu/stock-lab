"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowUpDown, FlaskConical, RotateCw, Search } from "lucide-react";
import { loadParamOpt, loadExitOpt, invalidatePrefix, IS_STATIC } from "../../../lib/data";
import Skeleton from "../../../components/Skeleton";

const STRAT_LABELS = {
  sma_cross: "SMA Cross",
  rsi_reversion: "RSI Mean Reversion",
  macd_trend: "MACD Trend",
  bb_breakout: "Bollinger Breakout",
  supertrend: "SuperTrend",
  ut_bot: "UT Bot (ATR)",
  ttm_squeeze: "TTM Squeeze",
  wavetrend: "WaveTrend",
  natural_trade: "自然交易 (Fib引力)",
};

const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });

function ParamChips({ params }) {
  return (
    <span>
      {Object.entries(params).map(([k, v]) => (
        <span key={k} className="param-chip">{k}={v}</span>
      ))}
    </span>
  );
}

export default function ParamOptimize() {
  const [data, setData] = useState(null);
  const [exitData, setExitData] = useState(null);
  const [error, setError] = useState(null);
  const [strategy, setStrategy] = useState("supertrend");
  const [gridSort, setGridSort] = useState("total_pnl");
  const [exitStrategy, setExitStrategy] = useState("all");
  const [pairStrategy, setPairStrategy] = useState("all");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("delta");
  const [sortDir, setSortDir] = useState(-1);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    loadParamOpt().then(setData).catch((e) => setError(String(e)));
    loadExitOpt().then(setExitData).catch(() => {}); // panel degrades gracefully
  }, []);

  // poll while an evolution run is in progress (triggered by the button)
  useEffect(() => {
    if (!running) return undefined;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const s = await (await fetch("/api/evolve/refresh")).json();
        if (!s.running) {
          clearInterval(timer);
          ["paramopt", "exitopt", "stocklab", "stpair", "prices", "stockpaper"]
            .forEach(invalidatePrefix);
          const d = await loadParamOpt();
          const ex = await loadExitOpt().catch(() => null);
          if (!cancelled) { setData(d); if (ex) setExitData(ex); setRunning(false); }
        }
      } catch {
        clearInterval(timer);
        if (!cancelled) setRunning(false);
      }
    }, 15000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [running]);

  const startRun = async () => {
    setRunning(true);
    try {
      const r = await (await fetch("/api/evolve/refresh?force=1", { method: "POST" })).json();
      if (r.status !== "started" && r.status !== "running") setRunning(false);
    } catch {
      setRunning(false);
    }
  };

  const strategies = useMemo(
    () => (data ? Object.keys(data.strategies).sort() : []), [data]);

  const grid = useMemo(() => {
    if (!data) return [];
    const rows = [...(data.strategies[strategy] || [])];
    rows.sort((a, b) => (b[gridSort] ?? -Infinity) - (a[gridSort] ?? -Infinity));
    return rows;
  }, [data, strategy, gridSort]);

  const exitGrid = useMemo(() => {
    if (!exitData) return [];
    const rows = exitStrategy === "all"
      ? [...(exitData.global || [])]
      : [...(exitData.strategies[exitStrategy] || [])];
    rows.sort((a, b) => (b[gridSort] ?? -Infinity) - (a[gridSort] ?? -Infinity));
    return rows;
  }, [exitData, exitStrategy, gridSort]);

  const pairs = useMemo(() => {
    if (!data) return [];
    let rows = data.pairs;
    if (pairStrategy !== "all") rows = rows.filter((p) => p.strategy === pairStrategy);
    if (query.trim()) {
      const q = query.trim().toUpperCase();
      rows = rows.filter((p) => p.symbol.includes(q));
    }
    rows = [...rows].sort((a, b) => {
      const av = a[sortKey] ?? -Infinity;
      const bv = b[sortKey] ?? -Infinity;
      return (av > bv ? 1 : av < bv ? -1 : 0) * sortDir;
    });
    return rows;
  }, [data, pairStrategy, query, sortKey, sortDir]);

  if (error)
    return <div className="panel"><h2>数据加载失败</h2><p className="muted">{error}</p></div>;
  if (!data) return <Skeleton variant="dashboard" />;

  const improved = data.pairs.filter((p) => p.delta > 0).length;
  const totalCombos = Object.values(data.strategies)
    .reduce((a, g) => a + g.reduce((x, c) => x + c.symbols, 0), 0);
  const runDate = data.run_at ? new Date(data.run_at) : null;
  const now = new Date();
  const stale = !runDate
    || runDate.getFullYear() !== now.getFullYear()
    || runDate.getMonth() !== now.getMonth()
    || runDate.getDate() !== now.getDate();
  const toggleSort = (key) => {
    if (sortKey === key) setSortDir((d) => -d);
    else { setSortKey(key); setSortDir(-1); }
  };
  const PAIR_COLUMNS = [
    { key: "symbol", label: "股票" },
    { key: "strategy", label: "策略" },
    { key: "default_pnl", label: "默认参数盈亏", num: true },
    { key: "best_pnl", label: "最优参数盈亏", num: true },
    { key: "delta", label: "提升", num: true },
  ];

  return (
    <>
      <h1>
        <FlaskConical size={20} style={{ verticalAlign: "-3px", marginRight: 8, color: "var(--accent)" }} aria-hidden="true" />
        参数寻优
      </h1>
      <p className="subtitle">
        {strategies.length} 策略 × 参数网格 × {new Set(data.pairs.map((p) => p.symbol)).size} 只股票 ·
        与选股实验室同一回测引擎 · 默认参数为基线 ·
        <Link href="/lab" style={{ color: "var(--accent)" }}>
          <ArrowLeft size={12} style={{ verticalAlign: "-1px" }} aria-hidden="true" /> 返回实验室
        </Link>
      </p>

      {running && (
        <div className="refresh-banner" role="status">
          <span className="pulse-dot" aria-hidden="true" />
          正在进化更新：从最后数据日补抓全部价格到今天 → 重跑参数 + 出场网格 → 样本外守卫晋升 → 重跑回测（约 15–20 分钟），完成后自动刷新…
        </div>
      )}

      {!running && stale && (
        <div className="refresh-banner" role="status" style={{ justifyContent: "space-between" }}>
          <span>
            ⚠️ 数据不是最新的（最后更新：{runDate ? runDate.toLocaleString("zh-CN", { hour12: false }) : "从未"}）。
            进化更新会把价格从最后数据日补抓到今天，并重跑全部寻优。
          </span>
          <button className="btn primary" onClick={startRun} style={{ flexShrink: 0 }}>
            <RotateCw size={13} aria-hidden="true" /> 立即进化更新
          </button>
        </div>
      )}

      <div className="stat-strip">
        <div className="stat-item">
          <span className="label">参数组合</span>
          <strong>{totalCombos.toLocaleString()}</strong>
        </div>
        <div className="stat-item">
          <span className="label">策略</span>
          <strong>{strategies.length}</strong>
        </div>
        <div className="stat-item">
          <span className="label">跑赢默认的配对</span>
          <strong>{improved} / {data.pairs.length}</strong>
        </div>
        <div className="stat-item">
          <span className="label">寻优时间</span>
          <strong style={{ fontSize: 14 }}>
            {data.run_at ? new Date(data.run_at).toLocaleString("zh-CN", { hour12: false }) : "—"}
          </strong>
        </div>
        {!IS_STATIC && (
          <div className="stat-item" style={{ justifyContent: "center" }}>
            <button className="btn primary" onClick={startRun} disabled={running}>
              <RotateCw size={13} aria-hidden="true" /> 进化更新
            </button>
          </div>
        )}
      </div>

      <div className="panel">
        <h2>全局参数榜</h2>
        <p className="hint">
          同一参数在全部股票上的合计表现 · 排名靠前且稳定的参数才有参考价值（单只股票的最优容易是过拟合）
        </p>
        <div className="filters" style={{ alignItems: "center" }}>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)} aria-label="选择策略">
            {strategies.map((s) => (
              <option key={s} value={s}>{STRAT_LABELS[s] || s}</option>
            ))}
          </select>
          <span className="muted" style={{ fontSize: 12 }}>排序:</span>
          {[["total_pnl", "总盈亏"], ["win_rate", "胜率"], ["avg_pnl", "每笔期望"]].map(([k, label]) => (
            <button key={k} className={`btn ${gridSort === k ? "primary" : ""}`}
                    style={{ padding: "4px 10px", fontSize: 12 }}
                    onClick={() => setGridSort(k)} aria-pressed={gridSort === k}>
              {label}
            </button>
          ))}
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th><th>参数</th>
                <th className="num">笔数</th>
                <th className="num">胜率</th>
                <th className="num">均盈亏</th>
                <th className="num">盈亏比</th>
                <th className="num">总盈亏</th>
              </tr>
            </thead>
            <tbody>
              {grid.map((g, i) => (
                <tr key={JSON.stringify(g.params)} className={g.is_default ? "row-default" : ""}>
                  <td className="muted">{i + 1}</td>
                  <td>
                    <ParamChips params={g.params} />
                    {g.is_default && <span className="badge backtest">默认</span>}
                  </td>
                  <td className="num">{g.trades.toLocaleString()}</td>
                  <td className="num">{fmt(g.win_rate, 1)}%</td>
                  <td className={`num ${g.avg_pnl >= 0 ? "pos" : "neg"}`}>${fmt(g.avg_pnl)}</td>
                  <td className="num">{fmt(g.profit_factor)}</td>
                  <td className={`num ${g.total_pnl >= 0 ? "pos" : "neg"}`}>
                    <strong>${fmt(g.total_pnl)}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {exitData && exitGrid.length > 0 && (
        <div className="panel">
          <h2>出场结构寻优</h2>
          <p className="hint">
            入场信号固定为生产默认参数，只变止盈/止损 · 与参数榜共用排序切换 · 单策略视图下高亮行 = 该策略当前生产出场
          </p>
          <div className="filters">
            <select value={exitStrategy} onChange={(e) => setExitStrategy(e.target.value)} aria-label="选择策略查看出场结构">
              <option value="all">全部策略合计</option>
              {strategies.map((s) => (
                <option key={s} value={s}>{STRAT_LABELS[s] || s}</option>
              ))}
            </select>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th><th>止盈 / 止损</th>
                  <th className="num">笔数</th>
                  <th className="num">胜率</th>
                  <th className="num">均盈亏</th>
                  <th className="num">盈亏比</th>
                  <th className="num">总盈亏</th>
                </tr>
              </thead>
              <tbody>
                {exitGrid.map((g, i) => (
                  <tr key={`${g.take_profit}-${g.stop_loss}`} className={g.is_default ? "row-default" : ""}>
                    <td className="muted">{i + 1}</td>
                    <td>
                      <span className="param-chip">tp +{Math.round(g.take_profit * 100)}%</span>
                      <span className="param-chip">sl {Math.round(g.stop_loss * 100)}%</span>
                      {g.is_default && <span className="badge backtest">默认</span>}
                    </td>
                    <td className="num">{g.trades.toLocaleString()}</td>
                    <td className="num">{fmt(g.win_rate, 1)}%</td>
                    <td className={`num ${g.avg_pnl >= 0 ? "pos" : "neg"}`}>${fmt(g.avg_pnl)}</td>
                    <td className="num">{fmt(g.profit_factor)}</td>
                    <td className={`num ${g.total_pnl >= 0 ? "pos" : "neg"}`}>
                      <strong>${fmt(g.total_pnl)}</strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="panel">
        <h2>配对寻优提升榜</h2>
        <p className="hint">
          每对 股票 × 策略：网格最优参数相对默认参数的盈亏提升 · 样本内结果，仅供筛选参考
        </p>
        <div className="filters">
          <select value={pairStrategy} onChange={(e) => setPairStrategy(e.target.value)} aria-label="按策略筛选">
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
                {PAIR_COLUMNS.map((c) => (
                  <th key={c.key} onClick={() => toggleSort(c.key)}
                      style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}
                      aria-sort={sortKey === c.key ? (sortDir === 1 ? "ascending" : "descending") : undefined}>
                    {c.label} <ArrowUpDown size={11} style={{ verticalAlign: "-1px", opacity: sortKey === c.key ? 1 : 0.35 }} aria-hidden="true" />
                  </th>
                ))}
                <th>最优参数</th>
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
                  <td><span className="badge backtest">{STRAT_LABELS[p.strategy] || p.strategy}</span></td>
                  <td className={`num ${p.default_pnl >= 0 ? "pos" : "neg"}`}>
                    ${fmt(p.default_pnl)}
                    <span className="muted" style={{ fontSize: 11 }}> ({p.default_trades}笔)</span>
                  </td>
                  <td className={`num ${p.best_pnl >= 0 ? "pos" : "neg"}`}>
                    ${fmt(p.best_pnl)}
                    <span className="muted" style={{ fontSize: 11 }}> ({p.best_trades}笔)</span>
                  </td>
                  <td className={`num ${p.delta > 0 ? "pos" : p.delta < 0 ? "neg" : "muted"}`}>
                    <strong>{p.delta > 0 ? "+" : ""}${fmt(p.delta)}</strong>
                  </td>
                  <td><ParamChips params={p.best_params} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          共 {pairs.length} 个配对 · 默认参数行在全局榜中以高亮标出 · 点击股票代码进入该配对详情
        </p>
      </div>
    </>
  );
}
