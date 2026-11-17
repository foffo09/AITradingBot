import { describe, it, expect, vi } from "vitest";
import { api, request, parseMarket, parseState, parseProposal } from "./api";

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

it.each([
  { context: 'paper', symbol: 'AAPL', interval: '1Day' },
  { context: 'demo', symbol: 'MSFT', interval: '1Day' },
  { context: 'demo', symbol: 'AAPL', interval: '1Hour' },
])('rifiuta proposta con identità discordante %o', async (identity) => {
  const { api } = await import('./api');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    api_version: '1', ...identity, direction: 'BUY', validation_state: 'PAPER_PROPOSAL', reason: 'fixture',
  }))));
  await expect(api.proposal('demo', 'AAPL', '1Day')).rejects.toThrow('coerente');
});

it('conserva la stessa chiave dopo esito incerto e blocca payload diversi fino a conferma', async () => {
  const { api } = await import('./api');
  localStorage.clear();
  const bodies: Record<string, unknown>[] = [];
  let fail = true;
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
    bodies.push(JSON.parse(init.body as string));
    if (fail) throw new TypeError('network');
    return new Response(JSON.stringify({ api_version: '1', context: 'demo', connection: {status:'local'}, account: null, positions: [], orders: [], trades: [], automation: {state:'STOPPED'} }));
  }));
  await expect(api.trade('demo', 'AAPL', 'buy', 1)).rejects.toThrow();
  expect(bodies[0].idempotency_key).toMatch(/^[0-9a-f-]{36}$/);
  await expect(api.trade('demo', 'AAPL', 'buy', 2)).rejects.toThrow('incerto');
  expect(bodies).toHaveLength(1);
  await expect(api.trade('demo', 'AAPL', 'buy', 1)).rejects.toThrow();
  expect(bodies[1]).toEqual(bodies[0]);
  fail = false;
  await api.trade('demo', 'AAPL', 'buy', 1);
  await api.trade('demo', 'AAPL', 'buy', 2);
  expect(bodies[3].idempotency_key).not.toBe(bodies[0].idempotency_key);
  localStorage.clear();
});

it('conserva serie Python e rifiuta indicatori con punti non finiti o fuori dalle barre', () => {
  const base = {api_version:'1', context:'demo',symbol:'AAPL', interval:'1Day',status:'ready',source:'synthetic-demo',quote:null,bars:[{time:1700000000,open:10,high:12,low:9,close:11,volume:1}]};
  const indicator = {id:'sma10',label:'SMA 10',pane:'price',unit:'USD',method:'SMA',parameters:{window:10},points:[{time:1700000000,value:null}]};
  expect(parseMarket({...base,indicators:[indicator]}).indicators).toEqual([indicator]);
  expect(()=>parseMarket({...base,indicators:[{...indicator,points:[{time:1700000000,value:Infinity}]}]})).toThrow();
  expect(()=>parseMarket({...base,indicators:[{...indicator,points:[{time:1700000001,value:10}]}]})).toThrow();
});

it('libera una richiesta dopo rifiuto definitivo, conserva 409 ambiguo', async () => {
  const {api} = await import('./api');
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', {status:409, headers:{'X-Request-Outcome':'rejected'}})));
  await expect(api.trade('demo','AAPL','buy',10000)).rejects.toThrow();
  expect(localStorage.getItem('aitb-pending-trade-demo')).toBeNull();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', {status:409})));
  await expect(api.trade('demo','AAPL','buy',1)).rejects.toThrow();
  expect(localStorage.getItem('aitb-pending-trade-demo')).not.toBeNull();
  localStorage.clear();
});


describe("preferenze dal servizio", () => {
  it.each([
    {theme:"evil", density:"compact", analysis_width:60},
    {theme:"dark", density:"compact", analysis_width:Infinity},
    {theme:"dark", density:"compact", analysis_width:49},
    {theme:"dark", density:"compact", analysis_width:60.5},
    {theme:"dark", density:"evil", analysis_width:60},
  ])("rifiuta preferenze non valide: %j", async preferences => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({api_version:"1",stored:true,preferences}))));
    await expect(api.preferences()).rejects.toThrow();
  });
});
