"use client";

import { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import {
  loadStockPaper, loadStockPaper1h, loadPaperEquity, loadPaper1hEquity,
} from "../lib/data";

const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d });
const signed = (n) => `${n >= 0 ? "+" : "-"}$${fmt(Math.abs(n))}`;
const COLORS = { daily: "#f59e0b", h1: "#6366f1" };

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
  const [eqD, setEqD] = useState([]);
  const [eqH, setEqH] = useState([]);

  useEffect(() => {
    loadStockPaper().then(setDaily).catch(() => {});
    loadStockPaper1h().then(setH1).catch(() => {});
    loadPaperEquity().then(setEqD).catch(() => {});
    loadPaper1hEquity().then(setEqH).catch(() => {});
  }, []);

  if (!daily && !h1) return null;

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
