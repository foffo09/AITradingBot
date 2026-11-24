import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  api,
  pendingTrade,
  type Context,
  type State,
  type Market,
  type Proposal,
  type Instrument,
  type Backtest,
  type RecordData,
  type Preferences,
  type WalkForward,
  type SystemStatus,
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
  "Watchlist",
  "Segnali",
  "Portafoglio",
  "Storico",
  "Backtesting",
  "Automazione",
  "Connessioni",
  "Stato sistema",
  "Impostazioni",
] as const;
type Page = (typeof pages)[number];
const icons = ["◈", "⌁", "☰", "↗", "▣", "◷", "▥", "▷", "⇄", "◉", "⚙"];
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
const columnAliases: Record<string, string[]> = {
  qty: ["quantity", "volume", "volume_initial"],
  avg_entry_price: ["average_entry", "price_open"],
  current_price: ["market_price", "price_current"],
  unrealized_pl: ["profit"],
  side: ["direction"],
  entry_fee_alloc: ["entry_fee"],
};
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
                          columnAliases[key]
                            ?.map((alias) => row[alias])
                            .find(
                              (value) => value !== null && value !== undefined,
                            ),
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
  const expiry = typeof proposal?.expires_at === "string" ? Date.parse(proposal.expires_at) : NaN;
  const actionable = proposal?.direction === "BUY" || proposal?.direction === "SELL";
  const expired = actionable && (!Number.isFinite(expiry) || expiry <= now);
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
            <dd>{number(blocked ? null : proposal?.[key])}</dd>
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
function Equity({
  points,
  unit,
}: {
  points: Backtest["equity"];
  unit: string;
}) {
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
        aria-label={`Equity del backtest, da ${number(values[0], unit)} a ${number(values.at(-1), unit)}`}
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
        teorica {unit} · min {number(min)} / max {number(max)}
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
  const moneyUnit = context === "mt5" ? "valuta strumento N/D" : "USD";
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
          Intervallo del backtest: 1 giorno. SMA su singolo campione storico; OOS non eseguito.
        </p>
        <form onSubmit={run} className="inline-form">
          <label>
            Finestra breve
            <input
              type="number"
              min="1"
              max="198"
              required
              value={short}
              onChange={(e) => setShort(Number(e.target.value))}
            />
          </label>
          <label>
            Finestra lunga
            <input
              type="number"
              min="2"
              max="199"
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
              unit={moneyUnit}
              caption="Backtest · dato del motore"
            />
          </div>
          <Equity points={result.equity} unit={moneyUnit} />
          <DataTable
            rows={result.trades}
            columns={tradeColumns(moneyUnit)}
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
const tradeColumns = (currency: string): [string, string][] => [
  ["symbol", "Strumento"],
  ["side", "Lato"],
  ["quantity", "Quantità"],
  ["entry_price", `Ingresso · ${currency}`],
  ["exit_price", `Uscita · ${currency}`],
  ["net_pnl", `P/L netto · ${currency}`],
  ["entry_fee_alloc", `Fee ingresso · ${currency}`],
  ["exit_fee", `Fee uscita · ${currency}`],
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
    [notice, setNotice] = useState(""),
    [pending, setPending] = useState(() => pendingTrade(context));
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
      else await api.trade(context, pending?.symbol ?? symbol, pending?.side ?? side, pending?.quantity ?? Number(quantity));
      setNotice(
        kind === "account"
          ? "Conto virtuale disponibile. Il conto esistente non è stato azzerato."
          : "Registrazione virtuale completata nel ledger del contesto.",
      );
      onChanged();
    } catch (e) {
      setError(message(e));
    } finally {
      setPending(pendingTrade(context));
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h2>Ledger virtuale · {contexts[context]}</h2>
      <p>
        Solo capitale fittizio e dati sintetici dichiarati. Demo e Simulazione
        conservano conti separati. Dopo un riavvio verifica lo storico prima di creare una nuova richiesta; la memoria delle richieste dipende dall’origine locale (anche dalla porta).
      </p>
      {pending && <p className="notice">Registrazione con esito incerto: {pending.symbol} · {pending.side} · quantità {number(pending.quantity)}. Riprovando si conserva lo stesso identificativo; verifica anche lo storico.</p>}
      {state === null ? (
        <p className="notice">
          Stato del conto non disponibile: nessuna operazione è possibile finché il servizio locale non risponde.
        </p>
      ) : !state.account ? (
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
            <input readOnly value={pending?.symbol ?? symbol} />
          </label>
          <label>
            Lato
            <select disabled={!!pending} value={pending?.side ?? side} onChange={(e) => setSide(e.target.value)}>
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
              disabled={!!pending}
              value={pending?.quantity ?? quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
          </label>
          <button className="primary" disabled={busy}>
            {pending ? "Riprova registrazione incerta" : "Registra operazione virtuale"}
          </button>
        </form>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
      {notice && state !== null && (
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
function Automation({ context, state, onChanged }: {
  context: Context;
  state: State | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const current = state?.automation;
  const local = context === "demo" || context === "simulation";
  async function command(value: "start" | "pause" | "stop" | "cycle") {
    setBusy(true);
    setError("");
    try {
      await api.automation(context, value, crypto.randomUUID());
    } catch (e) {
      setError(message(e));
    } finally {
      onChanged();
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h2>Automazione · dry-run</h2>
      <p>Solo cicli analitici espliciti nei contesti locali. Nessun ordine broker viene inviato. Nessun ciclo periodico è avviato dal frontend.</p>
      <strong>{text(current?.state)}</strong>
      <p>{text(current?.reason)}</p>
      <div className="button-group">
        {([
          ["start", "Avvia dry-run"],
          ["pause", "Pausa dry-run"],
          ["stop", "Arresta dry-run"],
          ["cycle", "Esegui ciclo dry-run"],
        ] as const).map(([value, label]) => (
          <button key={value}
            disabled={busy || !local || !current || current.execution_enabled !== false || current.mode !== "dry-run" || !(value === "start" ? ["STOPPED", "PAUSED"].includes(current.state) : value === "stop" ? ["RUNNING", "PAUSED", "ERROR"].includes(current.state) : current.state === "RUNNING")}
            onClick={() => void command(value)}>
            {label}
          </button>
        ))}
      </div>
      {!local && <p className="notice">Automazione broker non disponibile da questo terminale.</p>}
      {error && <ErrorNote>{error}</ErrorNote>}
      <dl className="metadata">
        {[
          ["last_start", "Ultimo avvio"], ["last_stop", "Ultimo arresto"],
          ["last_cycle", "Ultimo ciclo"], ["last_error", "Ultimo errore"],
          ["reconciliation", "Riconciliazione"],
        ].map(([key, label]) => (
          <div key={key}><dt>{label}</dt>
            <dd>{key.startsWith("last_") && key !== "last_error" ? instant(current?.[key]) : text(current?.[key])}</dd>
          </div>
        ))}
      </dl>
      <div className="metrics">
        <Metric label="Proposte" value={current?.proposals} />
        <Metric label="Intenti dry-run" value={current?.intents} />
      </div>
    </section>
  );
}
function WalkForwardPanel({ context, symbol }: { context: Context; symbol: string }) {
  const [training, setTraining] = useState(""),
    [test, setTest] = useState(""),
    [result, setResult] = useState<WalkForward | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function run(e: FormEvent) {
    e.preventDefault();
    setError("");
    setResult(null);
    setBusy(true);
    try {
      setResult(await api.walkForward(context, symbol, Number(training) || undefined, Number(test) || undefined));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Validazione fuori campione</span>
          <h2>Walk-forward · {symbol}</h2>
        </div>
        <span className="badge muted">Nessun ordine · nessun ledger</span>
      </div>
      <p>
        Il motore sceglie le finestre SMA (2/4, 3/6, 5/10) solo sul training di ogni fold e le
        verifica sulle barre successive. Lasciare vuoti i campi per il dimensionamento automatico.
      </p>
      <form onSubmit={run} className="inline-form">
        <label>
          Barre di training
          <input type="number" min="12" step="1" placeholder="auto" value={training} onChange={(e) => setTraining(e.target.value)} />
        </label>
        <label>
          Barre di test
          <input type="number" min="12" step="1" placeholder="auto" value={test} onChange={(e) => setTest(e.target.value)} />
        </label>
        <button className="primary" disabled={busy}>{busy ? "Valutazione in corso…" : "Esegui walk-forward"}</button>
      </form>
      {error && <ErrorNote>{error}</ErrorNote>}
      {result && (
        <>
          <p className="notice">
            Fonte {result.source} · campione {result.sample.bars} barre giornaliere ({instant(result.sample.start)} →{" "}
            {instant(result.sample.end)}) · training {result.training_bars}, test {result.test_bars}, passo {result.step_bars} ·
            selezione: {result.selection_metric}.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Periodo di test</th>
                  <th scope="col">Finestre scelte</th>
                  <th scope="col">Rendimento training %</th>
                  <th scope="col">Rendimento OOS %</th>
                  <th scope="col">Operazioni OOS</th>
                  <th scope="col">Drawdown OOS %</th>
                  <th scope="col">Sharpe OOS</th>
                </tr>
              </thead>
              <tbody>
                {result.folds.map((fold) => (
                  <tr key={fold.test_start}>
                    <td>{instant(fold.test_start)} → {instant(fold.test_end)}</td>
                    <td>{fold.parameters.short_window}/{fold.parameters.long_window}</td>
                    <td>{number(fold.in_sample_return_pct)}</td>
                    <td>{number(fold.out_of_sample.return_pct)}</td>
                    <td>{number(fold.out_of_sample.total_trades)}</td>
                    <td>{number(fold.out_of_sample.max_drawdown_pct)}</td>
                    <td>{number(fold.out_of_sample.sharpe_ratio)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.folds.length === 0 && <p className="notice">Nessun fold valido: nessun risultato fuori campione.</p>}
          {result.excluded.map((item) => (
            <p className="notice" key={item.test_start}>
              Fold escluso ({instant(item.test_start)} → {instant(item.test_end)}): {item.reason}
            </p>
          ))}
          <p className="notice">I risultati fuori campione su dati storici o sintetici non dimostrano redditività futura.</p>
        </>
      )}
    </section>
  );
}
interface WatchRow { market: Market | null; error: string }
function Watchlist({
  context,
  instruments,
  onOpen,
}: {
  context: Context;
  instruments: Instrument[];
  onOpen: (symbol: string) => void;
}) {
  const [symbols, setSymbols] = useState<string[] | null>(null),
    [rows, setRows] = useState<Record<string, WatchRow>>({}),
    [candidate, setCandidate] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api.watchlist(controller.signal).then(setSymbols).catch((e) => {
      if (!controller.signal.aborted) setError(message(e));
    });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!symbols) return;
    const controller = new AbortController();
    void Promise.allSettled(symbols.map((symbol) => api.market(context, symbol, "1Day", controller.signal))).then((results) => {
      if (controller.signal.aborted) return;
      // Keyed by context so a context switch never shows the previous context's prices.
      setRows(Object.fromEntries(symbols.map((symbol, i) => {
        const r = results[i];
        return [`${context}/${symbol}`, r.status === "fulfilled" ? { market: r.value, error: "" } : { market: null, error: message(r.reason) }];
      })));
    });
    return () => controller.abort();
  }, [symbols, context]);
  async function save(next: string[]) {
    setError("");
    setBusy(true);
    try {
      setSymbols(await api.saveWatchlist(next));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  const available = instruments.filter((i) => !symbols?.includes(i.symbol));
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Strumenti seguiti</span>
          <h2>Watchlist · {contexts[context]}</h2>
        </div>
        <span className="badge muted">Barre giornaliere · nessun ordine</span>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {symbols === null && !error && <p>Caricamento watchlist…</p>}
      {symbols && (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Strumento</th>
                  <th scope="col">Ultima chiusura</th>
                  <th scope="col">Variazione %</th>
                  <th scope="col">Fonte</th>
                  <th scope="col">Aggiornato</th>
                  <th scope="col">Azioni</th>
                </tr>
              </thead>
              <tbody>
                {symbols.map((symbol) => {
                  const { market, error: rowError } = rows[`${context}/${symbol}`] ?? { market: null, error: "" };
                  const bars = market?.bars ?? [];
                  const last = bars.at(-1), previous = bars.at(-2);
                  const change = last && previous ? ((last.close - previous.close) / previous.close) * 100 : null;
                  return (
                    <tr key={symbol}>
                      <th scope="row">{symbol}</th>
                      <td>{number(last?.close)}</td>
                      <td>{number(change)}</td>
                      <td>{rowError || (market?.status === "ready" ? market.source ?? "N/D" : market?.reason ?? "Caricamento…")}</td>
                      <td>{instant(market?.as_of)}</td>
                      <td>
                        <button className="secondary" type="button" onClick={() => onOpen(symbol)}>Grafico</button>{" "}
                        <button className="secondary" type="button" disabled={busy} onClick={() => void save(symbols.filter((s) => s !== symbol))}>
                          Rimuovi
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {symbols.length === 0 && <p className="notice">Watchlist vuota.</p>}
          <form className="inline-form" onSubmit={(e) => { e.preventDefault(); if (candidate) void save([...symbols, candidate]).then(() => setCandidate("")); }}>
            <label>
              Aggiungi strumento
              <select value={candidate} onChange={(e) => setCandidate(e.target.value)}>
                <option value="">Seleziona…</option>
                {available.map((i) => <option key={i.symbol} value={i.symbol}>{i.symbol} · {i.name}</option>)}
              </select>
            </label>
            <button className="primary" disabled={busy || !candidate || symbols.length >= 20}>Aggiungi</button>
          </form>
          <p className="notice">La variazione confronta le ultime due chiusure giornaliere disponibili; non è una quotazione in tempo reale.</p>
        </>
      )}
    </section>
  );
}
const connectionLabels: Record<string, string> = {
  local: "Ledger locale", connected: "Collegato (sola lettura)", disconnected: "Non collegato",
  unsupported: "Non supportato su questa piattaforma", busy: "Occupato (lettura broker in corso)",
};
function SystemPanel({ revision }: { revision: number }) {
  const [status, setStatus] = useState<SystemStatus | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api.system(controller.signal).then((value) => { setStatus(value); setError(""); }).catch((e) => {
      if (!controller.signal.aborted) { setStatus(null); setError(message(e)); }
    });
    return () => controller.abort();
  }, [revision]);
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Servizio locale</span>
          <h2>Stato sistema</h2>
        </div>
        <span className="badge muted">Invio ordini: disabilitato</span>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      {!status && !error && <p>Lettura stato…</p>}
      {status && (
        <>
          <div className="metrics">
            <Metric label="Versione servizio" value={null} caption={status.service_version} />
            <Metric label="Attivo da" value={status.uptime_seconds} unit="s" caption={`Avvio ${instant(status.started_at)}`} />
            <Metric label="Piattaforma" value={null} caption={`${status.platform} · Python ${status.python}`} />
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Contesto</th>
                  <th scope="col">Connessione</th>
                  <th scope="col">Ledger</th>
                  <th scope="col">Automazione</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(status.contexts).map(([name, c]) => (
                  <tr key={name}>
                    <th scope="row">{contexts[name as Context] ?? name}</th>
                    <td>{connectionLabels[c.connection] ?? c.connection}</td>
                    <td>{c.ledger === "present" ? "Presente" : c.ledger === "absent" ? "Non creato" : "Non applicabile"}</td>
                    <td>{c.automation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
export default function App() {
  const [page, setPage] = useState<Page>("Panoramica"),
    [context, setContext] = useState<Context>("demo"),
    [symbol, setSymbol] = useState("AAPL"),
    [interval, setIntervalValue] = useState("1Day");
  const [theme, setTheme] = useState<Preferences["theme"]>(() =>
      saved("aitb-theme", "light") === "dark" ? "dark" : "light",
    ),
    [density, setDensity] = useState<Preferences["density"]>(() =>
      saved("aitb-density", "comfortable") === "compact"
        ? "compact"
        : "comfortable",
    );
  const [analysisShare, setAnalysisShare] = useState(() => {
    const value = Number(saved("aitb-analysis-width", "68"));
    return Number.isInteger(value) && value >= 50 && value <= 75 ? value : 68;
  });
  const currentPreferences = useRef<Preferences>({theme, density, analysis_width:analysisShare});
  const preferencesLoaded = useRef(false),
    preferencesSaving = useRef(false), preferencesAlive = useRef(true),
    pendingPreferences = useRef<Preferences | null>(null);
  const [preferencesReady, setPreferencesReady] = useState(false);
  const [preferenceError, setPreferenceError] = useState<string | null>(null);
  useEffect(() => {
    preferencesAlive.current = true;
    return () => {preferencesAlive.current = false; pendingPreferences.current = null;};
  }, []);
  const changePreferences = (change: Partial<Preferences>) => {
    if (!preferencesReady) return;
    const next = {...currentPreferences.current, ...change};
    currentPreferences.current = next;
    setTheme(next.theme); setDensity(next.density); setAnalysisShare(next.analysis_width);
    pendingPreferences.current = next;
    const flush = async () => {
      if (preferencesSaving.current) return;
      preferencesSaving.current = true;
      try {
        while (pendingPreferences.current && preferencesAlive.current) {
          const values = pendingPreferences.current;
          pendingPreferences.current = null;
          try {
            await api.savePreferences(values);
            if (preferencesAlive.current) setPreferenceError(null);
          } catch {
            if (preferencesAlive.current) setPreferenceError("Preferenze non salvate nel servizio locale; modifica attiva solo in questa sessione.");
          }
        }
      } finally {preferencesSaving.current = false;}
    };
    void flush();
  };
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
    persist("aitb-analysis-width", String(analysisShare));
  }, [analysisShare]);
  useEffect(() => {
    const controller = new AbortController();
    let active = true, inFlight = false;
    async function load() {
      if (inFlight) return;
      inFlight = true;
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
        inFlight = false;
        return;
      }
      if (!preferencesLoaded.current) {
        preferencesLoaded.current = true;
        void api.preferences(controller.signal).then(values => {
          if (!active) {preferencesLoaded.current = false; return;}
          if (values) {
            currentPreferences.current = values;
            setTheme(values.theme); setDensity(values.density); setAnalysisShare(values.analysis_width);
          }
          setPreferenceError(null);
          setPreferencesReady(true);
        }).catch(() => {
          if (!active) {preferencesLoaded.current = false; return;}
          setPreferencesReady(true);
          setPreferenceError("Preferenze del servizio locale non disponibili; ricarica per riprovare.");
        });
      }
      const results = await Promise.allSettled([
        api.state(context, controller.signal),
        api.market(context, symbol, interval, controller.signal),
        api.proposal(context, symbol, interval, controller.signal),
        api.instruments(controller.signal),
      ]);
      inFlight = false;
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
  const automationLabel = state?.automation.state === "stopped" || state?.automation.state === "STOPPED" ? "Automazione ferma" : `Automazione ${state?.automation.state ?? "N/D"}`;
  const offline = context === "demo" || context === "simulation";
  const account = state?.account;
  const accountCurrency =
    typeof account?.currency === "string" && account.currency.trim()
      ? account.currency
      : offline
        ? "USD"
        : "valuta N/D";
  const priceCurrency = context === "mt5" ? "valuta strumento N/D" : "USD";
  const volumeUnit = context === "mt5" ? "tick" : "unità";
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
      {page !== "Backtesting" && (
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
      )}
    </div>
  );
  const chart = (
    <section className="panel market-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Analisi di mercato</span>
          <h2>
            {symbol} <small>/ {priceCurrency}</small>
          </h2>
        </div>
        {selectMarket}
      </div>
      <div className="quote-row">
        <strong>{number(market?.bars.at(-1)?.close, priceCurrency)}</strong>
        <span>Ultimo close storico</span>
        <span className="badge muted">{market?.source ?? "Fonte N/D"}</span>
      </div>
      <div className="quote-detail">
        <span>Bid {number(market?.quote?.bid, priceCurrency)}</span>
        <span>Ask {number(market?.quote?.ask, priceCurrency)}</span>
        <span>Quota: {instant(market?.quote?.timestamp)}</span>
        <span>Fonte quota: {text(market?.quote?.source)}</span>
      </div>
      {errors.market && <ErrorNote>{errors.market}</ErrorNote>}
      {market?.reason && <p className="notice">{market.reason}</p>}
      <MarketChart
        bars={market?.bars ?? []}
        indicators={market?.indicators}
        identity={`${context}/${symbol}/${interval}`}
        theme={theme}
        priceUnit={priceCurrency}
        volumeUnit={volumeUnit}
      />
      <p className="metadata">
        Acquisizione storico: {instant(market?.as_of)} · Qualità: {text(market?.metadata?.quality)}
        {" · "}Calendario: {text(market?.metadata?.bar_calendar)}
        {" · "}Contratto barre: {text(market?.metadata?.bar_time_contract)}.
        Le barre possono essere in formazione. Lo storico non è una quota corrente.
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
            {automationLabel}
          </div>
          <p>
            Modalità dry-run; nessun invio broker.
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
          {preferenceError && <ErrorNote>{preferenceError}</ErrorNote>}
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
                <Metric
                  label="Equity"
                  value={account?.equity}
                  unit={accountCurrency}
                />
                <Metric
                  label="Liquidità"
                  value={account?.cash}
                  unit={accountCurrency}
                />
                <Metric
                  label="Capitale iniziale"
                  value={account?.initial_cash}
                  unit={accountCurrency}
                  caption={
                    offline
                      ? "Fonte: ledger virtuale del contesto"
                      : "Solo se fornito dal conto verificato"
                  }
                />
                <Metric
                  label="P/L realizzato"
                  value={account?.realized_pnl}
                  unit={accountCurrency}
                />
              </div>
              <div className="metrics">
                <Metric label="P/L cumulativo netto stimato" value={account?.total_pnl} unit={accountCurrency} />
                <Metric label="P/L realizzato giornaliero" value={account?.daily_realized_pnl} unit={accountCurrency} caption={`Giorno ${text(account?.pnl_day)} · ${text(account?.pnl_timezone)} · ledger`} />
                <Metric label="Esposizione long" value={account?.market_value} unit={accountCurrency} caption="Valorizzazione mark del ledger; disponibile solo se fornita" />
                <Metric label="Commissioni sostenute" value={account?.fees} unit={accountCurrency} />
                <Metric label="Slippage sostenuto" value={account?.slippage} unit={accountCurrency} />
                <Metric label="Spread sostenuto" value={account?.spread} unit={accountCurrency} />
              </div>
              <div className="analysis-layout">
                <label>
                  Larghezza relativa del grafico
                  <input type="range" disabled={!preferencesReady} min="50" max="75" step="1" value={analysisShare}
                    onChange={event => {
                      const value = Number(event.target.value);
                      if (Number.isInteger(value) && value >= 50 && value <= 75) changePreferences({analysis_width:value});
                    }} />
                </label>
                <output>{analysisShare}%</output>
              </div>
              <section className="analysis-grid" aria-label="Analisi di mercato"
                style={{"--analysis-main": `${analysisShare}fr`, "--analysis-side": `${100-analysisShare}fr`} as CSSProperties}>
                {chart}
                <ProposalPanel proposal={proposal} error={errors.proposal} />
              </section>
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
                  columns={positionColumns(
                    priceCurrency,
                    accountCurrency,
                    context === "mt5",
                  )}
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
                <Metric
                  label="Equity"
                  value={account?.equity}
                  unit={accountCurrency}
                />
                <Metric
                  label="Liquidità"
                  value={account?.cash}
                  unit={accountCurrency}
                />
                <Metric
                  label="Buying power"
                  value={account?.buying_power}
                  unit={accountCurrency}
                />
                <Metric
                  label="P/L non realizzato"
                  value={account?.unrealized_pnl}
                  unit={accountCurrency}
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
                  columns={positionColumns(
                    priceCurrency,
                    accountCurrency,
                    context === "mt5",
                  )}
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
                  columns={orderColumns(priceCurrency, context === "mt5")}
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
                columns={tradeColumns(priceCurrency)}
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
              <WalkForwardPanel key={`wf/${context}/${symbol}`} context={context} symbol={symbol} />
            </>
          )}
          {page === "Automazione" && <Automation key={context} context={context} state={state} onChanged={refresh} />}
          {page === "Connessioni" && <Connections onChanged={refresh} />}
          {page === "Watchlist" && (
            <Watchlist
              context={context}
              instruments={instruments}
              onOpen={(next) => { clear(); setSymbol(next); setPage("Mercati"); }}
            />
          )}
          {page === "Stato sistema" && <SystemPanel revision={revision} />}
          {page === "Impostazioni" && (
            <section className="panel settings">
              <span className="eyebrow">Preferenze locali</span>
              <h2>Il tuo workspace</h2>
              <label>
                Tema
                <select
                  disabled={!preferencesReady}
                  value={theme}
                  onChange={(e) => {const value=e.target.value; if (value === "dark" || value === "light") changePreferences({theme:value});}}
                >
                  <option value="dark">Scuro</option>
                  <option value="light">Chiaro</option>
                </select>
              </label>
              <label>
                Densità del layout
                <select
                  disabled={!preferencesReady}
                  value={density}
                  onChange={(e) => {const value=e.target.value; if (value === "comfortable" || value === "compact") changePreferences({density:value});}}
                >
                  <option value="comfortable">Comoda</option>
                  <option value="compact">Compatta</option>
                </select>
              </label>
              <p>
                Le sole preferenze grafiche sono salvate dal servizio locale su questo dispositivo, anche se cambia la porta. Nessuna
                credenziale viene conservata qui.
              </p>
              <div className="notice">
                <b>{automationLabel}</b>
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
            <span>{contexts[context]} · {automationLabel}</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
const positionColumns = (
  priceCurrency: string,
  accountCurrency: string,
  mt5: boolean,
): [string, string][] => [
  ["symbol", "Strumento"],
  ["qty", mt5 ? "Volume · lotti" : "Quantità"],
  ["avg_entry_price", `Prezzo medio · ${priceCurrency}`],
  ["current_price", `Prezzo · ${priceCurrency}`],
  ["market_value", `Valore · ${accountCurrency}`],
  ["unrealized_pl", `P/L · ${accountCurrency}`],
];
const orderColumns = (
  priceCurrency: string,
  mt5: boolean,
): [string, string][] =>
  mt5
    ? [
        ["symbol", "Strumento"],
        ["type", "Tipo terminale (codice)"],
        ["volume_initial", "Volume iniziale · lotti"],
        ["volume_current", "Volume residuo · lotti"],
        ["state", "Stato terminale (codice)"],
        ["price_open", `Prezzo richiesto · ${priceCurrency}`],
      ]
    : [
        ["symbol", "Strumento"],
        ["side", "Lato"],
        ["qty", "Quantità"],
        ["filled_qty", "Eseguita"],
        ["status", "Stato"],
        ["filled_avg_price", `Prezzo fill · ${priceCurrency}`],
        ["submitted_at", "Invio · UTC"],
      ];
