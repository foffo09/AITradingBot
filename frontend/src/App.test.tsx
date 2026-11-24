import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import App from "./App";
vi.mock("./MarketChart", () => ({ default: () => <div>Grafico test</div> }));
const state = {
  api_version: "1",
  context: "paper",
  connection: { status: "error", reason: "Paper non configurato" },
  account: null,
  positions: [],
  orders: [],
  trades: [],
  automation: { state: "stopped", reason: "Sola lettura" },
};
const fetcher = vi.fn();
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", fetcher);
  fetcher.mockImplementation(
    async (url: string) =>
      new Response(
        JSON.stringify(
          url.includes("/instruments")
            ? {
                api_version: "1",
                instruments: [{ symbol: "AAPL", name: "Apple" }],
              }
            : url.includes("/state")
              ? {
                  ...state,
                  context: new URL(url, "http://localhost").searchParams.get(
                    "context",
                  ),
                }
              : url.includes("/market")
                ? {
                    api_version: "1",
                    context: "demo",
                    symbol: "AAPL",
                    interval: "1Day",
                    status: "unavailable",
                    reason: "Feed non disponibile",
                    source: null,
                    as_of: null,
                    bars: [],
                    quote: null,
                  }
                : url.includes("/proposal")
                  ? {
                      api_version: "1",
                      context: "demo", symbol: "AAPL", interval: "1Day",
                      direction: "WAIT",
                      validation_state: "NO_TRADE",
                      reason: "Rischio non verificato",
                      entry: null,
                    }
                  : { api_version: "1", status: "ready" },
        ),
      ),
  );
  const fallback = fetcher.getMockImplementation()!;
  let preferences = {theme:'dark', density:'comfortable', analysis_width:68};
  let stored = false;
  fetcher.mockImplementation(async (url:string, init?:RequestInit) => {
    if (url.includes('/preferences')) {
      if (init?.method === 'POST') {preferences=JSON.parse(String(init.body)); stored=true;}
      return new Response(JSON.stringify({api_version:'1',preferences,stored}));
    }
    return fallback(url,init);
  });
});
describe("terminale senza dati inventati", () => {
  it("mostra provenienza sintetica, N/D e automazione ferma", async () => {
    render(<App />);
    expect(
      await screen.findByText("Paper non configurato"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("N/D").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Automazione ferma/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Dati sintetici dichiarati/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Avvia automazione/ }),
    ).not.toBeInTheDocument();
  });
  it("stato non disponibile non propone di creare un conto (AUDIT-L4)", async () => {
    const base = fetcher.getMockImplementation()!;
    fetcher.mockImplementation(async (url: string, init?: RequestInit) =>
      url.includes("/state")
        ? new Response(JSON.stringify({ detail: "Servizio occupato" }), { status: 503 })
        : base(url, init));
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Portafoglio" }));
    await waitFor(() =>
      expect(screen.getByText(/Stato del conto non disponibile/)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "Crea conto virtuale" })).not.toBeInTheDocument();
  });
  it("Paper non espone comandi di ledger locale e conserva errori", async () => {
    render(<App />);
    await userEvent.selectOptions(screen.getByLabelText("Contesto"), "paper");
    await userEvent.click(screen.getByRole("button", { name: "Portafoglio" }));
    await waitFor(() =>
      expect(screen.getByText("Paper non configurato")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: "Crea conto virtuale" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Le operazioni Paper e MT5 sono in sola lettura/),
    ).toBeInTheDocument();
  });
  it("invia backtest esplicito al motore senza esporre trading", async () => {
    fetcher.mockImplementation(
      async (url: string, init: RequestInit) =>
        new Response(
          JSON.stringify(
            init?.method === "POST"
              ? {
                  api_version: "1",
                  context: "demo",
                  symbol: "AAPL",
                  source: "synthetic-demo",
                  metrics: { total_return: 0.02 },
                  equity: [],
                  trades: [],
                }
              : url.includes("/instruments")
                ? { api_version: "1", instruments: [] }
                : url.includes("/state")
                  ? {
                      ...state,
                      context: new URL(
                        url,
                        "http://localhost",
                      ).searchParams.get("context"),
                    }
                  : url.includes("/market")
                    ? {
                        api_version: "1",
                        context: "demo",
                        symbol: "AAPL",
                        interval: "1Day",
                        status: "unavailable",
                        source: null,
                        bars: [],
                        quote: null,
                      }
                    : url.includes("/proposal")
                      ? {
                          context: "demo", symbol: "AAPL", interval: "1Day",
                      direction: "WAIT",
                          validation_state: "NO_TRADE",
                          reason: "Dati mancanti",
                        }
                      : { api_version: "1", status: "ready" },
          ),
        ),
    );
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Backtesting" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Esegui backtest" }),
    );
    await waitFor(() =>
      expect(fetcher).toHaveBeenCalledWith(
        "/api/v1/backtest",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            context: "demo",
            symbol: "AAPL",
            short_window: 10,
            long_window: 30,
          }),
        }),
      ),
    );
    expect(await screen.findByText("Risultato del motore")).toBeInTheDocument();
  });
});

