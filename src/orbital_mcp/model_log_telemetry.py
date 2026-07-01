from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_MODEL_LOG_TAIL_BYTES = 512 * 1024


@dataclass
class ModelLogTokenRecord:
    provider: str
    source: str
    attribution: str
    task_id: str | None = None
    input: int | None = None
    output: int | None = None
    total: int | None = None
    raw_lines: list[str] = field(default_factory=list)


@dataclass
class ModelLogTokenTelemetry:
    known: bool
    source: str
    provider: str | None = None
    attribution: str = "unattributed"
    input: int | None = None
    output: int | None = None
    total: int | None = None
    records: list[ModelLogTokenRecord] = field(default_factory=list)
    latest_record: ModelLogTokenRecord | None = None
    caveats: list[str] = field(default_factory=list)


class LlamaCppLogParser:
    provider = "llama_cpp"
    _TASK_RE = re.compile(r"\|\s*task\s+(-?\d+)\s*\|")
    _PROMPT_RE = re.compile(r"prompt eval time\s*=.*?/\s*(\d+)\s+tokens")
    _EVAL_RE = re.compile(r"\beval time\s*=.*?/\s*(\d+)\s+tokens")
    _TOTAL_RE = re.compile(r"total time\s*=.*?/\s*(\d+)\s+tokens")

    def parse(self, text: str, *, source: str) -> list[ModelLogTokenRecord]:
        by_task: dict[str, ModelLogTokenRecord] = {}
        order: list[str] = []
        for line in text.splitlines():
            task = self._task_id(line)
            if task is None:
                continue
            prompt = self._match_int(self._PROMPT_RE, line)
            output = self._match_int(self._EVAL_RE, line)
            total = self._match_int(self._TOTAL_RE, line)
            if prompt is None and output is None and total is None:
                continue
            if task not in by_task:
                by_task[task] = ModelLogTokenRecord(
                    provider=self.provider,
                    source=source,
                    attribution="unattributed",
                    task_id=task,
                )
                order.append(task)
            record = by_task[task]
            if prompt is not None:
                record.input = prompt
            if output is not None:
                record.output = output
            if total is not None:
                record.total = total
            record.raw_lines.append(line)
        return [by_task[task] for task in order if _has_tokens(by_task[task])]

    def _task_id(self, line: str) -> str | None:
        match = self._TASK_RE.search(line)
        if not match:
            return None
        task = match.group(1)
        return task if task != "-1" else None

    def _match_int(self, pattern: re.Pattern[str], line: str) -> int | None:
        match = pattern.search(line)
        if not match:
            return None
        return int(match.group(1))


PARSERS = (LlamaCppLogParser(),)


def extract_model_log_token_telemetry(
    path: Path | str | None,
    *,
    parser: str = "auto",
    tail_bytes: int = DEFAULT_MODEL_LOG_TAIL_BYTES,
) -> ModelLogTokenTelemetry:
    if path is None:
        return ModelLogTokenTelemetry(
            known=False,
            source="not_configured",
            caveats=["No model log path was configured."],
        )
    resolved = Path(path).expanduser()
    if not resolved.exists():
        return ModelLogTokenTelemetry(
            known=False,
            source=str(resolved),
            caveats=["Model log path does not exist."],
        )
    try:
        text = _tail_text(resolved, tail_bytes)
    except OSError as exc:
        return ModelLogTokenTelemetry(
            known=False,
            source=str(resolved),
            caveats=[str(exc)],
        )
    records = _parse_records(text, source=str(resolved), parser=parser)
    if not records:
        return ModelLogTokenTelemetry(
            known=False,
            source=str(resolved),
            caveats=["No supported model-log token records were found."],
        )
    latest = records[-1]
    return ModelLogTokenTelemetry(
        known=True,
        source=str(resolved),
        provider=latest.provider,
        attribution="unattributed",
        input=latest.input,
        output=latest.output,
        total=latest.total,
        records=records[-100:],
        latest_record=latest,
        caveats=[
            "Model-log token records are external and not attributed to a Orbital run unless a harness provides correlation metadata.",
        ],
    )


def _parse_records(text: str, *, source: str, parser: str) -> list[ModelLogTokenRecord]:
    records: list[ModelLogTokenRecord] = []
    for candidate in PARSERS:
        if parser not in {"auto", candidate.provider}:
            continue
        records.extend(candidate.parse(text, source=source))
    return records


def _has_tokens(record: ModelLogTokenRecord) -> bool:
    return record.input is not None or record.output is not None or record.total is not None


def _tail_text(path: Path, max_bytes: int) -> str:
    size = path.stat().st_size
    max_bytes = max(0, max_bytes)
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        raw = handle.read(max_bytes)
    return raw.decode("utf-8", errors="replace")
