import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Bar } from "./api";
import { instant, number } from "./format";
export default function MarketChart({
  bars,
  identity,
  theme,
}: {
  bars: Bar[];
  identity: string;
  theme: string;
}) {
  const host = useRef<HTMLDivElement>(null),
    chart = useRef<IChartApi | null>(null),
    ranges = useRef(new Map<string, { from: number; to: number }>());
  const [hover, setHover] = useState<Bar | null>(null);
  useEffect(() => {
    if (!host.current || !bars.length) return;
    const light = theme === "light";
    const c = createChart(host.current, {
      height: 390,
      autoSize: true,
      layout: {
        background: {
          type: ColorType.Solid,
          color: light ? "#ffffff" : "#121a29",
        },
        textColor: light ? "#43516b" : "#8997af",
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: light ? "#edf0f5" : "#1b2638" },
        horzLines: { color: light ? "#edf0f5" : "#1b2638" },
      },
      rightPriceScale: { borderColor: "#29354a" },
      timeScale: { timeVisible: true, borderColor: "#29354a" },
      crosshair: { mode: 0 },
    });
    chart.current = c;
    const candle = c.addSeries(CandlestickSeries, {
      upColor: "#35c6a4",
      downColor: "#f3778d",
      wickUpColor: "#35c6a4",
      wickDownColor: "#f3778d",
      borderVisible: false,
    });
    candle.setData(bars.map((b) => ({ ...b, time: b.time as UTCTimestamp })));
    const volume = c.addSeries(
      HistogramSeries,
      { priceFormat: { type: "volume" } },
      1,
    );
    volume.setData(
      bars.map((b) => ({
        time: b.time as UTCTimestamp,
        value: b.volume,
        color: b.close >= b.open ? "#35c6a46b" : "#f3778d6b",
      })),
    );
    c.panes()[0]?.setHeight(290);
    c.panes()[1]?.setHeight(100);
    const rangeCache = ranges.current;
    const saved = rangeCache.get(identity);
    if (saved) c.timeScale().setVisibleLogicalRange(saved);
    else c.timeScale().fitContent();
    c.subscribeCrosshairMove((p) => {
      const point = p.seriesData.get(candle);
      setHover(
        point && "close" in point
          ? (bars.find((b) => b.time === point.time) ?? null)
          : null,
      );
    });
    return () => {
      const range = c.timeScale().getVisibleLogicalRange();
      if (range) rangeCache.set(identity, range);
      c.remove();
      chart.current = null;
    };
  }, [bars, identity, theme]);
  const current = hover ?? bars.at(-1);
  const zoom = (factor: number) => {
    const scale = chart.current?.timeScale(),
      range = scale?.getVisibleLogicalRange();
    if (scale && range) {
      const middle = (range.from + range.to) / 2,
        width = ((range.to - range.from) * factor) / 2;
      scale.setVisibleLogicalRange({
        from: middle - width,
        to: middle + width,
      });
    }
  };
  return (
    <div className="chart-section">
      <div className="chart-toolbar">
        <div className="ohlc" aria-live="off">
          <span>
            O <b>{number(current?.open)}</b>
          </span>
          <span>
            H <b>{number(current?.high)}</b>
          </span>
          <span>
            L <b>{number(current?.low)}</b>
          </span>
          <span>
            C <b>{number(current?.close)}</b>
          </span>
          <span>
            Vol <b>{number(current?.volume)}</b>
          </span>
        </div>
        <div className="button-group">
          <button
            onClick={() => zoom(0.7)}
            disabled={!bars.length}
            aria-label="Ingrandisci grafico"
          >
            ＋
          </button>
          <button
            onClick={() => zoom(1.4)}
            disabled={!bars.length}
            aria-label="Riduci grafico"
          >
            −
          </button>
          <button
            onClick={() => chart.current?.timeScale().fitContent()}
            disabled={!bars.length}
          >
            Adatta
          </button>
        </div>
      </div>
      <div
        ref={host}
        className="chart"
        role="img"
        aria-label={`Candlestick e volume. Ultima barra ${instant(current?.time)}. Prezzi USD; volume unità dello strumento. Zoom con rotella e trascinamento.`}
      />
      {!bars.length && (
        <p className="empty">
          Nessuna barra disponibile. Nessun grafico sintetico di fallback.
        </p>
      )}
      <div className="chart-foot">
        <span>Prezzi USD · Volume in unità · Trascina per navigare</span>
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
          Grafici TradingView Lightweight Charts™
        </a>
      </div>
    </div>
  );
}
