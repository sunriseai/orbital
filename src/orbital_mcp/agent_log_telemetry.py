from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .telemetry import TokenUsage, TokenUsageRecord


DEFAULT_CORRELATION_PADDING_SECONDS = 300
DEFAULT_MAX_RECORDS = 100


@dataclass
class AgentLogTokenRecord:
    agent: str
    session_id: str
    source: str
    attribution: str
    project: str | None = None
    timestamp: str | None = None
    model: str | None = None
    input: int | None = None
    output: int | None = None
    cache: int | None = None
    total: int | None = None


@dataclass
class AgentLogTokenTelemetry:
    known: bool
    source: str
    attribution: str = "external_agent_logs"
    input: int | None = None
    output: int | None = None
    cache: int | None = None
    total: int | None = None
    records: list[AgentLogTokenRecord] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def scan_external_agent_token_telemetry(
    *,
    project: Path | str | None = None,
    since: datetime | str | None = None,
    until: datetime | str | None = None,
    home: Path | str | None = None,
    max_records: int = DEFAULT_MAX_RECORDS,
    require_unique: bool = False,
) -> AgentLogTokenTelemetry:
    root = Path(home or os.environ.get("ORBITAL_AGENT_LOG_HOME") or Path.home()).expanduser()
    project_path = _normalize_path(project) if project is not None else None
    since_dt = _coerce_datetime(since)
    until_dt = _coerce_datetime(until)
    records = _scan_claude(root, since_dt, until_dt) + _scan_codex(root, since_dt, until_dt) + _scan_opencode(
        root, since_dt, until_dt
    )
    records = [
        record
        for record in records
        if _matches_project(record, project_path) and _matches_time(record, since_dt, until_dt)
    ]
    records.sort(key=lambda record: record.timestamp or "", reverse=True)
    records = records[: max(0, max_records)]
    if not records:
        return AgentLogTokenTelemetry(
            known=False,
            source=str(root),
            caveats=["No correlated Codex, Claude, or OpenCode local agent-log token records were found."],
        )
    if require_unique and len(records) != 1:
        return AgentLogTokenTelemetry(
            known=False,
            source=str(root),
            records=records,
            caveats=[
                f"Canonical token usage is unknown because {len(records)} correlated local agent-log records matched the run window.",
                "Use an isolated token workspace or adapter-provided run correlation before treating token totals as exact.",
            ],
        )
    return AgentLogTokenTelemetry(
        known=True,
        source=str(root),
        input=_sum_optional(record.input for record in records),
        output=_sum_optional(record.output for record in records),
        cache=_sum_optional(record.cache for record in records),
        total=_sum_optional(record.total for record in records),
        records=records,
        caveats=[
            "External agent-log telemetry is parsed from local Codex/Claude/OpenCode session files and kept separate from adapter-reported totals.",
            "Correlation uses workspace path and run time window, not an adapter-provided run identifier.",
        ],
    )


def agent_log_token_usage(telemetry: AgentLogTokenTelemetry, *, source: str = "external_agent_logs") -> TokenUsage:
    if not telemetry.known:
        return TokenUsage(known=False, source="not_available")
    return TokenUsage(
        known=True,
        source=source,
        input=telemetry.input,
        output=telemetry.output,
        cache=telemetry.cache,
        total=telemetry.total,
        records=[
            TokenUsageRecord(
                source=f"{record.agent}:{record.attribution}",
                input=record.input,
                output=record.output,
                cache=record.cache,
                total=record.total,
            )
            for record in telemetry.records
        ],
    )


def run_time_window(
    events: list[dict[str, Any]],
    *,
    padding_seconds: int = DEFAULT_CORRELATION_PADDING_SECONDS,
) -> tuple[datetime | None, datetime | None]:
    timestamps = [_coerce_datetime(event.get("timestamp")) for event in events]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    if not timestamps:
        return None, None
    padding = timedelta(seconds=max(0, padding_seconds))
    return min(timestamps) - padding, max(timestamps) + padding


