from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral

import numpy as np
import pandas as pd

from src.backtesting.engine import BacktestEngine, BacktestResult, BacktestStrategy
from src.strategy.levels import LevelConfig


@dataclass
class WalkForwardFold:
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    selected_parameters: dict[str, int]
    in_sample_return_pct: float
    in_sample_trades: int
    in_sample_result: BacktestResult
    out_of_sample: BacktestResult


@dataclass
class WalkForwardExclusion:
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    reason: str


@dataclass
class WalkForwardResult:
    data_source: str
    selection_metric: str
    training_bars: int
    test_bars: int
    step_bars: int
    folds: list[WalkForwardFold]
    excluded_folds: list[WalkForwardExclusion]


def _validate_windows(parameters: Mapping[str, object]) -> dict[str, int]:
    if set(parameters) != {"short_window", "long_window"}:
        raise ValueError("Each parameter candidate must define short_window and long_window only.")
    validated: dict[str, int] = {}
    for name in ("short_window", "long_window"):
        value = parameters[name]
        if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
            raise ValueError(f"{name} must be a positive integer.")
        validated[name] = int(value)
    if validated["short_window"] >= validated["long_window"]:
        raise ValueError("short_window must be smaller than long_window.")
    return validated


def walk_forward_evaluate(
    data: pd.DataFrame,
    *,
    engine: BacktestEngine,
    parameter_candidates: Sequence[Mapping[str, object]],
    training_bars: int,
    test_bars: int,
    step_bars: int | None = None,
    data_source: str,
    backtest_options: Mapping[str, object] | None = None,
) -> WalkForwardResult:
    """Select MA windows on chronological training slices, then test each on later bars.

    Test folds are disjoint. Each fold's indicators are initialized from that test
    slice alone, so training prices cannot generate test-period signals. Its initial
    moving-average warm-up is consequently not tradable.
    """
    if not isinstance(data, pd.DataFrame) or data.empty:
        raise ValueError("Walk-forward data must be a non-empty dataframe.")
    if not isinstance(data_source, str) or not data_source.strip():
        raise ValueError("A non-empty data source label is required.")
    for name, value in (("training_bars", training_bars), ("test_bars", test_bars)):
        if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
            raise ValueError(f"{name} must be a positive integer.")
    training_bars, test_bars = int(training_bars), int(test_bars)
    if step_bars is None:
        step_bars = test_bars
    if isinstance(step_bars, bool) or not isinstance(step_bars, Integral) or step_bars <= 0:
        raise ValueError("step_bars must be a positive integer.")
    step_bars = int(step_bars)
    if step_bars < test_bars:
        raise ValueError("step_bars must be at least test_bars so test folds do not overlap.")
    if "open" not in data.columns or "close" not in data.columns:
        raise ValueError("Walk-forward data must contain open and close prices.")
    prices = data[["open", "close"]].apply(pd.to_numeric, errors="coerce")
    if (
        prices.isna().any().any()
        or not np.isfinite(prices.to_numpy(dtype=float)).all()
        or (prices <= 0).any().any()
    ):
        raise ValueError("Walk-forward prices must be present, finite, and positive.")
    if data.index.has_duplicates or not data.index.is_monotonic_increasing:
        raise ValueError("Walk-forward rows must have a strictly increasing, unique index.")

    frame = data.copy()
    frame[["open", "close"]] = prices
    if "timestamp" in frame.columns:
        timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        if (
            timestamps.isna().any()
            or not timestamps.is_monotonic_increasing
            or timestamps.duplicated().any()
        ):
            raise ValueError(
                "Walk-forward timestamps must be valid, strictly increasing, and unique."
            )

    candidates = [_validate_windows(candidate) for candidate in parameter_candidates]
    if not candidates:
        raise ValueError("At least one moving-average parameter candidate is required.")
    minimum_bars = max(candidate["long_window"] for candidate in candidates) + 2
    if training_bars < minimum_bars or test_bars < minimum_bars:
        raise ValueError(
            f"Training and test windows must each contain at least {minimum_bars} bars "
            "for the candidate moving averages."
        )

    options = dict(backtest_options or {})
    if {"short_window", "long_window"} & options.keys():
        raise ValueError("Moving-average windows must be provided as parameter candidates.")
    folds: list[WalkForwardFold] = []
    excluded_folds: list[WalkForwardExclusion] = []
    train_start = 0
    while train_start + training_bars + test_bars <= len(frame):
        train_end = train_start + training_bars
        test_start = train_end
        test_end = test_start + test_bars
        training_slice = frame.iloc[train_start:train_end]
        test_slice = frame.iloc[test_start:test_end]

        best_parameters: dict[str, int] | None = None
        best_training_result: BacktestResult | None = None
        try:
            for candidate in candidates:
                result = engine.run(training_slice, **options, **candidate)
                if (
                    best_training_result is None
                    or result.return_pct > best_training_result.return_pct
                ):
                    best_parameters = candidate
                    best_training_result = result

            if best_parameters is None or best_training_result is None:
                raise ValueError("Training did not produce a valid parameter candidate.")
            out_of_sample = engine.run(test_slice, **options, **best_parameters)
        except ValueError as exc:
            excluded_folds.append(WalkForwardExclusion(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                reason=str(exc),
            ))
            train_start += step_bars
            continue

        folds.append(WalkForwardFold(
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            selected_parameters=dict(best_parameters),
            in_sample_return_pct=best_training_result.return_pct,
            in_sample_trades=best_training_result.total_trades,
            in_sample_result=best_training_result,
            out_of_sample=out_of_sample,
        ))
        train_start += step_bars

    if not folds and not excluded_folds:
        raise ValueError(
            "Insufficient data for one complete chronological training/test fold."
        )

    return WalkForwardResult(
        data_source=data_source.strip(),
        selection_metric="training net return after modeled costs",
        training_bars=training_bars,
        test_bars=test_bars,
        step_bars=step_bars,
        folds=folds,
        excluded_folds=excluded_folds,
    )


