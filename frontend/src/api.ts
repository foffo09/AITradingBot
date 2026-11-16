export type Context = "demo" | "simulation" | "paper" | "mt5";
export type RecordData = Record<string, unknown>;
export interface State {
  api_version: "1";
  context: Context;
  connection: { status: string; reason?: string };
  account: RecordData | null;
  positions: RecordData[];
  orders: RecordData[];
  trades: RecordData[];
  automation: { state: string; reason?: string };
}
export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
export interface Market {
  context: Context;
  symbol: string;
  interval: string;
  status: string;
  reason?: string;
  source: string | null;
  as_of: string | null;
  bars: Bar[];
  quote: RecordData | null;
}
export interface Proposal extends RecordData {
  direction: "BUY" | "SELL" | "WAIT" | "NO_TRADE";
  validation_state: string;
  reason: string;
}
export interface Instrument {
  symbol: string;
  name: string;
}
export interface Backtest {
  source: string;
  metrics: RecordData;
  trades: RecordData[];
  equity: { time: number; value: number }[];
}
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status = 0,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
const invalid = (): never => {
  throw new ApiError(
    "Risposta del servizio non valida o versione non supportata.",
  );
};
export function object(value: unknown): RecordData {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as RecordData)
    : invalid();
}
function version(value: unknown) {
  const data = object(value);
  if (data.api_version !== "1") invalid();
  return data;
}
function string(value: unknown): string {
  return typeof value === "string" ? value : invalid();
}
function context(value: unknown): Context {
  return ["demo", "simulation", "paper", "mt5"].includes(string(value))
    ? (value as Context)
    : invalid();
}
function records(value: unknown): RecordData[] {
  return Array.isArray(value) ? value.map(object) : invalid();
}
export function finite(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
function numeric(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : invalid();
}
export async function request(
  path: string,
  options: RequestInit = {},
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(12000)])
        : AbortSignal.timeout(12000),
      credentials: "include",
      headers: {
        "X-Local-Request": "1",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      "Servizio locale non raggiungibile. Verifica che il backend sia avviato.",
    );
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new ApiError("Risposta del servizio non leggibile.", response.status);
  }
  if (!response.ok) {
    const detail = object(data).detail;
    throw new ApiError(
      typeof detail === "string"
        ? detail
        : `Richiesta non riuscita (HTTP ${response.status}).`,
      response.status,
    );
  }
  return data;
}
export function parseState(value: unknown): State {
  const d = version(value),
    connection = object(d.connection),
    automation = object(d.automation);
  return {
    api_version: "1",
    context: context(d.context),
    connection: {
      status: string(connection.status),
      reason:
        typeof connection.reason === "string" ? connection.reason : undefined,
    },
    account: d.account === null ? null : object(d.account),
    positions: records(d.positions),
    orders: records(d.orders),
    trades: records(d.trades),
    automation: {
      state: string(automation.state),
      reason:
        typeof automation.reason === "string" ? automation.reason : undefined,
    },
  };
}
export function parseMarket(value: unknown): Market {
  const d = version(value);
  if (!Array.isArray(d.bars)) invalid();
  let previous = -Infinity;
  const bars = (d.bars as unknown[]).map((value) => {
    const b = object(value);
    const bar = {
      time: numeric(b.time),
      open: numeric(b.open),
      high: numeric(b.high),
      low: numeric(b.low),
      close: numeric(b.close),
      volume: numeric(b.volume),
    };
    if (
      bar.time <= previous ||
      !Number.isInteger(bar.time) ||
      bar.time <= 0 ||
      bar.volume < 0 ||
      bar.low <= 0 ||
      bar.low > Math.min(bar.open, bar.close) ||
      bar.high < Math.max(bar.open, bar.close) ||
      bar.high < bar.low
    )
      invalid();
    previous = bar.time;
    return bar;
  });
  return {
    context: context(d.context),
    symbol: string(d.symbol),
    interval: string(d.interval),
    status: string(d.status),
    reason: typeof d.reason === "string" ? d.reason : undefined,
    source: d.source === null ? null : string(d.source),
    as_of: typeof d.as_of === "string" ? d.as_of : null,
    bars,
    quote: d.quote === null ? null : object(d.quote),
  };
}
export function parseProposal(value: unknown): Proposal {
  const d = object(value);
  if (d.api_version !== undefined && d.api_version !== "1") invalid();
  const direction = string(d.direction);
  if (!["BUY", "SELL", "WAIT", "NO_TRADE"].includes(direction)) invalid();
  return {
    ...d,
    direction: direction as Proposal["direction"],
    validation_state: string(d.validation_state),
    reason: string(d.reason),
  };
}
export function parseInstruments(value: unknown): Instrument[] {
  const d = version(value);
  return records(d.instruments).map((i) => ({
    symbol: string(i.symbol),
    name: string(i.name),
  }));
}
export function parseBacktest(value: unknown): Backtest {
  const d = version(value);
  return {
    source: string(d.source),
    metrics: object(d.metrics),
    trades: records(d.trades),
    equity: records(d.equity).map((p) => ({
      time: numeric(p.time),
      value: numeric(p.value),
    })),
  };
}
const query = (c: Context, symbol?: string, interval?: string) =>
  new URLSearchParams({
    context: c,
    ...(symbol ? { symbol } : {}),
    ...(interval ? { interval } : {}),
  }).toString();
export const api = {
  session: async (signal?: AbortSignal) => {
    version(await request("/session", { signal }));
  },
  state: async (c: Context, signal?: AbortSignal) => {
    const state = parseState(await request(`/state?${query(c)}`, { signal }));
    if (state.context !== c)
      throw new ApiError("Risposta del contesto non coerente.");
    return state;
  },
  instruments: async (signal?: AbortSignal) =>
    parseInstruments(await request("/instruments", { signal })),
  market: async (
    c: Context,
    symbol: string,
    interval: string,
    signal?: AbortSignal,
  ) => {
    const market = parseMarket(
      await request(`/market?${query(c, symbol, interval)}`, { signal }),
    );
    if (
      market.context !== c ||
      market.symbol !== symbol ||
      market.interval !== interval
    )
      throw new ApiError(
        "Risposta del contesto, strumento o intervallo non coerente.",
      );
    return market;
  },
  proposal: async (
    c: Context,
    symbol: string,
    interval: string,
    signal?: AbortSignal,
  ) =>
    parseProposal(
      await request(`/proposal?${query(c, symbol, interval)}`, { signal }),
    ),
  account: async (c: Context, initial_cash: number) =>
    parseState(
      await request("/local-account", {
        method: "POST",
        body: JSON.stringify({ context: c, initial_cash }),
      }),
    ),
  trade: async (c: Context, symbol: string, side: string, quantity: number) =>
    parseState(
      await request("/local-trades", {
        method: "POST",
        body: JSON.stringify({ context: c, symbol, side, quantity }),
      }),
    ),
  connect: async (c: "paper" | "mt5") =>
    parseState(await request(`/connections/${c}`, { method: "POST" })),
  backtest: async (
    c: Context,
    symbol: string,
    short_window: number,
    long_window: number,
  ) =>
    parseBacktest(
      await request("/backtest", {
        method: "POST",
        body: JSON.stringify({ context: c, symbol, short_window, long_window }),
      }),
    ),
};