it("invalida equity e proposta dopo un errore di refresh, senza valori precedenti", async () => {
  let failed = false;
  fetcher.mockImplementation(async (url: string) => {
    if (url.includes("/state"))
      return failed
        ? new Response(JSON.stringify({ detail: "Snapshot scaduto" }), {
            status: 503,
          })
        : new Response(
            JSON.stringify({
              ...state,
              context: "demo",
              account: { equity: 12345 },
            }),
          );
    if (url.includes("/instruments"))
      return new Response(
        JSON.stringify({ api_version: "1", instruments: [] }),
      );
    if (url.includes("/market"))
      return new Response(
        JSON.stringify({
          api_version: "1",
          context: "demo",
          symbol: "AAPL",
          interval: "1Day",
          status: "ready",
          source: "synthetic-demo",
          bars: [],
          quote: null,
        }),
      );
    if (url.includes("/proposal"))
      return failed
        ? new Response(JSON.stringify({ detail: "Proposta indisponibile" }), {
            status: 503,
          })
        : new Response(
            JSON.stringify({
              context: "demo", symbol: "AAPL", interval: "1Day", expires_at: "2099-01-01T00:00:00Z",
              direction: "BUY",
              validation_state: "PAPER_PROPOSAL",
              reason: "Fixture valida",
              entry: 120,
            }),
          );
    return new Response(JSON.stringify({ api_version: "1", status: "ready" }));
  });
  render(<App />);
  expect(await screen.findByText("12.345 USD")).toBeInTheDocument();
  expect(screen.getByText("BUY")).toBeInTheDocument();
  failed = true;
  await userEvent.click(screen.getByRole("button", { name: /Aggiorna dati/ }));
  expect(await screen.findByText("Snapshot scaduto")).toBeInTheDocument();
  expect(screen.queryByText("12.345 USD")).not.toBeInTheDocument();
  expect(screen.queryByText("BUY")).not.toBeInTheDocument();
});

