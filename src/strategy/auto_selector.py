from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from numbers import Integral
from typing import Literal

import pandas as pd

from config.settings import AppSettings
from src.backtesting.engine import BacktestEngine
from src.backtesting.walk_forward import walk_forward_evaluate
from src.data.bar_timing import bar_timing
from src.data.instruments import INSTRUMENTS
from src.risk.risk_manager import RiskManager, RiskViolationError
from src.strategy.moving_average import MovingAverageStrategy


STRATEGY_NAME = "moving_average"
SUPPORTED_INTERVALS: dict[str, tuple[int, int]] = {
    "1Min": (60, 600),
    "5Min": (300, 1_200),
    "15Min": (900, 2_700),
    "1Hour": (3_600, 10_800),
    "1Day": (86_400, 345_600),
    "1Week": (604_800, 864_000),
}
_WALK_FORWARD_CACHE_TTL_SECONDS = 24 * 60 * 60
_WALK_FORWARD_CACHE_MAX_ENTRIES = 64
_WALK_FORWARD_CACHE: OrderedDict[str, tuple[float, object]] = OrderedDict()
_WALK_FORWARD_CACHE_LOCK = threading.RLock()


def _cached_walk_forward(
    data: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    candidates: Sequence[Mapping[str, int]],
    training_bars: int,
    test_bars: int,
    settings: AppSettings,
    backtest_options: Mapping[str, object],
) -> object:
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    fingerprint = hashlib.sha256(
        pd.util.hash_pandas_object(data[columns], index=False).values.tobytes()
    ).hexdigest()
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "symbol": symbol,
                "interval": interval,
                "fingerprint": fingerprint,
                "candidates": list(candidates),
                "training_bars": training_bars,
                "test_bars": test_bars,
                "backtest_options": dict(backtest_options),
            },
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    now = time.monotonic()
    with _WALK_FORWARD_CACHE_LOCK:
        cached = _WALK_FORWARD_CACHE.pop(cache_key, None)
        if cached is not None and now - cached[0] < _WALK_FORWARD_CACHE_TTL_SECONDS:
            _WALK_FORWARD_CACHE[cache_key] = cached
            return cached[1]

    result = walk_forward_evaluate(
        data,
        engine=BacktestEngine(settings),
        parameter_candidates=candidates,
        training_bars=training_bars,
        test_bars=test_bars,
        step_bars=test_bars,
        data_source=f"{symbol} real historical",
        backtest_options=dict(backtest_options),
    )
    with _WALK_FORWARD_CACHE_LOCK:
        _WALK_FORWARD_CACHE[cache_key] = (now, result)
        while len(_WALK_FORWARD_CACHE) > _WALK_FORWARD_CACHE_MAX_ENTRIES:
            _WALK_FORWARD_CACHE.popitem(last=False)
    return result


@dataclass(frozen=True)
class SelectionCriteria:
    """Minimum out-of-sample evidence required before proposing an action."""

    min_validation_folds: int = 2
    min_oos_trades: int = 3
    min_mean_oos_return_pct: float = 0.0
    max_oos_drawdown_pct: float = 20.0

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, Integral) or value <= 0
            for value in (self.min_validation_folds, self.min_oos_trades)
        ):
            raise ValueError("Minimum validation folds and trades must be positive integers.")
        if not math.isfinite(self.min_mean_oos_return_pct):
            raise ValueError("Minimum OOS return must be finite.")
        if (
            not math.isfinite(self.max_oos_drawdown_pct)
            or not 0 <= self.max_oos_drawdown_pct <= 100
        ):
            raise ValueError("Maximum OOS drawdown must be between 0 and 100 percent.")


@dataclass(frozen=True)
class CandidateEvaluation:
    asset: str
    strategy: str
    parameters: dict[str, int]
    validation_folds: int
    oos_trades: int
    mean_oos_return_pct: float
    mean_oos_drawdown_pct: float
    max_oos_drawdown_pct: float
    mean_oos_win_rate_pct: float | None
    latest_training_return_pct: float | None


@dataclass(frozen=True)
class AutoSelectionResult:
    status: Literal["SELECTED", "NO_TRADE"]
    asset: str | None
    strategy: str | None
    parameters: dict[str, int] | None
    side: Literal["buy", "sell"] | None
    proposed_quantity: float | None
    reason: str
    evaluations: tuple[CandidateEvaluation, ...] = field(default_factory=tuple)
    exclusions: tuple[str, ...] = field(default_factory=tuple)


