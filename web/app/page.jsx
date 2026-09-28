"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Wallet, FlaskConical, History, Calculator, Layers, ArrowRight,
} from "lucide-react";
import {
  loadStockPaper, loadStockPaper1h, loadSignalsData, loadStockLab,
  loadFutuSim, invalidatePrefix,
} from "../lib/data";
import { STRAT_LABELS } from "../lib/stratLabels";
import Skeleton from "../components/Skeleton";

const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });
const signed = (n) => `${n >= 0 ? "+" : ""}$${fmt(n)}`;

export default function Home() {
  const [paper, setPaper] = useState(null);      // 日线账本
  const [paper1h, setPaper1h] = useState(null);  // 1h 账本
  const [sig, setSig] = useState(null);
  const [lab, setLab] = useState(null);
  const [futu, setFutu] = useState(null);        // 富途模拟账户
  const [futuBusy, setFutuBusy] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    loadStockPaper().then(setPaper).catch(() => {});
    loadStockPaper1h().then(setPaper1h).catch(() => {});
    loadSignalsData().then(setSig).catch(() => {});
    loadFutuSim().then(setFutu).catch(() => {});
    loadStockLab().then(setLab).catch(() => {}).finally(() => setReady(true));
  }, []);

  const refreshFutu = async () => {
    setFutuBusy(true);
    try {
      const r = await fetch("/api/futu/refresh", { method: "POST" });
      if (r.ok) {
        const payload = await r.json();
        invalidatePrefix("futusim");
        setFutu(payload);
      }
    } catch { /* dev server 未启动时静默失败 */ }
    setFutuBusy(false);
  };

  if (!ready && !lab) return <Skeleton variant="dashboard" />;

  // ---- 模拟账户合计（日线 + 1h 两本账） ----
  const books = [
    paper && { label: "日线", ...paper },
    paper1h && { label: "1 小时", positions: paper1h.positions || [],
                 closed_trades: paper1h.closed_trades || [],
                 updated_at: paper1h.updated_at },
  ].filter(Boolean);

  const sum = (xs, f) => Math.round(xs.reduce((a, x) => a + f(x), 0) * 100) / 100;
  const open = books.reduce((a, b) => a + b.positions.length, 0);
  const unrealized = sum(books, (b) => b.positions.reduce((x, p) => x + (p.unrealized_pnl ?? 0), 0));
  const realized = sum(books, (b) => b.closed_trades.reduce((x, t) => x + (t.pnl || 0), 0));
  const total = Math.round((realized + unrealized) * 100) / 100;
  const updatedAt = [paper1h?.updated_at, lab?.run_at].filter(Boolean).sort().pop();

  // ---- 今日信号概览 ----
  const signals = sig?.signals || [];
  const sigDate = signals.length
    ? signals.map((s) => s.created_at).sort().pop()?.slice(0, 10) : null;
  const buys = signals.filter((s) => s.signal === 1);
  const sells = signals.filter((s) => s.signal === -1);

  return (
    <>
      <h1>首页</h1>
      <p className="subtitle">
        美股短线 · 每笔 $100 名义本金 · 多策略 × 多股票 · 云端每日自动更新
      </p>

      {/* 富途模拟账户：本机 OpenD 在线时实时可查 */}
      <div className="panel" style={{ borderColor: futu?.available ? "var(--accent)" : undefined,
                                      borderStyle: futu?.available ? "solid" : "dashed",
                                      opacity: futu?.available ? 1 : 0.85 }}>
        <h2>
          <Wallet size={15} style={{ verticalAlign: "-2px", marginRight: 6 }} aria-hidden="true" />
          富途模拟账户
          <span className={`badge ${futu?.available ? "call" : "flat"}`} style={{ marginLeft: 8 }}>
            {futu?.available ? "OpenD 在线" : "OpenD 离线"}
          </span>
          <button className="btn" style={{ marginLeft: "auto", padding: "4px 10px", fontSize: 12 }}
                  onClick={refreshFutu} disabled={futuBusy}>
            {futuBusy ? "刷新中…" : "刷新"}
          </button>
        </h2>
        {futu?.available ? (() => {
          const acct = futu.account || {};
          const posList = futu.positions || [];
          const unreal = posList.reduce((a, p) => a + (p.pl_val || 0), 0);
          const activeOrders = (futu.orders || []).filter((o) =>
            ["SUBMITTED", "SUBMITTING", "WAITING_SUBMIT", "FILLED_PART"].includes(o.order_status));
          return (
            <>
              <div className="cards" style={{ marginTop: 12 }}>
                <div className="card"><div className="label">总资产</div>
                  <div className="value">${fmt(acct.total_assets)}</div></div>
                <div className="card"><div className="label">现金</div>
                  <div className="value">${fmt(acct.cash)}</div></div>
                <div className="card"><div className="label">持仓市值</div>
                  <div className="value">${fmt(acct.market_val)}</div></div>
                <div className="card"><div className="label">持仓浮动盈亏</div>
                  <div className={`value ${unreal >= 0 ? "pos" : "neg"}`}>{signed(unreal)}</div></div>
              </div>
              {posList.length > 0 && (
                <table style={{ marginTop: 14 }}>
                  <thead><tr>
                    <th>代码</th><th style={{ textAlign: "right" }}>数量</th>
                    <th style={{ textAlign: "right" }}>成本价</th>
                    <th style={{ textAlign: "right" }}>市值</th>
                    <th style={{ textAlign: "right" }}>盈亏</th>
                  </tr></thead>
                  <tbody>
                    {posList.map((p) => (
                      <tr key={p.code}>
                        <td>{p.code}</td>
                        <td style={{ textAlign: "right" }}>{fmt(p.qty, 0)}</td>
                        <td style={{ textAlign: "right" }}>${fmt(p.cost_price)}</td>
                        <td style={{ textAlign: "right" }}>${fmt(p.market_val)}</td>
                        <td style={{ textAlign: "right" }}
                            className={p.pl_val >= 0 ? "pos" : "neg"}>
                          {signed(p.pl_val)} ({p.pl_ratio >= 0 ? "+" : ""}{fmt(p.pl_ratio, 1)}%)
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {activeOrders.length > 0 && (
                <>
                  <h3 style={{ marginTop: 16 }}>未完成订单</h3>
                  <table style={{ marginTop: 8 }}>
                    <thead><tr>
                      <th>代码</th><th>方向</th>
                      <th style={{ textAlign: "right" }}>数量</th>
                      <th style={{ textAlign: "right" }}>价格</th><th>状态</th>
                    </tr></thead>
                    <tbody>
                      {activeOrders.map((o) => (
                        <tr key={o.order_id}>
                          <td>{o.code}</td>
                          <td className={o.trd_side === "BUY" ? "pos" : "neg"}>
                            {o.trd_side === "BUY" ? "买入" : "卖出"}
                          </td>
                          <td style={{ textAlign: "right" }}>{fmt(o.qty, 0)}</td>
                          <td style={{ textAlign: "right" }}>
                            {o.price > 0 ? `$${fmt(o.price)}` : "市价"}
                          </td>
                          <td><span className="badge flat">{o.order_status}</span></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
              {(() => {
                const night = (futu.quotes || []).filter((q) => q.overnight_price > 0);
                if (!night.length) return null;
                return (
                  <>
                    <h3 style={{ marginTop: 16 }}>
                      夜盘实况
                      <span className="muted" style={{ fontSize: 12, fontWeight: 400, marginLeft: 8 }}>
                        美东 20:00–04:00 · Blue Ocean
                      </span>
                    </h3>
                    <table style={{ marginTop: 8 }}>
                      <thead><tr>
                        <th>代码</th>
                        <th style={{ textAlign: "right" }}>收盘价</th>
                        <th style={{ textAlign: "right" }}>夜盘价</th>
                        <th style={{ textAlign: "right" }}>夜盘涨跌</th>
                        <th style={{ textAlign: "right" }}>夜盘区间</th>
                      </tr></thead>
                      <tbody>
                        {night.map((q) => (
                          <tr key={q.code}>
                            <td>{q.code.replace("US.", "")}</td>
                            <td style={{ textAlign: "right" }}>${fmt(q.last_price)}</td>
                            <td style={{ textAlign: "right" }}>${fmt(q.overnight_price)}</td>
                            <td style={{ textAlign: "right" }}
                                className={q.overnight_change_rate >= 0 ? "pos" : "neg"}>
                              {q.overnight_change_rate >= 0 ? "+" : ""}{fmt(q.overnight_change_rate, 2)}%
                            </td>
                            <td style={{ textAlign: "right" }} className="muted">
                              {fmt(q.overnight_low_price)} ~ {fmt(q.overnight_high_price)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                );
              })()}
              <p className="hint" style={{ marginTop: 10 }}>
                账户 {futu.acc_id} · 更新于{" "}
                {new Date(futu.updated_at).toLocaleString("zh-CN", { hour12: false })}
                {" · 需本机 OpenD 在线，云端访问时显示最后快照"}
              </p>
            </>
          );
        })() : (
          <>
            <div className="cards" style={{ marginTop: 12 }}>
              <div className="card"><div className="label">总资产</div><div className="value">—</div></div>
              <div className="card"><div className="label">现金</div><div className="value">—</div></div>
              <div className="card"><div className="label">持仓市值</div><div className="value">—</div></div>
              <div className="card"><div className="label">浮动盈亏</div><div className="value">—</div></div>
            </div>
            <p className="hint" style={{ marginTop: 10 }}>
              {futu?.error ? `连接失败：${futu.error}` : "富途 OpenD 未运行或未登录，启动后点「刷新」。"}
              {" "}真实账户接入规划中，当前仅模拟环境。
            </p>
          </>
        )}
      </div>

      {/* 模拟账户摘要 */}
      <div className="panel" style={{ borderColor: "var(--accent)" }}>
        <h2>模拟账户（纸面）</h2>
        <div className="cards" style={{ marginTop: 12 }}>
          <div className="card">
            <div className="label">在仓</div>
            <div className="value">{open}</div>
          </div>
          <div className="card">
            <div className="label">浮动盈亏</div>
            <div className={`value ${unrealized >= 0 ? "pos" : "neg"}`}>{signed(unrealized)}</div>
          </div>
          <div className="card">
            <div className="label">已实现盈亏</div>
            <div className={`value ${realized >= 0 ? "pos" : "neg"}`}>{signed(realized)}</div>
          </div>
          <div className="card">
            <div className="label">合计</div>
            <div className={`value ${total >= 0 ? "pos" : "neg"}`}>{signed(total)}</div>
          </div>
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          {books.map((b) => b.label).join(" + ") || "—"} 两本账 · 数据更新于{" "}
          {updatedAt ? new Date(updatedAt).toLocaleString("zh-CN", { hour12: false }) : "—"}
          {" · "}
          <Link href="/sim" style={{ color: "var(--accent)" }}>
            查看 $1000 组合模拟详情 <ArrowRight size={11} style={{ verticalAlign: "-1px" }} aria-hidden="true" />
          </Link>
        </p>
      </div>

      {/* 今日信号 */}
      <div className="panel">
        <h2>最新信号{sigDate && <span className="muted" style={{ fontSize: 13, fontWeight: 400, marginLeft: 8 }}>{sigDate}</span>}</h2>
        {signals.length ? (
          <>
            <div className="cards" style={{ marginTop: 12 }}>
              <div className="card">
                <div className="label">买入信号</div>
                <div className="value pos">{buys.length}</div>
              </div>
              <div className="card">
                <div className="label">卖出信号</div>
                <div className="value neg">{sells.length}</div>
              </div>
              <div className="card">
                <div className="label">覆盖配对</div>
                <div className="value">{signals.length}</div>
              </div>
            </div>
            {buys.length > 0 && (
              <p style={{ margin: "12px 0 0", display: "flex", gap: 6, flexWrap: "wrap" }}>
                {buys.slice(0, 12).map((s) => (
                  <Link key={`${s.symbol}-${s.strategy}`}
                        href={`/lab/pair?strategy=${s.strategy}&symbol=${s.symbol}`}
                        className="badge call" style={{ textDecoration: "none" }}>
                    {s.symbol} · {STRAT_LABELS[s.strategy] || s.strategy}
                  </Link>
                ))}
                {buys.length > 12 && <span className="badge flat">+{buys.length - 12}</span>}
              </p>
            )}
          </>
        ) : (
          <p className="hint">暂无信号数据</p>
        )}
      </div>

      {/* 快捷入口 */}
      <div className="panel">
        <h2>快捷入口</h2>
        <p style={{ margin: "4px 0 0", display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Link href="/lab" className="btn">
            <FlaskConical size={13} aria-hidden="true" /> 策略排行与 Top10
          </Link>
          <Link href="/history" className="btn">
            <History size={13} aria-hidden="true" /> 历史标的
          </Link>
          <Link href="/sim" className="btn">
            <Calculator size={13} aria-hidden="true" /> 组合模拟
          </Link>
          <Link href="/options" className="btn">
            <Layers size={13} aria-hidden="true" /> 期权账本
          </Link>
        </p>
      </div>
    </>
  );
}
