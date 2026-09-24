// Shared strategy key -> display label map (single source for all pages).
export const STRAT_LABELS = {
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

export const stratLabel = (key) => STRAT_LABELS[key] || key;

// the stock-lab matrix runs on daily bars (intraday experiment concluded:
// daily is the only production timeframe)
export const INTERVAL_LABEL = "日线";