def _scan_claude(home: Path, since: datetime | None = None, until: datetime | None = None) -> list[AgentLogTokenRecord]:
    projects_dir = home / ".claude" / "projects"
    if not projects_dir.is_dir():
        return []
    records: list[AgentLogTokenRecord] = []
    for path in projects_dir.glob("*/*.jsonl"):
        if not _matches_file_window(path, since, until):
            continue
        record = AgentLogTokenRecord(
            agent="claude",
            session_id=path.stem,
            source=str(path),
            attribution="claude_project_jsonl",
            timestamp=_file_mtime_iso(path),
        )
        cache_high_water = 0
        input_total = 0
        output_total = 0
        found_usage = False
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value.get("cwd"), str) and not record.project:
                record.project = value["cwd"]
            timestamp = _coerce_datetime(value.get("timestamp"))
            if timestamp is not None:
                record.timestamp = _isoformat_z(timestamp)
            if value.get("type") != "assistant":
                continue
            message = value.get("message") if isinstance(value.get("message"), dict) else {}
            if isinstance(message.get("model"), str) and not record.model and message.get("model") != "<synthetic>":
                record.model = message["model"]
            usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
            if not usage:
                continue
            found_usage = True
            input_total += _int_value(usage.get("input_tokens"))
            output_total += _int_value(usage.get("output_tokens"))
            cache_high_water = max(cache_high_water, _int_value(usage.get("cache_read_input_tokens")))
        if found_usage:
            record.input = input_total
            record.output = output_total
            record.cache = cache_high_water
            record.total = input_total + output_total + cache_high_water
            records.append(record)
    return records


def _scan_codex(home: Path, since: datetime | None = None, until: datetime | None = None) -> list[AgentLogTokenRecord]:
    sessions_dir = home / ".codex" / "sessions"
    if not sessions_dir.is_dir():
        return []
    files_by_session: dict[str, list[Path]] = {}
    for path in sessions_dir.rglob("rollout-*.jsonl"):
        if not _matches_file_window(path, since, until):
            continue
        sid = _codex_session_id(path)
        files_by_session.setdefault(sid, []).append(path)

    records: list[AgentLogTokenRecord] = []
    for sid, paths in files_by_session.items():
        record = AgentLogTokenRecord(
            agent="codex",
            session_id=sid,
            source=",".join(str(path) for path in sorted(paths)),
            attribution="codex_rollout_jsonl",
        )
        net_input = 0
        cache = 0
        output = 0
        found_usage = False
        for path in sorted(paths):
            if record.timestamp is None:
                record.timestamp = _file_mtime_iso(path)
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = _coerce_datetime(value.get("timestamp"))
                if timestamp is not None:
                    record.timestamp = _isoformat_z(timestamp)
                payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
                if value.get("type") == "session_meta":
                    if isinstance(payload.get("cwd"), str):
                        record.project = payload["cwd"]
                    if isinstance(payload.get("model"), str) and not record.model:
                        record.model = payload["model"]
                elif value.get("type") == "turn_context" and isinstance(payload.get("model"), str) and not record.model:
                    record.model = payload["model"]
                if value.get("type") != "event_msg":
                    continue
                info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
                usage = info.get("total_token_usage") if isinstance(info.get("total_token_usage"), dict) else {}
                if not usage:
                    continue
                found_usage = True
                gross_input = _int_value(usage.get("input_tokens"))
                cached_input = _int_value(usage.get("cached_input_tokens"))
                output_tokens = _int_value(usage.get("output_tokens"))
                reasoning_tokens = _int_value(usage.get("reasoning_output_tokens"))
                total_tokens = _int_value(usage.get("total_tokens"))
                billable_output = output_tokens
                if total_tokens > gross_input + output_tokens:
                    billable_output += reasoning_tokens
                net_input = max(net_input, max(0, gross_input - cached_input))
                cache = max(cache, cached_input)
                output = max(output, billable_output)
        if found_usage:
            record.input = net_input
            record.output = output
            record.cache = cache
            record.total = net_input + output + cache
            records.append(record)
    return records


