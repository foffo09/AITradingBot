"""Version 1 transport DTOs. Provider records remain extensible, finite JSON."""
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, AfterValidator, model_validator

Context = Literal['demo', 'simulation', 'paper', 'mt5']
LocalContext = Literal['demo', 'simulation']
Interval = Literal['1Min', '5Min', '15Min', '1Hour', '1Day', '1Week']
Number = Annotated[float, Field(allow_inf_nan=False)]
Price = Annotated[Number, Field(gt=0)]
def _finite_record(value):
    # JsonValue accepts NaN and serializes it as null; do not hide invalid provider data.
    json.dumps(value, allow_nan=False)
    return value


Record = Annotated[dict[str, JsonValue], AfterValidator(_finite_record)]


class Output(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)


class Versioned(Output):
    api_version: Literal['1']


class ErrorResponse(Output):
    detail: str


class HealthResponse(Versioned):
    status: Literal['ready']


class IdentityResponse(Output):
    pid: Annotated[int, Field(gt=0)]
    instance_id: str


class ShutdownResponse(Versioned):
    status: Literal['stopping']


class Connection(Output):
    status: str
    reason: str | None = None


class Automation(Output):
    state: Literal['STOPPED', 'STARTING', 'RUNNING', 'PAUSING', 'PAUSED', 'STOPPING', 'ERROR', 'RECOVERY_REQUIRED']
    reason: str
    context: Context
    mode: Literal['dry-run']
    execution_enabled: Literal[False]
    last_start: str | None
    last_stop: str | None
    last_cycle: str | None
    last_error: str | None
    proposals: Annotated[int, Field(ge=0)]
    intents: Annotated[int, Field(ge=0)]
    reconciliation: Literal['not_required', 'required', 'verified_offline']


class StateResponse(Versioned):
    context: Context
    connection: Connection
    account: Record | None
    positions: list[Record]
    orders: list[Record]
    trades: list[Record]
    automation: Automation

    @model_validator(mode='after')
    def same_control_context(self):
        if self.automation.context != self.context:
            raise ValueError('Control context mismatch')
        return self


class TradeResponse(StateResponse):
    fill: Record


class Instrument(Output):
    symbol: str
    name: str


class InstrumentsResponse(Versioned):
    instruments: list[Instrument]


class Bar(Output):
    time: Annotated[int, Field(gt=0)]
    open: Price
    high: Price
    low: Price
    close: Price
    volume: Annotated[Number, Field(ge=0)]

    @model_validator(mode='after')
    def consistent_prices(self):
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError('Inconsistent bar')
        return self


class Quote(Output):
    bid: Price
    ask: Price
    price: Price
    timestamp: str
    source: str

    @model_validator(mode='after')
    def ordered_spread(self):
        if self.bid > self.ask:
            raise ValueError('Crossed quote')
        return self


class Point(Output):
    time: Annotated[int, Field(gt=0)]
    value: Number | None


class Indicator(Output):
    id: str
    label: str
    pane: Literal['price', 'rsi']
    unit: str
    method: str
    parameters: Record
    points: list[Point]


class MarketResponse(Versioned):
    context: Context
    symbol: str
    interval: Interval
    status: str
    reason: str
    source: str | None
    as_of: str | None
    bars: list[Bar]
    quote: Quote | None
    metadata: Record
    indicators: list[Indicator]


class Sample(Output):
    start: str
    end: str
    bars: Annotated[int, Field(gt=0)]


class BacktestValidation(Output):
    kind: Literal['single_sample']
    out_of_sample: None


class EquityPoint(Point):
    value: Number


class BacktestResponse(Versioned):
    context: Context
    symbol: str
    source: str
    strategy: Literal['sma']
    parameters: dict[str, int]
    interval: Literal['1Day']
    sample: Sample
    validation: BacktestValidation
    metrics: Record
    trades: list[Record]
    equity: list[EquityPoint]


