import { describe, it, expect, vi } from "vitest";
import { request, parseMarket, parseState, parseProposal } from "./api";

describe("confine HTTP locale", () => {
  it("include cookie e header anche nel bootstrap senza leggere token", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ api_version: "1", status: "ready" })),
      );
    vi.stubGlobal("fetch", fetcher);
    await request("/session");
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/session",
      expect.objectContaining({
        credentials: "include",
        headers: expect.objectContaining({ "X-Local-Request": "1" }),
      }),
    );
  });
  it("non trasforma un errore backend in successo", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ detail: "Conto non configurato" }), {
            status: 503,
          }),
        ),
    );
    await expect(request("/state")).rejects.toThrow("Conto non configurato");
  });
  it("rifiuta HTML e versioni sconosciute", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>")));
    await expect(request("/state")).rejects.toThrow("Risposta");
    expect(() => parseState({ api_version: "2" })).toThrow();
  });
});
describe("dati non inventati", () => {
  it("conserva account assente e liste reali vuote", () => {
    const state = parseState({
      api_version: "1",
      context: "paper",
      connection: { status: "error", reason: "Offline" },
      account: null,
      positions: [],
      orders: [],
      trades: [],
      automation: { state: "stopped", reason: "Sola lettura" },
    });
    expect(state.account).toBeNull();
    expect(state.connection.reason).toBe("Offline");
  });
  it("rifiuta barre duplicate, prezzi non finiti e OHLC incoerenti", () => {
    const bar = {
      time: 1700000000,
      open: 10,
      high: 12,
      low: 9,
      close: 11,
      volume: 100,
    };
    const base = {
      api_version: "1",
      context: "demo",
      symbol: "AAPL",
      interval: "1Day",
      status: "ready",
      source: "synthetic-demo",
      as_of: null,
      quote: null,
    };
    expect(parseMarket({ ...base, bars: [bar] }).bars).toHaveLength(1);
    for (const bars of [
      [bar, bar],
      [{ ...bar, close: Infinity }],
      [{ ...bar, low: 12 }],
    ])
      expect(() => parseMarket({ ...base, bars })).toThrow();
  });
  it("mantiene NO_TRADE e livelli mancanti senza fallback", () => {
    expect(
      parseProposal({
        api_version: "1",
        direction: "WAIT",
        validation_state: "NO_TRADE",
        reason: "Dati mancanti",
        entry: null,
        stop_loss: null,
        take_profit: null,
      }).validation_state,
    ).toBe("NO_TRADE");
    expect(() => parseProposal({ direction: "EXECUTE" })).toThrow();
  });
});

describe("isolamento delle risposte", () => {
  it("rifiuta snapshot di un altro contesto anche se valido", async () => {
    const { api } = await import("./api");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              api_version: "1",
              context: "paper",
              connection: { status: "ready" },
              account: null,
              positions: [],
              orders: [],
              trades: [],
              automation: { state: "stopped" },
            }),
          ),
        ),
    );
    await expect(api.state("demo")).rejects.toThrow("contesto");
  });
  it("rifiuta mercato di un simbolo o intervallo diverso", async () => {
    const { api } = await import("./api");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              api_version: "1",
              context: "demo",
              symbol: "MSFT",
              interval: "1Day",
              status: "ready",
              source: "synthetic-demo",
              bars: [],
              quote: null,
            }),
          ),
        ),
    );
    await expect(api.market("demo", "AAPL", "1Day")).rejects.toThrow(
      "strumento",
    );
  });
});

it("conserva i metadati originali senza inventare calendario o provenienza", () => {
  const payload = {
    api_version: "1", context: "paper", symbol: "AAPL", interval: "1Day",
    status: "ready", source: "Alpaca", as_of: null, bars: [], quote: null,
    metadata: { quality: "real", bar_time_contract: "alpaca-start-v1", bar_calendar: "NYSE" },
  };
  expect(parseMarket(payload).metadata).toEqual(payload.metadata);
  expect(parseMarket({ ...payload, metadata: undefined }).metadata).toEqual({});
  expect(() => parseMarket({ ...payload, metadata: [] })).toThrow();
});
