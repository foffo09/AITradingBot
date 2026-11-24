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
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    // The service-side pending record is stored first; only the trade request itself is uncertain here.
    if (url.includes('/pending-trade')) return new Response(JSON.stringify({api_version: '1', context: 'demo', pending: null}));
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
  const pendingOk = () => new Response(JSON.stringify({api_version: '1', context: 'demo', pending: null}));
  const trades = (response: () => Response) => vi.fn(async (url: string) => url.includes('/pending-trade') ? pendingOk() : response());
  vi.stubGlobal('fetch', trades(() => new Response('{}', {status:409, headers:{'X-Request-Outcome':'rejected'}})));
  await expect(api.trade('demo','AAPL','buy',10000)).rejects.toThrow();
  expect(localStorage.getItem('aitb-pending-trade-demo')).toBeNull();
  vi.stubGlobal('fetch', trades(() => new Response('{}', {status:409})));
  await expect(api.trade('demo','AAPL','buy',1)).rejects.toThrow();
  expect(localStorage.getItem('aitb-pending-trade-demo')).not.toBeNull();
  localStorage.clear();
});


it('non invia l\'operazione se il servizio non registra la richiesta in sospeso', async () => {
  const {api} = await import('./api');
  localStorage.clear();
  const urls: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    urls.push(url);
    return new Response(JSON.stringify({detail: 'Another uncertain virtual trade is pending; retry it first.'}), {status: 409, headers: {'X-Request-Outcome': 'rejected'}});
  }));
  await expect(api.trade('demo', 'AAPL', 'buy', 1)).rejects.toThrow('retry it first');
  expect(urls[0]).toBe('/api/v1/pending-trade');
  expect(urls.some((url) => url.includes('/local-trades'))).toBe(false); // nothing was sent
  expect(localStorage.getItem('aitb-pending-trade-demo')).toBeNull();
});

it('ripristina dal servizio la richiesta incerta dopo un riavvio su nuova porta', async () => {
  const {api, restorePendingTrade, pendingTrade} = await import('./api');
  localStorage.clear();
  const record = {context: 'demo', symbol: 'AAPL', side: 'buy', quantity: 1, idempotency_key: '0b6c2d5e-6a52-4c58-9a4b-8d2b1d6f1e11'};
  const sent: Record<string, unknown>[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes('/pending-trade') && !init?.method) return new Response(JSON.stringify({api_version: '1', context: 'demo', pending: record}));
    if (url.includes('/local-trades')) sent.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify({api_version: '1', context: 'demo', connection: {status: 'local'}, account: null, positions: [], orders: [], trades: [], automation: {state: 'STOPPED'}}));
  }));
  await restorePendingTrade('demo');
  expect(pendingTrade('demo')).toEqual({symbol: 'AAPL', side: 'buy', quantity: 1});
  await expect(api.trade('demo', 'AAPL', 'buy', 2)).rejects.toThrow('incerto');
  await api.trade('demo', 'AAPL', 'buy', 1);
  expect(sent).toEqual([record]);
  expect(localStorage.getItem('aitb-pending-trade-demo')).toBeNull();
});

it('PUT registrato ma risposta persa: il nuovo tentativo riusa la stessa chiave (review Codex #2)', async () => {
  const {api} = await import('./api');
  localStorage.clear();
  const puts: Record<string, unknown>[] = [], trades: Record<string, unknown>[] = [];
  let lose = true;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/v1/pending-trade' && init?.method === 'PUT') {
      puts.push(JSON.parse(String(init.body)));
      if (lose) { lose = false; throw new TypeError('response lost'); } // stored server-side, reply lost
      return new Response(JSON.stringify({api_version: '1', context: 'demo', pending: puts.at(-1)}));
    }
    if (url.includes('/local-trades')) {
      trades.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({api_version: '1', context: 'demo', connection: {status: 'local'}, account: null, positions: [], orders: [], trades: [], automation: {state: 'STOPPED'}}));
    }
    return new Response(JSON.stringify({api_version: '1', context: 'demo', pending: null}));
  }));
  await expect(api.trade('demo', 'AAPL', 'buy', 1)).rejects.toThrow();
  expect(trades).toHaveLength(0);
  await api.trade('demo', 'AAPL', 'buy', 1);
  expect(puts[1].idempotency_key).toBe(puts[0].idempotency_key);
  expect(trades[0].idempotency_key).toBe(puts[0].idempotency_key);
});

it('conferma al servizio solo dopo aver ricevuto l\'esito (review Codex #1)', async () => {
  const {api} = await import('./api');
  localStorage.clear();
  const calls: string[] = [];
  let tradeFails = true;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url.split('?')[0]}`);
    if (url.includes('/local-trades')) {
      if (tradeFails) { tradeFails = false; throw new TypeError('booked, response lost'); }
      return new Response(JSON.stringify({api_version: '1', context: 'demo', connection: {status: 'local'}, account: null, positions: [], orders: [], trades: [], automation: {state: 'STOPPED'}}));
    }
    return new Response(JSON.stringify({api_version: '1', context: 'demo', pending: null}));
  }));
  await expect(api.trade('demo', 'AAPL', 'buy', 1)).rejects.toThrow();
  expect(calls.some((call) => call.startsWith('DELETE'))).toBe(false); // outcome unknown: keep the record
  expect(localStorage.getItem('aitb-pending-trade-demo')).not.toBeNull();
  await api.trade('demo', 'AAPL', 'buy', 1);
  expect(calls.at(-1)).toBe('DELETE /api/v1/pending-trade'); // confirmed only after the response arrived
  expect(localStorage.getItem('aitb-pending-trade-demo')).toBeNull();
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
describe("timeout e annullamento (AUDIT-L1)", () => {
  const abort = (name: string) => vi.fn().mockRejectedValue(new DOMException("Fetch is aborted", name));
  it("WebKit: timeout interno come AbortError diventa messaggio italiano", async () => {
    vi.stubGlobal("fetch", abort("AbortError"));
    await expect(request("/state")).rejects.toThrow("non ha risposto entro 12 secondi");
  });
  it("TimeoutError standard diventa lo stesso messaggio", async () => {
    vi.stubGlobal("fetch", abort("TimeoutError"));
    await expect(request("/state")).rejects.toThrow("non ha risposto entro 12 secondi");
  });
  it("annullamento del chiamante resta AbortError originale", async () => {
    vi.stubGlobal("fetch", abort("AbortError"));
    const controller = new AbortController();
    controller.abort();
    await expect(request("/state", { signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
  });
});
