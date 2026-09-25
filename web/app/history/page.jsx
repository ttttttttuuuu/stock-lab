"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowUpDown, Search } from "lucide-react";
import { loadSymbols } from "../../lib/data";
import { STRAT_LABELS } from "../../lib/stratLabels";
import Skeleton from "../../components/Skeleton";

const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });

const COLUMNS = [
  { key: "symbol", label: "代码" },
  { key: "last_close", label: "最新收盘", num: true },
  { key: "active_pairs", label: "有效配对", num: true },
  { key: "best_strategy", label: "最佳策略" },
  { key: "best_pnl", label: "最佳盈亏", num: true },
  { key: "best_win_rate", label: "最佳胜率", num: true },
];

export default function HistoryPage() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("best_pnl");
  const [sortDir, setSortDir] = useState(-1);

  useEffect(() => {
    loadSymbols()
      .then((d) => (d && d.length ? setRows(d) : setError("暂无标的数据")))
      .catch((e) => setError(String(e)));
  }, []);

  const view = useMemo(() => {
    if (!rows) return [];
    let r = rows;
    if (query.trim()) {
      const q = query.trim().toUpperCase();
      r = r.filter((x) => x.symbol.includes(q));
    }
    const col = COLUMNS.find((c) => c.key === sortKey);
    return [...r].sort((a, b) => {
      const av = a[sortKey] ?? (col?.num ? -Infinity : "");
      const bv = b[sortKey] ?? (col?.num ? -Infinity : "");
      return (av > bv ? 1 : av < bv ? -1 : 0) * sortDir;
    });
  }, [rows, query, sortKey, sortDir]);

  if (error)
    return <div className="panel"><h2>暂无数据</h2><p className="muted">{error}</p></div>;
  if (!rows) return <Skeleton variant="dashboard" />;

  const lastDate = rows.map((r) => r.last_date).filter(Boolean).sort().pop();
  const toggleSort = (key) => {
    if (sortKey === key) setSortDir((d) => -d);
    else { setSortKey(key); setSortDir(key === "symbol" || key === "best_strategy" ? 1 : -1); }
  };

  return (
    <>
      <h1>历史</h1>
      <p className="subtitle">
        股票池 {rows.length} 只标的 · 日线数据截至 {lastDate || "—"} ·
        每只股票展示回测表现最佳的策略配对，点击进入完整交易明细
      </p>

      <div className="panel">
        <div className="filters" style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
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
                <th>数据区间</th>
              </tr>
            </thead>
            <tbody>
              {view.map((r, i) => (
                <tr key={r.symbol}>
                  <td className="muted">{i + 1}</td>
                  <td>
                    {r.best_strategy ? (
                      <Link href={`/lab/pair?strategy=${r.best_strategy}&symbol=${r.symbol}`} className="sym-link">
                        <strong>{r.symbol}</strong>
                      </Link>
                    ) : (
                      <strong>{r.symbol}</strong>
                    )}
                  </td>
                  <td className="num">${fmt(r.last_close)}</td>
                  <td className="num">{r.active_pairs}</td>
                  <td>
                    {r.best_strategy
                      ? <span className="badge backtest">{STRAT_LABELS[r.best_strategy] || r.best_strategy}</span>
                      : "—"}
                  </td>
                  <td className={`num ${(r.best_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                    {r.best_pnl != null ? <strong>${fmt(r.best_pnl)}</strong> : "—"}
                  </td>
                  <td className="num">{r.best_win_rate != null ? `${fmt(r.best_win_rate, 1)}%` : "—"}</td>
                  <td className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                    {r.first_date?.slice(0, 7)} ~ {r.last_date}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          共 {view.length} 只标的 · 最佳盈亏为该股票全部策略配对中 2 年回测总盈亏最高者 ·
          完整 K 线与逐笔交易在配对详情页
        </p>
      </div>
    </>
  );
}
