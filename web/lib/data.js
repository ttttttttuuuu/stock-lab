// Dual-mode data layer with caching:
// - Supabase mode when NEXT_PUBLIC_SUPABASE_URL + NEXT_PUBLIC_SUPABASE_ANON_KEY
//   are set (reads live cloud tables via PostgREST)
// - Static JSON mode otherwise (files exported by `python -m engine.export_web`)
//
// Caching: in-memory Map for the session (all loaders) + localStorage
// stale-while-revalidate for small payloads (overview/signals). TTL 5 min.
// The 7.5MB trades payload is memory-cached only (localStorage quota).

const SB_URL = process.env.NEXT_PUBLIC_SUPABASE_URL
  || "https://hmdiyqqvdwtqbbhwsgjr.supabase.co";
const SB_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  || "sb_publishable_cNJ6-lUSzM88MigBIoDpiQ_TEqtEccp";
export const DATA_SOURCE = SB_URL && SB_KEY ? "supabase" : "local";
// true on static hosting (Cloudflare Pages): no server, no /api/* routes
export const IS_STATIC = process.env.NEXT_PUBLIC_STATIC_EXPORT === "1";

const TTL_MS = 5 * 60 * 1000;
const SWR_WINDOW_MS = 24 * 3600 * 1000;
const memCache = new Map();

// jsonb columns may come back double-encoded as strings from older syncs
const maybeParse = (v) => {
  if (typeof v !== "string") return v;
  try { return JSON.parse(v); } catch { return v; }
};