def _validated_candidates(
    candidates: Sequence[Mapping[str, object]],
) -> list[dict[str, int]]:
    if not candidates:
        raise ValueError("At least one moving-average candidate is required.")
    validated: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for candidate in candidates:
        if set(candidate) != {"short_window", "long_window"}:
            raise ValueError(
                "Only the existing moving-average short_window and long_window "
                "parameters are supported."
            )
        short_window, long_window = candidate["short_window"], candidate["long_window"]
        if any(
            isinstance(value, bool) or not isinstance(value, Integral) or value <= 0
            for value in (short_window, long_window)
        ):
            raise ValueError("Moving-average windows must be positive integers.")
        short_window, long_window = int(short_window), int(long_window)
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window.")
        pair = (short_window, long_window)
        if pair not in seen:
            MovingAverageStrategy(*pair)
            validated.append({"short_window": short_window, "long_window": long_window})
            seen.add(pair)
    return validated


def _utc_now(value: datetime | pd.Timestamp | None) -> pd.Timestamp:
    now = pd.Timestamp.now(tz="UTC") if value is None else pd.Timestamp(value)
    if now.tzinfo is None:
        raise ValueError("as_of must include a timezone.")
    return now.tz_convert("UTC")


def _fresh_completed_bars(
    symbol: str,
    data: pd.DataFrame,
    *,
    interval: str,
    as_of: pd.Timestamp,
) -> tuple[pd.DataFrame | None, str | None]:
    if symbol not in INSTRUMENTS:
        return None, f"{symbol}: asset non presente nel catalogo supportato."
    if not isinstance(data, pd.DataFrame) or data.empty:
        return None, f"{symbol}: dati assenti."
    if data.attrs.get("quality") != "real":
        return None, f"{symbol}: richiesti dati storici reali; dati sintetici esclusi."
    data_interval = data.attrs.get("interval")
    if data_interval is not None and data_interval != interval:
        return None, f"{symbol}: intervallo dati diverso dall'intervallo richiesto."
    if interval not in SUPPORTED_INTERVALS:
        return None, f"{symbol}: intervallo non supportato."
    if "timestamp" not in data.columns:
        return None, f"{symbol}: timestamp delle barre assente."

    timestamps = pd.to_datetime(data["timestamp"], utc=True, errors="coerce")
    if (
        timestamps.isna().any()
        or not timestamps.is_monotonic_increasing
        or timestamps.duplicated().any()
    ):
        return None, f"{symbol}: timestamp non validi, duplicati o fuori ordine."

    latest_age = (as_of - timestamps.iloc[-1]).total_seconds()
    minimum_age, maximum_age = SUPPORTED_INTERVALS[interval]

    if latest_age < 0:
        return None, f"{symbol}: timestamp dell'ultima barra nel futuro."

    completed = data.copy()
    completed["timestamp"] = timestamps

    while not completed.empty:
        is_forming, timestamp_age, _ = bar_timing(
            symbol,
            interval,
            completed["timestamp"].iloc[-1],
            as_of,
            minimum_age,
        )
        if timestamp_age < 0:
            return None, f"{symbol}: timestamp dell'ultima barra nel futuro."
        if not is_forming:
            break
        completed = completed.iloc[:-1].copy()

    if completed.empty:
        return None, f"{symbol}: nessuna barra completata disponibile."

    completed_forming, completed_timestamp_age, completed_age = bar_timing(
        symbol,
        interval,
        completed["timestamp"].iloc[-1],
        as_of,
        minimum_age,
    )

    if (
        completed_forming
        or completed_timestamp_age < -120
        or completed_age < -120
        or completed_age > maximum_age
    ):
        return None, f"{symbol}: dati obsoleti."

    completed.attrs.update(data.attrs)
    completed.attrs["interval"] = interval
    return completed, None


def _no_trade(
    reason: str,
    *,
    evaluations: Sequence[CandidateEvaluation] = (),
    exclusions: Sequence[str] = (),
    asset: str | None = None,
    parameters: dict[str, int] | None = None,
) -> AutoSelectionResult:
    return AutoSelectionResult(
        status="NO_TRADE",
        asset=asset,
        strategy=STRATEGY_NAME if asset is not None else None,
        parameters=parameters,
        side=None,
        proposed_quantity=None,
        reason=reason,
        evaluations=tuple(evaluations),
        exclusions=tuple(exclusions),
    )


