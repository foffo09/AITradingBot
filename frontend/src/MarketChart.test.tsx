import { act, render, screen } from "@testing-library/react";
import { it, expect, vi } from "vitest";
import MarketChart from "./MarketChart";
const stub = vi.hoisted(() => ({
  move: undefined as
    | ((event: {
        seriesData: Map<unknown, { time: number; close: number }>;
      }) => void)
    | undefined,
  candle: { setData: vi.fn() },
}));
vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  CandlestickSeries: "candles",
  HistogramSeries: "volume",
  createChart: () => ({
    addSeries: () => stub.candle,
    panes: () => [],
    timeScale: () => ({
      fitContent() {},
      getVisibleLogicalRange: () => null,
      setVisibleLogicalRange() {},
    }),
    subscribeCrosshairMove: (callback: typeof stub.move) => {
      stub.move = callback;
    },
    remove() {},
  }),
}));
const bar = {
  time: 1700000000,
  open: 101,
  high: 105,
  low: 99,
  close: 102,
  volume: 500,
};
it("non conserva OHLC del crosshair dopo indisponibilità o cambio contesto", () => {
  const { rerender } = render(
    <MarketChart bars={[bar]} identity="demo/AAPL/1Day" theme="dark" />,
  );
  act(() =>
    stub.move?.({
      seriesData: new Map([
        [stub.candle, { time: bar.time, close: bar.close }],
      ]),
    }),
  );
  rerender(<MarketChart bars={[]} identity="paper/AAPL/1Day" theme="dark" />);
  expect(screen.queryByText("101")).not.toBeInTheDocument();
  expect(screen.queryByText("102")).not.toBeInTheDocument();
  expect(screen.getAllByText("N/D")).toHaveLength(5);
  rerender(
    <MarketChart
      bars={[{ ...bar, open: 201, high: 205, low: 199, close: 202 }]}
      identity="simulation/AAPL/1Day"
      theme="dark"
    />,
  );
  expect(screen.getByText("201")).toBeInTheDocument();
  expect(screen.queryByText("101")).not.toBeInTheDocument();
});
it("rilegge il valore del crosshair dalle barre aggiornate", () => {
  const { rerender } = render(
    <MarketChart bars={[bar]} identity="demo/AAPL/1Day" theme="dark" />,
  );
  act(() =>
    stub.move?.({
      seriesData: new Map([
        [stub.candle, { time: bar.time, close: bar.close }],
      ]),
    }),
  );
  rerender(
    <MarketChart
      bars={[{ ...bar, close: 103 }]}
      identity="demo/AAPL/1Day"
      theme="dark"
    />,
  );
  expect(screen.getByText("103")).toBeInTheDocument();
  expect(screen.queryByText("102")).not.toBeInTheDocument();
});
