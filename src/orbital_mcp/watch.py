from __future__ import annotations

import argparse
import curses
import json
import time
from pathlib import Path
from typing import Any

from .config import load_config
from .liveness import LivenessThresholds, analyze_run_liveness, latest_run_id
from .run_store import RunStore


DEFAULT_TUI_EVENTS = 18
DEFAULT_TUI_RUNS = 14
DEFAULT_TUI_TAIL_CHARS = 1600
TUI_GUTTER = 2
TUI_PANEL_GAP = 2
NOISY_EVENT_KINDS = {"agent_message_chunk"}
DETAIL_MODES = {"operator", "events", "logs"}
IMPORTANT_EVENT_KINDS = {
    "acceptance_check_failed",
    "acceptance_check_passed",
    "permission_requested",
    "permission_resolved",
    "policy_violation",
    "run_error",
    "run_finished",
    "stderr",
    "startup_prompt_sent",
    "task_submitted",
    "tool_call_completed",
    "tool_call_failed",
    "tool_call_started",
    "tool_call_updated",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch Orbital run liveness.")
    parser.add_argument("--base-dir", default=".", help="Directory containing orbital.config.json")
    parser.add_argument("--run-id", default="latest", help="Run id to inspect, or latest")
    parser.add_argument("--session-id", help="Delegation session id to inspect, or latest")
    parser.add_argument("--model-log", help="Optional llama-server log path")
    parser.add_argument("--once", action="store_true", help="Emit one JSON liveness payload and exit")
    parser.add_argument("--follow", action="store_true", help="Print a live liveness line until interrupted")
    parser.add_argument("--tui", action="store_true", help="Run a terminal dashboard for live operator status")
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--orbital-quiet-seconds", type=float, default=60.0)
    parser.add_argument("--model-active-seconds", type=float, default=30.0)
    parser.add_argument("--stop-safe-seconds", type=float, default=180.0)
    parser.add_argument("--no-process", action="store_true", help="Disable process inspection")
    parser.add_argument("--show-chunks", action="store_true", help="Include raw agent_message_chunk events in TUI/log views")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    config = load_config(base_dir)
    store_root = base_dir / config.storage_root
    thresholds = LivenessThresholds(
        orbital_quiet_seconds=args.orbital_quiet_seconds,
        model_active_seconds=args.model_active_seconds,
        stop_safe_seconds=args.stop_safe_seconds,
    )

    if args.tui:
        store = RunStore(base_dir, model_log_path=args.model_log, thresholds=thresholds)
        if args.session_id:
            curses.wrapper(
                _run_session_tui,
                store,
                args.session_id,
                args.interval_seconds,
            )
            return
        curses.wrapper(
            _run_tui,
            store,
            args.run_id,
            args.interval_seconds,
            args.show_chunks,
        )
        return

    if args.once or not args.follow:
        if args.session_id:
            store = RunStore(base_dir, model_log_path=args.model_log, thresholds=thresholds)
            payload = store.session_payload(args.session_id)
            payload["operator"] = _session_operator_summary(payload)
        else:
            payload = _payload(args, store_root, thresholds)
            payload["operator"] = _operator_run_state(_payload_to_run_payload(payload))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    try:
        while True:
            payload = _payload(args, store_root, thresholds)
            print(_format_line(payload), flush=True)
            time.sleep(max(0.2, args.interval_seconds))
    except KeyboardInterrupt:
        return


def _payload(args: argparse.Namespace, store_root: Path, thresholds: LivenessThresholds) -> dict[str, Any]:
    run_id = latest_run_id(store_root) if args.run_id == "latest" else args.run_id
    return analyze_run_liveness(
        store_root,
        run_id,
        model_log_path=args.model_log,
        inspect_process=not args.no_process,
        thresholds=thresholds,
    )


def _format_line(payload: dict[str, Any]) -> str:
    signals = payload.get("signals", {})
    orbital = signals.get("orbital", {})
    model = signals.get("model", {})
    pending_tool = signals.get("pending_tool")
    recommendation = payload.get("recommendation") or {}
    pieces = [
        f"run={payload.get('run_id')}",
        f"verdict={payload.get('verdict')}",
        f"stop_safe={payload.get('stop_safe')}",
        f"recommendation={recommendation.get('action', 'unknown')}",
        f"last_orbital={_age(orbital.get('last_event_age_seconds'))}:{orbital.get('last_event_kind')}",
    ]
    if model.get("configured"):
        pieces.append(f"model_active={model.get('active_recent')}")
        pieces.append(f"model_mtime={_age(model.get('mtime_age_seconds'))}")
    if pending_tool:
        pieces.append(f"pending_tool={_age(pending_tool.get('age_seconds'))}:{pending_tool.get('text')}")
    reasons = payload.get("reasons") or []
    if reasons:
        pieces.append(f"reason={reasons[0]}")
    if recommendation.get("summary"):
        pieces.append(f"summary={recommendation.get('summary')}")
    return " | ".join(str(piece) for piece in pieces)


def _operator_run_state(run_payload: dict[str, Any]) -> dict[str, Any]:
    run = run_payload.get("run") or {}
    liveness = run_payload.get("liveness") or {}
    activity = run_payload.get("activity") or {}
    final_report = run_payload.get("final_report") or {}
    status = str(run.get("status") or "")
    verdict = str(liveness.get("verdict") or "")
    attention_items = _attention_items(run_payload)
    if status == "running":
        if verdict == "waiting_permission":
            state = "waiting_permission"
            attention = "permission"
        elif verdict == "active_model":
            state = "quiet_working"
            attention = "model active"
        elif verdict == "suspect_stalled":
            state = "possibly_stuck"
            attention = "stuck_risk"
        elif verdict == "stop_safe":
            state = "safe_to_stop"
            attention = "safe_to_stop"
        else:
            state = "working"
            attention = "none"
    elif status == "completed":
        state = "complete"
        attention = "review_needed" if attention_items else "none"
    elif status == "failed":
        state = "failed"
        attention = "review_needed"
    elif status == "cancelled":
        state = "cancelled"
        attention = "cancelled early"
    elif status == "interrupted":
        state = "stopped"
        attention = "interrupted"
    else:
        state = "needs_review"
        attention = "review_needed"

    if attention == "none":
        for item in attention_items:
            if "permission" in item.lower():
                attention = "permission"
                break
            if "missing" in item.lower() or "failed check" in item.lower():
                attention = "missing_check"
                break
            if "warning" in item.lower() or "policy" in item.lower() or "forbidden" in item.lower():
                attention = "warning"
                break

    user_action_needed = attention not in {"none", "model active"} and state not in {"working", "quiet_working"}
    return {
        "state": state,
        "attention": attention,
        "status_sentence": _human_liveness_summary(liveness, activity, status=status),
        "current_activity": _current_activity(run_payload),
        "last_activity_age": activity.get("last_event_age_seconds"),
        "last_activity_age_text": _age(activity.get("last_event_age_seconds")),
        "stuck_risk": _stuck_risk(verdict),
        "recommendation": _recommendation_text(liveness),
        "user_action_needed": user_action_needed,
        "task_title": str((run.get("task") or {}).get("title") or run.get("run_id") or ""),
        "run_id": run.get("run_id"),
        "status": status,
        "changed_files": list((final_report or {}).get("changed_files") or run.get("changed_files") or []),
    }


def _payload_to_run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    status = ((payload.get("signals") or {}).get("run_status")) or "running"
    return {
        "run": {"run_id": payload.get("run_id"), "status": status, "task": {}},
        "liveness": payload,
        "activity": {
            "last_event_age_seconds": ((payload.get("signals") or {}).get("orbital") or {}).get("last_event_age_seconds"),
            "last_event_kind": ((payload.get("signals") or {}).get("orbital") or {}).get("last_event_kind"),
            "last_event_text": ((payload.get("signals") or {}).get("orbital") or {}).get("last_event_text"),
            "latest_pending_tool": (payload.get("signals") or {}).get("pending_tool"),
        },
    }


def _session_operator_summary(payload: dict[str, Any]) -> dict[str, Any]:
    current = _current_session_run(payload)
    return {
        "current_run": _operator_run_state(current) if current else None,
        "needs_attention": _session_attention_items(payload),
        "health": payload.get("health") or {},
    }


def _human_liveness_summary(liveness: dict[str, Any], activity: dict[str, Any], *, status: str | None = None) -> str:
    verdict = str(liveness.get("verdict") or "unknown")
    action = (liveness.get("recommendation") or {}).get("action")
    age = _age(activity.get("last_event_age_seconds"))
    if status and status != "running":
        return f"Run is {status}; review the result."
    if verdict == "active_orbital":
        return f"Worker is active. Last useful event was {age} ago. No action needed."
    if verdict == "active_model":
        return f"Orbital is quiet, but the model log indicates active generation. Keep polling."
    if verdict == "waiting_permission":
        return "Worker is waiting for a permission decision."
    if verdict == "quiet_short":
        return f"Worker is quiet for {age}, below the stop-safe threshold. Recheck soon."
    if verdict == "suspect_stalled":
        return "Worker may be stuck. Inspect activity and recheck before stopping."
    if verdict == "stop_safe":
        return "No recent activity was observed. It is reasonable to stop this run."
    if action == "inspect":
        return "Liveness is unknown. Inspect logs or events before acting."
    return "No liveness signal is available yet."


def _current_activity(run_payload: dict[str, Any]) -> str:
    liveness = run_payload.get("liveness") or {}
    signals = liveness.get("signals") or {}
    pending_permission = signals.get("pending_permission")
    if pending_permission:
        return "Waiting for permission"
    pending_tool = (run_payload.get("activity") or {}).get("latest_pending_tool") or signals.get("pending_tool")
    if pending_tool:
        return _tool_activity_label(str(pending_tool.get("text") or ""))
    model = signals.get("model") or {}
    if model.get("active_recent"):
        return "Model still generating"
    event_text = str((run_payload.get("activity") or {}).get("last_event_text") or "")
    event_kind = str((run_payload.get("activity") or {}).get("last_event_kind") or "")
    if event_kind == "agent_message_chunk":
        return "Worker is thinking or reporting progress"
    if "execute" in event_text or "bash" in event_text or "shell" in event_text:
        return "Running shell command"
    if "edit" in event_text or "write" in event_text:
        return "Editing files"
    return "No recent activity"


def _attention_items(run_payload: dict[str, Any]) -> list[str]:
    items: list[str] = []
    run = run_payload.get("run") or {}
    liveness = run_payload.get("liveness") or {}
    signals = liveness.get("signals") or {}
    recommendation = liveness.get("recommendation") or {}
    final_report = run_payload.get("final_report") or {}
    if signals.get("pending_permission"):
        summary = signals["pending_permission"].get("summary") or "permission requested"
        items.append(f"Permission needed: {summary}")
    if recommendation.get("action") == "recheck":
        items.append("Possible stall: inspect and recheck before stopping.")
    if recommendation.get("action") == "stop":
        items.append("Safe to stop: no recent activity was observed.")
    warnings = _warning_details(run_payload)
    for warning in warnings:
        code = str(warning.get("code") or "warning")
        message = str(warning.get("message") or code)
        if code in {"requested_check_missing", "missing_requested_check"}:
            items.append(message)
        elif code in {"requested_check_failed", "failed_requested_check"}:
            items.append(message)
        elif code in {"policy_violation", "changed_forbidden_paths", "changed_outside_allowed_paths"}:
            items.append(message)
        else:
            items.append(f"Warning: {message}")
    if run.get("status") in {"failed", "cancelled", "blocked", "interrupted"} and not items:
        items.append(f"Review needed: run ended as {run.get('status')}.")
    if final_report.get("last_error"):
        items.append(f"Error: {final_report.get('last_error')}")
    return _dedupe(items)


def _progress_items(events: list[dict[str, Any]], run_payload: dict[str, Any]) -> list[str]:
    items: list[str] = []
    compressed: list[dict[str, Any]] = []
    previous_key: tuple[str, str] | None = None
    previous_count = 0
    previous_event: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal previous_key, previous_count, previous_event
        if previous_event is None or previous_key is None:
            return
        event = dict(previous_event)
        if previous_count > 1:
            event["_count"] = previous_count
        compressed.append(event)
        previous_key = None
        previous_count = 0
        previous_event = None

    for event in events:
        kind = str(event.get("kind") or "")
        if kind in NOISY_EVENT_KINDS:
            continue
        if kind == "tool_call_updated":
            key = (kind, _tool_signature(str(event.get("text") or "")))
            if key == previous_key:
                previous_count += 1
                previous_event = event
                continue
            flush()
            previous_key = key
            previous_count = 1
            previous_event = event
            continue
        flush()
        compressed.append(event)
    flush()

    for event in compressed[-8:]:
        label = _event_progress_label(event)
        if label:
            items.append(label)
    pending_tool = (run_payload.get("activity") or {}).get("latest_pending_tool")
    if pending_tool:
        items.append("Current: " + _tool_activity_label(str(pending_tool.get("text") or "")))
    return _dedupe(items) or ["No progress events yet."]


def _evidence_items(run_payload: dict[str, Any]) -> list[str]:
    run = run_payload.get("run") or {}
    final_report = run_payload.get("final_report") or {}
    accounting = run_payload.get("token_accounting") or {}
    changed_files = list((final_report or {}).get("changed_files") or run.get("changed_files") or [])
    warnings = _warning_details(run_payload)
    permissions_count = ((run.get("counts") or {}).get("permission_count")) or (run_payload.get("counts") or {}).get("permissions", 0)
    pending_permission = ((run_payload.get("liveness") or {}).get("signals") or {}).get("pending_permission")
    checks = _check_counts_from_warnings(warnings, run)
    changed_preview = ", ".join(changed_files[:3])
    if len(changed_files) > 3:
        changed_preview += f", +{len(changed_files) - 3} more"
    return [
        f"Changed files: {len(changed_files)}" + (f" ({changed_preview})" if changed_preview else ""),
        f"Checks: observed={checks['observed']} passed={checks['passed']} failed={checks['failed']} missing={checks['missing']}",
        f"Permissions: requested={permissions_count} pending={'yes' if pending_permission else 'no'}",
        f"Warnings: {len(warnings)}",
        f"Tokens: {_tokens_line(accounting)}",
    ]


def _tool_activity_label(text: str) -> str:
    lowered = text.lower()
    if "todowrite" in lowered or "todo" in lowered:
        return "Updating plan"
    if "execute" in lowered or "bash" in lowered or "shell" in lowered:
        return "Running shell command"
    if "edit" in lowered or "write" in lowered:
        return "Editing files"
    if "read" in lowered:
        return "Reading files"
    return _compact(text or "Working", 80)


def _event_progress_label(event: dict[str, Any]) -> str | None:
    kind = str(event.get("kind") or "")
    timestamp = str(event.get("timestamp") or "")[-13:]
    text = str(event.get("text") or "")
    count = int(event.get("_count") or 1)
    suffix = f" ({count} updates)" if count > 1 else ""
    if kind == "task_submitted":
        return f"{timestamp} Task submitted"
    if kind == "startup_prompt_sent":
        return f"{timestamp} Worker started"
    if kind == "permission_requested":
        return f"{timestamp} Permission requested: {_compact(text, 60)}"
    if kind == "tool_call_started":
        return f"{timestamp} Started: {_tool_activity_label(text)}"
    if kind == "tool_call_updated":
        return f"{timestamp} Updated: {_tool_activity_label(text)}{suffix}"
    if kind == "tool_call_completed":
        return f"{timestamp} Completed: {_tool_activity_label(text)}"
    if kind == "tool_call_failed":
        return f"{timestamp} Failed: {_tool_activity_label(text)}"
    if kind in {"policy_violation", "run_error", "acceptance_check_failed"}:
        return f"{timestamp} Attention: {_compact(text, 70)}"
    return None


def _tool_signature(text: str) -> str:
    compact = " ".join(text.split())
    if "|" in compact:
        compact = compact.split("|", 1)[0].strip()
    return compact[:80]


def _warning_details(run_payload: dict[str, Any]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    summary = run_payload.get("summary") if isinstance(run_payload.get("summary"), dict) else {}
    for warning in summary.get("warning_details", []) if summary else []:
        if isinstance(warning, dict):
            details.append(warning)
    run = run_payload.get("run") or {}
    for warning in run.get("warning_details", []) if isinstance(run.get("warning_details"), list) else []:
        if isinstance(warning, dict):
            details.append(warning)
    final_report = run_payload.get("final_report") or {}
    if final_report.get("last_error"):
        details.append({"code": "last_error", "message": str(final_report.get("last_error")), "severity": "error"})
    return _dedupe_warnings(details)


def _check_counts_from_warnings(warnings: list[dict[str, Any]], run: dict[str, Any]) -> dict[str, int]:
    requested = len((run.get("task") or {}).get("checks") or [])
    missing = sum(1 for warning in warnings if warning.get("code") in {"requested_check_missing", "missing_requested_check"})
    failed = sum(1 for warning in warnings if warning.get("code") in {"requested_check_failed", "failed_requested_check"})
    observed = max(0, requested - missing)
    passed = max(0, observed - failed)
    return {"observed": observed, "passed": passed, "failed": failed, "missing": missing}


def _stuck_risk(verdict: str) -> str:
    if verdict in {"active_orbital", "active_model"}:
        return "low"
    if verdict in {"quiet_short", "waiting_permission"}:
        return "medium"
    if verdict in {"suspect_stalled", "stop_safe", "unknown"}:
        return "high"
    return "none"


def _recommendation_text(liveness: dict[str, Any]) -> str:
    recommendation = liveness.get("recommendation") or {}
    action = recommendation.get("action") or "inspect"
    summary = recommendation.get("summary") or ""
    if action == "keep_polling":
        return "Keep polling"
    if action == "resolve_permission":
        return "Resolve permission"
    if action == "recheck":
        return "Inspect and recheck"
    if action == "stop":
        return "Safe to stop"
    if action == "none":
        return "No action needed"
    if action == "inspect":
        return "Liveness is unknown. Inspect logs or events before acting."
    return _compact(summary or str(action), 80)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _dedupe_warnings(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        key = (str(value.get("code") or ""), str(value.get("message") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _run_tui(
    stdscr: Any,
    store: RunStore,
    requested_run_id: str,
    interval_seconds: float,
    show_chunks: bool,
) -> None:
    _init_colors()
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.nodelay(True)
    stdscr.timeout(max(200, int(interval_seconds * 1000)))
    selected_idx = 0
    pinned_run_id = None if requested_run_id == "latest" else requested_run_id
    message = "q quits, up/down selects, r refreshes, e events, l logs, o operator"
    detail_mode = "operator"
    runs: list[dict[str, Any]] = []
    while True:
        try:
            runs = store.list_runs()
            if pinned_run_id:
                idx = next((index for index, run in enumerate(runs) if run.get("run_id") == pinned_run_id), selected_idx)
                selected_idx = min(max(idx, 0), max(0, len(runs) - 1))
            else:
                selected_idx = min(max(selected_idx, 0), max(0, len(runs) - 1))
            selected = runs[selected_idx] if runs else None
            _draw_tui(stdscr, store, runs, selected_idx, selected, show_chunks, message, detail_mode)
        except Exception as exc:  # pragma: no cover - defensive for operator UI
            stdscr.erase()
            _addstr(stdscr, 0, 0, f"orbital-watch --tui error: {exc}", curses.A_BOLD)
            _addstr(stdscr, 2, 0, "Press q to quit or r to retry.")
            stdscr.refresh()

        key = stdscr.getch()
        if key in {ord("q"), ord("Q")}:
            return
        if key in {curses.KEY_UP, ord("k")}:
            selected_idx = max(0, selected_idx - 1)
            pinned_run_id = str(runs[selected_idx].get("run_id")) if runs else pinned_run_id
        elif key in {curses.KEY_DOWN, ord("j")}:
            selected_idx = min(max(0, len(runs) - 1), selected_idx + 1)
            pinned_run_id = str(runs[selected_idx].get("run_id")) if runs else pinned_run_id
        elif key in {ord("r"), ord("R")}:
            message = "refreshed"
        elif key in {ord("o"), ord("O")}:
            detail_mode = "operator"
            message = "mode:operator"
        elif key in {ord("e"), ord("E")}:
            detail_mode = "events"
            message = "mode:events"
        elif key in {ord("l"), ord("L")}:
            detail_mode = "logs"
            message = "mode:logs"
        elif key in {ord("c"), ord("C")}:
            show_chunks = not show_chunks
            message = f"agent_message_chunk {'shown' if show_chunks else 'hidden'}"


def _run_session_tui(
    stdscr: Any,
    store: RunStore,
    session_id: str,
    interval_seconds: float,
) -> None:
    _init_colors()
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.nodelay(True)
    stdscr.timeout(max(200, int(interval_seconds * 1000)))
    message = "q quits, r refreshes, e events, l logs, o operator"
    detail_mode = "operator"
    while True:
        try:
            payload = store.session_payload(session_id)
            _draw_session_tui(stdscr, payload, message, detail_mode)
        except Exception as exc:  # pragma: no cover - defensive for operator UI
            stdscr.erase()
            _addstr(stdscr, 0, 0, f"orbital-watch session error: {exc}", curses.A_BOLD)
            _addstr(stdscr, 2, 0, "Press q to quit or r to retry.")
            stdscr.refresh()
        key = stdscr.getch()
        if key in {ord("q"), ord("Q")}:
            return
        if key in {ord("r"), ord("R")}:
            message = "refreshed"
        elif key in {ord("o"), ord("O")}:
            detail_mode = "operator"
            message = "mode:operator"
        elif key in {ord("e"), ord("E")}:
            detail_mode = "events"
            message = "mode:events"
        elif key in {ord("l"), ord("L")}:
            detail_mode = "logs"
            message = "mode:logs"


def _draw_tui(
    stdscr: Any,
    store: RunStore,
    runs: list[dict[str, Any]],
    selected_idx: int,
    selected: dict[str, Any] | None,
    show_chunks: bool,
    message: str,
    detail_mode: str,
) -> None:
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    if height < 12 or width < 60:
        _addstr(stdscr, 0, 0, "Terminal is too small for Orbital TUI.")
        stdscr.refresh()
        return
    left_width = min(72, max(48, width // 3))
    separator_x = left_width + TUI_PANEL_GAP
    right_x = separator_x + TUI_PANEL_GAP
    right_width = width - right_x - TUI_GUTTER
    _draw_header(stdscr, width, message, show_chunks, detail_mode)
    _draw_runs(stdscr, runs, selected_idx, left_width, height)
    _vline(stdscr, 1, separator_x, height - 1)
    if not selected:
        _addstr(stdscr, 2, right_x, "No runs found.")
        stdscr.refresh()
        return
    run_id = str(selected.get("run_id") or "")
    payload = store.run_payload(run_id)
    liveness = payload.get("liveness") or {}
    events = _read_run_events(store, run_id)
    if detail_mode == "events":
        _draw_summary(stdscr, payload, liveness, right_x, right_width)
        visible_events = _meaningful_events(events, show_chunks=show_chunks, limit=DEFAULT_TUI_EVENTS)
        _draw_events(stdscr, visible_events, right_x, 10, right_width, height - 11)
    elif detail_mode == "logs":
        _draw_summary(stdscr, payload, liveness, right_x, right_width)
        _draw_log_tails(stdscr, store, run_id, right_x, 10, right_width, height - 11)
    else:
        _draw_operator_detail(stdscr, payload, events, right_x, 2, right_width, height - 3)
    stdscr.refresh()


def _draw_session_tui(stdscr: Any, payload: dict[str, Any], message: str, detail_mode: str) -> None:
    height, width = stdscr.getmaxyx()
    stdscr.erase()
    if height < 12 or width < 60:
        _addstr(stdscr, 0, 0, "Terminal is too small for Orbital session TUI.")
        stdscr.refresh()
        return
    session = payload.get("session") or {}
    health = payload.get("health") or {}
    _addstr(stdscr, 0, 0, f" Orbital Session  mode:{detail_mode}  {message}"[: width - 1], curses.A_REVERSE)
    if detail_mode in {"events", "logs"}:
        _draw_session_detail_mode(stdscr, payload, detail_mode, width, height)
        return
    current = _current_session_run(payload)
    current_operator = _operator_run_state(current) if current else None
    lines = [
        f"session={session.get('session_id')} status={session.get('status')} health={health.get('status')}",
        f"objective={_compact(str(session.get('objective') or ''), width - 11)}",
        f"preferred_profile={session.get('preferred_profile_id')} requirements={health.get('requirement_count')} tickets={health.get('ticket_count')} attempts={health.get('attempt_count')}",
        f"current={_compact((current_operator or {}).get('task_title') or 'none', width - 10)}",
        f"next={_session_next_action(session, health)}",
    ]
    row = 2
    for line in lines:
        _addstr(stdscr, row, TUI_GUTTER, line[: width - TUI_GUTTER - 1])
        row += 1
    row += 1
    row += 1
    _addstr(stdscr, row, TUI_GUTTER, "Needs Attention", curses.A_BOLD)
    row += 1
    for item in _session_attention_items(payload)[: max(1, height // 5)]:
        _addstr(stdscr, row, TUI_GUTTER, "- " + _compact(item, width - TUI_GUTTER - 3))
        row += 1
    row += 1
    _addstr(stdscr, row, TUI_GUTTER, "Tickets", curses.A_BOLD)
    row += 1
    _addstr(stdscr, row, TUI_GUTTER, "status        attempts attention       title", _color("divider"))
    row += 1
    for ticket in session.get("tickets", [])[: max(0, height // 4)]:
        attempts = [attempt for attempt in session.get("attempts", []) if attempt.get("ticket_id") == ticket.get("ticket_id")]
        attention = _ticket_attention(ticket, attempts)
        text = f"{str(ticket.get('status') or '')[:12]:12} {len(attempts):>8} {attention[:15]:15} {ticket.get('title')}"
        _addstr(stdscr, row, TUI_GUTTER, text[: width - TUI_GUTTER - 1])
        row += 1
        if row >= height - 7:
            break
    row += 1
    _addstr(stdscr, row, TUI_GUTTER, "Recent runs", curses.A_BOLD)
    row += 1
    _addstr(stdscr, row, TUI_GUTTER, "state              age      attention       task", _color("divider"))
    row += 1
    for run_payload in payload.get("runs", [])[: max(0, height - row - 1)]:
        operator = _operator_run_state(run_payload)
        text = f"{operator['state'][:18]:18} {operator['last_activity_age_text'][:8]:>8} {operator['attention'][:15]:15} {operator['task_title']}"
        _addstr(stdscr, row, TUI_GUTTER, text[: width - TUI_GUTTER - 1])
        row += 1
    stdscr.refresh()


def _draw_header(stdscr: Any, width: int, message: str, show_chunks: bool, detail_mode: str) -> None:
    suffix = "chunks:on" if show_chunks else "chunks:off"
    text = f" Orbital Watch  mode:{detail_mode}  {suffix}  {message}"
    _addstr(stdscr, 0, 0, text[: width - 1], curses.A_REVERSE)
    if len(text) < width:
        _addstr(stdscr, 0, len(text), " " * (width - len(text) - 1), curses.A_REVERSE)


def _draw_runs(stdscr: Any, runs: list[dict[str, Any]], selected_idx: int, width: int, height: int) -> None:
    x = TUI_GUTTER
    _addstr(stdscr, 2, x, f"Runs ({len(runs)})", curses.A_BOLD)
    _addstr(stdscr, 3, x, "state              age      attention       task", _color("divider"))
    max_rows = min(DEFAULT_TUI_RUNS, height - 5)
    for row, run in enumerate(runs[:max_rows], start=4):
        idx = row - 4
        selected = idx == selected_idx
        row_parts = _run_row_parts(run)
        attr = curses.A_REVERSE if selected else curses.A_NORMAL
        age_attr = attr if selected else _age_attr(row_parts["age_seconds"])
        _addstr(stdscr, row, x, row_parts["state"], attr)
        _addstr(stdscr, row, x + 19, row_parts["age"], age_attr)
        _addstr(stdscr, row, x + 28, row_parts["attention"], attr)
        _addstr(stdscr, row, x + 44, row_parts["title"][: max(1, width - x - 45)], attr)


def _draw_operator_detail(
    stdscr: Any,
    payload: dict[str, Any],
    events: list[dict[str, Any]],
    x: int,
    y: int,
    width: int,
    height: int,
) -> None:
    operator = _operator_run_state(payload)
    row = y
    row = _draw_block(
        stdscr,
        x,
        row,
        width,
        height,
        "Current Run",
        [
            operator["task_title"],
            f"State: {operator['state']}",
            f"Current activity: {operator['current_activity']}",
            f"Last useful activity: {operator['last_activity_age_text']} ago",
            f"Stuck risk: {operator['stuck_risk']}",
            f"Recommendation: {operator['recommendation']}",
            f"Human action needed: {'yes' if operator['user_action_needed'] else 'no'}",
            operator["status_sentence"],
        ],
    )
    row = _draw_block(stdscr, x, row + 1, width, height, "Progress", _progress_items(events, payload))
    attention = _attention_items(payload) or ["none"]
    row = _draw_block(stdscr, x, row + 1, width, height, "Needs Attention", attention)
    _draw_block(stdscr, x, row + 1, width, height, "Evidence", _evidence_items(payload))


def _draw_block(
    stdscr: Any,
    x: int,
    y: int,
    width: int,
    max_height: int,
    title: str,
    lines: list[str],
) -> int:
    if y >= max_height:
        return y
    _addstr(stdscr, y, x, title, curses.A_BOLD)
    row = y + 1
    for line in lines:
        if row >= max_height:
            break
        prefix = "- " if title in {"Progress", "Needs Attention", "Evidence"} else ""
        _addstr(stdscr, row, x, _compact(prefix + str(line), width - 1))
        row += 1
    return row


def _draw_summary(stdscr: Any, payload: dict[str, Any], liveness: dict[str, Any], x: int, width: int) -> None:
    run = payload.get("run") or {}
    activity = payload.get("activity") or {}
    signals = liveness.get("signals") or {}
    model = signals.get("model") or {}
    process = signals.get("process") or {}
    recommendation = liveness.get("recommendation") or {}
    token_accounting = payload.get("token_accounting") or {}
    lines = [
        str((run.get("task") or {}).get("title") or run.get("run_id") or ""),
        f"status={run.get('status')} profile={(run.get('harness') or {}).get('profile_id')} run={run.get('run_id')}",
        f"liveness={liveness.get('verdict')} stop_safe={liveness.get('stop_safe')} action={recommendation.get('action')}",
        f"activity={activity.get('orbital_observation')} last={activity.get('last_event_kind')} age={_age(activity.get('last_event_age_seconds'))}",
        f"pending_tool={_compact((activity.get('latest_pending_tool') or {}).get('text') or 'none', width - 14)}",
        f"model_active={model.get('active_recent')} model_mtime={_age(model.get('mtime_age_seconds'))} process={process.get('state')} pid={process.get('pid')}",
        f"tokens={_tokens_line(token_accounting)}",
    ]
    reasons = liveness.get("reasons") or []
    if reasons:
        lines.append(f"reason={_compact(str(reasons[0]), width - 8)}")
    for offset, line in enumerate(lines, start=2):
        attr = curses.A_BOLD if offset == 2 else curses.A_NORMAL
        _addstr(stdscr, offset, x, line[: max(1, width - 1)], attr)


def _draw_events(stdscr: Any, events: list[dict[str, Any]], x: int, y: int, width: int, height: int) -> None:
    _addstr(stdscr, y, x, "Meaningful events", curses.A_BOLD)
    row = y + 1
    for event in events:
        if row >= y + height:
            break
        kind = str(event.get("kind") or "event")
        timestamp = str(event.get("timestamp") or "")
        text = _compact(str(event.get("text") or ""), width - 4)
        _addstr(stdscr, row, x, f"{kind[:22]:22} {timestamp[-13:]} {text}"[: max(1, width - 1)])
        row += 1
    if not events:
        _addstr(stdscr, row, x, "No meaningful events yet.")


def _draw_session_detail_mode(stdscr: Any, payload: dict[str, Any], detail_mode: str, width: int, height: int) -> None:
    runs = payload.get("runs") or []
    current = _current_session_run(payload)
    if not current:
        _addstr(stdscr, 2, TUI_GUTTER, "No runs found for this session.")
        stdscr.refresh()
        return
    run = current.get("run") or {}
    run_id = str(run.get("run_id") or "")
    if detail_mode == "events":
        events = _meaningful_events(_events_from_payload(current), show_chunks=False, limit=max(8, height - 4))
        _draw_events(stdscr, events, TUI_GUTTER, 2, width - TUI_GUTTER - 1, height - 3)
    else:
        refs = current.get("log_refs") or {}
        lines = [f"Selected run: {run_id}"]
        for key in ["stderr", "transcript", "dialogue"]:
            if refs.get(key):
                lines.append(f"{key}: {refs[key]}")
        _draw_block(stdscr, TUI_GUTTER, 2, width - TUI_GUTTER - 1, height - 2, "Log refs", lines)
    stdscr.refresh()


def _draw_log_tails(stdscr: Any, store: RunStore, run_id: str, x: int, y: int, width: int, height: int) -> None:
    if height <= 2:
        return
    _addstr(stdscr, y, x, "Transcript / stderr tail", curses.A_BOLD)
    try:
        stderr = store.log_tail(run_id, "stderr.log", DEFAULT_TUI_TAIL_CHARS).get("text") or ""
        transcript = store.log_tail(run_id, "transcript.log", DEFAULT_TUI_TAIL_CHARS).get("text") or ""
    except (OSError, ValueError) as exc:
        _addstr(stdscr, y + 1, x, f"log tail unavailable: {exc}"[: max(1, width - 1)])
        return
    rows = _tail_lines(stderr, max(1, height // 3), "stderr") + _tail_lines(transcript, max(1, height - 3 - height // 3), "transcript")
    row = y + 1
    for line in rows:
        if row >= y + height:
            break
        _addstr(stdscr, row, x, line[: max(1, width - 1)])
        row += 1
    if not rows:
        _addstr(stdscr, row, x, "No stderr/transcript output yet.")


def _current_session_run(payload: dict[str, Any]) -> dict[str, Any] | None:
    runs = payload.get("runs") or []
    for run_payload in reversed(runs):
        run = run_payload.get("run") or {}
        if run.get("status") == "running":
            return run_payload
    return runs[-1] if runs else None


def _session_attention_items(payload: dict[str, Any]) -> list[str]:
    session = payload.get("session") or {}
    health = payload.get("health") or {}
    items: list[str] = []
    for run_payload in payload.get("runs") or []:
        run = run_payload.get("run") or {}
        for item in _attention_items(run_payload):
            items.append(f"{run.get('run_id')}: {item}")
    for run_id in health.get("pending_attempt_run_ids") or []:
        items.append(f"Unreviewed attempt: {run_id}")
    for requirement_id in health.get("unsatisfied_requirement_ids") or []:
        items.append(f"Unsatisfied requirement: {requirement_id}")
    for warning in session.get("session_warnings") or []:
        if isinstance(warning, dict):
            items.append(str(warning.get("message") or warning.get("code") or "session warning"))
    return _dedupe(items) or ["none"]


def _session_next_action(session: dict[str, Any], health: dict[str, Any]) -> str:
    if health.get("pending_attempt_run_ids"):
        return "review pending attempt"
    if health.get("unsatisfied_requirement_ids"):
        return "continue or repair unsatisfied requirements"
    if health.get("error_count"):
        return "resolve session warnings"
    if session.get("status") == "finished":
        return "finished"
    return "ready to finish or continue"


def _ticket_attention(ticket: dict[str, Any], attempts: list[dict[str, Any]]) -> str:
    if any(attempt.get("decision") == "pending" for attempt in attempts):
        return "review"
    status = str(ticket.get("status") or "")
    if status == "needs_repair":
        return "repair"
    if status == "rejected":
        return "rejected"
    if status == "accepted":
        return "none"
    return "start"


def _events_from_payload(run_payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = run_payload.get("events")
    return events if isinstance(events, list) else []


def _meaningful_events(events: list[dict[str, Any]], *, show_chunks: bool, limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for event in reversed(events):
        kind = str(event.get("kind") or "")
        if not show_chunks and kind in NOISY_EVENT_KINDS:
            continue
        if show_chunks or kind in IMPORTANT_EVENT_KINDS or kind.startswith("permission"):
            selected.append(event)
        if len(selected) >= limit:
            break
    return list(reversed(selected))


def _read_run_events(store: RunStore, run_id: str) -> list[dict[str, Any]]:
    path = store.runs_root / run_id / "dialogue.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _tail_lines(text: str, count: int, label: str) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return [f"{label}: {line}" for line in lines[-count:]]


def _compact(value: str, width: int) -> str:
    text = " ".join(value.split())
    if width <= 1:
        return ""
    if len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "…"


def _addstr(stdscr: Any, y: int, x: int, text: str, attr: int = curses.A_NORMAL) -> None:
    height, width = stdscr.getmaxyx()
    if y < 0 or y >= height or x < 0 or x >= width:
        return
    try:
        stdscr.addstr(y, x, text[: max(0, width - x - 1)], attr)
    except curses.error:
        return


def _vline(stdscr: Any, y: int, x: int, height: int) -> None:
    for row in range(y, min(y + height, stdscr.getmaxyx()[0])):
        _addstr(stdscr, row, x, "|", _color("divider"))


def _age(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "unknown"
    if value < 0:
        value = 0
    if value < 60:
        return f"{value:.1f}s"
    total_seconds = int(value)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _tokens_line(accounting: dict[str, Any]) -> str:
    primary = accounting.get("primary")
    secondary = accounting.get("secondary")
    combined = accounting.get("combined")
    model_log = accounting.get("model_log")
    return (
        f"primary={_token_total(primary)} "
        f"secondary={_token_total(secondary)} "
        f"combined={_token_total(combined)} "
        f"model_log={_model_log_token_total(model_log)}"
    )


def _token_total(value: Any) -> str:
    if value is None:
        return "unknown"
    known = value.get("known") if isinstance(value, dict) else getattr(value, "known", False)
    total = value.get("total") if isinstance(value, dict) else getattr(value, "total", None)
    if not known or total is None:
        return "unknown"
    return str(total)


def _model_log_token_total(value: Any) -> str:
    if value is None:
        return "unknown"
    known = value.get("known") if isinstance(value, dict) else getattr(value, "known", False)
    total = value.get("total") if isinstance(value, dict) else getattr(value, "total", None)
    provider = value.get("provider") if isinstance(value, dict) else getattr(value, "provider", None)
    if not known or total is None:
        return "unknown"
    return f"{provider or 'external'}:{total}"


def _run_row_parts(run: dict[str, Any]) -> dict[str, Any]:
    operator = _operator_run_state(
        {
            "run": run,
            "liveness": run.get("liveness") or {},
            "activity": run.get("activity") or {},
        }
    )
    age_seconds = (run.get("activity") or {}).get("last_event_age_seconds")
    running = str(run.get("status") or "") == "running"
    age = _age(age_seconds) if running else ""
    return {
        "state": f"{operator['state'][:18]:18}",
        "attention": f"{operator['attention'][:15]:15}",
        "age": f"{age:>8}",
        "age_seconds": age_seconds if running else None,
        "title": str(operator["task_title"]),
    }


def _init_colors() -> None:
    if not curses.has_colors():
        return
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_BLUE, -1)
    except curses.error:
        return


def _age_attr(age_seconds: Any) -> int:
    if not isinstance(age_seconds, (int, float)):
        return curses.A_NORMAL
    if age_seconds < 60:
        return _color("age_ok")
    if age_seconds < 180:
        return _color("age_warn")
    return _color("age_bad")


def _color(name: str) -> int:
    if not curses.has_colors():
        return curses.A_NORMAL
    pairs = {
        "age_ok": 1,
        "age_warn": 2,
        "age_bad": 3,
        "divider": 4,
    }
    pair = pairs.get(name)
    if not pair:
        return curses.A_NORMAL
    try:
        return curses.color_pair(pair)
    except curses.error:
        return curses.A_NORMAL


if __name__ == "__main__":
    main()