class ProposalResponse(Versioned):
    model_config = ConfigDict(extra='ignore')
    contract_version: Literal['1']
    context: Context
    symbol: str
    interval: Interval
    direction: Literal['BUY', 'SELL', 'WAIT', 'NO_TRADE']
    validation_state: Literal['NO_TRADE', 'PAPER_PROPOSAL']
    reason: str
    signal_id: str | None
    timestamp: str | None
    expires_at: str | None
    reference_price: Number | None
    entry: Number | None
    entry_type: str | None
    stop_loss: Number | None
    take_profit: Number | None
    stop_distance: Number | None
    target_distance: Number | None
    reward_risk: Number | None
    net_reward_risk: Number | None
    quantity: Number | None
    risk_amount: Number | None
    quality: str
    invalidation_conditions: list[str]
    provenance: Record
    indicators: Record


    @model_validator(mode='after')
    def complete_paper_proposal(self):
        if self.direction not in {'BUY', 'SELL'} and self.validation_state != 'PAPER_PROPOSAL':
            return self
        if self.context != 'paper' or self.direction not in {'BUY', 'SELL'} or self.validation_state != 'PAPER_PROPOSAL':
            raise ValueError('Operational proposal context or state is invalid')
        if not self.signal_id or not self.signal_id.strip() or not self.entry_type:
            raise ValueError('Proposal identity and entry type are required')
        times = [datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None
                 for value in (self.timestamp, self.expires_at)]
        if any(value is None or value.tzinfo is None or value.utcoffset() is None for value in times) or times[1] <= times[0]:
            raise ValueError('Proposal timezone-aware lifetime is required')
        if any(getattr(self, key) is None or getattr(self, key) <= 0 for key in
               ('reference_price', 'entry', 'stop_loss', 'take_profit', 'stop_distance',
                'target_distance', 'reward_risk', 'net_reward_risk', 'quantity', 'risk_amount')):
            raise ValueError('Complete positive proposal values are required')
        return self


class Preferences(Output):
    theme: Literal['dark', 'light']
    density: Literal['comfortable', 'compact']
    analysis_width: Annotated[int, Field(ge=50, le=75)]


class PreferencesResponse(Versioned):
    preferences: Preferences
    stored: bool


class WalkForwardWindow(Output):
    train_start: str
    train_end: str
    test_start: str
    test_end: str


class WalkForwardFoldOut(WalkForwardWindow):
    parameters: dict[str, int]
    in_sample_return_pct: Number
    in_sample_trades: Annotated[int, Field(ge=0)]
    out_of_sample: Record


class WalkForwardExcluded(WalkForwardWindow):
    reason: str


class WalkForwardResponse(Versioned):
    context: Context
    symbol: str
    source: str
    strategy: Literal['sma']
    interval: Literal['1Day']
    sample: Sample
    candidates: list[dict[str, int]]
    selection_metric: str
    training_bars: Annotated[int, Field(gt=0)]
    test_bars: Annotated[int, Field(gt=0)]
    step_bars: Annotated[int, Field(gt=0)]
    folds: list[WalkForwardFoldOut]
    excluded: list[WalkForwardExcluded]


class ContextStatus(Output):
    connection: Literal['local', 'connected', 'disconnected', 'unsupported', 'unavailable', 'busy']
    ledger: Literal['present', 'absent', 'not_applicable']
    automation: str


class SystemResponse(Versioned):
    status: Literal['ready']
    service_version: str
    python: str
    platform: str
    started_at: str
    uptime_seconds: Annotated[float, Field(ge=0)]
    order_submission: Literal['disabled']
    contexts: dict[str, ContextStatus]


class WatchlistBody(Output):
    symbols: Annotated[list[str], Field(max_length=20)]


class WatchlistResponse(Versioned):
    symbols: list[str]
    stored: bool


class PendingTradeResponse(Versioned):
    context: LocalContext
    pending: Record | None
