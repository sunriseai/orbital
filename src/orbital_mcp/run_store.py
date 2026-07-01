from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import load_config
from .liveness import LivenessThresholds, analyze_run_liveness
from .model_log_telemetry import extract_model_log_token_telemetry
from .models import normalize_run_status
from .telemetry import (
    PrimaryTokenUsageRecord,
    aggregate_primary_tokens,
    combine_token_usage,
    extract_run_telemetry,
)


DEFAULT_MAX_EVENTS = 100
DEFAULT_TAIL_BYTES = 64 * 1024
MAX_TAIL_BYTES = 512 * 1024


class RunStore:
    def __init__(
        self,
        base_dir: Path | str,
        model_log_path: Path | str | None = None,
        thresholds: LivenessThresholds | None = None,
    ):
        self.base_dir = Path(base_dir).resolve()
        config = load_config(self.base_dir)
        self.root = (self.base_dir / config.storage_root).resolve()
        self.runs_root = self.root / "runs"
        self.sessions_root = self.root / "sessions"
        self.model_log_path = Path(model_log_path).expanduser() if model_log_path else None
        self.thresholds = thresholds or LivenessThresholds()

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        if not self.runs_root.exists():
            return runs
        paths = sorted(self.runs_root.glob("*/run.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in paths:
            try:
                run = _read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            run["run_dir_mtime"] = path.stat().st_mtime
            events = _read_jsonl(path.parent / "dialogue.jsonl")
            run["activity"] = run_activity(run, events)
            run["liveness"] = self.liveness(run["run_id"])
            runs.append(run)
        return runs

    def run_payload(self, run_id: str) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        run = _read_json(run_dir / "run.json")
        events = _read_jsonl(run_dir / "dialogue.jsonl")
        final_report_path = run_dir / "final_report.json"
        final_report = _read_json(final_report_path) if final_report_path.exists() else None
        return {
            "run": run,
            "final_report": final_report,
            "events": events,
            "activity": run_activity(run, events),
            "liveness": self.liveness(run_id),
            "token_accounting": self.token_accounting(run_id, events),
            "log_refs": {
                "dialogue": str(run_dir / "dialogue.jsonl"),
                "transcript": str(run_dir / "transcript.log"),
                "stderr": str(run_dir / "stderr.log"),
                "permissions": str(run_dir / "permissions.jsonl"),
                "final_report": str(final_report_path),
            },
            "counts": {
                "dialogue_events": len(events),
                "permissions": len(_read_jsonl(run_dir / "permissions.jsonl")),
            },
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        if not self.sessions_root.exists():
            return sessions
        paths = sorted(self.sessions_root.glob("*/session.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in paths:
            try:
                session = _read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            session["session_dir_mtime"] = path.stat().st_mtime
            session["health"] = session_health(session)
            sessions.append(session)
        return sessions

    def latest_session_id(self) -> str:
        sessions = self.list_sessions()
        if not sessions:
            raise FileNotFoundError(f"no sessions found under {self.sessions_root}")
        return str(sessions[0]["session_id"])

    def session_payload(self, session_id: str) -> dict[str, Any]:
        sid = self.latest_session_id() if session_id == "latest" else session_id
        session = _read_json(self._session_dir(sid) / "session.json")
        run_payloads = []
        for run_id in session.get("run_ids", []):
            try:
                run_payloads.append(self.run_payload(str(run_id)))
            except (OSError, ValueError, FileNotFoundError, json.JSONDecodeError):
                continue
        return {
            "session": session,
            "health": session_health(session),
            "runs": run_payloads,
        }

    def token_accounting(self, run_id: str, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        run_events = events if events is not None else _read_jsonl(run_dir / "dialogue.jsonl")
        secondary = extract_run_telemetry(run_dir, run_events).tokens
        primary_records = self._primary_token_records_for_run(run_id)
        primary = aggregate_primary_tokens(primary_records, source="primary")
        combined = combine_token_usage(primary, secondary)
        model_log = extract_model_log_token_telemetry(self.model_log_path)
        return {
            "primary": primary,
            "secondary": secondary,
            "combined": combined,
            "model_log": model_log,
            "primary_known": primary.known,
            "secondary_known": secondary.known,
            "model_log_known": model_log.known,
            "primary_records": primary_records[-100:],
        }

    def events(self, run_id: str, since_event_id: str | None = None, max_events: int = DEFAULT_MAX_EVENTS) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        events = _read_jsonl(run_dir / "dialogue.jsonl")
        if since_event_id:
            for idx, event in enumerate(events):
                if event.get("event_id") == since_event_id:
                    events = events[idx + 1 :]
                    break
        limited = events[: max(0, max_events)]
        return {"events": limited, "has_more": len(events) > len(limited)}

    def liveness(self, run_id: str) -> dict[str, Any]:
        return analyze_run_liveness(
            self.root,
            run_id,
            model_log_path=self.model_log_path,
            thresholds=self.thresholds,
        )

    def log_tail(self, run_id: str, name: str, max_bytes: int = DEFAULT_TAIL_BYTES) -> dict[str, Any]:
        if name not in {"stderr.log", "transcript.log"}:
            raise ValueError("unsupported log")
        run_dir = self._run_dir(run_id)
        path = run_dir / name
        max_bytes = max(0, min(max_bytes, MAX_TAIL_BYTES))
        if not path.exists():
            return {"text": "", "truncated": False, "bytes": 0}
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                raw = handle.read(max_bytes)
                truncated = True
            else:
                raw = handle.read()
                truncated = False
        return {"text": raw.decode("utf-8", errors="replace"), "truncated": truncated, "bytes": size}

    def _run_dir(self, run_id: str) -> Path:
        if not _valid_run_id(run_id):
            raise ValueError(f"invalid run_id: {run_id}")
        run_dir = (self.runs_root / run_id).resolve()
        if not _is_relative_to(run_dir, self.runs_root.resolve()):
            raise ValueError(f"invalid run_id: {run_id}")
        if not (run_dir / "run.json").exists():
            raise FileNotFoundError(run_id)
        return run_dir

    def _session_dir(self, session_id: str) -> Path:
        if not _valid_run_id(session_id):
            raise ValueError(f"invalid session_id: {session_id}")
        session_dir = (self.sessions_root / session_id).resolve()
        if not _is_relative_to(session_dir, self.sessions_root.resolve()):
            raise ValueError(f"invalid session_id: {session_id}")
        if not (session_dir / "session.json").exists():
            raise FileNotFoundError(session_id)
        return session_dir

    def _primary_token_records_for_run(self, run_id: str) -> list[PrimaryTokenUsageRecord]:
        records: list[PrimaryTokenUsageRecord] = []
        sessions_root = self.root / "sessions"
        if not sessions_root.exists():
            return records
        for path in sorted(sessions_root.glob("*/primary_token_usage.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if value.get("run_id") != run_id:
                    continue
                records.append(_primary_record_from_dict(value))
        return records


def run_activity(run: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    last_event = events[-1] if events else None
    last_timestamp = str(last_event.get("timestamp")) if last_event else None
    age_seconds = _age_seconds(last_timestamp)
    pending_tool = _latest_pending_tool(events)
    return {
        "last_event_id": last_event.get("event_id") if last_event else None,
        "last_event_kind": last_event.get("kind") if last_event else None,
        "last_event_text": last_event.get("text") if last_event else None,
        "last_event_timestamp": last_timestamp,
        "last_event_age_seconds": age_seconds,
        "latest_pending_tool": pending_tool,
        "orbital_observation": _activity_label(normalize_run_status(run.get("status")), age_seconds, pending_tool),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise json.JSONDecodeError("expected object", path.name, 0)
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    values: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            values.append(value)
    return values


def _primary_record_from_dict(value: dict[str, Any]) -> PrimaryTokenUsageRecord:
    return PrimaryTokenUsageRecord(
        timestamp=str(value["timestamp"]),
        source=str(value["source"]),
        scope=value.get("scope"),
        run_id=value.get("run_id"),
        model=value.get("model"),
        input=value.get("input"),
        output=value.get("output"),
        cache=value.get("cache"),
        total=value.get("total"),
        notes=value.get("notes"),
    )


def _latest_pending_tool(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        kind = str(event.get("kind") or "")
        text = str(event.get("text") or "")
        if kind in {"tool_call_completed", "tool_call_failed"}:
            return None
        if kind in {"tool_call_started", "tool_call_updated"} and (
            "pending]" in text or "in_progress]" in text or "pending" in text or "in_progress" in text
        ):
            return {
                "event_id": event.get("event_id"),
                "kind": kind,
                "timestamp": event.get("timestamp"),
                "text": event.get("text"),
                "age_seconds": _age_seconds(str(event.get("timestamp") or "")),
            }
    return None


def _activity_label(status: str, age_seconds: float | None, pending_tool: dict[str, Any] | None) -> str:
    if status in {"completed", "failed", "blocked", "cancelled", "interrupted", "unknown"}:
        return "terminal"
    if status in {"created", "launching"} or age_seconds is None:
        return "starting"
    if status == "waiting_for_permission":
        return "waiting_permission"
    if status == "stopping":
        return "stopping"
    if pending_tool and age_seconds >= 30:
        return "pending_tool_silent"
    if age_seconds >= 60:
        return "orbital_silent"
    return "recent_orbital_activity"


def _age_seconds(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


def session_health(session: dict[str, Any]) -> dict[str, Any]:
    requirements = list(session.get("requirements", []))
    attempts = list(session.get("attempts", []))
    warnings = list(session.get("session_warnings", []))
    unsatisfied = [
        str(requirement.get("requirement_id"))
        for requirement in requirements
        if requirement.get("status") != "satisfied"
    ]
    pending_attempts = [
        str(attempt.get("run_id"))
        for attempt in attempts
        if attempt.get("decision", "pending") == "pending"
    ]
    error_count = sum(1 for warning in warnings if warning.get("severity") == "error")
    return {
        "status": "blocked" if error_count else ("needs_review" if unsatisfied or pending_attempts else "ready"),
        "requirement_count": len(requirements),
        "unsatisfied_requirement_ids": sorted(unsatisfied),
        "ticket_count": len(session.get("tickets", [])),
        "attempt_count": len(attempts),
        "pending_attempt_run_ids": sorted(pending_attempts),
        "warning_count": len(warnings),
        "error_count": error_count,
    }


def _valid_run_id(run_id: str) -> bool:
    return bool(run_id) and all(char.isalnum() or char in {"-", "_"} for char in run_id)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
