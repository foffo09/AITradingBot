import {
  useCallback,
  useEffect,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  api,
  type Context,
  type State,
  type Market,
  type Proposal,
  type Instrument,
  type Backtest,
  type RecordData,
} from "./api";
import { instant, number, text } from "./format";
import MarketChart from "./MarketChart";
const contexts: Record<Context, string> = {
  demo: "Demo",
  simulation: "Simulazione",
  paper: "Alpaca Paper",
  mt5: "MetaTrader 5",
};
const pages = [
  "Panoramica",
  "Mercati",
  "Segnali",
  "Portafoglio",
  "Storico",
  "Backtesting",
  "Connessioni",
  "Impostazioni",
] as const;
type Page = (typeof pages)[number];
const icons = ["◈", "⌁", "↗", "▣", "◷", "▥", "⇄", "⚙"];
function saved(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}
function persist(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Le preferenze restano attive nella sessione se lo storage è bloccato. */
  }
}
function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p className="notice error" role="alert">
      {children}
    </p>
  );
}
function Metric({
  label,
  value,
  unit,
  caption,
}: {
  label: string;
  value: unknown;
  unit?: string;
  caption?: string;
}) {
  return (
    <article className="metric">
      <span className="eyebrow">{label}</span>
      <strong>{number(value, unit)}</strong>
      <small>{caption ?? "Fonte: snapshot del contesto"}</small>
    </article>
  );
}
function DataTable({
  rows,
  columns,
  empty,
}: {
  rows: RecordData[] | undefined;
  columns: [string, string][];
  empty: string;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map(([key, label]) => (
              <th key={key} scope="col">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows?.map((row, i) => (
            <tr key={i}>
              {columns.map(([key]) => (
                <td key={key}>
                  {/timestamp|_at$/.test(key)
                    ? instant(row[key])
                    : text(
                        row[key] ??
                          row[
                            (
                              {
                                qty: "quantity",
                                avg_entry_price: "average_entry",
                                current_price: "market_price",
                              } as Record<string, string>
                            )[key]
                          ],
                      )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows?.length && (
        <p className="empty">
          {rows ? empty : "N/D · Snapshot non disponibile."}
        </p>
      )}
    </div>
  );
}
function ProposalPanel({
  proposal,
  error,
}: {
  proposal: Proposal | null;
  error?: string;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const expired =
    typeof proposal?.expires_at === "string" &&
    new Date(proposal.expires_at).getTime() <= now;
  const blocked =
    !proposal || proposal.validation_state === "NO_TRADE" || expired;
  return (
    <section className="panel signal-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Motore strategico</span>
          <h2>Proposta analitica</h2>
        </div>
        <span
          className={`badge ${blocked ? "muted" : proposal.direction === "BUY" ? "positive" : "warning"}`}
        >
          {blocked ? "NO_TRADE" : proposal.direction}
        </span>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      <p className="signal-reason">
        {expired
          ? "Proposta scaduta: richiedi un aggiornamento."
          : (proposal?.reason ?? "In attesa di dati verificabili dal motore.")}
      </p>
      <dl className="levels">
        {[
          ["entry", "Ingresso · USD"],
          ["take_profit", "Take profit · USD"],
          ["stop_loss", "Stop loss · USD"],
          ["reward_risk", "Rendimento / rischio"],
          ["quantity", "Quantità teorica"],
        ].map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>{number(proposal?.[key])}</dd>
          </div>
        ))}
      </dl>
      <div className="metadata">
        <span>
          Validazione <b>{text(proposal?.validation_state)}</b>
        </span>
        <span>
          Generata <b>{instant(proposal?.timestamp)}</b>
        </span>
        <span>
          Scadenza <b>{instant(proposal?.expires_at)}</b>
        </span>
        <span>
          ID <b>{text(proposal?.signal_id)}</b>
        </span>
        <span>
          Fonte <b>{sourceOf(proposal?.provenance ?? proposal)}</b>
        </span>
      </div>
      <p className="notice">
        Una proposta non è un ordine. BUY e SELL non autorizzano un invio.
        Regole non calibrate, nessuna probabilità di successo.
      </p>
    </section>
  );
}
function sourceOf(value: unknown) {
  if (value && typeof value === "object") {
    const p = value as RecordData;
    const bars = p.bars as RecordData | undefined;
    return text(p.source ?? p.data_source ?? bars?.source);
  }
  return "N/D";
}
function Equity({ points }: { points: Backtest["equity"] }) {
  if (points.length < 2)
    return <p className="empty">Curva equity N/D · Campione insufficiente.</p>;
  const values = points.map((p) => p.value),
    min = Math.min(...values),
    max = Math.max(...values),
    span = max - min || 1;
  return (
    <figure className="equity-figure">
      <svg
        viewBox="0 0 800 160"
        role="img"
        aria-label={`Equity del backtest, da ${number(values[0], "USD")} a ${number(values.at(-1), "USD")}`}
      >
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          points={points
            .map(
              (p, i) =>
                `${(i / (points.length - 1)) * 800},${145 - ((p.value - min) / span) * 130}`,
            )
            .join(" ")}
        />
      </svg>
      <figcaption>
        {instant(points[0].time)} → {instant(points.at(-1)?.time)} · Equity
        teorica USD · min {number(min)} / max {number(max)}
      </figcaption>
    </figure>
  );
}
function Backtesting({
  context,
  symbol,
}: {
  context: Context;
  symbol: string;
}) {
  const [short, setShort] = useState(10),
    [long, setLong] = useState(30),
    [result, setResult] = useState<Backtest | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function run(e: FormEvent) {
    e.preventDefault();
    setError("");
    setResult(null);
    if (short >= long) {
      setError("La finestra breve deve essere inferiore alla finestra lunga.");
      return;
    }
    setBusy(true);
    try {
      setResult(await api.backtest(context, symbol, short, long));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Laboratorio storico</span>
            <h2>Backtesting · {symbol}</h2>
          </div>
          <span className="badge muted">Capitale separato</span>
        </div>
        <p>
          Calcolo nel motore esistente sui dati del contesto selezionato. Costi
          e metriche provengono dal backend; nessun ordine viene inviato.
        </p>
        <form onSubmit={run} className="inline-form">
          <label>
            Finestra breve
            <input
              type="number"
              min="2"
              max="200"
              required
              value={short}
              onChange={(e) => setShort(Number(e.target.value))}
            />
          </label>
          <label>
            Finestra lunga
            <input
              type="number"
              min="3"
              max="500"
              required
              value={long}
              onChange={(e) => setLong(Number(e.target.value))}
            />
          </label>
          <button className="primary" disabled={busy}>
            {busy ? "Calcolo in corso…" : "Esegui backtest"}
          </button>
        </form>
        {error && <ErrorNote>{error}</ErrorNote>}
      </section>
      {result && (
        <section className="panel">
          <div className="panel-heading">
            <h2>Risultato del motore</h2>
            <span className="badge muted">Fonte: {result.source}</span>
          </div>
          <div className="metrics">
            <Metric
              label="Rendimento storico"
              value={result.metrics.return_pct}
              unit="%"
              caption="Backtest · dato del motore"
            />
            <Metric
              label="Drawdown massimo"
              value={result.metrics.max_drawdown_pct}
              unit="%"
              caption="Backtest · dato del motore"
            />
            <Metric
              label="Operazioni chiuse"
              value={result.metrics.total_trades}
              caption="Backtest · dato del motore"
            />
            <Metric
              label="Costi totali"
              value={result.metrics.total_transaction_costs}
              unit="USD"
              caption="Backtest · dato del motore"
            />
          </div>
          <Equity points={result.equity} />
          <DataTable
            rows={result.trades}
            columns={tradeColumns}
            empty="Il motore non ha prodotto operazioni chiuse."
          />
          <p className="notice">
            Il risultato storico, anche su dati sintetici, non dimostra
            redditività futura o idoneità operativa.
          </p>
        </section>
      )}
    </>
  );
}
const tradeColumns: [string, string][] = [
  ["symbol", "Strumento"],
  ["side", "Lato"],
  ["quantity", "Quantità"],
  ["entry_price", "Ingresso · USD"],
  ["exit_price", "Uscita · USD"],
  ["net_pnl", "P/L netto · USD"],
  ["entry_fee_alloc", "Fee ingresso · USD"],
  ["exit_fee", "Fee uscita · USD"],
  ["closed_at", "Chiusura · UTC"],
];
function message(error: unknown) {
  return error instanceof Error ? error.message : "Operazione non riuscita.";
}
function LocalLedger({
  context,
  symbol,
  state,
  onChanged,
}: {
  context: Context;
  symbol: string;
  state: State | null;
  onChanged: () => void;
}) {
  const [capital, setCapital] = useState("10000"),
    [quantity, setQuantity] = useState("1"),
    [side, setSide] = useState("buy"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  if (context === "paper" || context === "mt5")
    return (
      <p className="notice">
        Le operazioni Paper e MT5 sono in sola lettura. Nessun invio è
        disponibile da questo terminale.
      </p>
    );
  async function act(e: FormEvent, kind: "account" | "trade") {
    e.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      if (kind === "account") await api.account(context, Number(capital));
      else await api.trade(context, symbol, side, Number(quantity));
      setNotice(
        kind === "account"
          ? "Conto virtuale disponibile. Il conto esistente non è stato azzerato."
          : "Registrazione virtuale completata nel ledger del contesto.",
      );
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h2>Ledger virtuale · {contexts[context]}</h2>
      <p>
        Solo capitale fittizio e dati sintetici dichiarati. Demo e Simulazione
        conservano conti separati.
      </p>
      {!state?.account ? (
        <form className="inline-form" onSubmit={(e) => void act(e, "account")}>
          <label>
            Capitale iniziale · USD
            <input
              type="number"
              min="1"
              step="0.01"
              required
              value={capital}
              onChange={(e) => setCapital(e.target.value)}
            />
          </label>
          <button className="primary" disabled={busy}>
            Crea conto virtuale
          </button>
        </form>
      ) : (
        <form className="inline-form" onSubmit={(e) => void act(e, "trade")}>
          <label>
            Strumento
            <input readOnly value={symbol} />
          </label>
          <label>
            Lato
            <select value={side} onChange={(e) => setSide(e.target.value)}>
              <option value="buy">Acquisto virtuale</option>
              <option value="sell">Vendita virtuale</option>
            </select>
          </label>
          <label>
            Quantità
            <input
              type="number"
              min="0.000001"
              step="any"
              required
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </label>
          <button className="primary" disabled={busy}>
            Registra operazione virtuale
          </button>
        </form>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
      {notice && (
        <p role="status" className="notice">
          {notice}
        </p>
      )}
    </section>
  );
}
function Connections({ onChanged }: { onChanged: () => void }) {
  const [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [state, setState] = useState<State | null>(null);
  async function connect(c: "paper" | "mt5") {
    setBusy(c);
    setError("");
    setState(null);
    try {
      setState(await api.connect(c));
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <div className="connection-grid">
        {(["paper", "mt5"] as const).map((c) => (
          <section className="panel" key={c}>
            <span className="eyebrow">Connettore · sola lettura</span>
            <h2>{contexts[c]}</h2>
            <p>
              {c === "paper"
                ? "Conto, posizioni e ordini del conto Alpaca Paper configurato. Solo dati reali, nessun fallback Demo."
                : "Disponibilità del bridge locale MetaTrader 5. Se assente, il backend spiega il limite di piattaforma."}
            </p>
            <p className="notice">
              Configurazione esterna al frontend. Nessuna password o chiave
              viene richiesta o salvata nella UI.
            </p>
            <button
              className="primary"
              disabled={!!busy}
              onClick={() => void connect(c)}
            >
              {busy === c ? "Verifica in corso…" : `Verifica ${contexts[c]}`}
            </button>
          </section>
        ))}
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {state && (
        <p role="status" className="notice">
          {contexts[state.context]} · {state.connection.status}:{" "}
          {state.connection.reason ?? "Verifica completata dal servizio."}
        </p>
      )}
    </>
  );
}
export default function App() {
  const [page, setPage] = useState<Page>("Panoramica"),
    [context, setContext] = useState<Context>("demo"),
    [symbol, setSymbol] = useState("AAPL"),
    [interval, setIntervalValue] = useState("1Day");
  const [theme, setTheme] = useState(() =>
      saved("aitb-theme", "dark") === "light" ? "light" : "dark",
    ),
    [density, setDensity] = useState(() =>
      saved("aitb-density", "comfortable") === "compact"
        ? "compact"
        : "comfortable",
    );
  const [state, setState] = useState<State | null>(null),
    [market, setMarket] = useState<Market | null>(null),
    [proposal, setProposal] = useState<Proposal | null>(null),
    [instruments, setInstruments] = useState<Instrument[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({}),
    [loading, setLoading] = useState(true),
    [revision, setRevision] = useState(0),
    [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const clear = useCallback(() => {
    setState(null);
    setMarket(null);
    setProposal(null);
    setErrors({});
    setLoading(true);
    setLastRefresh(null);
  }, []);
  const refresh = useCallback(() => {
    clear();
    setRevision((v) => v + 1);
  }, [clear]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    persist("aitb-theme", theme);
  }, [theme]);
  useEffect(() => {
    document.documentElement.dataset.density = density;
    persist("aitb-density", density);
  }, [density]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    async function load() {
      try {
        await api.session(controller.signal);
      } catch (e) {
        if (active) {
          setState(null);
          setMarket(null);
          setProposal(null);
          setErrors({ session: message(e) });
          setLoading(false);
        }
        return;
      }
      const results = await Promise.allSettled([
        api.state(context, controller.signal),
        api.market(context, symbol, interval, controller.signal),
        api.proposal(context, symbol, interval, controller.signal),
        api.instruments(controller.signal),
      ]);
      if (!active) return;
      const nextErrors: Record<string, string> = {};
      const [s, m, p, i] = results;
      if (s.status === "fulfilled") setState(s.value);
      else {
        setState(null);
        nextErrors.state = message(s.reason);
      }
      if (m.status === "fulfilled") setMarket(m.value);
      else {
        setMarket(null);
        nextErrors.market = message(m.reason);
      }
      if (p.status === "fulfilled") setProposal(p.value);
      else {
        setProposal(null);
        nextErrors.proposal = message(p.reason);
      }
      if (i.status === "fulfilled") setInstruments(i.value);
      else {
        setInstruments([]);
        nextErrors.instruments = message(i.reason);
      }
      setErrors(nextErrors);
      setLastRefresh(new Date().toISOString());
      setLoading(false);
    }
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [context, symbol, interval, revision]);
  const offline = context === "demo" || context === "simulation";
  const account = state?.account;
  const selectMarket = (
    <div className="market-selectors">
      <label>
        Strumento
        <select
          value={symbol}
          onChange={(e) => {
            clear();
            setSymbol(e.target.value);
          }}
        >
          {!instruments.some((i) => i.symbol === symbol) && (
            <option value={symbol}>{symbol}</option>
          )}
          {instruments.map((i) => (
            <option key={i.symbol} value={i.symbol}>
              {i.symbol} · {i.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Intervallo
        <select
          value={interval}
          onChange={(e) => {
            clear();
            setIntervalValue(e.target.value);
          }}
        >
          {[
            ["1Min", "1 min"],
            ["5Min", "5 min"],
            ["15Min", "15 min"],
            ["1Hour", "1 ora"],
            ["1Day", "1 giorno"],
            ["1Week", "1 settimana"],
          ].map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
  const chart = (
    <section className="panel market-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Analisi di mercato</span>
          <h2>
            {symbol} <small>/ USD</small>
          </h2>
        </div>
        {selectMarket}
      </div>
      <div className="quote-row">
        <strong>{number(market?.bars.at(-1)?.close, "USD")}</strong>
        <span>Ultimo close storico</span>
        <span className="badge muted">{market?.source ?? "Fonte N/D"}</span>
      </div>
      <div className="quote-detail">
        <span>Bid {number(market?.quote?.bid, "USD")}</span>
        <span>Ask {number(market?.quote?.ask, "USD")}</span>
        <span>Quota: {instant(market?.quote?.timestamp)}</span>
        <span>Fonte quota: {text(market?.quote?.source)}</span>
      </div>
      {errors.market && <ErrorNote>{errors.market}</ErrorNote>}
      {market?.reason && <p className="notice">{market.reason}</p>}
      <MarketChart
        bars={market?.bars ?? []}
        identity={`${context}/${symbol}/${interval}`}
        theme={theme}
      />
      <p className="metadata">
        Acquisizione storico: {instant(market?.as_of)} · Le barre possono essere
        in formazione. Lo storico non è una quota corrente.
      </p>
    </section>
  );
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Vai al contenuto
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">AI</span>
          <div>
            TradingBot<small>TERMINALE ANALITICO</small>
          </div>
        </div>
        <span className="nav-caption">WORKSPACE</span>
        <nav aria-label="Navigazione principale">
          {pages.map((name, i) => (
            <button
              key={name}
              className={page === name ? "nav-item active" : "nav-item"}
              aria-current={page === name ? "page" : undefined}
              onClick={() => setPage(name)}
            >
              <span aria-hidden="true">{icons[i]}</span>
              {name}
              {name === "Segnali" && <i className="nav-dot" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="status-line">
            <i className="status-dot" />
            Automazione ferma
          </div>
          <p>
            Nessun invio automatico.
            <br />
            Analisi e contabilità separate.
          </p>
          <span className="version">AITradingBot · React / Tauri 2</span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <span>/</span> <b>{page}</b>
          </div>
          <div className="top-controls">
            <label className="context-label">
              Contesto
              <select
                aria-label="Contesto"
                value={context}
                onChange={(e) => {
                  clear();
                  setContext(e.target.value as Context);
                }}
              >
                {Object.entries(contexts).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <span className="readonly-label">SOLA LETTURA BROKER</span>
          </div>
        </header>
        <main id="main-content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">
                {contexts[context]} /{" "}
                {offline ? "Ambiente virtuale" : "Dati reali richiesti"}
              </span>
              <h1>{page}</h1>
              <p>
                {page === "Panoramica"
                  ? "Mercati, capitale e proposte. Ogni dato conserva la propria origine."
                  : "Workspace analitico · nessuna autorizzazione implicita a operare."}
              </p>
            </div>
            <button className="secondary" onClick={refresh} disabled={loading}>
              {loading ? "Aggiornamento…" : "↻ Aggiorna dati"}
            </button>
          </div>
          <div className={`environment-strip ${offline ? "synthetic" : ""}`}>
            <span className="status-dot" />
            {offline
              ? "Dati sintetici dichiarati · capitale fittizio · nessun broker"
              : "Solo dati del connettore reale · nessun fallback sintetico"}
            <span className="strip-end">Refresh 15 s</span>
          </div>
          {errors.session && <ErrorNote>{errors.session}</ErrorNote>}
          {errors.state && <ErrorNote>{errors.state}</ErrorNote>}
          {errors.instruments && <ErrorNote>{errors.instruments}</ErrorNote>}
          <div className="connection-status" role="status">
            <span>
              {state?.connection.reason ??
                state?.connection.status ??
                (loading
                  ? "Collegamento al servizio locale…"
                  : "Stato conto N/D")}
            </span>
            <small>Ultimo tentativo UI {instant(lastRefresh)}</small>
          </div>
          {page === "Panoramica" && (
            <>
              <div className="metrics">
                <Metric label="Equity" value={account?.equity} unit="USD" />
                <Metric label="Liquidità" value={account?.cash} unit="USD" />
                <Metric
                  label="Capitale iniziale"
                  value={account?.initial_cash}
                  unit="USD"
                  caption={
                    offline
                      ? "Fonte: ledger virtuale del contesto"
                      : "Solo se fornito dal conto verificato"
                  }
                />
                <Metric
                  label="P/L realizzato"
                  value={account?.realized_pnl}
                  unit="USD"
                />
              </div>
              <div className="analysis-grid">
                {chart}
                <ProposalPanel proposal={proposal} error={errors.proposal} />
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Posizioni del contesto</h2>
                  <button
                    className="text-button"
                    onClick={() => setPage("Portafoglio")}
                  >
                    Apri portafoglio →
                  </button>
                </div>
                <DataTable
                  rows={state?.positions}
                  columns={positionColumns}
                  empty="Nessuna posizione restituita dal contesto."
                />
              </section>
            </>
          )}
          {page === "Mercati" && chart}
          {page === "Segnali" && (
            <>
              {selectMarket}
              <ProposalPanel proposal={proposal} error={errors.proposal} />
            </>
          )}
          {page === "Portafoglio" && (
            <>
              <div className="metrics">
                <Metric label="Equity" value={account?.equity} unit="USD" />
                <Metric label="Liquidità" value={account?.cash} unit="USD" />
                <Metric
                  label="Buying power"
                  value={account?.buying_power}
                  unit="USD"
                />
                <Metric
                  label="P/L non realizzato"
                  value={account?.unrealized_pnl}
                  unit="USD"
                />
              </div>
              <LocalLedger
                key={context}
                context={context}
                symbol={symbol}
                state={state}
                onChanged={refresh}
              />
              <section className="panel">
                <h2>Posizioni</h2>
                <DataTable
                  rows={state?.positions}
                  columns={positionColumns}
                  empty="Nessuna posizione nel contesto."
                />
              </section>
              <section className="panel">
                <h2>Ordini restituiti dal connettore</h2>
                <p>
                  Ordini e fill restano distinti. L'elenco broker non è una
                  riconciliazione contabile completa.
                </p>
                <DataTable
                  rows={state?.orders}
                  columns={orderColumns}
                  empty="Nessun ordine restituito dal contesto."
                />
              </section>
            </>
          )}
          {page === "Storico" && (
            <section className="panel">
              <h2>Storico · {contexts[context]}</h2>
              <p>
                Solo operazioni restituite dal contesto corrente. Costi assenti
                restano N/D.
              </p>
              <DataTable
                rows={state?.trades}
                columns={tradeColumns}
                empty="Nessuna operazione restituita. Lo storico broker può non essere disponibile."
              />
            </section>
          )}
          {page === "Backtesting" && (
            <>
              {selectMarket}
              <Backtesting
                key={`${context}/${symbol}`}
                context={context}
                symbol={symbol}
              />
            </>
          )}
          {page === "Connessioni" && <Connections onChanged={refresh} />}
          {page === "Impostazioni" && (
            <section className="panel settings">
              <span className="eyebrow">Preferenze locali</span>
              <h2>Il tuo workspace</h2>
              <label>
                Tema
                <select
                  value={theme}
                  onChange={(e) => setTheme(e.target.value)}
                >
                  <option value="dark">Scuro</option>
                  <option value="light">Chiaro</option>
                </select>
              </label>
              <label>
                Densità del layout
                <select
                  value={density}
                  onChange={(e) => setDensity(e.target.value)}
                >
                  <option value="comfortable">Comoda</option>
                  <option value="compact">Compatta</option>
                </select>
              </label>
              <p>
                Le preferenze sono salvate solo su questo dispositivo. Nessuna
                credenziale viene conservata qui.
              </p>
              <div className="notice">
                <b>Automazione ferma</b>
                <p>
                  {state?.automation.reason ??
                    "Questo frontend non espone percorsi di avvio o invio broker."}
                </p>
              </div>
              <details>
                <summary>Licenze e attribuzioni</summary>
                <p>
                  TradingView Lightweight Charts™ · Copyright (с) 2025
                  TradingView, Inc. · Apache 2.0.
                </p>
                <a
                  href="https://www.tradingview.com/"
                  target="_blank"
                  rel="noreferrer"
                >
                  TradingView
                </a>{" "}
                ·{" "}
                <a href="/lightweight-charts-LICENSE.txt">Licenza Apache 2.0</a>{" "}
                ·{" "}
                <a href="/lightweight-charts-NOTICE.txt">
                  Avviso di attribuzione
                </a>
              </details>
            </section>
          )}
          <footer>
            <span>
              Origine e timestamp sempre espliciti · N/D = dato non disponibile
            </span>
            <span>{contexts[context]} · Automazione ferma</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
const positionColumns: [string, string][] = [
  ["symbol", "Strumento"],
  ["qty", "Quantità"],
  ["avg_entry_price", "Prezzo medio · USD"],
  ["current_price", "Prezzo · USD"],
  ["market_value", "Valore · USD"],
  ["unrealized_pl", "P/L · USD"],
];
const orderColumns: [string, string][] = [
  ["symbol", "Strumento"],
  ["side", "Lato"],
  ["qty", "Quantità"],
  ["filled_qty", "Eseguita"],
  ["status", "Stato"],
  ["filled_avg_price", "Prezzo fill · USD"],
  ["submitted_at", "Invio · UTC"],
];