function persistGet(key) {
  try {
    const raw = localStorage.getItem("wot:" + key);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function persistSet(key, entry) {
  try { localStorage.setItem("wot:" + key, JSON.stringify(entry)); } catch {}
}

async function cached(key, loader, { persist = false } = {}) {
  const now = Date.now();
  const mem = memCache.get(key);
  if (mem && now - mem.t < TTL_MS) return mem.v;

  if (persist && typeof localStorage !== "undefined") {
    const disk = persistGet(key);
    if (disk) {
      if (now - disk.t < TTL_MS) {
        memCache.set(key, disk);
        return disk.v;
      }
      if (now - disk.t < SWR_WINDOW_MS) {
        // stale-while-revalidate: serve stale, refresh in background
        memCache.set(key, disk);
        loader().then((v) => {
          const entry = { t: Date.now(), v };
          memCache.set(key, entry);
          persistSet(key, entry);
        }).catch(() => {});
        return disk.v;
      }
    }
  }

  const v = await loader();
  const entry = { t: now, v };
  memCache.set(key, entry);
  if (persist && typeof localStorage !== "undefined") persistSet(key, entry);
  return v;
}

const PAGE = 1000;

async function sbTable(table, query = "") {
  const all = [];
  let from = 0;
  for (;;) {
    const res = await fetch(`${SB_URL}/rest/v1/${table}?${query}`, {
      headers: {
        apikey: SB_KEY,
        Authorization: `Bearer ${SB_KEY}`,
        Range: `${from}-${from + PAGE - 1}`,
      },
    });
    if (!res.ok) throw new Error(`Supabase ${table}: ${res.status}`);
    const rows = await res.json();
    all.push(...rows);
    if (rows.length < PAGE) break;
    from += PAGE;
  }
  return all;
}

// ---------- overview aggregation (mirrors engine/export_web.py) ----------

function aggregate(trades) {
  const bt = trades.filter((t) => t.source === "backtest");
  const paper = trades.filter((t) => t.source === "paper");
  const byStrat = {};
  bt.forEach((t) => (byStrat[t.strategy] = byStrat[t.strategy] || []).push(t));

  const leaderboard = Object.entries(byStrat)
    .map(([strategy, ts]) => {
      const wins = ts.filter((t) => t.pnl > 0);
      const grossWin = wins.reduce((a, t) => a + t.pnl, 0);
      const grossLoss = -ts.filter((t) => t.pnl <= 0).reduce((a, t) => a + t.pnl, 0);
      return {
        strategy,
        trades: ts.length,
        win_rate: Math.round((wins.length / ts.length) * 1000) / 10,
        total_pnl: Math.round(ts.reduce((a, t) => a + t.pnl, 0) * 100) / 100,
        avg_pnl:
          Math.round((ts.reduce((a, t) => a + t.pnl, 0) / ts.length) * 100) / 100,
        profit_factor: grossLoss > 0 ? Math.round((grossWin / grossLoss) * 100) / 100 : null,
      };
    })
    .sort((a, b) => b.total_pnl - a.total_pnl);

  const curves = {};
  Object.entries(byStrat).forEach(([strategy, ts]) => {
    const daily = {};
    ts.forEach((t) => (daily[t.exit_date] = (daily[t.exit_date] || 0) + t.pnl));
    let cum = 0;
    curves[strategy] = Object.keys(daily)
      .sort()
      .map((d) => ({ date: d, pnl: Math.round((cum += daily[d]) * 100) / 100 }));
  });

  const heatmap = {};
  bt.forEach((t) => {
    heatmap[t.symbol] = heatmap[t.symbol] || {};
    heatmap[t.symbol][t.strategy] =
      Math.round(((heatmap[t.symbol][t.strategy] || 0) + t.pnl) * 100) / 100;
  });

  return {
    leaderboard,
    curves,
    heatmap,
    // closed paper trades (paper rows only exist once closed) — used for
    // deviation alerts on Overview without an extra heavy fetch
    paper_trades: paper.filter((t) => t.exit_date),
    totals: {
      backtest_trades: bt.length,
      paper_trades: paper.length,
      symbols: [...new Set(bt.map((t) => t.symbol))].sort(),
      strategies: Object.keys(byStrat).sort(),
      total_pnl: Math.round(bt.reduce((a, t) => a + t.pnl, 0) * 100) / 100,
    },
  };
}

function buildPaperAccount(trades, positions, snapshots) {
  const paper = trades.filter((t) => t.source === "paper");
  const cost = positions.reduce((a, p) => a + p.entry_price * 100 * p.qty, 0);
  const value = positions.reduce(
    (a, p) => a + (p.last_mark ?? p.entry_price) * 100 * p.qty, 0);
  const unrealized = Math.round((value - cost) * 100) / 100;
  const realized = Math.round(paper.reduce((a, t) => a + t.pnl, 0) * 100) / 100;

  let equity = [];
  const entries = positions.map((p) => p.entry_date)
    .concat(paper.map((t) => t.entry_date));
  if (snapshots && snapshots.length) {
    // daily snapshots carry full history (total = realized + unrealized)
    equity = snapshots.map((s) => ({ date: s.date, pnl: s.total }));
    if (entries.length && equity[0].date > entries.reduce((a, b) => (a < b ? a : b)))
      equity.unshift({ date: entries.reduce((a, b) => (a < b ? a : b)), pnl: 0 });
    if (positions.length && equity.length) equity[equity.length - 1].unrealized = true;
  } else {
    // fallback: realized exits + current unrealized point
    const daily = {};
    paper.forEach((t) => (daily[t.exit_date] = (daily[t.exit_date] || 0) + t.pnl));
    let cum = 0;
    equity = Object.keys(daily).sort()
      .map((d) => ({ date: d, pnl: Math.round((cum += daily[d]) * 100) / 100 }));
    if (entries.length) {
      const first = entries.reduce((a, b) => (a < b ? a : b));
      if (!equity.length || equity[0].date > first)
        equity.unshift({ date: first, pnl: 0 });
    }
    if (positions.length) {
      const markDay = (positions[0].marked_at || "").slice(0, 10);
      if (markDay)
        equity.push({ date: markDay,
                      pnl: Math.round((cum + unrealized) * 100) / 100,
                      unrealized: true });
    }
  }

  return {
    positions,
    cost: Math.round(cost * 100) / 100,
    value: Math.round(value * 100) / 100,
    unrealized,
    realized,
    equity,
    marked_at: positions[0]?.marked_at ?? null,
  };
}

// ---------- public loaders ----------

export function loadTrades() {
  // big payload: memory cache only
  return cached("trades", () =>
    DATA_SOURCE === "supabase"
      ? sbTable("trades", "order=entry_date.asc")
      : fetch("/data/trades.json").then((r) => r.json()));
}

export function loadOverview() {
  return cached("overview:" + DATA_SOURCE, async () => {
    if (DATA_SOURCE === "supabase") {
      const [trades, positionsRaw, snapshots] = await Promise.all([
        loadTrades(),
        sbTable("paper_positions"),
        // table may not exist yet on older clouds — degrade to fallback curve
        sbTable("equity_snapshots", "order=date.asc").catch(() => null),
      ]);
      const ov = aggregate(trades);
      ov.paper_account = buildPaperAccount(
        trades, positionsRaw.map((p) => maybeParse(p.data)), snapshots);
      return ov;
    }
    return (await fetch("/data/overview.json")).json();
  }, { persist: true });
}

export function loadSignalsData() {
  return cached("signals:" + DATA_SOURCE, async () => {
    if (DATA_SOURCE === "supabase") {
      const [signalsRaw, positionsRaw, trades] = await Promise.all([
        // latest per symbol+strategy: 50 symbols x 6 strategies = 300 rows
        sbTable("signals", "order=created_at.desc&limit=400"),
        sbTable("paper_positions"),
        sbTable("trades", "source=eq.paper&order=entry_date.asc"),
      ]);
      const seen = new Set();
      const signals = [];
      for (const s of signalsRaw) {
        const key = `${s.symbol}|${s.strategy}`;
        if (!seen.has(key)) {
          seen.add(key);
          signals.push({ ...s, details: maybeParse(s.details) });
        }
      }
      return {
        signals,
        paper_positions: positionsRaw.map((p) => maybeParse(p.data)),
        paper_trades: trades,
      };
    }
    return (await fetch("/data/signals.json")).json();
  }, { persist: true });
}

// ---------- stock lab (strategy x symbol stock-price backtest) ----------

// drop cached entries (memory + localStorage) by key prefix — used after a
// lazy refresh writes new data so the page re-reads fresh values
export function invalidatePrefix(prefix) {
  for (const k of [...memCache.keys()]) {
    if (k.startsWith(prefix)) memCache.delete(k);
  }
  if (typeof localStorage !== "undefined") {
    Object.keys(localStorage)
      .filter((k) => k.startsWith("wot:" + prefix))
      .forEach((k) => localStorage.removeItem(k));
  }
}

export function loadStockLab() {
  return cached("stocklab:" + DATA_SOURCE, async () => {
    if (DATA_SOURCE === "supabase") {
      try {
        const runs = await sbTable("stock_runs", "order=run_at.desc");
        if (runs.length) {
          const latest = runs[0].run_at;
          const pairs = runs
            .filter((r) => r.run_at === latest)
            .map((r) => ({ symbol: r.symbol, strategy: r.strategy,
                            ...maybeParse(r.metrics) }))
            .sort((a, b) => (b.total_pnl || 0) - (a.total_pnl || 0));
          return { run_at: latest, pairs };
        }
      } catch { /* tables not created yet — fall back to local export */ }
    }
    return (await fetch("/data/stock_lab.json")).json();
  }, { persist: true });
}

export function loadStockPairTrades(strategy, symbol) {
  return cached(`stpair:${strategy}:${symbol}:${DATA_SOURCE}`, async () => {
    if (DATA_SOURCE === "supabase") {
      try {
        return await sbTable("stock_trades",
          `strategy=eq.${strategy}&symbol=eq.${symbol}&order=entry_date.asc`);
      } catch { /* fall back to local export */ }
    }
    const r = await fetch(`/data/stock_trades/${strategy}__${symbol}.json`);
    return r.ok ? r.json() : [];
  });
}

export function loadPrices(symbol) {
  return cached(`prices:${symbol}:${DATA_SOURCE}`, async () => {
    if (DATA_SOURCE === "supabase") {
      try {
        return await sbTable("prices", `symbol=eq.${symbol}&order=date.asc`);
      } catch { /* fall back to local export */ }
    }
    const r = await fetch(`/data/prices/${symbol}.json`);
    return r.ok ? r.json() : [];
  });
}

// capital simulation ("what if I started on day X with $1000") — static file
// written by engine.capital_sim, same-origin in both data modes
export function loadCapitalSim() {
  return cached("capsim", async () => {
    const r = await fetch("/data/capital_sim.json");
    return r.ok ? r.json() : null;
  });
}

// live 1h paper verification of the recommended portfolio — static file
// written by engine.intraday_paper, same-origin in both data modes
export function loadStockPaper1h() {
  return cached("stockpaper1h", async () => {
    const r = await fetch("/data/stock_paper_1h.json");
    return r.ok ? r.json() : null;
  });
}

// production params (incl. watchlist of probation strategies) — static file
// served same-origin in both Supabase and local mode; written by export_web
export function loadProductionParams() {
  return cached("prodparams", async () => {
    const r = await fetch("/data/production_params.json");
    return r.ok ? r.json() : { watchlist: [] };
  });
}

// live paper verification book for top stock-lab pairs
export function loadStockPaper() {
  return cached("stockpaper:" + DATA_SOURCE, async () => {
    if (DATA_SOURCE === "supabase") {
      try {
        const [positionsRaw, trades] = await Promise.all([
          sbTable("stock_paper_positions"),
          sbTable("stock_paper_trades", "order=entry_date.asc"),
        ]);
        return {
          positions: positionsRaw.map((p) => maybeParse(p.data)),
          closed_trades: trades,
        };
      } catch { /* tables not created yet — fall back to local export */ }
    }
    const r = await fetch("/data/stock_paper.json");
    return r.ok ? r.json() : { positions: [], closed_trades: [] };
  }, { persist: true });
}

// ---------- parameter optimization grid results ----------

// mirrors engine/export_web.py aggregation (Supabase mode)
function aggregateParamOpt(rows, runAt) {
  const r2 = (n) => Math.round(n * 100) / 100;
  const byCombo = new Map();
  const byPair = new Map();
  for (const r of rows) {
    const ck = r.strategy + "|" + JSON.stringify(r.params);
    if (!byCombo.has(ck)) byCombo.set(ck, []);
    byCombo.get(ck).push(r);
    const pk = r.symbol + "|" + r.strategy;
    if (!byPair.has(pk)) byPair.set(pk, []);
    byPair.get(pk).push(r);
  }

  const strategies = {};
  for (const [ck, list] of byCombo) {
    const strat = list[0].strategy;
    const trades = list.reduce((a, r) => a + (r.metrics.trades || 0), 0);
    const wins = list.reduce((a, r) => a + (r.metrics.wins || 0), 0);
    const grossWin = list.reduce((a, r) => a + (r.metrics.avg_win || 0) * (r.metrics.wins || 0), 0);
    const grossLoss = list.reduce((a, r) => a + -(r.metrics.avg_loss || 0) * ((r.metrics.trades || 0) - (r.metrics.wins || 0)), 0);
    const totalPnl = r2(list.reduce((a, r) => a + (r.metrics.total_pnl || 0), 0));
    (strategies[strat] = strategies[strat] || []).push({
      params: list[0].params,
      is_default: !!list[0].is_default,
      symbols: list.length,
      trades,
      win_rate: trades ? Math.round((wins / trades) * 1000) / 10 : 0,
      total_pnl: totalPnl,
      avg_pnl: trades ? r2(totalPnl / trades) : 0,
      profit_factor: grossLoss > 0 ? r2(grossWin / grossLoss) : null,
    });
  }
  for (const s of Object.values(strategies)) s.sort((a, b) => b.total_pnl - a.total_pnl);

  const pairs = [];
  for (const [pk, list] of byPair) {
    const sorted = [...list].sort((a, b) => (b.metrics.total_pnl || 0) - (a.metrics.total_pnl || 0));
    const best = sorted[0];
    const dflt = list.find((r) => r.is_default);
    if (!dflt) continue;
    const [symbol, strategy] = pk.split("|");
    pairs.push({
      symbol, strategy,
      default_params: dflt.params,
      default_pnl: dflt.metrics.total_pnl || 0,
      default_win_rate: dflt.metrics.win_rate || 0,
      default_trades: dflt.metrics.trades || 0,
      best_params: best.params,
      best_pnl: best.metrics.total_pnl || 0,
      best_win_rate: best.metrics.win_rate || 0,
      best_trades: best.metrics.trades || 0,
      delta: r2((best.metrics.total_pnl || 0) - (dflt.metrics.total_pnl || 0)),
    });
  }
  pairs.sort((a, b) => b.delta - a.delta);
  return { run_at: runAt, strategies, pairs };
}

export function loadParamOpt() {
  return cached("paramopt:" + DATA_SOURCE, async () => {
    if (DATA_SOURCE === "supabase") {
      try {
        const rows = await sbTable("param_runs", "order=run_at.desc");
        if (rows.length) {
          const latest = rows[0].run_at;
          const grid = rows
            .filter((r) => r.run_at === latest)
            .map((r) => ({ ...r, params: maybeParse(r.params),
                            metrics: maybeParse(r.metrics),
                            is_default: !!r.is_default }));
          return aggregateParamOpt(grid, latest);
        }
      } catch { /* table not created yet — fall back to local export */ }
    }
    return (await fetch("/data/param_opt.json")).json();
  }, { persist: true });
}

// ---------- exit-structure grid results ----------

// mirrors engine/export_web.py aggregation (Supabase mode)
function aggregateExitOpt(rows, runAt) {
  const r2 = (n) => Math.round(n * 100) / 100;
  const agg = (list) => {
    const trades = list.reduce((a, r) => a + (r.metrics.trades || 0), 0);
    const wins = list.reduce((a, r) => a + (r.metrics.wins || 0), 0);
    const grossWin = list.reduce((a, r) => a + (r.metrics.avg_win || 0) * (r.metrics.wins || 0), 0);
    const grossLoss = list.reduce((a, r) => a + -(r.metrics.avg_loss || 0) * ((r.metrics.trades || 0) - (r.metrics.wins || 0)), 0);
    const totalPnl = r2(list.reduce((a, r) => a + (r.metrics.total_pnl || 0), 0));
    const f = list[0];
    return {
      take_profit: f.take_profit, stop_loss: f.stop_loss,
      is_default: !!f.is_default,
      trades,
      win_rate: trades ? Math.round((wins / trades) * 1000) / 10 : 0,
      total_pnl: totalPnl,
      avg_pnl: trades ? r2(totalPnl / trades) : 0,
      profit_factor: grossLoss > 0 ? r2(grossWin / grossLoss) : null,
    };
  };
  const byExit = new Map();
  const byStratExit = new Map();
  for (const r of rows) {
    const ek = r.take_profit + "|" + r.stop_loss;
    if (!byExit.has(ek)) byExit.set(ek, []);
    byExit.get(ek).push(r);
    const sk = r.strategy + "|" + ek;
    if (!byStratExit.has(sk)) byStratExit.set(sk, []);
    byStratExit.get(sk).push(r);
  }
  const globalExit = [...byExit.values()].map(agg)
    .sort((a, b) => b.total_pnl - a.total_pnl);
  const strategies = {};
  for (const [sk, list] of byStratExit) {
    const strat = sk.split("|")[0];
    (strategies[strat] = strategies[strat] || []).push(agg(list));
  }
  for (const s of Object.values(strategies)) s.sort((a, b) => b.total_pnl - a.total_pnl);
  return { run_at: runAt, global: globalExit, strategies };
}

export function loadExitOpt() {
  return cached("exitopt:" + DATA_SOURCE, async () => {
    if (DATA_SOURCE === "supabase") {
      try {
        const rows = await sbTable("exit_runs", "order=run_at.desc");
        if (rows.length) {
          const latest = rows[0].run_at;
          const grid = rows
            .filter((r) => r.run_at === latest)
            .map((r) => ({ ...r, metrics: maybeParse(r.metrics),
                            is_default: !!r.is_default }));
          return aggregateExitOpt(grid, latest);
        }
      } catch { /* table not created yet — fall back to local export */ }
    }
    return (await fetch("/data/exit_opt.json")).json();
  }, { persist: true });
}