def _scan_opencode(home: Path, since: datetime | None = None, until: datetime | None = None) -> list[AgentLogTokenRecord]:
    db_path = home / ".local" / "share" / "opencode" / "opencode.db"
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(_sqlite_readonly_uri(db_path), uri=True, timeout=1.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return []

    records: list[AgentLogTokenRecord] = []
    try:
        session_columns = _sqlite_columns(conn, "session")
        model_column = "model" in session_columns
        parent_select = ", parent_id" if "parent_id" in session_columns else ""
        model_select = ", model" if model_column else ""
        query = f"SELECT id, directory, title, time_created, time_updated{parent_select}{model_select} FROM session"
        for row in conn.execute(query).fetchall():
            timestamp = _opencode_timestamp(row["time_updated"] or row["time_created"])
            if not _matches_datetime_window(timestamp, since, until):
                continue
            sid = str(row["id"])
            record = AgentLogTokenRecord(
                agent="opencode",
                session_id=sid,
                source=str(db_path),
                attribution="opencode_sqlite",
                project=row["directory"],
                timestamp=_isoformat_z(timestamp) if timestamp is not None else _file_mtime_iso(db_path),
                model=_resolve_opencode_model(row["model"]) if model_column else None,
            )
            if not record.model:
                record.model = _opencode_message_model(conn, sid)
            best_input = 0
            best_output = 0
            best_cache = 0
            best_total = 0
            found_usage = False
            for part_row in conn.execute("SELECT data FROM part WHERE session_id=? ORDER BY time_created", (sid,)):
                try:
                    data = json.loads(part_row["data"] or "{}")
                except json.JSONDecodeError:
                    continue
                if data.get("type") != "step-finish":
                    continue
                tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
                if not tokens:
                    continue
                found_usage = True
                cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
                input_tokens = _int_value(tokens.get("input"))
                output_tokens = _int_value(tokens.get("output"))
                cache_tokens = _int_value(cache.get("read"))
                total_tokens = _int_value(tokens.get("total")) or input_tokens + output_tokens + cache_tokens
                if total_tokens >= best_total:
                    best_input = input_tokens
                    best_output = output_tokens
                    best_cache = cache_tokens
                    best_total = total_tokens
            if found_usage:
                record.input = best_input
                record.output = best_output
                record.cache = best_cache
                record.total = best_total
                records.append(record)
    except sqlite3.Error:
        return records
    finally:
        conn.close()
    return records


def _opencode_message_model(conn: sqlite3.Connection, session_id: str) -> str | None:
    try:
        rows = conn.execute("SELECT data FROM message WHERE session_id=? ORDER BY time_created", (session_id,))
    except sqlite3.Error:
        return None
    fallback: str | None = None
    for row in rows:
        try:
            data = json.loads(row["data"] or "{}")
        except json.JSONDecodeError:
            continue
        model = (
            _resolve_opencode_model(data.get("model"))
            or _string_or_none(data.get("modelID"))
            or _string_or_none(data.get("providerID"))
        )
        if data.get("role") == "assistant" and model:
            return model
        if model and fallback is None:
            fallback = model
    return fallback


def _resolve_opencode_model(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return stripped
            return _resolve_opencode_model(parsed) or stripped
        return stripped
    if isinstance(value, dict):
        return (
            _string_or_none(value.get("id"))
            or _string_or_none(value.get("modelID"))
            or _string_or_none(value.get("providerID"))
        )
    return None


def _opencode_timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def _sqlite_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def _sqlite_readonly_uri(path: Path) -> str:
    return "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"


def _codex_session_id(path: Path) -> str:
    parts = path.stem.split("-")
    if len(parts) >= 6:
        return "-".join(parts[-5:])
    return path.stem


def _matches_project(record: AgentLogTokenRecord, project: Path | None) -> bool:
    if project is None:
        return True
    if not record.project:
        return False
    return _normalize_path(record.project) == project


def _matches_time(
    record: AgentLogTokenRecord,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    timestamp = _coerce_datetime(record.timestamp)
    if timestamp is None:
        return True
    if since is not None and timestamp < since:
        return False
    if until is not None and timestamp > until:
        return False
    return True


def _matches_file_window(path: Path, since: datetime | None, until: datetime | None) -> bool:
    if since is None and until is None:
        return True
    try:
        timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return True
    return _matches_datetime_window(timestamp, since, until)


def _matches_datetime_window(timestamp: datetime | None, since: datetime | None, until: datetime | None) -> bool:
    if timestamp is None:
        return True
    if since is not None and timestamp < since:
        return False
    if until is not None and timestamp > until:
        return False
    return True


def _normalize_path(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    return Path(value).expanduser().resolve(strict=False)


def _coerce_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_mtime_iso(path: Path) -> str | None:
    try:
        return _isoformat_z(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
    except OSError:
        return None


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return 0


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _sum_optional(values: Any) -> int | None:
    total = 0
    found = False
    for value in values:
        if value is None:
            continue
        total += value
        found = True
    return total if found else None
