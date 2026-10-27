"use client";

import { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import { loadStockPaper, loadStockPaper1h } from "../lib/data";

const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });
const signed = (n) => `${n >= 0 ? "+" : "-"}$${fmt(Math.abs(n))}`;
const COLORS = { daily: "#f59e0b", h1: "#6366f1" };

// ---- Futu HK real costs (mirrors engine/futu_costs.py, official schedule) ----
function futuOrderFees(shares, price, side) {
  const amount = shares * price;
  const commission = Math.min(Math.max(0.0049 * shares, 0.99), amount * 0.005);
  const platform = Math.min(Math.max(0.005 * shares, 1.0), amount * 0.005);
  let fees = commission + platform + 0.003 * shares;
  if (side === "sell") {
    fees += Math.max(amount * 0.000008, 0.01);
    fees += Math.min(Math.max(0.000166 * shares, 0.01), 8.30);
  }
  return fees;
}

function tradeNet(t, notional) {
  const shares = notional / t.entry_price;
  const short = t.side === "short";
  const fees = futuOrderFees(shares, t.entry_price, short ? "sell" : "buy")
             + futuOrderFees(shares, t.exit_price, short ? "buy" : "sell");
  const gross = notional * (t.pnl_pct || 0) / 100;
  const days = Math.max(0, (new Date(t.exit_date) - new Date(t.entry_date)) / 86400000);
  const borrow = short ? notional * 0.05 * days / 365 : 0;
  const slippage = notional * 0.0005 * 2; // 5 bps per side
  return { gross, net: gross - fees - borrow - slippage,
           cost: fees + borrow + slippage };
}

function bookStats(book, equity) {
  const closed = book?.closed_trades || [];
  const pos = book?.positions || [];
  const realized = closed.reduce((a, t) => a + (t.pnl || 0), 0);
  const unrealized = pos.reduce((a, p) => a + (p.unrealized_pnl || 0), 0);
  const gw = closed.filter((t) => (t.pnl || 0) > 0).reduce((a, t) => a + t.pnl, 0);
  const gl = -closed.filter((t) => (t.pnl || 0) < 0).reduce((a, t) => a + t.pnl, 0);
  let peak = 0, mdd = 0;
  for (const h of equity || []) {
    peak = Math.max(peak, h.total);
    mdd = Math.min(mdd, h.total - peak);
  }
  return {
    realized, unrealized, total: realized + unrealized,
    n: closed.length,
    wins: closed.filter((t) => (t.pnl || 0) > 0).length,
    pf: gl > 0 ? gw / gl : null,
    exp: closed.length ? realized / closed.length : null,
    mdd,
  };
}

// Equity curve derived LIVE from the book's closed trades (Supabase) +
// current open-position marks — no static files, always fresh on refresh.
// Historical points are realized-only; the final point adds today's
// unrealized PnL (same convention as the cloud daily snapshots).
function buildEquity(book) {
  const closed = book?.closed_trades || [];
  const byDay = {};
  for (const t of closed) {
    const d = (t.exit_date || "").slice(0, 10);
    if (d) byDay[d] = (byDay[d] || 0) + (t.pnl || 0);
  }
  let cum = 0;
  const hist = Object.keys(byDay).sort().map((d) => {
    cum += byDay[d];
    return { date: d, total: Math.round(cum * 100) / 100 };
  });
  if (!hist.length) return hist;
  const u = (book?.positions || [])
    .reduce((a, p) => a + (p.unrealized_pnl || 0), 0);
  const today = new Date().toISOString().slice(0, 10);
  const lastTotal = Math.round((cum + u) * 100) / 100;
  if (hist[hist.length - 1].date === today) hist[hist.length - 1].total = lastTotal;
  else hist.push({ date: today, total: lastTotal });
  return hist;
}

function isoWeek(dateStr) {
  const d = new Date(dateStr.slice(0, 10) + "T00:00:00Z");
  const day = (d.getUTCDay() + 6) % 7; // Mon=0
  d.setUTCDate(d.getUTCDate() - day + 3); // Thursday of this week
  const year = d.getUTCFullYear();
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Day = (jan4.getUTCDay() + 6) % 7;
  jan4.setUTCDate(jan4.getUTCDate() - jan4Day + 3);
  const week = 1 + Math.round((d - jan4) / (7 * 86400000));
  return `${year}-W${String(week).padStart(2, "0")}`;
}

