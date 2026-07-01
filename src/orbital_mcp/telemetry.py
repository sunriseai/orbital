from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MODEL_KEYS = ("model", "model_id", "modelId", "model_name", "modelName")
USAGE_KEYS = ("usage", "tokenUsage", "token_usage", "modelUsage")


@dataclass
class ModelTelemetryRecord:
    source: str
    model: str
    event_id: str | None = None


@dataclass
class ModelTelemetry:
    known: bool
    source: str
    model: str | None = None
    models: list[str] = field(default_factory=list)
    records: list[ModelTelemetryRecord] = field(default_factory=list)


@dataclass
class TokenUsageRecord:
    source: str
    input: int | None = None
    output: int | None = None
    cache: int | None = None
    total: int | None = None
    event_id: str | None = None


@dataclass
class TokenUsage:
    known: bool
    source: str
    input: int | None = None
    output: int | None = None
    cache: int | None = None
    total: int | None = None
    records: list[TokenUsageRecord] = field(default_factory=list)


@dataclass
class PrimaryTokenUsageRecord:
    timestamp: str
    source: str
    scope: str | None = None
    run_id: str | None = None
    model: str | None = None
    input: int | None = None
    output: int | None = None
    cache: int | None = None
    total: int | None = None
    notes: str | None = None


@dataclass
class RunTelemetry:
    tokens: TokenUsage
    model: ModelTelemetry


def extract_run_telemetry(run_dir: Path, events: list[dict[str, Any]]) -> RunTelemetry:
    token_records: list[TokenUsageRecord] = []
    model_records: list[ModelTelemetryRecord] = []
    for event in events:
        event_id = str(event.get("event_id")) if event.get("event_id") else None
        token_records.extend(_token_records_from_value(event.get("raw"), source="dialogue.raw", event_id=event_id))
        model_records.extend(_model_records_from_value(event.get("raw"), source="dialogue.raw", event_id=event_id))

    transcript = run_dir / "transcript.log"
    if transcript.exists():
        for line in transcript.read_text(encoding="utf-8").splitlines():
            payload = line[2:] if line.startswith(("< ", "> ")) else line
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                continue
            token_records.extend(_token_records_from_value(value, source="transcript", event_id=None))
            model_records.extend(_model_records_from_value(value, source="transcript", event_id=None))

    return RunTelemetry(
        tokens=aggregate_tokens(token_records, source="run"),
        model=aggregate_models(model_records, source="run"),
    )


def aggregate_tokens(values: list[TokenUsage | TokenUsageRecord], *, source: str) -> TokenUsage:
    records: list[TokenUsageRecord] = []
    for value in values:
        if isinstance(value, TokenUsage):
            records.extend(value.records)
        else:
            records.append(value)
    if not records:
        return TokenUsage(known=False, source="not_available")
    input_tokens = max((record.input for record in records if record.input is not None), default=None)
    output_tokens = max((record.output for record in records if record.output is not None), default=None)
    cache_tokens = max((record.cache for record in records if record.cache is not None), default=None)
    total_tokens = max((record.total for record in records if record.total is not None), default=None)
    if total_tokens is None:
        total_tokens = _sum_optional(input_tokens, output_tokens, cache_tokens)
    return TokenUsage(
        known=True,
        source=source,
        input=input_tokens,
        output=output_tokens,
        cache=cache_tokens,
        total=total_tokens,
        records=records,
    )


def aggregate_primary_tokens(records: list[PrimaryTokenUsageRecord], *, source: str) -> TokenUsage:
    token_records = [
        TokenUsageRecord(
            source=record.source,
            input=record.input,
            output=record.output,
            cache=record.cache,
            total=record.total,
        )
        for record in records
    ]
    if not token_records:
        return TokenUsage(known=False, source="not_available")
    return TokenUsage(
        known=True,
        source=source,
        input=_sum_optional(*(record.input for record in token_records)),
        output=_sum_optional(*(record.output for record in token_records)),
        cache=_sum_optional(*(record.cache for record in token_records)),
        total=_sum_optional(*(record.total for record in token_records)),
        records=token_records,
    )


