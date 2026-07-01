from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import (
    DelegationSession,
    DialogueEvent,
    FinalReport,
    LogRefs,
    PermissionRequest,
    TaskRun,
    to_jsonable,
)
from .telemetry import PrimaryTokenUsageRecord


class RunStore:
    def __init__(self, root: Path):
        self.root = root
        self.runs_root = root / "runs"
        self.sessions_root = root / "sessions"
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.sessions_root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        _validate_id(run_id, "run_id")
        path = (self.runs_root / run_id).resolve()
        _ensure_under(path, self.runs_root.resolve(), "run_id")
        return path

    def create_run(self, run: TaskRun) -> None:
        rd = self.run_dir(run.run_id)
        rd.mkdir(parents=True, exist_ok=True)
        self.write_json(run.run_id, "task.json", run.task)
        self.save_run(run)
        for name in ["dialogue.jsonl", "transcript.log", "stderr.log", "permissions.jsonl"]:
            (rd / name).touch(exist_ok=True)

    def log_refs(self, run_id: str) -> LogRefs:
        rd = self.run_dir(run_id)
        return LogRefs(
            dialogue=str(rd / "dialogue.jsonl"),
            transcript=str(rd / "transcript.log"),
            stderr=str(rd / "stderr.log"),
            permissions=str(rd / "permissions.jsonl"),
            final_report=str(rd / "final_report.json"),
        )

    def save_run(self, run: TaskRun) -> None:
        self.write_json(run.run_id, "run.json", run)

    def load_run(self, run_id: str) -> dict[str, Any]:
        return json.loads((self.run_dir(run_id) / "run.json").read_text(encoding="utf-8"))

    def load_final_report(self, run_id: str) -> dict[str, Any] | None:
        path = self.run_dir(run_id) / "final_report.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for path in sorted(self.runs_root.glob("*/run.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                runs.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return runs

    def session_dir(self, session_id: str) -> Path:
        _validate_id(session_id, "session_id")
        path = (self.sessions_root / session_id).resolve()
        _ensure_under(path, self.sessions_root.resolve(), "session_id")
        return path

    def save_session(self, session: DelegationSession) -> None:
        directory = self.session_dir(session.session_id)
        directory.mkdir(parents=True, exist_ok=True)
        with _file_lock(directory / ".lock"):
            _atomic_write_text(directory / "session.json", json.dumps(to_jsonable(session), indent=2, sort_keys=True) + "\n")

    def load_session(self, session_id: str) -> dict[str, Any]:
        return json.loads((self.session_dir(session_id) / "session.json").read_text(encoding="utf-8"))

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for path in sorted(self.sessions_root.glob("*/session.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                sessions.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sessions

    def append_primary_token_usage(self, session_id: str, record: PrimaryTokenUsageRecord) -> None:
        self.load_session(session_id)
        path = self.session_dir(session_id) / "primary_token_usage.jsonl"
        with _file_lock(path.parent / ".lock"):
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(to_jsonable(record), sort_keys=True) + "\n")

    def read_primary_token_usage(self, session_id: str) -> list[PrimaryTokenUsageRecord]:
        self.load_session(session_id)
        path = self.session_dir(session_id) / "primary_token_usage.jsonl"
        if not path.exists():
            return []
        records: list[PrimaryTokenUsageRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            records.append(
                PrimaryTokenUsageRecord(
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
            )
        return records

    def write_json(self, run_id: str, name: str, value: Any) -> None:
        rd = self.run_dir(run_id)
        with _file_lock(rd / ".lock"):
            _atomic_write_text(rd / name, json.dumps(to_jsonable(value), indent=2, sort_keys=True) + "\n")

    def append_dialogue(self, event: DialogueEvent) -> None:
        self._append_jsonl(event.run_id, "dialogue.jsonl", event)

    def append_permission(self, permission: PermissionRequest) -> None:
        self._append_jsonl(permission.run_id, "permissions.jsonl", permission)

    def read_permissions(self, run_id: str) -> list[dict[str, Any]]:
        return self._read_jsonl(run_id, "permissions.jsonl")

    def save_final_report(self, report: FinalReport) -> None:
        self.write_json(report.run_id, "final_report.json", report)

    def append_transcript(self, run_id: str, text: str) -> None:
        self._append_text(run_id, "transcript.log", text)

    def append_stderr(self, run_id: str, text: str) -> None:
        self._append_text(run_id, "stderr.log", text)

    def read_log_tail(self, run_id: str, name: str, max_bytes: int = 64 * 1024) -> dict[str, Any]:
        if name not in {"transcript.log", "stderr.log"}:
            raise ValueError(f"unsupported log name: {name}")
        if max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        path = self.run_dir(run_id) / name
        if not path.exists():
            return {"text": "", "bytes_read": 0, "truncated": False, "path": str(path)}
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(max(0, size - max_bytes))
                raw = f.read(max_bytes)
                truncated = True
            else:
                raw = f.read()
                truncated = False
        return {
            "text": raw.decode("utf-8", errors="replace"),
            "bytes_read": len(raw),
            "truncated": truncated,
            "path": str(path),
        }

    def read_dialogue(
        self,
        run_id: str,
        since_event_id: str | None = None,
        max_events: int = 100,
    ) -> dict[str, Any]:
        events = self._read_jsonl(run_id, "dialogue.jsonl")
        if since_event_id:
            for idx, event in enumerate(events):
                if event.get("event_id") == since_event_id:
                    events = events[idx + 1 :]
                    break
        limited = events[:max_events]
        return {"events": limited, "has_more": len(events) > len(limited)}

    def storage_diagnostics(self, run_id: str) -> dict[str, Any]:
        rd = self.run_dir(run_id)
        issues: list[dict[str, Any]] = []
        for name in ["run.json", "task.json", "final_report.json"]:
            path = rd / name
            if name == "final_report.json" and not path.exists():
                continue
            if not path.exists():
                issues.append({"code": "missing_artifact", "path": str(path), "severity": "error"})
                continue
            _diagnose_json(path, issues)
        for name in ["dialogue.jsonl", "permissions.jsonl"]:
            path = rd / name
            if not path.exists():
                issues.append({"code": "missing_artifact", "path": str(path), "severity": "warning"})
                continue
            _diagnose_jsonl(path, issues)
        for name in ["transcript.log", "stderr.log"]:
            path = rd / name
            if not path.exists():
                issues.append({"code": "missing_artifact", "path": str(path), "severity": "warning"})
        for path in sorted(rd.glob("*.tmp")):
            issues.append({"code": "partial_write_tmp", "path": str(path), "severity": "warning"})
        return {"schema_version": 1, "run_id": run_id, "issues": issues, "ok": not any(item["severity"] == "error" for item in issues)}

    def _append_jsonl(self, run_id: str, name: str, value: Any) -> None:
        rd = self.run_dir(run_id)
        with _file_lock(rd / ".lock"):
            with (rd / name).open("a", encoding="utf-8") as f:
                f.write(json.dumps(to_jsonable(value), sort_keys=True) + "\n")

    def _append_text(self, run_id: str, name: str, text: str) -> None:
        rd = self.run_dir(run_id)
        with _file_lock(rd / ".lock"):
            with (rd / name).open("a", encoding="utf-8") as f:
                f.write(text)
                if not text.endswith("\n"):
                    f.write("\n")

    def _read_jsonl(self, run_id: str, name: str) -> list[dict[str, Any]]:
        path = self.run_dir(run_id) / name
        if not path.exists():
            return []
        values: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return values

    def recover_interrupted_runs(self) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        terminal = {"completed", "failed", "blocked", "cancelled", "interrupted", "unknown", "passed", "stopped"}
        for run in self.list_runs():
            if run.get("status") in terminal:
                continue
            run["status"] = "interrupted"
            run["last_error"] = "Run recovered after Orbital restart without an active controller."
            run_id = str(run.get("run_id"))
            self.write_json(run_id, "run.json", run)
            self._append_recovery_event(run_id, run["last_error"])
            recovered.append(run)
        return recovered

    def _append_recovery_event(self, run_id: str, message: str) -> None:
        event = {
            "event_id": "recovery",
            "run_id": run_id,
            "timestamp": None,
            "kind": "storage_recovery",
            "speaker": "server",
            "text": message,
        }
        self._append_jsonl(run_id, "dialogue.jsonl", event)


def _validate_id(value: str, field: str) -> None:
    if not value or not all(char.isalnum() or char in {"-", "_"} for char in value):
        raise ValueError(f"invalid {field}: {value}")


def _ensure_under(path: Path, parent: Path, field: str) -> None:
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {path}") from exc


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def _file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock:
        try:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _diagnose_json(path: Path, issues: list[dict[str, Any]]) -> None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append({"code": "malformed_json", "path": str(path), "line": exc.lineno, "severity": "error"})
        return
    if isinstance(value, dict) and int(value.get("schema_version", 1)) > 1:
        issues.append(
            {
                "code": "unsupported_schema_version",
                "path": str(path),
                "schema_version": value.get("schema_version"),
                "severity": "error",
            }
        )


def _diagnose_jsonl(path: Path, issues: list[dict[str, Any]]) -> None:
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError:
            issues.append(
                {
                    "code": "malformed_jsonl",
                    "path": str(path),
                    "line": line_number,
                    "severity": "warning",
                }
            )