export default function LongTermPanel() {
  const [daily, setDaily] = useState(null);
  const [h1, setH1] = useState(null);
  const [notional, setNotional] = useState(1000);

  useEffect(() => {
    loadStockPaper().then(setDaily).catch(() => {});
    loadStockPaper1h().then(setH1).catch(() => {});
  }, []);

  if (!daily && !h1) return null;

  const eqD = buildEquity(daily);
  const eqH = buildEquity(h1);
  const sd = bookStats(daily, eqD);
  const sh = bookStats(h1, eqH);

  // merge equity curves by date
  const dates = [...new Set([...eqD, ...eqH].map((h) => h.date))].sort();
  const mapD = Object.fromEntries(eqD.map((h) => [h.date, h.total]));
  const mapH = Object.fromEntries(eqH.map((h) => [h.date, h.total]));
  const curve = dates.map((d) => ({ date: d.slice(5), daily: mapD[d], h1: mapH[d] }));

  // weekly realized per book
  const weeks = [...new Set([...(daily?.closed_trades || []), ...(h1?.closed_trades || [])]
    .map((t) => isoWeek(t.exit_date)))].sort();
  const weekly = weeks.map((w) => {
    const sum = (book) => Math.round((book?.closed_trades || [])
      .filter((t) => isoWeek(t.exit_date) === w)
      .reduce((a, t) => a + (t.pnl || 0), 0) * 100) / 100;
    return { week: w.slice(5), daily: sum(daily), h1: sum(h1) };
  });

  const rows = [
    { label: "日线", s: sd, color: COLORS.daily },
    { label: "1 小时", s: sh, color: COLORS.h1 },
  ];

  // real-cost scenario at the selected per-trade notional
  const costRows = [
    { label: "日线", book: daily, color: COLORS.daily },
    { label: "1 小时", book: h1, color: COLORS.h1 },
  ].map(({ label, book, color }) => {
    const nets = (book?.closed_trades || []).map((t) => tradeNet(t, notional));
    const total = nets.reduce((a, x) => a + x.net, 0);
    const gross = nets.reduce((a, x) => a + x.gross, 0);
    const cost = nets.reduce((a, x) => a + x.cost, 0);
    const gw = nets.filter((x) => x.net > 0).reduce((a, x) => a + x.net, 0);
    const gl = -nets.filter((x) => x.net < 0).reduce((a, x) => a + x.net, 0);
    return { label, color, total,
             exp: nets.length ? total / nets.length : null,
             pf: gl > 0 ? gw / gl : null,
             costPct: gross ? Math.abs((cost / gross) * 100) : null };
  });

  return (
    <div className="panel" style={{ borderColor: "var(--accent)" }}>
      <h2>
        长期表现 · 主账本
        <span className="badge call" style={{ marginLeft: 8 }}>9/18 起每日记录</span>
      </h2>
      <p className="hint" style={{ margin: "4px 0 12px" }}>
        稳定盈利 = 期望为正 + 回撤可控，不要求每笔都赚。历史段为已实现口径，浮动仅计入当日。
      </p>
      <table>
        <thead><tr>
          <th>账本</th><th style={{ textAlign: "right" }}>已实现</th>
          <th style={{ textAlign: "right" }}>浮动</th>
          <th style={{ textAlign: "right" }}>合计</th>
          <th style={{ textAlign: "right" }}>最大回撤</th>
          <th style={{ textAlign: "right" }}>盈利因子</th>
          <th style={{ textAlign: "right" }}>每笔期望</th>
          <th style={{ textAlign: "right" }}>胜率（笔数）</th>
        </tr></thead>
        <tbody>
          {rows.map(({ label, s, color }) => (
            <tr key={label}>
              <td><span style={{ color, fontWeight: 600 }}>{label}</span></td>
              <td style={{ textAlign: "right" }}>{signed(s.realized)}</td>
              <td style={{ textAlign: "right" }}>{signed(s.unrealized)}</td>
              <td style={{ textAlign: "right", fontWeight: 700 }}
                  className={s.total >= 0 ? "pos" : "neg"}>{signed(s.total)}</td>
              <td style={{ textAlign: "right" }} className="neg">{signed(s.mdd)}</td>
              <td style={{ textAlign: "right" }}>{s.pf == null ? "—" : fmt(s.pf)}</td>
              <td style={{ textAlign: "right" }}
                  className={(s.exp ?? 0) >= 0 ? "pos" : "neg"}>{s.exp == null ? "—" : signed(s.exp)}</td>
              <td style={{ textAlign: "right" }} className="muted">
                {s.n ? `${Math.round((s.wins / s.n) * 100)}%（${s.n}）` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* 富途真实成本测算 */}
      <h3 style={{ marginTop: 18 }}>富途真实成本测算</h3>
      <p style={{ margin: "8px 0", display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <span className="muted" style={{ fontSize: 12 }}>单笔金额：</span>
        {[100, 500, 1000, 2000].map((n) => (
          <button key={n} className="btn" onClick={() => setNotional(n)}
                  style={{ padding: "3px 10px", fontSize: 12,
                           ...(notional === n ? { borderColor: "var(--accent)",
                             color: "var(--accent)", fontWeight: 700 } : {}) }}>
            ${n}
          </button>
        ))}
      </p>
      <table>
        <thead><tr>
          <th>账本</th><th style={{ textAlign: "right" }}>净合计（扣费）</th>
          <th style={{ textAlign: "right" }}>每笔净期望</th>
          <th style={{ textAlign: "right" }}>盈利因子（净）</th>
          <th style={{ textAlign: "right" }}>费用占毛利</th>
        </tr></thead>
        <tbody>
          {costRows.map(({ label, color, total, exp, pf, costPct }) => (
            <tr key={label}>
              <td><span style={{ color, fontWeight: 600 }}>{label}</span></td>
              <td style={{ textAlign: "right", fontWeight: 700 }}
                  className={total >= 0 ? "pos" : "neg"}>{signed(total)}</td>
              <td style={{ textAlign: "right" }}
                  className={(exp ?? 0) >= 0 ? "pos" : "neg"}>{exp == null ? "—" : signed(exp)}</td>
              <td style={{ textAlign: "right" }}>{pf == null ? "—" : fmt(pf)}</td>
              <td style={{ textAlign: "right" }} className="muted">
                {costPct == null ? "—" : `${fmt(costPct, 0)}%`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint" style={{ marginTop: 8 }}>
        含佣金/平台费/交收费/卖出规费、滑点 0.05%×2、沽空借货年化 5%；未含碎股优惠（待验证）。
        按同一批真实平仓交易等比换算，不代表未来收益。
      </p>

      {curve.length > 1 && (
        <>
          <h3 style={{ marginTop: 18 }}>累计净值（已实现 + 当日浮动）</h3>
          <div style={{ width: "100%", height: 220, marginTop: 8 }}>
            <ResponsiveContainer>
              <LineChart data={curve} margin={{ top: 4, right: 8, bottom: 0, left: -14 }}>
                <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={24}
                       stroke="var(--muted)" />
                <YAxis tick={{ fontSize: 11 }} stroke="var(--muted)" />
                <Tooltip formatter={(v) => (v == null ? "—" : signed(v))}
                         contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }} />
                <ReferenceLine y={0} stroke="var(--border)" />
                <Line type="monotone" dataKey="daily" name="日线" stroke={COLORS.daily}
                      dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="h1" name="1 小时" stroke={COLORS.h1}
                      dot={false} strokeWidth={2} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      {weekly.length > 1 && (
        <>
          <h3 style={{ marginTop: 18 }}>每周已实现盈亏</h3>
          <div style={{ width: "100%", height: 170, marginTop: 8 }}>
            <ResponsiveContainer>
              <BarChart data={weekly} margin={{ top: 4, right: 8, bottom: 0, left: -14 }}>
                <XAxis dataKey="week" tick={{ fontSize: 11 }} stroke="var(--muted)" />
                <YAxis tick={{ fontSize: 11 }} stroke="var(--muted)" />
                <Tooltip formatter={(v) => signed(v)}
                         contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }} />
                <ReferenceLine y={0} stroke="var(--border)" />
                <Bar dataKey="daily" name="日线" fill={COLORS.daily} radius={[3, 3, 0, 0]} />
                <Bar dataKey="h1" name="1 小时" fill={COLORS.h1} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