def sum_token_usages(values: list[TokenUsage], *, source: str) -> TokenUsage:
    known_values = [value for value in values if value.known]
    if not known_values:
        return TokenUsage(known=False, source="not_available")
    return TokenUsage(
        known=True,
        source=source,
        input=_sum_optional(*(value.input for value in known_values)),
        output=_sum_optional(*(value.output for value in known_values)),
        cache=_sum_optional(*(value.cache for value in known_values)),
        total=_sum_optional(*(value.total for value in known_values)),
        records=[record for value in known_values for record in value.records],
    )


def combine_token_usage(primary: TokenUsage, secondary: TokenUsage) -> TokenUsage:
    if not primary.known or not secondary.known or primary.total is None or secondary.total is None:
        return TokenUsage(known=False, source="not_available")
    return TokenUsage(
        known=True,
        source="primary_secondary",
        input=_sum_if_all_known(primary.input, secondary.input),
        output=_sum_if_all_known(primary.output, secondary.output),
        cache=_sum_if_all_known(primary.cache, secondary.cache),
        total=primary.total + secondary.total,
    )


def aggregate_models(values: list[ModelTelemetry | ModelTelemetryRecord], *, source: str) -> ModelTelemetry:
    records: list[ModelTelemetryRecord] = []
    for value in values:
        if isinstance(value, ModelTelemetry):
            records.extend(value.records)
        else:
            records.append(value)
    if not records:
        return ModelTelemetry(known=False, source="not_available")
    models = sorted({record.model for record in records if record.model})
    return ModelTelemetry(
        known=bool(models),
        source=source if models else "not_available",
        model=models[0] if len(models) == 1 else None,
        models=models,
        records=records,
    )


def _token_records_from_value(value: Any, *, source: str, event_id: str | None) -> list[TokenUsageRecord]:
    records: list[TokenUsageRecord] = []
    if isinstance(value, dict):
        if _looks_like_usage(value):
            records.append(_usage_record(value, source=source, event_id=event_id))
        for key in USAGE_KEYS:
            nested = value.get(key)
            if isinstance(nested, dict):
                records.extend(_token_records_from_value(nested, source=f"{source}.{key}", event_id=event_id))
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                records.extend(_token_records_from_value(nested, source=source, event_id=event_id))
    elif isinstance(value, list):
        for item in value:
            records.extend(_token_records_from_value(item, source=source, event_id=event_id))
    return records


def _model_records_from_value(value: Any, *, source: str, event_id: str | None) -> list[ModelTelemetryRecord]:
    records: list[ModelTelemetryRecord] = []
    if isinstance(value, dict):
        for key in MODEL_KEYS:
            model = value.get(key)
            if isinstance(model, str) and model.strip():
                records.append(ModelTelemetryRecord(source=source, model=model.strip(), event_id=event_id))
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                records.extend(_model_records_from_value(nested, source=source, event_id=event_id))
    elif isinstance(value, list):
        for item in value:
            records.extend(_model_records_from_value(item, source=source, event_id=event_id))
    return records


def _looks_like_usage(value: dict[str, Any]) -> bool:
    keys = set(value)
    return bool(
        keys
        & {
            "input_tokens",
            "prompt_tokens",
            "output_tokens",
            "completion_tokens",
            "total_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        }
    )


def _usage_record(value: dict[str, Any], *, source: str, event_id: str | None) -> TokenUsageRecord:
    input_tokens = _int_or_none(value.get("input_tokens")) or _int_or_none(value.get("prompt_tokens"))
    output_tokens = _int_or_none(value.get("output_tokens")) or _int_or_none(value.get("completion_tokens"))
    cache_tokens = _sum_optional(
        _int_or_none(value.get("cache_creation_input_tokens")),
        _int_or_none(value.get("cache_read_input_tokens")),
    )
    total_tokens = _int_or_none(value.get("total_tokens")) or _sum_optional(input_tokens, output_tokens, cache_tokens)
    return TokenUsageRecord(
        source=source,
        input=input_tokens,
        output=output_tokens,
        cache=cache_tokens,
        total=total_tokens,
        event_id=event_id,
    )


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _sum_optional(*values: int | None) -> int | None:
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _sum_if_all_known(*values: int | None) -> int | None:
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)