it("rimuove snapshot quando il bootstrap di sessione fallisce nel polling", async () => {
  let failed = false;
  fetcher.mockImplementation(async (url: string) => {
    if (url.includes("/session") && failed)
      return new Response(JSON.stringify({ detail: "Sessione scaduta" }), {
        status: 401,
      });
    if (url.includes("/state"))
      return new Response(
        JSON.stringify({
          ...state,
          context: "demo",
          account: { equity: 12345 },
        }),
      );
    if (url.includes("/instruments"))
      return new Response(
        JSON.stringify({ api_version: "1", instruments: [] }),
      );
    if (url.includes("/market"))
      return new Response(
        JSON.stringify({
          api_version: "1",
          context: "demo",
          symbol: "AAPL",
          interval: "1Day",
          status: "ready",
          source: "synthetic-demo",
          bars: [],
          quote: null,
        }),
      );
    if (url.includes("/proposal"))
      return new Response(
        JSON.stringify({
          context: "demo", symbol: "AAPL", interval: "1Day",
                      direction: "WAIT",
          validation_state: "NO_TRADE",
          reason: "Fixture",
        }),
      );
    return new Response(JSON.stringify({ api_version: "1", status: "ready" }));
  });
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  try {
    render(<App />);
    expect(await screen.findByText("12.345 USD")).toBeInTheDocument();
    failed = true;
    const { act } = await import("@testing-library/react");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(await screen.findByText("Sessione scaduta")).toBeInTheDocument();
    expect(screen.queryByText("12.345 USD")).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

it("mostra direzione e commissione ingresso del motore senza campi inventati", async () => {
  fetcher.mockImplementation(
    async (url: string, init: RequestInit) =>
      new Response(
        JSON.stringify(
          init?.method === "POST"
            ? {
                api_version: "1",
                context: "demo",
                symbol: "AAPL",
                source: "synthetic-demo",
                metrics: {},
                equity: [],
                trades: [
                  {
                    symbol: "AAPL",
                    direction: "long",
                    quantity: 1,
                    entry_fee: 1.25,
                  },
                ],
              }
            : url.includes("/instruments")
              ? { api_version: "1", instruments: [] }
              : url.includes("/state")
                ? { ...state, context: "demo" }
                : url.includes("/market")
                  ? {
                      api_version: "1",
                      context: "demo",
                      symbol: "AAPL",
                      interval: "1Day",
                      status: "ready",
                      source: "synthetic-demo",
                      bars: [],
                      quote: null,
                    }
                  : url.includes("/proposal")
                    ? {
                        context: "demo", symbol: "AAPL", interval: "1Day",
                      direction: "WAIT",
                        validation_state: "NO_TRADE",
                        reason: "Fixture",
                      }
                    : { api_version: "1", status: "ready" },
        ),
      ),
  );
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Backtesting" }));
  expect(screen.queryByLabelText("Intervallo")).not.toBeInTheDocument();
  expect(
    screen.getByText(/Intervallo del backtest: 1 giorno/),
  ).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Esegui backtest" }),
  );
  expect(await screen.findByText("long")).toBeInTheDocument();
  expect(screen.getByText("1,25")).toBeInTheDocument();
});

it("conserva valuta e unità MT5 e mostra i campi terminale disponibili", async () => {
  fetcher.mockImplementation(async (url: string) => {
    const c =
      new URL(url, "http://localhost").searchParams.get("context") ?? "demo";
    if (url.includes("/backtest"))
      return new Response(
        JSON.stringify({
          api_version: "1",
          context: "mt5",
          symbol: "AAPL",
          source: "Terminal",
          metrics: {},
          equity: [
            { time: 1700000000, value: 100 },
            { time: 1700086400, value: 101 },
          ],
          trades: [],
        }),
      );
    return new Response(
      JSON.stringify(
        url.includes("/state")
          ? {
              ...state,
              context: c,
              account: { cash: 100, equity: 101, currency: "EUR" },
              positions: [
                {
                  symbol: "AAPL",
                  volume: 2,
                  price_open: 90,
                  price_current: 95,
                  profit: 10,
                },
              ],
              orders: [],
            }
          : url.includes("/instruments")
            ? { api_version: "1", instruments: [] }
            : url.includes("/market")
              ? {
                  api_version: "1",
                  context: c,
                  symbol: "AAPL",
                  interval: "1Day",
                  status: "ready",
                  source: "MetaTrader 5 terminal",
                  bars: [],
                  quote: null,
                }
              : url.includes("/proposal")
                ? {
                    context: "demo", symbol: "AAPL", interval: "1Day",
                      direction: "WAIT",
                    validation_state: "NO_TRADE",
                    reason: "Fixture",
                  }
                : { api_version: "1", status: "ready" },
      ),
    );
  });
  render(<App />);
  await userEvent.selectOptions(screen.getByLabelText("Contesto"), "mt5");
  await userEvent.click(screen.getByRole("button", { name: "Portafoglio" }));
  expect(await screen.findByText("101 EUR")).toBeInTheDocument();
  expect(screen.getByText("100 EUR")).toBeInTheDocument();
  expect(screen.getByText("Volume · lotti")).toBeInTheDocument();
  expect(screen.getByText("2")).toBeInTheDocument();
  expect(screen.getByText("90")).toBeInTheDocument();
  expect(screen.getByText("95")).toBeInTheDocument();
  expect(screen.getByText("10")).toBeInTheDocument();
  expect(screen.getByText("P/L · EUR")).toBeInTheDocument();
  expect(screen.getByText("Prezzo · valuta strumento N/D")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Backtesting" }));
  await userEvent.click(
    screen.getByRole("button", { name: "Esegui backtest" }),
  );
  expect(
    await screen.findByRole("img", { name: /Equity del backtest/ }),
  ).toHaveAccessibleName(/valuta strumento N\/D/);
});

it.each([undefined, 'invalid', '2020-01-01T00:00:00Z'])('blocca BUY senza scadenza valida futura %s', async (expires_at) => {
  const original = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (url: string, init: RequestInit) => url.includes('/proposal')
    ? new Response(JSON.stringify({ api_version: '1', context: 'demo', symbol: 'AAPL', interval: '1Day', direction: 'BUY', validation_state: 'PAPER_PROPOSAL', reason: 'fixture', expires_at, entry: 120 }))
    : original(url, init));
  render(<App />);
  expect(await screen.findByText('NO_TRADE')).toBeInTheDocument();
  expect(screen.queryByText('BUY')).not.toBeInTheDocument();
  expect(screen.queryByText('120')).not.toBeInTheDocument();
});

it('non sovrappone cicli quando il bootstrap è ancora in corso', async () => {
  const original = fetcher.getMockImplementation()!;
  let sessions = 0;
  fetcher.mockImplementation(async (url: string, init: RequestInit) => {
    if (url.includes('/session')) { sessions++; return new Promise<Response>(() => {}); }
    return original(url, init);
  });
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
  try {
    render(<App />);
    const { act } = await import('@testing-library/react');
    await act(async () => { await vi.advanceTimersByTimeAsync(45000); });
    expect(sessions).toBe(1);
  } finally { vi.useRealTimers(); }
});

it('mostra metriche contabili già disponibili e dichiara il backtest senza OOS', async () => {
  const original = fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (url: string, init: RequestInit) => url.includes('/state')
    ? new Response(JSON.stringify({ ...state, context: 'demo', account: {currency:'USD', total_pnl: 321, market_value: 456, fees: 1.2, slippage: 2.3, spread: 3.4, daily_realized_pnl: 12, pnl_day:'2026-11-16', pnl_timezone:'UTC'} }))
    : original(url, init));
  render(<App />);
  expect(await screen.findByText('321 USD')).toBeInTheDocument();
  expect(screen.getByText('456 USD')).toBeInTheDocument();
  expect(screen.getByText('12 USD')).toBeInTheDocument();
  expect(screen.getByText('1,2 USD')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', {name:'Backtesting'}));
  expect(screen.getByText(/OOS non eseguito/)).toBeInTheDocument();
});

it('mostra lo stato dry-run del backend e invia un ciclo esplicito con richiesta identificata', async () => {
  const original = fetcher.getMockImplementation()!;
  let cycle = false;
  fetcher.mockImplementation(async (url: string, init: RequestInit) => {
    if (url.includes('/automation')) {
      const body = JSON.parse(init.body as string);
      expect(body.command).toBe('cycle'); expect(body.context).toBe('demo');
      expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
      cycle = true;
    }
    if (url.includes('/state') || url.includes('/automation')) return new Response(JSON.stringify({...state, context:'demo', automation:{state:'RUNNING', mode:'dry-run', execution_enabled:false, reason:'Solo analisi offline', proposals:cycle ? 2 : 1, intents:0, reconciliation:'none'}}));
    return original(url, init);
  });
  render(<App />);
  await userEvent.click(screen.getByRole('button', {name:'Automazione'}));
  expect(await screen.findByText('RUNNING')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', {name:'Esegui ciclo dry-run'}));
  expect(await screen.findByText('2')).toBeInTheDocument();
  expect(cycle).toBe(true);
  expect(screen.queryByText('Automazione ferma')).not.toBeInTheDocument();
});

it('riprende una registrazione incerta dopo rimontaggio conservando quantità e chiave', async () => {
  localStorage.clear();
  localStorage.setItem('aitb-pending-trade-demo', JSON.stringify({payload:JSON.stringify({context:'demo',symbol:'MSFT',side:'sell',quantity:3}),idempotency_key:'9d18dcad-e25a-42d7-964a-e8755a3b2a42'}));
  const original=fetcher.getMockImplementation()!;
  let posted: Record<string,unknown> | null=null;
  fetcher.mockImplementation(async (url:string,init:RequestInit)=>{
    if(url.includes('/local-trades')) {posted=JSON.parse(init.body as string); return new Response(JSON.stringify({...state,context:'demo',account:{cash:100}}));}
    if(url.includes('/state')) return new Response(JSON.stringify({...state,context:'demo',account:{cash:100}}));
    return original(url,init);
  });
  render(<App/>);
  await userEvent.click(screen.getByRole('button',{name:'Portafoglio'}));
  await userEvent.click(await screen.findByRole('button',{name:'Riprova registrazione incerta'}));
  await waitFor(()=>expect(posted).toEqual({context:'demo',symbol:'MSFT',side:'sell',quantity:3,idempotency_key:'9d18dcad-e25a-42d7-964a-e8755a3b2a42'}));
  expect(localStorage.getItem('aitb-pending-trade-demo')).toBeNull();
});

it('disabilita transizioni dry-run non ammesse dallo stato corrente', async () => {
  const original=fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (url:string,init:RequestInit)=>url.includes('/state')
    ? new Response(JSON.stringify({...state,context:'demo',automation:{state:'STOPPED',mode:'dry-run',execution_enabled:false}}))
    : original(url,init));
  render(<App/>);
  await userEvent.click(screen.getByRole('button',{name:'Automazione'}));
  expect(await screen.findByRole('button',{name:'Avvia dry-run'})).toBeEnabled();
  expect(screen.getByRole('button',{name:'Pausa dry-run'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Esegui ciclo dry-run'})).toBeDisabled();
});

it('mantiene il motivo NO_TRADE del gate senza inventare una scadenza', async () => {
  const original=fetcher.getMockImplementation()!;
  fetcher.mockImplementation(async (url:string,init:RequestInit)=>url.includes('/proposal')
    ? new Response(JSON.stringify({api_version:'1',context:'demo',symbol:'AAPL',interval:'1Day',direction:'WAIT',validation_state:'NO_TRADE',reason:'Synthetic data blocked by operational gate.',expires_at:null}))
    : original(url,init));
  render(<App/>);
  expect(await screen.findByText('Synthetic data blocked by operational gate.')).toBeInTheDocument();
  expect(screen.queryByText('Proposta scaduta: richiedi un aggiornamento.')).not.toBeInTheDocument();
});


describe("pannelli analisi ridimensionabili", () => {
  it("salva la ripartizione senza richieste finanziarie e la recupera al riavvio UI", async () => {
    const first = render(<App />);
    await screen.findByText("Paper non configurato");
    const slider = screen.getByRole("slider", {name: "Larghezza relativa del grafico"});
    expect(slider).toHaveAttribute("type", "range");
    fireEvent.change(slider, {target: {value: "72"}});
    expect(screen.getByRole("region", {name: "Analisi di mercato"})).toHaveStyle({"--analysis-main": "72fr", "--analysis-side": "28fr"});
    expect(localStorage.getItem("aitb-analysis-width")).toBe("72");
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST").every(([url]) => String(url).includes("/preferences"))).toBe(true);
    first.unmount();
    render(<App />);
    expect(screen.getByRole("slider", {name: "Larghezza relativa del grafico"})).toHaveValue("72");
  });

  it.each(["NaN", "Infinity", "", "9", "99", "70px"])("ignora una preferenza invalida: %s", (value) => {
    localStorage.setItem("aitb-analysis-width", value);
    render(<App />);
    expect(screen.getByRole("slider", {name: "Larghezza relativa del grafico"})).toHaveValue("68");
  });

  it("resta utilizzabile quando lo storage delle preferenze è indisponibile", async () => {
    const denied = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {throw new Error("Storage denied");});
    try {
      render(<App />);
      await screen.findByText("Paper non configurato");
      fireEvent.change(screen.getByRole("slider", {name: "Larghezza relativa del grafico"}), {target:{value:"60"}});
      expect(screen.getByRole("region", {name: "Analisi di mercato"})).toHaveStyle({"--analysis-main":"60fr"});
    } finally {denied.mockRestore();}
  });
});

describe("preferenze durevoli del backend", () => {
  it("attende il caricamento prima di salvare senza perdere le altre preferenze", async () => {
    const base=fetcher.getMockImplementation()!;
    let release: (response:Response)=>void = () => {};
    fetcher.mockImplementation(async (url:string,init?:RequestInit)=>url.includes('/preferences') && init?.method !== 'POST'
      ? new Promise<Response>(resolve=>{release=resolve;}) : base(url,init));
    render(<App />);
    await screen.findByText('Paper non configurato');
    expect(screen.getByRole('slider',{name:'Larghezza relativa del grafico'})).toBeDisabled();
    release(new Response(JSON.stringify({api_version:'1',stored:true,preferences:{theme:'light',density:'compact',analysis_width:71}})));
    await waitFor(()=>expect(screen.getByRole('slider',{name:'Larghezza relativa del grafico'})).toBeEnabled());
    fireEvent.change(screen.getByRole('slider',{name:'Larghezza relativa del grafico'}),{target:{value:'72'}});
    await waitFor(()=>expect(fetcher.mock.calls.some(([,init])=>init?.method==='POST')).toBe(true));
    const write=fetcher.mock.calls.find(([,init])=>init?.method==='POST')!;
    expect(JSON.parse(String(write[1]?.body))).toEqual({theme:'light',density:'compact',analysis_width:72});
  });

  it("recupera le preferenze senza dipendere dallo storage della porta e senza POST all'avvio", async () => {
    const base = fetcher.getMockImplementation()!;
    fetcher.mockImplementation(async (url: string, init?: RequestInit) => url.includes('/preferences')
      ? new Response(JSON.stringify({api_version:'1', stored:true, preferences:{theme:'dark',density:'compact',analysis_width:71}}))
      : base(url, init));
    render(<App />);
    // Stored value differs from the light default, so this proves it came from the backend.
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'));
    expect(document.documentElement.dataset.density).toBe('compact');
    expect(screen.getByRole('slider', {name:'Larghezza relativa del grafico'})).toHaveValue('71');
    expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });

  it("serializza e accorpa le modifiche mentre una scrittura è in corso", async () => {
    const base = fetcher.getMockImplementation()!;
    const writes: Record<string, unknown>[] = [];
    let release: (r:Response) => void = () => {};
    fetcher.mockImplementation(async (url:string, init?:RequestInit) => {
      if (url.includes('/preferences') && init?.method === 'POST') {
        const preferences=JSON.parse(String(init.body));
        writes.push(preferences);
        if (writes.length === 1) return new Promise<Response>(resolve => {release=resolve;});
        return new Response(JSON.stringify({api_version:'1',preferences,stored:true}));
      }
      return base(url,init);
    });
    render(<App />);
    await screen.findByText('Paper non configurato');
    const slider=screen.getByRole('slider',{name:'Larghezza relativa del grafico'});
    fireEvent.change(slider,{target:{value:'70'}});
    fireEvent.change(slider,{target:{value:'71'}});
    fireEvent.change(slider,{target:{value:'72'}});
    await waitFor(()=>expect(writes).toHaveLength(1));
    release(new Response(JSON.stringify({api_version:'1',preferences:writes[0],stored:true})));
    await waitFor(()=>expect(writes).toHaveLength(2));
    expect(writes[1]).toEqual({theme:'light',density:'comfortable',analysis_width:72});
    expect(fetcher.mock.calls.filter(([, init])=>init?.method==='POST').every(([url])=>String(url).includes('/preferences'))).toBe(true);
  });

  it("segnala la preferenza non salvata senza bloccare i dati o cambiare il capitale", async () => {
    const base=fetcher.getMockImplementation()!;
    fetcher.mockImplementation(async (url:string,init?:RequestInit)=>url.includes('/preferences') && init?.method==='POST'
      ? new Response(JSON.stringify({detail:'Unavailable'}),{status:503}) : base(url,init));
    render(<App />);
    await screen.findByText('Paper non configurato');
    fireEvent.change(screen.getByRole('slider',{name:'Larghezza relativa del grafico'}),{target:{value:'70'}});
    expect(await screen.findByText(/Preferenze non salvate/)).toBeInTheDocument();
    expect(screen.getByRole('slider',{name:'Larghezza relativa del grafico'})).toHaveValue('70');
    expect(screen.getAllByText('N/D').length).toBeGreaterThan(0);
  });
});
describe("pagine aggiunte per la dismissione di Streamlit", () => {
  const withRoutes = (routes: Record<string, unknown>) => {
    const base = fetcher.getMockImplementation()!;
    fetcher.mockImplementation(async (url: string, init?: RequestInit) => {
      const hit = Object.keys(routes).find((path) => url.includes(path));
      return hit ? new Response(JSON.stringify(routes[hit])) : base(url, init);
    });
  };
  it("Stato sistema mostra contesti e invio ordini disabilitato", async () => {
    withRoutes({"/system": {api_version: "1", status: "ready", service_version: "0.1.0", python: "3.11.18", platform: "Darwin arm64",
      started_at: "2026-11-24T10:00:00+00:00", uptime_seconds: 12.5, order_submission: "disabled",
      contexts: {demo: {connection: "local", ledger: "absent", automation: "STOPPED"}, paper: {connection: "busy", ledger: "not_applicable", automation: "N/D"}}}});
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Stato sistema" }));
    await waitFor(() => expect(screen.getByText(/Occupato \(lettura broker in corso\)/)).toBeInTheDocument());
    expect(screen.getByText("Invio ordini: disabilitato")).toBeInTheDocument();
    expect(screen.getByText("Non creato")).toBeInTheDocument();
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.getByText("Darwin arm64")).toBeInTheDocument();
  });
  it("Stato sistema rifiuta una risposta che non dichiara invio disabilitato", async () => {
    withRoutes({"/system": {api_version: "1", status: "ready", service_version: "0.1.0", python: "3", platform: "x",
      started_at: "x", uptime_seconds: 1, order_submission: "enabled", contexts: {}}});
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Stato sistema" }));
    await waitFor(() => expect(screen.getByText(/Risposta del servizio non valida/)).toBeInTheDocument());
  });
  it("Watchlist mostra N/D senza dati e non inventa prezzi", async () => {
    withRoutes({"/watchlist": {api_version: "1", symbols: ["AAPL"], stored: false}});
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Watchlist" }));
    await waitFor(() => expect(screen.getByText("Feed non disponibile")).toBeInTheDocument());
    const row = screen.getByRole("row", { name: /AAPL/ });
    expect(row.textContent).toContain("N/D");
    expect(screen.getByRole("button", { name: "Rimuovi" })).toBeInTheDocument();
    expect(screen.getByText(/ogni strumento ha una serie generata propria/)).toBeInTheDocument();
  });
  it("walk-forward mostra i fold fuori campione restituiti dal motore", async () => {
    withRoutes({"/walk-forward": {api_version: "1", source: "synthetic-demo", selection_metric: "training net return", training_bars: 66,
      test_bars: 33, step_bars: 33, sample: {start: "2026-01-01T00:00:00+00:00", end: "2026-07-01T00:00:00+00:00", bars: 200},
      folds: [{train_start: "2026-01-01T00:00:00+00:00", train_end: "2026-03-01T00:00:00+00:00", test_start: "2026-03-02T00:00:00+00:00",
        test_end: "2026-04-01T00:00:00+00:00", parameters: {short_window: 3, long_window: 6}, in_sample_return_pct: 1.5, in_sample_trades: 2,
        out_of_sample: {return_pct: -0.5, total_trades: 3, max_drawdown_pct: 1.2, sharpe_ratio: null}}],
      excluded: [{train_start: "x", train_end: "x", test_start: "2026-05-01T00:00:00+00:00", test_end: "2026-06-01T00:00:00+00:00", reason: "Nessun trade nel training"}]}});
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Backtesting" }));
    await userEvent.click(screen.getByRole("button", { name: "Esegui walk-forward" }));
    await waitFor(() => expect(screen.getByText("3/6")).toBeInTheDocument());
    expect(screen.getByText(/Nessun trade nel training/)).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /3\/6/ }).textContent).toContain("N/D");
  });
});
describe("MetaTrader 5 in sola lettura", () => {
  const withRoutes = (routes: Record<string, unknown>) => {
    const base = fetcher.getMockImplementation()!;
    fetcher.mockImplementation(async (url: string, init?: RequestInit) => {
      const hit = Object.keys(routes).find((path) => url.includes(path));
      return hit ? new Response(JSON.stringify(routes[hit])) : base(url, init);
    });
  };
  it("un errore di lettura MT5 non viene mostrato come conto vuoto", async () => {
    render(<App />);
    await userEvent.selectOptions(screen.getByLabelText("Contesto"), "mt5");
    await userEvent.click(screen.getByRole("button", { name: "Portafoglio" }));
    await waitFor(() => expect(screen.getByText(/questo non significa che il conto/)).toBeInTheDocument());
    expect(screen.getByText(/N\/D: lettura non riuscita/)).toBeInTheDocument();
  });
  it("mostra i campi del conto MT5 collegato, con N/D per quelli assenti", async () => {
    withRoutes({"/state": {...{api_version: "1", context: "mt5", positions: [], orders: [], trades: [], automation: {state: "STOPPED"}},
      connection: {status: "connected", reason: "Windows terminal read-only"},
      account: {cash: 1000, balance: 1000, equity: 1010, profit: 10, margin: 50, margin_free: 960, margin_level: null,
        currency: "EUR", server: "Demo-Server", source: "MetaTrader 5 terminal", updated_at: "2026-11-24T10:00:00+00:00"}}});
    render(<App />);
    await userEvent.selectOptions(screen.getByLabelText("Contesto"), "mt5");
    await userEvent.click(screen.getByRole("button", { name: "Portafoglio" }));
    await waitFor(() => expect(screen.getByText("Demo-Server")).toBeInTheDocument());
    expect(screen.getByText("Collegato")).toBeInTheDocument();
    const level = screen.getByText("Livello margine").closest("article")!;
    expect(level.textContent).toContain("N/D");
    expect(screen.getByText(/0 ordini pendenti/)).toBeInTheDocument();
  });
  it("dopo la verifica MT5 mostra la diagnostica senza credenziali", async () => {
    withRoutes({"/diagnostics/mt5": {api_version: "1", state: "unavailable", reason: "Terminal initialization failed (MT5 -10005: IPC timeout).",
      phase: "initialize", error_type: "mt5", mt5_error: [-10005, "IPC timeout"], elapsed_ms: 5003, request_id: "abc123",
      worker: {pid: 4242, executable: "python.exe", python: "3.11.9", startup_ms: 7300}, at: "2026-11-24T10:00:00+00:00"}});
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Connessioni" }));
    await userEvent.click(screen.getByRole("button", { name: "Verifica MetaTrader 5" }));
    await waitFor(() => expect(screen.getByText("Ultimo tentativo MetaTrader 5")).toBeInTheDocument());
    expect(screen.getByText("-10005 · IPC timeout")).toBeInTheDocument();
    expect(screen.getByText("7300 ms")).toBeInTheDocument();
    expect(screen.getByText("initialize")).toBeInTheDocument();
  });
});
