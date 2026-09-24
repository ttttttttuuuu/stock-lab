"use client";

// TradingView Lightweight Charts wrapper: candlesticks + trade markers.
// v5 API: chart.addSeries(CandlestickSeries, ...), createSeriesMarkers.
import { useEffect, useRef } from "react";
import {
  createChart, CandlestickSeries, createSeriesMarkers,
} from "lightweight-charts";

function themeColors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n) => cs.getPropertyValue(n).trim();
  const dark = document.documentElement.dataset.theme !== "light";
  return {
    text: v("--muted") || (dark ? "#9aa3b5" : "#5b6472"),
    grid: dark ? "rgba(139, 147, 165, 0.08)" : "rgba(100, 116, 139, 0.12)",
    border: v("--border") || (dark ? "#262b38" : "#e2e8f0"),
    green: v("--green") || "#22c55e",
    red: v("--red") || "#ef4444",
    accent: v("--accent") || "#6366f1",
  };
}

export default function StockChart({ candles, trades = [], height = 420 }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current || !candles?.length) return undefined;
    const c = themeColors();

    const chart = createChart(ref.current, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: c.text,
        attributionLogo: false,
        fontSize: 11,
      },
      grid: {
        vertLines: { color: c.grid },
        horzLines: { color: c.grid },
      },
      rightPriceScale: { borderColor: c.border },
      timeScale: { borderColor: c.border, rightOffset: 4 },
      crosshair: {
        vertLine: { color: c.accent, labelBackgroundColor: c.accent },
        horzLine: { color: c.accent, labelBackgroundColor: c.accent },
      },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: c.green, downColor: c.red, borderVisible: false,
      wickUpColor: c.green, wickDownColor: c.red,
    });
    series.setData(candles.map((b) => ({
      time: b.date, open: b.open, high: b.high, low: b.low, close: b.close,
    })));

    // entry / exit markers — must be sorted by time ascending
    const markers = [];
    for (const t of trades) {
      const long = t.side === "long";
      markers.push({
        time: t.entry_date,
        position: long ? "belowBar" : "aboveBar",
        color: long ? c.green : c.red,
        shape: long ? "arrowUp" : "arrowDown",
        text: `${long ? "买入" : "卖空"} ${t.entry_price}`,
      });
      if (t.exit_date) {
        markers.push({
          time: t.exit_date,
          position: long ? "aboveBar" : "belowBar",
          color: t.pnl > 0 ? c.green : c.red,
          shape: long ? "arrowDown" : "arrowUp",
          text: `平仓 ${t.pnl > 0 ? "+" : ""}${t.pnl}`,
        });
      }
    }
    markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
    createSeriesMarkers(series, markers);

    chart.timeScale().fitContent();

    // live theme switching without remount
    const obs = new MutationObserver(() => {
      const t = themeColors();
      chart.applyOptions({
        layout: { textColor: t.text },
        grid: { vertLines: { color: t.grid }, horzLines: { color: t.grid } },
        rightPriceScale: { borderColor: t.border },
        timeScale: { borderColor: t.border },
      });
      series.applyOptions({
        upColor: t.green, downColor: t.red,
        wickUpColor: t.green, wickDownColor: t.red,
      });
    });
    obs.observe(document.documentElement, {
      attributes: true, attributeFilter: ["data-theme"],
    });

    return () => { obs.disconnect(); chart.remove(); };
  }, [candles, trades]);

  return <div ref={ref} style={{ width: "100%", height }} aria-label="K线图" />;
}
