export type Context = "demo" | "simulation" | "paper" | "mt5";
export interface Preferences {
  theme: "dark" | "light";
  density: "comfortable" | "compact";
  analysis_width: number;
}
export type RecordData = Record<string, unknown>;
export interface State {
  api_version: "1";
  context: Context;
  connection: { status: string; reason?: string };
  account: RecordData | null;
  positions: RecordData[];
  orders: RecordData[];
  trades: RecordData[];
  automation: RecordData & { state: string; reason?: string };
}
export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
export interface Indicator {
  id: string; label: string; pane: "price" | "rsi"; unit: string; method: string;
  parameters: RecordData; points: {time:number;value:number|null}[];
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
  metadata?: RecordData;
  indicators?: Indicator[];
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
export interface WalkForwardFold {
  train_start: string; train_end: string; test_start: string; test_end: string;
  parameters: Record<string, number>; in_sample_return_pct: number; in_sample_trades: number;
  out_of_sample: RecordData;
}
export interface WalkForward {
  source: string; training_bars: number; test_bars: number; step_bars: number;
  selection_metric: string; sample: { start: string; end: string; bars: number };
  folds: WalkForwardFold[]; excluded: { test_start: string; test_end: string; reason: string }[];
}
export interface ContextStatus { connection: string; ledger: string; automation: string }
export interface SystemStatus {
  service_version: string; python: string; platform: string; started_at: string;
  uptime_seconds: number; order_submission: "disabled"; contexts: Record<string, ContextStatus>;
}
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status = 0,
    readonly outcome: string | null = null,
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
    // Only the caller's own cancellation is rethrown; WebKit reports the 12s timeout as AbortError too.
    if (options.signal?.aborted) throw error;
    if (error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError"))
      throw new ApiError(
        "Il servizio locale non ha risposto entro 12 secondi. Nuovo tentativo al prossimo aggiornamento.",
      );
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
      response.headers.get("X-Request-Outcome"),
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
      ...automation,
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
  const times = new Set(bars.map(b=>b.time));
  const ids = new Set<string>();
  const indicators = records(d.indicators ?? []).map(i => {
    const id = string(i.id);
    if (ids.has(id) || (i.pane !== "price" && i.pane !== "rsi")) invalid();
    ids.add(id);
    let last = -Infinity;
    const points = records(i.points).map(p => {
      const time = numeric(p.time), value = p.value === null ? null : numeric(p.value);
      if (!times.has(time) || time <= last) invalid();
      last = time;
      return {time,value};
    });
    return {id,label:string(i.label),pane:i.pane as "price"|"rsi",unit:string(i.unit),method:string(i.method),parameters:object(i.parameters),points};
  });
  return {
    indicators,
    context: context(d.context),
    symbol: string(d.symbol),
    interval: string(d.interval),
    status: string(d.status),
    reason: typeof d.reason === "string" ? d.reason : undefined,
    source: d.source === null ? null : string(d.source),
    as_of: typeof d.as_of === "string" ? d.as_of : null,
    bars,
    quote: d.quote === null ? null : object(d.quote),
    metadata: d.metadata === undefined ? {} : object(d.metadata),
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
export function parseWalkForward(value: unknown): WalkForward {
  const d = version(value), sample = object(d.sample);
  const window = (w: RecordData) => ({test_start: string(w.test_start), test_end: string(w.test_end)});
  return {
    source: string(d.source), selection_metric: string(d.selection_metric),
    training_bars: numeric(d.training_bars), test_bars: numeric(d.test_bars), step_bars: numeric(d.step_bars),
    sample: {start: string(sample.start), end: string(sample.end), bars: numeric(sample.bars)},
    folds: records(d.folds).map(f => ({
      ...window(f), train_start: string(f.train_start), train_end: string(f.train_end),
      parameters: Object.fromEntries(Object.entries(object(f.parameters)).map(([k, v]) => [k, numeric(v)])),
      in_sample_return_pct: numeric(f.in_sample_return_pct), in_sample_trades: numeric(f.in_sample_trades),
      out_of_sample: object(f.out_of_sample),
    })),
    excluded: records(d.excluded).map(e => ({...window(e), reason: string(e.reason)})),
  };
}
export function parseSystem(value: unknown): SystemStatus {
  const d = version(value);
  if (d.order_submission !== "disabled") invalid();
  return {
    service_version: string(d.service_version), python: string(d.python), platform: string(d.platform),
    started_at: string(d.started_at), uptime_seconds: numeric(d.uptime_seconds), order_submission: "disabled",
    contexts: Object.fromEntries(Object.entries(object(d.contexts)).map(([k, v]) => {
      const c = object(v);
      return [k, {connection: string(c.connection), ledger: string(c.ledger), automation: string(c.automation)}];
    })),
  };
}
function parseWatchlist(value: unknown): string[] {
  const d = version(value);
  if (!Array.isArray(d.symbols) || typeof d.stored !== "boolean") invalid();
  return (d.symbols as unknown[]).map(string);
}
function parsePreferences(value: unknown): {preferences: Preferences; stored: boolean} {
  const d = version(value), p = object(d.preferences);
  if ((p.theme !== "dark" && p.theme !== "light") ||
      (p.density !== "comfortable" && p.density !== "compact") ||
      typeof p.analysis_width !== "number" || !Number.isInteger(p.analysis_width) ||
      p.analysis_width < 50 || p.analysis_width > 75 || typeof d.stored !== "boolean") invalid();
  return {preferences:{theme:p.theme as Preferences["theme"], density:p.density as Preferences["density"], analysis_width:p.analysis_width as number},stored:d.stored as boolean};
}
const query = (c: Context, symbol?: string, interval?: string) =>
  new URLSearchParams({
    context: c,
    ...(symbol ? { symbol } : {}),
    ...(interval ? { interval } : {}),
  }).toString();
export function pendingTrade(c: Context): {symbol: string; side: string; quantity: number} | null {
  try {
    const raw = localStorage.getItem(`aitb-pending-trade-${c}`);
    if (!raw) return null;
    const record = object(JSON.parse(raw));
    const payload = object(JSON.parse(string(record.payload)));
    if (payload.context !== c || typeof payload.symbol !== "string" || !["buy","sell"].includes(String(payload.side)) || typeof payload.quantity !== "number" || !Number.isFinite(payload.quantity) || payload.quantity <= 0) return null;
    return {symbol:payload.symbol, side:String(payload.side),quantity:payload.quantity};
  } catch { return null; }
}
export async function restorePendingTrade(c: Context, signal?: AbortSignal): Promise<void> {
  const d = version(await request(`/pending-trade?${query(c)}`, { signal }));
  if (d.context !== c) invalid();
  if (d.pending === null) return;
  const p = object(d.pending);
  if (string(p.context) !== c || typeof p.quantity !== "number") invalid();
  const payload = JSON.stringify({ context: c, symbol: string(p.symbol), side: string(p.side), quantity: p.quantity });
  try {
    localStorage.setItem(`aitb-pending-trade-${c}`, JSON.stringify({ payload, idempotency_key: string(p.idempotency_key) }));
  } catch {
    /* Without storage the retry cannot reuse the key; the service still blocks a different request. */
  }
}
export const api = {
  preferences: async (signal?: AbortSignal) => {
    const result = parsePreferences(await request("/preferences", {signal}));
    return result.stored ? result.preferences : null;
  },
  savePreferences: async (preferences: Preferences) =>
    parsePreferences(await request("/preferences", {method:"POST",body:JSON.stringify(preferences)})).preferences,
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
  ) => {
    const proposal = parseProposal(await request(`/proposal?${query(c, symbol, interval)}`, { signal }));
    if (proposal.context !== c || proposal.symbol !== symbol || proposal.interval !== interval)
      throw new ApiError("Risposta del contesto, strumento o intervallo non coerente.");
    return proposal;
  },
  account: async (c: Context, initial_cash: number) =>
    parseState(
      await request("/local-account", {
        method: "POST",
        body: JSON.stringify({ context: c, initial_cash }),
      }),
    ),
  trade: async (c: Context, symbol: string, side: string, quantity: number) => {
    const storageKey = `aitb-pending-trade-${c}`;
    const payload = JSON.stringify({ context: c, symbol, side, quantity });
    const saved = localStorage.getItem(storageKey);
    const pending = saved ? object(JSON.parse(saved)) : { payload, idempotency_key: crypto.randomUUID() };
    if (pending.payload !== payload || typeof pending.idempotency_key !== "string")
      throw new ApiError("Esito incerto: ripeti la stessa operazione prima di modificarla; verifica lo storico.");
    const key = pending.idempotency_key;
    const body = JSON.stringify({ context: c, symbol, side, quantity, idempotency_key: key });
    // Remember the key before anything leaves the browser: if a response is lost, the retry reuses it.
    localStorage.setItem(storageKey, JSON.stringify(pending));
    const finished = async (resync: boolean) => {
      localStorage.removeItem(storageKey);
      // The service keeps its record until told the outcome arrived; if this fails it is restored later
      // and the retry returns the already booked duplicate, never a second fill.
      await request(`/pending-trade?${new URLSearchParams({ context: c, idempotency_key: key })}`, { method: "DELETE" }).catch(() => undefined);
      if (resync) await restorePendingTrade(c).catch(() => undefined);
    };
    try {
      // The service keeps the record too: browser storage is per port and lost when the app restarts.
      await request("/pending-trade", { method: "PUT", body });
    } catch (error) {
      // Definitively refused (another uncertain request is pending): show that one instead.
      if (error instanceof ApiError && (error.status === 422 || error.outcome === "rejected")) await finished(true);
      throw error; // otherwise uncertain: keep the key for the retry
    }
    try {
      const result = parseState(await request("/local-trades", { method: "POST", body }));
      if (result.context !== c) throw new ApiError("Risposta del contesto non coerente.");
      await finished(false);
      return result;
    } catch (error) {
      if (error instanceof ApiError && (error.status === 422 || error.outcome === "rejected")) await finished(true);
      throw error;
    }
  },
  automation: async (c: Context, command: "start" | "pause" | "stop" | "cycle", request_id: string) => {
    const state = parseState(await request("/automation", {method:"POST", body:JSON.stringify({context:c, command, request_id})}));
    if (state.context !== c) throw new ApiError("Risposta del contesto non coerente.");
    return state;
  },
  connect: async (c: "paper" | "mt5") =>
    parseState(await request(`/connections/${c}`, { method: "POST" })),
  walkForward: async (c: Context, symbol: string, training_bars?: number, test_bars?: number) =>
    parseWalkForward(await request("/walk-forward", {
      method: "POST",
      body: JSON.stringify({ context: c, symbol, ...(training_bars ? {training_bars} : {}), ...(test_bars ? {test_bars} : {}) }),
    })),
  system: async (signal?: AbortSignal) => parseSystem(await request("/system", { signal })),
  watchlist: async (signal?: AbortSignal) => parseWatchlist(await request("/watchlist", { signal })),
  saveWatchlist: async (symbols: string[]) =>
    parseWatchlist(await request("/watchlist", { method: "POST", body: JSON.stringify({ symbols }) })),
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
