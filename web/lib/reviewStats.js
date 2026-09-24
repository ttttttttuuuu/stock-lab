// Shared paper-trade review statistics + deviation alert logic.
// Used by /review (full table) and / (alert chip on the paper panel).

export function tradeStats(ts) {
  if (!ts.length) return null;
  const wins = ts.filter((t) => t.pnl > 0);
  const grossWin = wins.reduce((a, t) => a + t.pnl, 0);
  const grossLoss = -ts.filter((t) => t.pnl <= 0).reduce((a, t) => a + t.pnl, 0);
  return {
    n: ts.length,
    win_rate: Math.round((wins.length / ts.length) * 1000) / 10,
    total_pnl: Math.round(ts.reduce((a, t) => a + t.pnl, 0) * 100) / 100,
    avg_pnl: Math.round((ts.reduce((a, t) => a + t.pnl, 0) / ts.length) * 100) / 100,
    avg_win: wins.length ? Math.round((grossWin / wins.length) * 100) / 100 : null,
    avg_loss: ts.length - wins.length
      ? Math.round((grossLoss / (ts.length - wins.length)) * 100) / 100 : null,
    profit_factor: grossLoss > 0 ? Math.round((grossWin / grossLoss) * 100) / 100 : null,
    avg_days:
      Math.round((ts.reduce((a, t) => a + (t.hold_days || 0), 0) / ts.length) * 10) / 10,
  };
}

// Alert levels vs the 2-year backtest baseline:
//   insufficient — fewer than MIN_SAMPLE closed trades, no judgement
//   ok           — within tolerance
//   watch        — win rate -8pp or worse, or avg P&L down >50% vs baseline
//   critical     — win rate -15pp or worse, or sign flip vs a profitable baseline
export const MIN_SAMPLE = 5;
export const WIN_RATE_CRIT_PP = -15;
export const WIN_RATE_WATCH_PP = -8;

export function alertLevel(actual, baseline) {
  if (!actual || !baseline || actual.n < MIN_SAMPLE) {
    return { level: "insufficient", label: "样本不足", reasons: [] };
  }
  const dWin = Math.round((actual.win_rate - baseline.win_rate) * 10) / 10;
  const reasons = [];
  if (dWin <= WIN_RATE_CRIT_PP)
    reasons.push(`胜率偏离 ${dWin}pp（阈值 ${WIN_RATE_CRIT_PP}pp）`);
  if (baseline.avg_pnl > 0 && actual.avg_pnl < 0)
    reasons.push(`均盈亏由正转负（回测 $${baseline.avg_pnl} → 实际 $${actual.avg_pnl}）`);
  if (reasons.length)
    return { level: "critical", label: "⚠ 显著偏离", reasons, dWin };

  const watch = [];
  if (dWin <= WIN_RATE_WATCH_PP)
    watch.push(`胜率偏离 ${dWin}pp`);
  if (baseline.avg_pnl > 0 &&
      actual.avg_pnl < baseline.avg_pnl * 0.5)
    watch.push(`均盈亏不及回测一半（$${actual.avg_pnl} vs $${baseline.avg_pnl}）`);
  if (watch.length) return { level: "watch", label: "观察", reasons: watch, dWin };

  return { level: "ok", label: "正常", reasons: [], dWin };
}

// Evaluate every strategy that has both a baseline and/or live trades.
// baselineRows: overview.leaderboard entries; closedTrades: paper+closed.
export function evaluateStrategies(baselineRows, closedTrades) {
  const byStrat = {};
  closedTrades.forEach((t) => (byStrat[t.strategy] = byStrat[t.strategy] || []).push(t));
  return baselineRows.map((b) => {
    const actual = tradeStats(byStrat[b.strategy] || []);
    return { strategy: b.strategy, baseline: b, actual, alert: alertLevel(actual, b) };
  });
}