def select_strategy(
    asset_data: Mapping[str, pd.DataFrame],
    *,
    asset_availability: Mapping[str, bool],
    interval: str,
    parameter_candidates: Sequence[Mapping[str, object]],
    training_bars: int,
    test_bars: int,
    settings: AppSettings,
    available_cash: float,
    current_positions: Mapping[str, float] | None = None,
    pnl_today: float = 0.0,
    criteria: SelectionCriteria | None = None,
    as_of: datetime | pd.Timestamp | None = None,
) -> AutoSelectionResult:
    """Choose an MA parameter set from walk-forward evidence and check its current signal.

    This function performs no broker or ledger I/O. Data must be explicitly marked
    real and tradable by the caller; order size is only a risk-checked proposal.
    """
    candidates = _validated_candidates(parameter_candidates)
    if interval not in SUPPORTED_INTERVALS:
        raise ValueError(f"Unsupported market-data interval: {interval}")
    if any(
        isinstance(value, bool) or not isinstance(value, Integral) or value <= 0
        for value in (training_bars, test_bars)
    ):
        raise ValueError("Training and test bar counts must be positive integers.")
    if not math.isfinite(float(available_cash)) or available_cash < 0:
        raise ValueError("Available cash must be a finite non-negative number.")
    if not math.isfinite(float(pnl_today)):
        raise ValueError("Today's P/L must be finite.")
    active_criteria = criteria or SelectionCriteria()
    decision_time = _utc_now(as_of)
    if settings.trading_mode not in {"demo", "paper"}:
        return _no_trade("La selezione è disponibile solo in modalità Demo o Alpaca Paper.")
    positions = {
        str(symbol).strip().upper(): float(quantity)
        for symbol, quantity in (current_positions or {}).items()
    }
    if any(not math.isfinite(quantity) or quantity < 0 for quantity in positions.values()):
        raise ValueError("Current long positions must be finite and non-negative.")

    supported_symbols = set(INSTRUMENTS)
    excluded: list[str] = []
    evaluations: list[CandidateEvaluation] = []
    latest_training_returns: dict[str, float] = {}
    latest_training_parameters: dict[str, tuple[int, int]] = {}
    minimum_candidate_bars = max(
        candidate["long_window"] for candidate in candidates
    ) + 2
    if training_bars < minimum_candidate_bars or test_bars < minimum_candidate_bars:
        raise ValueError(
            f"Training and test windows must each contain at least "
            f"{minimum_candidate_bars} bars for the candidate moving averages."
        )
    prepared_data: dict[str, pd.DataFrame] = {}

    for raw_symbol, data in asset_data.items():
        symbol = str(raw_symbol).strip().upper()
        if symbol not in supported_symbols:
            excluded.append(f"{symbol}: asset non presente nel catalogo supportato.")
            continue
        if asset_availability.get(symbol) is not True:
            excluded.append(f"{symbol}: negoziabilità non verificata.")
            continue
        completed, exclusion = _fresh_completed_bars(
            symbol, data, interval=interval, as_of=decision_time
        )
        if completed is None:
            excluded.append(exclusion or f"{symbol}: dati non validi.")
            continue
        if len(completed) < training_bars + test_bars:
            excluded.append(
                f"{symbol}: dati insufficienti per almeno un fold walk-forward "
                f"({len(completed)} barre disponibili, {training_bars + test_bars} richieste)."
            )
            continue
        prepared_data[symbol] = completed
        try:
            walk_forward = _cached_walk_forward(
                completed,
                symbol=symbol,
                interval=interval,
                candidates=candidates,
                training_bars=training_bars,
                test_bars=test_bars,
                settings=settings,
                backtest_options={
                    "initial_capital": settings.initial_capital_usd,
                    "max_trade_fraction": settings.risk_max_trade_fraction,
                    "daily_loss_limit_fraction": settings.daily_loss_limit_pct,
                    "commission_bps": settings.commission_bps,
                    "spread_bps": settings.spread_bps,
                    "slippage_bps": settings.slippage_bps,
                    "periods_per_year": BacktestEngine.periods_per_year_for_interval(
                        interval, crypto=INSTRUMENTS[symbol]["kind"] == "crypto"
                    ),
                    "risk_free_rate_annual": 0.0,
                },
            )
        except ValueError as exc:
            excluded.append(f"{symbol}: walk-forward non disponibile ({exc}).")
            continue
        if not walk_forward.folds:
            excluded.append(f"{symbol}: nessun fold walk-forward valido.")
            continue

        latest_fold = walk_forward.folds[-1]
        latest_parameters = (
            int(latest_fold.selected_parameters["short_window"]),
            int(latest_fold.selected_parameters["long_window"]),
        )
        latest_training_parameters[symbol] = latest_parameters
        latest_training_returns[symbol] = float(latest_fold.in_sample_return_pct)

        by_parameters: dict[tuple[int, int], list[object]] = {}
        for fold in walk_forward.folds:
            key = (
                int(fold.selected_parameters["short_window"]),
                int(fold.selected_parameters["long_window"]),
            )
            by_parameters.setdefault(key, []).append(fold.out_of_sample)

        for parameters in candidates:
            pair = (parameters["short_window"], parameters["long_window"])
            fold_results = by_parameters.get(pair, [])
            if not fold_results:
                continue
            trade_count = sum(int(result.total_trades) for result in fold_results)
            win_rates = [
                (float(result.win_rate), int(result.total_trades))
                for result in fold_results
                if result.win_rate is not None and int(result.total_trades) > 0
            ]
            mean_win_rate = (
                sum(rate * trades for rate, trades in win_rates)
                / sum(trades for _, trades in win_rates)
                if win_rates else None
            )
            evaluation = CandidateEvaluation(
                asset=symbol,
                strategy=STRATEGY_NAME,
                parameters=dict(parameters),
                validation_folds=len(fold_results),
                oos_trades=trade_count,
                mean_oos_return_pct=sum(
                    float(result.return_pct) for result in fold_results
                ) / len(fold_results),
                mean_oos_drawdown_pct=sum(
                    float(result.max_drawdown_pct) for result in fold_results
                ) / len(fold_results),
                max_oos_drawdown_pct=max(
                    float(result.max_drawdown_pct) for result in fold_results
                ),
                mean_oos_win_rate_pct=mean_win_rate,
                latest_training_return_pct=(
                    float(latest_fold.in_sample_return_pct)
                    if pair == latest_parameters else None
                ),
            )
            evaluations.append(evaluation)

    eligible = [
        evaluation
        for evaluation in evaluations
        if (
            latest_training_parameters.get(evaluation.asset)
            == (
            evaluation.parameters["short_window"],
            evaluation.parameters["long_window"],
        )
            and evaluation.validation_folds >= active_criteria.min_validation_folds
            and evaluation.oos_trades >= active_criteria.min_oos_trades
            and evaluation.mean_oos_return_pct > active_criteria.min_mean_oos_return_pct
            and evaluation.max_oos_drawdown_pct
            <= active_criteria.max_oos_drawdown_pct
        )
    ]
    if not eligible:
        return _no_trade(
            "Nessun candidato ha superato le soglie OOS per fold, operazioni, rendimento e drawdown.",
            evaluations=evaluations,
            exclusions=excluded,
        )

    selected = max(
        eligible,
        key=lambda candidate: (
            latest_training_returns[candidate.asset],
            candidate.asset,
        ),
    )
    fresh_data = prepared_data[selected.asset]
    signal = MovingAverageStrategy(**selected.parameters).current_signal(fresh_data)
    if signal["signal"] not in {-1, 1}:
        return _no_trade(
            f"Strategia OOS selezionata; nessun incrocio operativo: {signal['reason']}.",
            evaluations=evaluations,
            exclusions=excluded,
            asset=selected.asset,
            parameters=selected.parameters,
        )

    price = float(fresh_data["close"].iloc[-1])
    risk_manager = RiskManager(settings)
    side: Literal["buy", "sell"] = "buy" if signal["signal"] == 1 else "sell"
    try:
        if side == "buy":
            quantity = risk_manager.calculate_position_size(
                float(available_cash), price
            )
        else:
            quantity = positions.get(selected.asset, 0.0)
            if quantity <= 0:
                return _no_trade(
                    "Segnale di uscita senza una posizione long disponibile.",
                    evaluations=evaluations,
                    exclusions=excluded,
                    asset=selected.asset,
                    parameters=selected.parameters,
                )
        validation = risk_manager.validate_order(
            side=side,
            quantity=quantity,
            price=price,
            available_cash=float(available_cash),
            current_position=positions.get(selected.asset, 0.0),
            symbol=selected.asset,
            pnl_today=float(pnl_today),
        )
    except RiskViolationError as exc:
        return _no_trade(
            f"Quantità non proposta: il risk manager ha bloccato la valutazione ({exc}).",
            evaluations=evaluations,
            exclusions=excluded,
            asset=selected.asset,
            parameters=selected.parameters,
        )
    if not validation.ok:
        return _no_trade(
            f"Quantità non proposta: {validation.reason}",
            evaluations=evaluations,
            exclusions=excluded,
            asset=selected.asset,
            parameters=selected.parameters,
        )

    return AutoSelectionResult(
        status="SELECTED",
        asset=selected.asset,
        strategy=STRATEGY_NAME,
        parameters=dict(selected.parameters),
        side=side,
        proposed_quantity=validation.quantity,
        reason=(
            f"{side.upper()} {selected.asset}: parametri scelti dal training dell'ultimo "
            f"fold walk-forward e validati su "
            f"{selected.validation_folds} fold e {selected.oos_trades} operazioni; "
            f"rendimento training finale "
            f"{selected.latest_training_return_pct:+.2f}%, "
            f"rendimento medio netto {selected.mean_oos_return_pct:+.2f}%, "
            f"drawdown OOS massimo {selected.max_oos_drawdown_pct:.2f}%. "
            f"Segnale: {signal['reason']}. Quantità proposta verificata dal risk manager."
        ),
        evaluations=tuple(evaluations),
        exclusions=tuple(excluded),
    )
