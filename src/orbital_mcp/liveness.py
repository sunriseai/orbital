from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .events import TERMINAL_STATUSES
from .models import normalize_run_status


LivenessVerdict = Literal[
    "active_orbital",
    "active_model",
    "waiting_permission",
    "quiet_short",
    "suspect_stalled",
    "stop_safe",
    "terminal",
    "unknown",
]

MODEL_ACTIVE_MARKERS = (" n_decoded =", "prompt processing", "processing task")
MODEL_IDLE_MARKERS = ("all slots are idle", "stop processing")
MODEL_CANCEL_MARKERS = ("cancel task",)
TOOL_PENDING_MARKERS = ("pending]", "in_progress]", "pending", "in_progress")

DEFAULT_ORBITAL_QUIET_SECONDS = 60.0
DEFAULT_MODEL_ACTIVE_SECONDS = 30.0
DEFAULT_STOP_SAFE_SECONDS = 180.0
DEFAULT_TAIL_BYTES = 128 * 1024


@dataclass
class LivenessThresholds:
    orbital_quiet_seconds: float = DEFAULT_ORBITAL_QUIET_SECONDS
    model_active_seconds: float = DEFAULT_MODEL_ACTIVE_SECONDS
    stop_safe_seconds: float = DEFAULT_STOP_SAFE_SECONDS


