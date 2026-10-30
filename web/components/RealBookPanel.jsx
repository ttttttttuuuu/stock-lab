"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { loadRealBook } from "../lib/data";
import { STRAT_LABELS } from "../lib/stratLabels";

const fmt = (n, d = 2) =>
  n == null || !Number.isFinite(Number(n)) ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });
const signed = (n) => n == null ? "—" : `${n >= 0 ? "+" : "-"}$${fmt(Math.abs(n))}`;

export default function RealBookPanel() {
  const [book, setBook] = useState(undefined);

  useEffect(() => {
    loadRealBook().then(setBook).catch(() => setBook(null));
  }, []);

  if (book === undefined) return null;

  const account = book?.account || { equity: 3000, cash: 3000, realized: 0, unrealized: 0 };
  const metrics = book?.metrics || {};
  const isPending = !book || book.sample_status === "pending";
  const net = account.equity - 3000;
  const curve = (book?.equity || []).map((p) => ({ ...p, dateLabel: p.date.slice(5) }));
  const recent = [...(book?.closed_trades || [])].reverse().slice(0, 8);
  const maxDrawdown = curve.reduce((acc, p) => {
    acc.peak = Math.max(acc.peak, p.equity);
    acc.mdd = Math.min(acc.mdd, p.equity - acc.peak);
    return acc;
  }, { peak: 3000, mdd: 0 }).mdd;

  return (
    <section className="panel" style={{ borderColor: "var(--accent)" }} aria-labelledby="real-book-title">
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <h2 id="real-book-title" style={{ margin: 0 }}>真实候选账</h2>
        <span className="badge call">$3,000 · 1h · Top3</span>
        <span className="badge flat">每笔 $1,000</span>
        {isPending
          ? <span className="badge flat">等待首次云端运行</span>
          : metrics.trades === 0
            ? <span className="badge flat">已启动 · 样本积累中</span>
            : <span className="badge backtest">{metrics.trades} 笔净成本交易</span>}
      </div>
      <p className="hint" style={{ margin: "8px 0 14px" }}>
        每周按扣费后的验证窗净收益重选；每个股票最多一个配对。掉榜只禁止新开仓，旧仓按原信号自然出场。
        费用、双边滑点与沽空借货全部计入；从首次云端运行开始记账，不回填历史。
      </p>

      {isPending ? (
        <div style={{ padding: "22px 0", borderTop: "1px solid var(--border)" }}>
          <strong>等待首次云端账本</strong>
          <p className="muted" style={{ margin: "6px 0 0", fontSize: 13 }}>
            新表写入 Supabase 且每日管线运行后，这里会显示真实净值与交易明细。
          </p>
        </div>
      ) : (
        <>
          <div className="cards">
            <div className="card"><div className="label">当前净值</div><div className={`value ${net >= 0 ? "pos" : "neg"}`}>${fmt(account.equity)}</div></div>
            <div className="card"><div className="label">累计净盈亏</div><div className={`value ${net >= 0 ? "pos" : "neg"}`}>{signed(net)}</div></div>
            <div className="card"><div className="label">现金</div><div className="value">${fmt(account.cash)}</div></div>
            <div className="card"><div className="label">平仓 / 浮动净额</div><div className="value" style={{ fontSize: 17 }}>{signed(account.realized)} / {signed(account.unrealized)}</div></div>
            <div className="card"><div className="label">每笔净期望</div><div className={`value ${(metrics.avg_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>{signed(metrics.avg_pnl)}</div></div>
            <div className="card"><div className="label">盈利因子</div><div className="value">{metrics.profit_factor == null ? "—" : fmt(metrics.profit_factor)}</div></div>
            <div className="card"><div className="label">净值最大回撤</div><div className="value neg">{signed(maxDrawdown)}</div></div>
          </div>

          {curve.length > 1 && (
            <div style={{ width: "100%", height: 210, marginTop: 16 }}>
              <ResponsiveContainer>
                <LineChart data={curve} margin={{ top: 8, right: 12, bottom: 0, left: 4 }}>
                  <XAxis dataKey="dateLabel" tick={{ fontSize: 11 }} stroke="var(--muted)" minTickGap={28} />
                  <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} stroke="var(--muted)" tickFormatter={(v) => `$${v}`} />
                  <Tooltip formatter={(v) => [`$${fmt(v)}`, "净值"]} contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }} />
                  <ReferenceLine y={3000} stroke="var(--border)" strokeDasharray="4 4" />
                  <Line dataKey="equity" stroke="#6366f1" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          <h3 style={{ marginTop: 18 }}>当前 3 个槽位</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>配对</th><th className="num">验证窗净收益</th><th className="num">训练窗净收益</th><th className="num">验证笔数</th><th>当前状态</th></tr></thead>
              <tbody>
                {(book.pairs || []).map((p) => {
                  const key = `${p.symbol}|${p.strategy}`;
                  const pos = (book.positions || []).find((x) => x.key === key);
                  return (
                    <tr key={key}>
                      <td><Link className="sym-link" href={`/lab/pair?strategy=${p.strategy}&symbol=${p.symbol}`}><strong>{p.symbol}</strong></Link> <span className="badge backtest">{STRAT_LABELS[p.strategy] || p.strategy}</span></td>
                      <td className={`num ${p.total_pnl >= 0 ? "pos" : "neg"}`}>{signed(p.total_pnl)}</td>
                      <td className="num">{signed(p.train_pnl)}</td>
                      <td className="num">{p.trades}</td>
                      <td>{pos ? <><span className={`badge ${pos.side === "long" ? "call" : "put"}`}>{pos.side === "long" ? "多" : "空"}</span> <span className={pos.unrealized_net >= 0 ? "pos" : "neg"}>{signed(pos.unrealized_net)}</span></> : <span className="badge flat">观望</span>}</td>
                    </tr>
                  );
                })}
                {!(book.pairs || []).length && <tr><td colSpan={5} className="muted">选拔结果将在首次云端运行后产生。</td></tr>}
              </tbody>
            </table>
          </div>

          {recent.length > 0 && (
            <>
              <h3 style={{ marginTop: 18 }}>最近平仓</h3>
              <div className="table-wrap"><table>
                <thead><tr><th>时间</th><th>配对</th><th>方向</th><th className="num">毛盈亏</th><th className="num">费用+滑点+借货</th><th className="num">净盈亏</th></tr></thead>
                <tbody>{recent.map((t) => {
                  const cost = (t.fees || 0) + (t.slippage || 0) + (t.borrow || 0);
                  return <tr key={t.id || `${t.symbol}-${t.exit_date}`}><td className="muted">{new Date(t.exit_date).toLocaleString("zh-CN", { hour12: false })}</td><td>{t.symbol} · {STRAT_LABELS[t.strategy] || t.strategy}</td><td>{t.side === "long" ? "多" : "空"}</td><td className="num">{signed(t.pnl)}</td><td className="num neg">-${fmt(cost)}</td><td className={`num ${t.pnl_net >= 0 ? "pos" : "neg"}`}><strong>{signed(t.pnl_net)}</strong></td></tr>;
                })}</tbody>
              </table></div>
            </>
          )}
          <p className="hint" style={{ marginTop: 10 }}>更新于 {book.updated_at ? new Date(book.updated_at).toLocaleString("zh-CN", { hour12: false }) : "—"} · 仅为纸面候选账，不代表未来收益。</p>
        </>
      )}
    </section>
  );
}