def evaluate_strategy_partitions(
    data: pd.DataFrame,
    *,
    engine: BacktestEngine,
    strategy: BacktestStrategy,
    training_bars: int,
    validation_bars: int,
    as_of: object,
    data_source: str,
    protection: LevelConfig | None = None,
    backtest_options: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Evaluate one fixed causal strategy on three independent historical slices.

    The caller's feed attests each timezone-aware ``closed_at``; completion is
    never inferred from a bar-start timestamp or operational freshness rules.
    Indicators and capital restart within each partition. There is no fitting,
    parameter selection, shared warm-up or claim of operational eligibility.
    The supplied strategy must be stateless across generate_signals calls.
    """
    from src.data.bar_timing import utc_timestamp

    if not isinstance(data, pd.DataFrame) or data.empty:
        raise ValueError("Partition data must be a non-empty dataframe.")
    if not isinstance(data_source, str) or not data_source.strip():
        raise ValueError("A non-empty data source label is required.")
    for name, value in (("training_bars", training_bars), ("validation_bars", validation_bars)):
        if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
            raise ValueError(f"{name} must be a positive integer.")
    if not {"timestamp", "closed_at"}.issubset(data.columns):
        raise ValueError("Partition data requires timestamp and closed_at columns.")
    cutoff = utc_timestamp(as_of, "Partition reference time")
    timestamps = pd.DatetimeIndex([utc_timestamp(value, "Bar timestamp") for value in data["timestamp"]])
    closes = pd.DatetimeIndex([utc_timestamp(value, "Bar closed_at") for value in data["closed_at"]])
    if any(values.has_duplicates or not values.is_monotonic_increasing for values in (timestamps, closes)):
        raise ValueError("Partition timestamps and closed_at must be strictly increasing and unique.")
    if (closes <= timestamps).any():
        raise ValueError("Each closed_at must be after its bar timestamp.")
    if (closes[:-1] > timestamps[1:]).any():
        raise ValueError("Historical bar intervals must not overlap.")
    frame = data.loc[closes <= cutoff].copy()
    options = dict(backtest_options or {})
    if {"strategy", "protection"} & options.keys():
        raise ValueError("Strategy and protection must be supplied explicitly.")
    long_window = options.get("long_window")
    if long_window is None:
        long_window = getattr(strategy, "long_window", engine.settings.long_window)
    if isinstance(long_window, bool) or not isinstance(long_window, Integral) or long_window < 1:
        raise ValueError("Strategy long_window must be a positive integer.")
    warmup = getattr(strategy, "warmup_bars", long_window + 1)
    if isinstance(warmup, bool) or not isinstance(warmup, Integral) or warmup < 1:
        raise ValueError("Strategy warmup_bars must be a positive integer.")
    minimum_bars = max(2, int(warmup) + 1)
    bounds = (
        ("training", 0, int(training_bars)),
        ("validation", int(training_bars), int(training_bars + validation_bars)),
        ("out_of_sample", int(training_bars + validation_bars), len(frame)),
    )
    if any(end - start < minimum_bars for _, start, end in bounds):
        raise ValueError(f"Each completed partition needs at least {minimum_bars} bars, including warm-up.")
    results: dict[str, object] = {
        "data_source": data_source.strip(),
        "as_of": cutoff.isoformat(),
        "excluded_incomplete_bars": len(data) - len(frame),
    }
    for name, start, end in bounds:
        partition = frame.iloc[start:end].copy()
        result = engine.run(partition, strategy=strategy, protection=protection, **options)
        results[name] = {
            "start": start,
            "end": end,
            "bars": len(partition),
            "start_timestamp": utc_timestamp(partition.iloc[0]["timestamp"], "Bar timestamp").isoformat(),
            "end_timestamp": utc_timestamp(partition.iloc[-1]["timestamp"], "Bar timestamp").isoformat(),
            "last_closed_at": utc_timestamp(partition.iloc[-1]["closed_at"], "Bar closed_at").isoformat(),
            "metrics": result.to_dict(),
        }
    return results