def analyze_run_liveness(
    store_root: Path | str,
    run_id: str,
    model_log_path: Path | str | None = None,
    *,
    inspect_process: bool = True,
    thresholds: LivenessThresholds | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or LivenessThresholds()
    now = now or datetime.now(UTC)
    root = Path(store_root).resolve()
    run_dir = _run_dir(root, run_id)
    run = _read_json(run_dir / "run.json")
    dialogue = _read_jsonl(run_dir / "dialogue.jsonl")
    permissions = _read_jsonl(run_dir / "permissions.jsonl")
    process = _process_signal(run, inspect_process=inspect_process)
    model = _model_signal(Path(model_log_path).expanduser() if model_log_path else None, now, thresholds)
    orbital = _orbital_signal(dialogue, now)
    pending_permission = _pending_permission(permissions)
    pending_tool = _latest_pending_tool(dialogue, now)
    verdict, reasons = _verdict(
        run=run,
        orbital=orbital,
        model=model,
        process=process,
        pending_permission=pending_permission,
        pending_tool=pending_tool,
        thresholds=thresholds,
    )
    recommendation = _recommendation(verdict, thresholds)
    return {
        "schema_version": 1,
        "run_id": run_id,
        "verdict": verdict,
        "stop_safe": verdict == "stop_safe",
        "recommendation": recommendation,
        "reasons": reasons,
        "thresholds": {
            "orbital_quiet_seconds": thresholds.orbital_quiet_seconds,
            "model_active_seconds": thresholds.model_active_seconds,
            "stop_safe_seconds": thresholds.stop_safe_seconds,
        },
        "signals": {
            "run_status": normalize_run_status(run.get("status")),
            "orbital": orbital,
            "model": model,
            "process": process,
            "pending_permission": pending_permission,
            "pending_tool": pending_tool,
        },
        "evidence": _evidence(orbital, model, process, pending_permission, pending_tool),
    }


def _recommendation(verdict: LivenessVerdict, thresholds: LivenessThresholds) -> dict[str, Any]:
    if verdict in {"active_orbital", "active_model"}:
        return {
            "action": "keep_polling",
            "stop_allowed": False,
            "severity": "info",
            "summary": "Run appears active; keep polling.",
            "next_check_seconds": thresholds.model_active_seconds,
        }
    if verdict == "quiet_short":
        return {
            "action": "keep_polling",
            "stop_allowed": False,
            "severity": "info",
            "summary": "Run is quiet but below the stop-safe threshold; recheck soon.",
            "next_check_seconds": max(1.0, min(thresholds.orbital_quiet_seconds, thresholds.stop_safe_seconds / 2)),
        }
    if verdict == "waiting_permission":
        return {
            "action": "resolve_permission",
            "stop_allowed": False,
            "severity": "warning",
            "summary": "Run is waiting on a permission request.",
        }
    if verdict == "suspect_stalled":
        return {
            "action": "recheck",
            "stop_allowed": False,
            "severity": "warning",
            "summary": "Worker process exists without recent activity; inspect and recheck before stopping.",
            "next_check_seconds": thresholds.orbital_quiet_seconds,
        }
    if verdict == "stop_safe":
        return {
            "action": "stop",
            "stop_allowed": True,
            "severity": "danger",
            "summary": "No recent activity or pending permission was observed; stopping is reasonable.",
        }
    if verdict == "terminal":
        return {
            "action": "none",
            "stop_allowed": False,
            "severity": "info",
            "summary": "Run is terminal; no stop action is needed.",
        }
    return {
        "action": "inspect",
        "stop_allowed": False,
        "severity": "warning",
        "summary": "Liveness is unknown; inspect run logs and process state before stopping.",
    }


def latest_run_id(store_root: Path | str) -> str:
    runs_root = Path(store_root).resolve() / "runs"
    paths = sorted(runs_root.glob("*/run.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not paths:
        raise FileNotFoundError(f"no runs found under {runs_root}")
    active = []
    for path in paths:
        try:
            run = _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if normalize_run_status(run.get("status")) not in TERMINAL_STATUSES:
            active.append(path)
    selected = active[0] if active else paths[0]
    return selected.parent.name


def _verdict(
    *,
    run: dict[str, Any],
    orbital: dict[str, Any],
    model: dict[str, Any],
    process: dict[str, Any],
    pending_permission: dict[str, Any] | None,
    pending_tool: dict[str, Any] | None,
    thresholds: LivenessThresholds,
) -> tuple[LivenessVerdict, list[str]]:
    status = normalize_run_status(run.get("status"))
    orbital_age = orbital.get("last_event_age_seconds")
    model_age = model.get("last_active_age_seconds")
    process_state = str(process.get("state") or "unknown")
    if status in TERMINAL_STATUSES:
        return "terminal", [f"run status is {status}"]
    if pending_permission:
        return "waiting_permission", ["run has a pending permission request"]
    if _is_recent(orbital_age, thresholds.orbital_quiet_seconds):
        return "active_orbital", [f"Orbital event arrived {orbital_age:.1f}s ago"]
    if _is_recent(model_age, thresholds.model_active_seconds):
        return "active_model", [f"model log indicates activity {model_age:.1f}s ago"]
    if orbital_age is None and model_age is None:
        return "unknown", ["no Orbital dialogue or model log activity is available"]
    if orbital_age is not None and orbital_age < thresholds.stop_safe_seconds:
        reason = f"Orbital has been quiet for {orbital_age:.1f}s, below stop-safe threshold"
        if pending_tool:
            reason += f"; latest tool is {pending_tool.get('text')}"
        return "quiet_short", [reason]
    if process_state == "exists":
        return "suspect_stalled", [
            "worker process still exists but no recent Orbital or model activity was observed",
        ]
    return "stop_safe", [
        "no pending permission, no recent model activity, and quiet duration exceeds stop-safe threshold",
    ]


def _orbital_signal(events: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    last = events[-1] if events else None
    timestamp = str(last.get("timestamp")) if last else None
    age = _age_seconds(timestamp, now)
    return {
        "last_event_id": last.get("event_id") if last else None,
        "last_event_kind": last.get("kind") if last else None,
        "last_event_text": last.get("text") if last else None,
        "last_event_timestamp": timestamp,
        "last_event_age_seconds": age,
        "event_count": len(events),
    }


def _model_signal(path: Path | None, now: datetime, thresholds: LivenessThresholds) -> dict[str, Any]:
    if path is None:
        return {"configured": False, "path": None, "available": False}
    result: dict[str, Any] = {"configured": True, "path": str(path), "available": path.exists()}
    if not path.exists():
        result["error"] = "model log does not exist"
        return result
    try:
        text = _tail_text(path, DEFAULT_TAIL_BYTES)
        stat = path.stat()
    except OSError as exc:
        result.update({"available": False, "error": str(exc)})
        return result
    lines = [line for line in text.splitlines() if line.strip()]
    last_active_idx, last_active = _last_matching(lines, MODEL_ACTIVE_MARKERS)
    last_idle_idx, last_idle = _last_matching(lines, MODEL_IDLE_MARKERS)
    _, last_cancel = _last_matching(lines, MODEL_CANCEL_MARKERS)
    mtime = datetime.fromtimestamp(stat.st_mtime, UTC)
    mtime_age = max(0.0, (now - mtime).total_seconds())
    idle_after_active = last_idle_idx is not None and last_active_idx is not None and last_idle_idx > last_active_idx
    active_recent = last_active is not None and not idle_after_active and mtime_age <= thresholds.model_active_seconds
    result.update(
        {
            "mtime": mtime.isoformat().replace("+00:00", "Z"),
            "mtime_age_seconds": mtime_age,
            "last_active_line": last_active,
            "last_idle_line": last_idle,
            "last_cancel_line": last_cancel,
            "last_active_age_seconds": mtime_age if active_recent else None,
            "active_recent": active_recent,
        }
    )
    return result


def _process_signal(run: dict[str, Any], *, inspect_process: bool) -> dict[str, Any]:
    pid = ((run.get("session") or {}).get("process_id")) if isinstance(run.get("session"), dict) else None
    result: dict[str, Any] = {"pid": pid, "inspected": inspect_process and bool(pid), "state": "unknown"}
    if not inspect_process or not pid:
        return result
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        result["state"] = "absent"
        return result
    except PermissionError:
        result["state"] = "exists"
    except OSError as exc:
        result.update({"state": "unknown", "error": str(exc)})
        return result
    else:
        result["state"] = "exists"
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid=,stat=,etime=,pcpu=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if completed.returncode == 0:
            result["ps"] = completed.stdout.strip()
        elif completed.stderr.strip():
            result["ps_error"] = completed.stderr.strip()
    except Exception as exc:
        result["ps_error"] = str(exc)
    return result


def _pending_permission(permissions: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest: dict[str, dict[str, Any]] = {}
    for permission in permissions:
        permission_id = str(permission.get("permission_id") or "")
        if permission_id:
            latest[permission_id] = permission
    for permission in latest.values():
        if permission.get("status") == "pending":
            return permission
    return None


def _latest_pending_tool(events: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    for event in reversed(events):
        kind = str(event.get("kind") or "")
        text = str(event.get("text") or "")
        if kind in {"tool_call_completed", "tool_call_failed"}:
            return None
        if kind in {"tool_call_started", "tool_call_updated"} and any(marker in text for marker in TOOL_PENDING_MARKERS):
            timestamp = str(event.get("timestamp") or "")
            return {
                "event_id": event.get("event_id"),
                "kind": kind,
                "timestamp": timestamp,
                "age_seconds": _age_seconds(timestamp, now),
                "text": event.get("text"),
            }
    return None


def _evidence(*signals: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for signal in signals:
        if not signal:
            continue
        if isinstance(signal, dict):
            text = (
                signal.get("last_event_text")
                or signal.get("last_active_line")
                or signal.get("last_idle_line")
                or signal.get("text")
                or signal.get("ps")
                or signal.get("error")
            )
            if text:
                items.append({"text": str(text)[:500], "source": _source_for_signal(signal)})
    return items


def _source_for_signal(signal: dict[str, Any]) -> str:
    if "last_event_id" in signal:
        return "orbital"
    if "last_active_line" in signal or "last_idle_line" in signal:
        return "model_log"
    if "permission_id" in signal:
        return "permission"
    if "pid" in signal:
        return "process"
    return "signal"


def _run_dir(root: Path, run_id: str) -> Path:
    if not run_id or any(char in run_id for char in "/\\:"):
        raise ValueError(f"invalid run_id: {run_id}")
    run_dir = (root / "runs" / run_id).resolve()
    if not _is_relative_to(run_dir, (root / "runs").resolve()):
        raise ValueError(f"invalid run_id: {run_id}")
    if not (run_dir / "run.json").exists():
        raise FileNotFoundError(f"unknown run_id: {run_id}")
    return run_dir


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
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def _tail_text(path: Path, max_bytes: int) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        raw = handle.read(max_bytes)
    return raw.decode("utf-8", errors="replace")


def _last_matching(lines: list[str], markers: tuple[str, ...]) -> tuple[int | None, str | None]:
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if any(marker in line for marker in markers):
            return idx, line
    return None, None


def _age_seconds(timestamp: str | None, now: datetime) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _is_recent(age_seconds: Any, threshold: float) -> bool:
    return isinstance(age_seconds, (int, float)) and age_seconds <= threshold


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
