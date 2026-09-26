"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { loadCapitalSim, loadStockPaper1h } from "../../lib/data";
import { STRAT_LABELS } from "../../lib/stratLabels";
import Skeleton from "../../components/Skeleton";

const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });
const signed = (n) => `${n >= 0 ? "+" : ""}$${fmt(n)}`;

const TF_LABELS = { "1d": "日线", "1h": "1 小时", "4h": "4 小时", "15m": "15 分钟" };

export default function CapitalSim() {
  const [data, setData] = useState(null);
  const [live, setLive] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadCapitalSim()
      .then((d) => (d ? setData(d) : setError("暂无模拟数据")))
      .catch((e) => setError(String(e)));
    loadStockPaper1h().then(setLive).catch(() => {}); // panel degrades gracefully
  }, []);

  if (error)
    return <div className="panel"><h2>暂无数据</h2><p className="muted">{error}</p></div>;
  if (!data) return <Skeleton variant="dashboard" />;

  const rec = data.results.find((r) => r.timeframe === data.recommended)
    || data.results[0];
  const port = rec.portfolio_top10;
  const finalValue = data.capital + port.test_total;
  const retPct = (port.test_total / data.capital) * 100;

  // 9/1 以来的盈亏：以 9/1 之前最后一个净值为基准
  const SEP = "2026-09-01";
  const eq = port.equity || [];
  const beforeSep = eq.filter((e) => e.date < SEP).pop();
  const sepPoint = eq.find((e) => e.date >= SEP);
  const sepBase = beforeSep ? beforeSep.pnl : 0;
  const sinceSep = sepPoint ? Math.round((port.test_total - sepBase) * 100) / 100 : null;

  return (
    <>
      <h1>模拟</h1>
      <p className="subtitle">
        $1000 本金 · Top10 组合（每腿 $100）· 从切分点真实执行到今天 ·
        选股/选策略只用切分点之前的数据（无未来函数）
      </p>

      {/* hero: the recommended answer */}
      <div className="panel" style={{ borderColor: "var(--accent)" }}>
        <h2>推荐方案：{TF_LABELS[rec.timeframe]} · Top10 组合</h2>
        <div className="cards" style={{ marginTop: 12 }}>
          <div className="card">
            <div className="label">投入 → 现在</div>
            <div className="value">
              ${fmt(data.capital, 0)} → <span className={port.test_total >= 0 ? "pos" : "neg"}>${fmt(finalValue, 0)}</span>
            </div>
          </div>
          <div className="card">
            <div className="label">收益（全程）</div>
            <div className={`value ${port.test_total >= 0 ? "pos" : "neg"}`}>
              {signed(port.test_total)}（{retPct >= 0 ? "+" : ""}{fmt(retPct, 1)}%）
            </div>
          </div>
          <div className="card">
            <div className="label">9/1 以来</div>
            <div className={`value ${(sinceSep ?? 0) >= 0 ? "pos" : "neg"}`}>
              {sinceSep != null ? signed(sinceSep) : "—"}
            </div>
          </div>
          <div className="card">
            <div className="label">执行窗口</div>
            <div className="value" style={{ fontSize: 16 }}>{rec.test_window}</div>
          </div>
          <div className="card">
            <div className="label">盈利腿</div>
            <div className="value">{port.winning_legs}/{port.pairs.length}</div>
          </div>
        </div>
        {port.equity?.length > 1 && (
          <div style={{ width: "100%", height: 220, marginTop: 8 }}>
            <ResponsiveContainer>
              <LineChart data={port.equity} margin={{ top: 8, right: 16, bottom: 0, left: 8 }}>
                <XAxis dataKey="date" tick={{ fill: "#8b93a5", fontSize: 11 }}
                       tickFormatter={(d) => d.slice(5)} minTickGap={40} />
                <YAxis tick={{ fill: "#8b93a5", fontSize: 11 }} width={64}
                       tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border)", borderRadius: 8 }}
                  labelStyle={{ color: "#8b93a5" }}
                  formatter={(v) => [`$${fmt(v)}`, "组合累计盈亏"]}
                />
                <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="4 4" />
                {sepPoint && (
                  <ReferenceLine x={sepPoint.date} stroke="#6366f1" strokeDasharray="4 4"
                                 label={{ value: "9/1", fill: "#6366f1", fontSize: 11, position: "top" }} />
                )}
                <Line dataKey="pnl" dot={false} isAnimationActive={false}
                      stroke={port.test_total >= 0 ? "#22c55e" : "#ef4444"} strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* comparison table */}
      <div className="panel">
        <h2>方案对比（$1000 本金）</h2>
        <p className="hint">每行一个级别 · 加粗为该级别最优 · 推荐行已高亮</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>级别</th><th>执行窗口</th>
                <th className="num">A · Top10 组合</th>
                <th className="num">B · 单配对满仓</th>
                <th className="num">C · 单策略分散</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((r) => {
                const a = r.portfolio_top10.test_total;
                const b = r.single_pair?.test_pnl_x10 ?? null;
                const c = r.single_strategy?.test_total ?? null;
                const best = Math.max(a, b ?? -Infinity, c ?? -Infinity);
                const isRec = r.timeframe === data.recommended;
                const cell = (v, txt) => (
                  <td className={`num ${v >= 0 ? "pos" : "neg"}`}>
                    {v === best ? <strong>{txt}</strong> : txt}
                  </td>
                );
                return (
                  <tr key={r.timeframe}
                      style={isRec ? { background: "rgba(99,102,241,0.08)" } : undefined}>
                    <td>
                      <strong>{TF_LABELS[r.timeframe] || r.timeframe}</strong>
                      {isRec && <span className="badge call" style={{ marginLeft: 6 }}>推荐</span>}
                    </td>
                    <td className="muted" style={{ fontSize: 12 }}>{r.test_window}</td>
                    {cell(a, `${signed(a)}（盈利腿 ${r.portfolio_top10.winning_legs}/${r.portfolio_top10.pairs.length}）`)}
                    {b == null ? <td className="num">—</td>
                      : cell(b, `${signed(b)} · ${r.single_pair.symbol}×${STRAT_LABELS[r.single_pair.strategy] || r.single_pair.strategy}`)}
                    {c == null ? <td className="num">—</td>
                      : cell(c, `${signed(c)} · ${STRAT_LABELS[r.single_strategy.strategy] || r.single_strategy.strategy}`)}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          B 收益最高但满仓单一配对、回撤风险大；A 组合分散、盈利面最广，是风险调整后最优。
          观察名单策略（{data.watchlist_excluded?.map((s) => STRAT_LABELS[s] || s).join("、") || "无"}）不参与选拔。
        </p>
      </div>

      {/* recommended portfolio legs */}
      <div className="panel">
        <h2>推荐组合明细（{TF_LABELS[rec.timeframe]} · Top10）</h2>
        <p className="hint">训练窗盈亏 = 切分点之前的表现（选拔依据）· 执行盈亏 = 切分点之后的真实结果</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th><th>配对</th>
                <th className="num">训练窗盈亏</th>
                <th className="num">执行盈亏</th>
                <th className="num">执行笔数</th>
              </tr>
            </thead>
            <tbody>
              {port.pairs.map((p, i) => (
                <tr key={`${p.symbol}-${p.strategy}`}>
                  <td className="muted">{i + 1}</td>
                  <td>
                    <Link href={`/lab/pair?strategy=${p.strategy}&symbol=${p.symbol}`} className="sym-link">
                      <strong>{p.symbol}</strong>
                    </Link>{" "}
                    <span className="badge backtest">{STRAT_LABELS[p.strategy] || p.strategy}</span>{" "}
                    <span className="badge flat">{TF_LABELS[rec.timeframe]}</span>
                  </td>
                  <td className={`num ${p.train_pnl >= 0 ? "pos" : "neg"}`}>
                    {signed(p.train_pnl)}
                  </td>
                  <td className={`num ${p.test_pnl >= 0 ? "pos" : "neg"}`}>
                    <strong>{signed(p.test_pnl)}</strong>
                  </td>
                  <td className="num">{p.test_trades}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 组合代际：换届记录 + 时间轴 */}
      <div className="panel">
        <h2>组合代际</h2>
        <p className="hint" style={{ lineHeight: 1.8 }}>
          Top10 组合每周重选一次（训练期过滤 + 近 90 天验证期排名）。换届掉榜的配对按规则平仓、
          新配对从下一信号建仓——<strong>净值连续拼接，不因换届归零</strong>。
          每一代的构成与期间已实现盈亏记录如下：
        </p>
        {live?.prev_gen_shadow && live?.generations?.length > 0 && (() => {
          const sh = live.prev_gen_shadow;
          const cur = live.generations.find((g) => g.current);
          const unreal = live.positions.reduce((a, p) => a + (p.unrealized_pnl ?? 0), 0);
          const newTotal = Math.round(((cur?.realized_pnl ?? 0) + unreal) * 100) / 100;
          const diff = Math.round((newTotal - sh.total) * 100) / 100;
          return (
            <div className="cards" style={{ marginTop: 12 }}>
              <div className="card">
                <div className="label">第 {sh.gen_id} 代 · 假设继续持有</div>
                <div className={`value ${sh.total >= 0 ? "pos" : "neg"}`}>{signed(sh.total)}</div>
              </div>
              <div className="card">
                <div className="label">第 {cur?.id} 代 · 实盘（含浮盈）</div>
                <div className={`value ${newTotal >= 0 ? "pos" : "neg"}`}>{signed(newTotal)}</div>
              </div>
              <div className="card">
                <div className="label">换届决策（{sh.since} 起）</div>
                <div className={`value ${diff >= 0 ? "pos" : "neg"}`}>
                  {diff >= 0 ? "跑赢" : "跑输"} ${fmt(Math.abs(diff))}
                </div>
              </div>
            </div>
          );
        })()}
        {live?.prev_gen_shadow && (
          <p className="hint" style={{ marginTop: 8 }}>
            假设持有 = 上一代 10 个配对从换届日起按同样规则在最新 K 线上重放的盈亏；
            实盘 = 当前代际已实现 + 在仓浮盈。每次换届后自动开始新一轮对照。
          </p>
        )}
        {live?.generations?.length > 0 && (
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
            {[...live.generations].reverse().map((g) => (
              <div key={g.id} className="panel"
                   style={{ padding: 14, margin: 0,
                            borderColor: g.current ? "var(--accent)" : undefined }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <strong>第 {g.id} 代</strong>
                  {g.current && <span className="badge call">进行中</span>}
                  <span className="muted" style={{ fontSize: 12 }}>
                    {g.start} ~ {g.end || "至今"}
                  </span>
                  <span style={{ marginLeft: "auto" }}
                        className={g.realized_pnl >= 0 ? "pos" : "neg"}>
                    <strong>{signed(g.realized_pnl)}</strong>{" "}
                    <span className="muted" style={{ fontSize: 12 }}>
                      已实现 · {g.trades} 笔
                    </span>
                  </span>
                </div>
                <p style={{ margin: "10px 0 0", display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {g.pairs.map((p) => (
                    <Link key={`${g.id}-${p.symbol}-${p.strategy}`}
                          href={`/lab/pair?strategy=${p.strategy}&symbol=${p.symbol}`}
                          className="badge flat" style={{ textDecoration: "none" }}>
                      {p.symbol} × {STRAT_LABELS[p.strategy] || p.strategy}
                    </Link>
                  ))}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {live && (live.positions.length > 0 || (live.closed_trades || []).length > 0) && (() => {
        const realized = (live.closed_trades || []).reduce((a, t) => a + (t.pnl || 0), 0);
        const unrealized = live.positions.reduce((a, p) => a + (p.unrealized_pnl ?? 0), 0);
        return (
          <div className="panel">
            <h2>实盘验证 · 1h Top10 组合（$100/腿）</h2>
            <p className="hint">
              模拟结果的真实兑现跟踪：免费数据源为 T+1 延迟，每日收盘后逐根重放昨日全部 1h K 线记账，决策与逐小时实盘完全一致 ·
              更新于 {live.updated_at ? new Date(live.updated_at).toLocaleString("zh-CN", { hour12: false }) : "—"}
              {" · "}已实现 <strong className={realized >= 0 ? "pos" : "neg"}>{signed(realized)}</strong>
              {" · "}浮盈 <strong className={unrealized >= 0 ? "pos" : "neg"}>{signed(unrealized)}</strong>
              {" · "}合计 <strong className={realized + unrealized >= 0 ? "pos" : "neg"}>{signed(realized + unrealized)}</strong>
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th><th>配对</th>
                    <th className="num">回测盈亏</th>
                    <th>实盘状态</th>
                    <th className="num">浮盈</th>
                    <th className="num">已实现</th>
                  </tr>
                </thead>
                <tbody>
                  {(live.pairs || []).map((p, i) => {
                    const key = `${p.symbol}|${p.strategy}`;
                    const pos = live.positions.find((x) => x.key === key);
                    const cls = (live.closed_trades || []).filter(
                      (t) => t.symbol === p.symbol && t.strategy === p.strategy);
                    const rl = cls.reduce((a, t) => a + (t.pnl || 0), 0);
                    return (
                      <tr key={key}>
                        <td className="muted">{i + 1}</td>
                        <td>
                          <Link href={`/lab/pair?strategy=${p.strategy}&symbol=${p.symbol}`} className="sym-link">
                            <strong>{p.symbol}</strong>
                          </Link>{" "}
                          <span className="badge backtest">{STRAT_LABELS[p.strategy] || p.strategy}</span>{" "}
                          <span className="badge flat">1 小时</span>
                        </td>
                        <td className={`num ${(p.backtest_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                          {p.backtest_pnl != null ? signed(p.backtest_pnl) : "—"}
                        </td>
                        <td>
                          {pos ? (
                            <>
                              <span className={`badge ${pos.side === "long" ? "call" : "put"}`}>
                                {pos.side === "long" ? "多" : "空"}
                              </span>{" "}
                              <span className="muted" style={{ fontSize: 11 }}>
                                @ ${fmt(pos.entry_price)}
                              </span>
                            </>
                          ) : (
                            <span className="badge flat">观望</span>
                          )}
                        </td>
                        <td className={`num ${(pos?.unrealized_pnl ?? 0) >= 0 ? "pos" : "neg"}`}>
                          {pos ? signed(pos.unrealized_pnl) : "—"}
                        </td>
                        <td className={`num ${rl >= 0 ? "pos" : "neg"}`}>
                          {cls.length ? `${signed(rl)} (${cls.length}笔)` : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })()}

      <p className="hint">
        方法：每个级别独立回测 · 每笔 $100 名义本金 · 多头/空头 · 策略级止盈止损 ·
        选拔窗口严格早于执行窗口。数据更新于 {data.run_at ? new Date(data.run_at).toLocaleString("zh-CN", { hour12: false }) : "—"}。
      </p>
    </>
  );
}
