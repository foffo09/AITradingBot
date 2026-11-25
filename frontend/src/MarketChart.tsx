import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { Bar, Indicator } from "./api";
import { instant, number, price, priceDigits } from "./format";

// shortcut: exponent notation (e.g. 1.5e-7) counts only mantissa decimals; fine while MT5/demo declare digits.
const decimals = (value: number) => {
  const [, fraction = ""] = String(value).split("e")[0].split(".");
  return Number.isFinite(value) ? fraction.length : 0;
};
const EMPTY_INDICATORS: Indicator[] = [];
export default function MarketChart({
  bars,
  identity,
  theme,
  priceUnit = "USD",
  priceDigits: declaredDigits = null,
  volumeUnit = "unità",
  indicators = EMPTY_INDICATORS,
}: {
  bars: Bar[];
  indicators?: Indicator[];
  identity: string;
  theme: string;
  priceUnit?: string;
  priceDigits?: unknown;
  volumeUnit?: string;
}) {
  const host = useRef<HTMLDivElement>(null),
    chart = useRef<IChartApi | null>(null),
    ranges = useRef(new Map<string, { from: number; to: number }>());
  const [hover, setHover] = useState<{ identity: string; time: number } | null>(
    null,
  );
  const [enabled, setEnabled] = useState<string[]>([]);
  // Declared instrument precision; otherwise the decimals actually present in the closes (max 8).
  const digits = priceDigits(declaredDigits) ?? Math.min(8, Math.max(0, ...bars.map((b) => decimals(b.close))));
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
      priceFormat: { type: "price", precision: digits, minMove: 10 ** -digits },
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
    for (const [index, indicator] of indicators.entries()) {
      if (!enabled.includes(indicator.id)) continue;
      const line = c.addSeries(LineSeries, { color: ["#a78bfa", "#60a5fa", "#f6c85f", "#fa9fb5", "#8dd3c7", "#b3a2cf"][index % 6], lineWidth: 2, title: indicator.label }, indicator.pane === "rsi" ? 2 : 0);
      line.setData(indicator.points.map(p => p.value === null ? {time:p.time as UTCTimestamp} : {time:p.time as UTCTimestamp,value:p.value}));
    }
    c.panes()[2]?.setHeight(100);
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
          ? { identity, time: Number(point.time) }
          : null,
      );
    });
    return () => {
      const range = c.timeScale().getVisibleLogicalRange();
      if (range) rangeCache.set(identity, range);
      c.remove();
      chart.current = null;
    };
  }, [bars, identity, theme, indicators, enabled, digits]);
  const current =
    (hover?.identity === identity
      ? bars.find((bar) => bar.time === hover.time)
      : undefined) ?? bars.at(-1);
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
      <fieldset className="chart-toolbar"><legend>Indicatori Python · solo analisi</legend>
        {indicators.map(i => <label key={i.id}><input type="checkbox" checked={enabled.includes(i.id)} onChange={e=>setEnabled(current=>e.target.checked ? [...current,i.id] : current.filter(id=>id!==i.id))}/>{i.label} · {i.method} · {i.unit}</label>)}
        {!indicators.length && <span>Indicatori N/D</span>}
      </fieldset>
      <div className="chart-toolbar">
        <div className="ohlc" aria-live="off">
          <span>
            O <b>{price(current?.open, digits)}</b>
          </span>
          <span>
            H <b>{price(current?.high, digits)}</b>
          </span>
          <span>
            L <b>{price(current?.low, digits)}</b>
          </span>
          <span>
            C <b>{price(current?.close, digits)}</b>
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
        aria-label={`Candlestick e volume. Ultima barra ${instant(current?.time)}. Prezzi ${priceUnit}; volume ${volumeUnit}. Zoom con rotella e trascinamento.`}
      />
      {!bars.length && (
        <p className="empty">
          Nessuna barra disponibile. Nessun grafico sintetico di fallback.
        </p>
      )}
      <div className="chart-foot">
        <span>
          Prezzi {priceUnit} · Volume in {volumeUnit} · Trascina per navigare
        </span>
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
          Grafici TradingView Lightweight Charts™
        </a>
      </div>
    </div>
  );
}
