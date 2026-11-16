import { render, screen, waitFor } from "@testing-library/react";
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
