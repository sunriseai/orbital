from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .events import TOOL_EVENT_KINDS
from .models import (
    DelegationAttribution,
    DelegationEvidenceSummary,
    DelegationReport,
    DelegationRunCounts,
    DelegationTimeSummary,
    FileAttributionRecord,
    OutcomeAssessment,
    RunMeasurement,
    RunSummary,
    RunWarning,
    TokenAccounting,
)
from .store import RunStore
from .telemetry import aggregate_models, aggregate_primary_tokens, aggregate_tokens, combine_token_usage, sum_token_usages


SummaryProvider = Callable[[str], RunSummary]


def build_delegation_report(
    store: RunStore,
    summary_provider: SummaryProvider,
    *,
    session_id: str | None = None,
    workdir: str | None = None,
    run_ids: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    objective: str | None = None,
    accepted_run_ids: list[str] | None = None,
    rejected_run_ids: list[str] | None = None,
) -> DelegationReport:
    selected_runs = _select_runs(store, workdir=workdir, run_ids=run_ids, since=since, until=until)
    accepted_ids = set(accepted_run_ids or [])
    rejected_ids = set(rejected_run_ids or [])
    measurements = [
        _measure_run(store, summary_provider(run["run_id"]), accepted_ids, rejected_ids)
        for run in selected_runs
    ]
    measurements.sort(key=lambda item: item.started_at or "")
    legacy_secondary_tokens = aggregate_tokens([measurement.tokens for measurement in measurements], source="delegation_report")
    secondary_tokens = sum_token_usages([measurement.tokens for measurement in measurements], source="secondary")
    primary_records = store.read_primary_token_usage(session_id) if session_id else []
    token_accounting = _token_accounting(primary_records, secondary_tokens)
    session = store.load_session(session_id) if session_id else None
    accepted_run_ids_result = sorted(accepted_ids & {measurement.run_id for measurement in measurements})
    rejected_run_ids_result = sorted(rejected_ids & {measurement.run_id for measurement in measurements})
    unassessed_run_ids = sorted(
        {
            measurement.run_id
            for measurement in measurements
            if measurement.run_id not in accepted_ids and measurement.run_id not in rejected_ids
        }
    )

    return DelegationReport(
        schema_version=1,
        session_id=session_id,
        objective=objective,
        workdir=workdir or _single_workdir(selected_runs),
        run_ids=[measurement.run_id for measurement in measurements],
        accepted_run_ids=accepted_run_ids_result,
        rejected_run_ids=rejected_run_ids_result,
        unassessed_run_ids=unassessed_run_ids,
        selected_profiles=sorted({measurement.profile_id for measurement in measurements}),
        profile_mix=_profile_mix(measurements),
        time=_time_summary(measurements),
        runs=_run_counts(measurements),
        outcome=_outcome(measurements),
        tokens=legacy_secondary_tokens,
        models=aggregate_models([measurement.model for measurement in measurements], source="delegation_report"),
        token_accounting=token_accounting,
        run_measurements=measurements,
        evidence=_evidence_summary(measurements),
        attribution=_attribution(store, selected_runs, measurements),
        warnings=_report_warnings(measurements, selected_runs, workdir),
        workflow=_workflow_summary(session, measurements),
    )


def _token_accounting(primary_records: list[Any], secondary_tokens: Any) -> TokenAccounting:
    primary_tokens = aggregate_primary_tokens(primary_records, source="primary")
    combined = combine_token_usage(primary_tokens, secondary_tokens)
    caveats: list[str] = []
    if not primary_tokens.known:
        caveats.append("Primary token usage is unknown because the primary harness did not report exact usage.")
    if not secondary_tokens.known:
        caveats.append("Secondary token usage is unknown because the secondary adapter did not expose exact usage.")
    if not combined.known:
        caveats.append("Combined token usage is unknown unless both primary and secondary totals are known exactly.")
    return TokenAccounting(
        primary=primary_tokens,
        secondary=secondary_tokens,
        combined=combined,
        primary_records=primary_records[-100:],
        primary_known=primary_tokens.known,
        secondary_known=secondary_tokens.known,
        caveats=caveats,
    )


def _select_runs(
    store: RunStore,
    *,
    workdir: str | None,
    run_ids: list[str] | None,
    since: str | None,
    until: str | None,
) -> list[dict[str, Any]]:
    if run_ids:
        runs = [store.load_run(run_id) for run_id in run_ids]
    else:
        runs = store.list_runs()
        if workdir:
            target = str(Path(workdir).resolve())
            runs = [run for run in runs if str(Path(str(run.get("workdir", ""))).resolve()) == target]

    start_bound = _parse_time(since) if since else None
    end_bound = _parse_time(until) if until else None
    selected: list[dict[str, Any]] = []
    for run in runs:
        run_start = _run_time_bounds(store, str(run["run_id"]))[0]
        if start_bound and run_start and run_start < start_bound:
            continue
        if end_bound and run_start and run_start > end_bound:
            continue
        selected.append(run)
    selected.sort(key=lambda run: _run_time_bounds(store, str(run["run_id"]))[0] or datetime.min.replace(tzinfo=UTC))
    return selected


def _measure_run(
    store: RunStore,
    summary: RunSummary,
    accepted_ids: set[str],
    rejected_ids: set[str],
) -> RunMeasurement:
    events = store.read_dialogue(summary.run_id, max_events=1_000_000)["events"]
    started, ended = _run_time_bounds(store, summary.run_id, events=events)
    duration = (ended - started).total_seconds() if started and ended else None
    warning_codes = [warning.code for warning in summary.warning_details]
    check_statuses = [check.status for check in summary.evidence.checks]
    accepted = summary.run_id in accepted_ids
    rejected = summary.run_id in rejected_ids
    accepted_candidate = _accepted_candidate(summary)
    return RunMeasurement(
        run_id=summary.run_id,
        status=summary.status,
        profile_id=summary.selected_profile.profile_id,
        runtime_family=summary.selected_profile.runtime_family,
        started_at=_format_time(started),
        ended_at=_format_time(ended),
        duration_seconds=duration,
        accepted=accepted,
        rejected=rejected,
        accepted_candidate=accepted_candidate,
        changed_files=summary.changed_files,
        warning_codes=warning_codes,
        check_statuses=check_statuses,
        failure_classification=summary.failure_classification,
        permission_requests=summary.evidence.permissions.requested,
        tool_calls_completed=summary.evidence.tool_calls.completed,
        write_edit_calls_completed=summary.evidence.tool_calls.completed_write_or_edit_count,
        execute_calls_completed=summary.evidence.tool_calls.completed_execute_count,
        tokens=summary.tokens,
        model=summary.model,
        policy_verdict=_measurement_policy_verdict(summary),
        policy_reason_codes=list(summary.failure_classification),
        file_attribution=summary.file_attribution,
    )


def _accepted_candidate(summary: RunSummary) -> bool:
    if summary.status != "completed":
        return False
    if any(warning.severity == "error" for warning in summary.warning_details):
        return False
    if any(check.status in {"failed", "missing"} for check in summary.evidence.checks):
        return False
    if summary.warning_details and not summary.changed_files:
        return False
    return True


def _measurement_policy_verdict(summary: RunSummary) -> str:
    reasons = set(summary.failure_classification)
    if summary.pending_permission_requests:
        return "blocked"
    if summary.status in {"created", "launching", "running", "waiting_for_permission", "stopping"}:
        return "requires_primary_review"
    if "changed_forbidden_paths" in reasons:
        return "reject"
    if "policy_violation" in reasons:
        return "requires_primary_review"
    if reasons or any(warning.severity == "error" for warning in summary.warning_details):
        return "needs_repair"
    if summary.status == "completed":
        return "accept_candidate"
    return "requires_primary_review"


def _run_time_bounds(
    store: RunStore,
    run_id: str,
    *,
    events: list[dict[str, Any]] | None = None,
) -> tuple[datetime | None, datetime | None]:
    events = events if events is not None else store.read_dialogue(run_id, max_events=1_000_000)["events"]
    timestamps = [_parse_time(event.get("timestamp")) for event in events if event.get("timestamp")]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    if timestamps:
        return min(timestamps), max(timestamps)
    final_report = store.run_dir(run_id) / "final_report.json"
    if final_report.exists():
        fallback = datetime.fromtimestamp(final_report.stat().st_mtime, UTC)
        return fallback, fallback
    return None, None


def _time_summary(measurements: list[RunMeasurement]) -> DelegationTimeSummary:
    starts = [_parse_time(item.started_at) for item in measurements if item.started_at]
    ends = [_parse_time(item.ended_at) for item in measurements if item.ended_at]
    durations = [item.duration_seconds for item in measurements if item.duration_seconds is not None]
    gaps: list[float] = []
    for previous, current in zip(measurements, measurements[1:]):
        previous_end = _parse_time(previous.ended_at)
        current_start = _parse_time(current.started_at)
        if previous_end and current_start:
            gaps.append(max(0.0, (current_start - previous_end).total_seconds()))

    started = min(starts) if starts else None
    ended = max(ends) if ends else None
    wall = (ended - started).total_seconds() if started and ended else None
    secondary = sum(durations)
    primary_gap = sum(gaps)
    return DelegationTimeSummary(
        started_at=_format_time(started),
        ended_at=_format_time(ended),
        wall_time_seconds=wall,
        secondary_run_seconds=secondary,
        primary_gap_seconds=primary_gap,
        primary_gap_ratio=(primary_gap / wall) if wall and wall > 0 else None,
        longest_secondary_run_seconds=max(durations) if durations else None,
        longest_primary_gap_seconds=max(gaps) if gaps else None,
    )


def _run_counts(measurements: list[RunMeasurement]) -> DelegationRunCounts:
    counts = DelegationRunCounts(total=len(measurements))
    for item in measurements:
        if item.status == "completed":
            counts.passed += 1
        elif item.status == "failed":
            counts.failed += 1
        elif item.status == "cancelled":
            counts.stopped += 1
        elif item.status == "interrupted":
            counts.interrupted += 1
        if item.accepted:
            counts.accepted += 1
        if item.rejected:
            counts.rejected += 1
        if item.accepted_candidate:
            counts.accepted_candidates += 1
    return counts


def _evidence_summary(measurements: list[RunMeasurement]) -> DelegationEvidenceSummary:
    evidence = DelegationEvidenceSummary()
    for item in measurements:
        evidence.tool_calls_completed += item.tool_calls_completed
        evidence.write_edit_calls_completed += item.write_edit_calls_completed
        evidence.execute_calls_completed += item.execute_calls_completed
        evidence.permission_requests += item.permission_requests
        if "policy_violation" in item.warning_codes:
            evidence.policy_violations += 1
        for classification in item.failure_classification:
            evidence.failure_classification_counts[classification] = (
                evidence.failure_classification_counts.get(classification, 0) + 1
            )
        evidence.checks_observed += sum(1 for status in item.check_statuses if status != "missing")
        evidence.checks_passed += sum(1 for status in item.check_statuses if status == "passed")
        evidence.checks_failed += sum(1 for status in item.check_statuses if status == "failed")
    return evidence


def _outcome(measurements: list[RunMeasurement]) -> OutcomeAssessment:
    if not measurements:
        return OutcomeAssessment(status="inconclusive", score=0.0, reason_codes=["no_runs"])

    score = 1.0
    reason_codes: list[str] = []
    failed_like = sum(1 for item in measurements if item.status in {"failed", "cancelled", "interrupted", "blocked"})
    policy_violations = sum(1 for item in measurements if "policy_violation" in item.warning_codes)
    no_op_passes = sum(1 for item in measurements if "no_changed_files" in item.warning_codes)
    missing_checks = sum(1 for item in measurements for status in item.check_statuses if status == "missing")
    failed_checks = sum(1 for item in measurements for status in item.check_statuses if status == "failed")
    accepted_candidates = sum(1 for item in measurements if item.accepted_candidate)

    if failed_like:
        score -= min(0.35, 0.06 * failed_like)
        reason_codes.append("failed_or_stopped_runs")
    if policy_violations:
        score -= min(0.25, 0.12 * policy_violations)
        reason_codes.append("policy_violations")
    if no_op_passes:
        score -= min(0.2, 0.08 * no_op_passes)
        reason_codes.append("no_op_passes")
    if missing_checks:
        score -= min(0.2, 0.05 * missing_checks)
        reason_codes.append("missing_requested_checks")
    if failed_checks:
        score -= min(0.25, 0.1 * failed_checks)
        reason_codes.append("failed_requested_checks")
    if accepted_candidates == 0:
        score -= 0.25
        reason_codes.append("no_accepted_candidate_runs")
    if failed_like >= accepted_candidates and failed_like > 0:
        score -= 0.15
        reason_codes.append("high_repair_burden")

    score = round(max(0.0, min(1.0, score)), 2)
    if score >= 0.85 and accepted_candidates:
        status = "success"
    elif score >= 0.5 and accepted_candidates:
        status = "partial_success"
    elif accepted_candidates:
        status = "inconclusive"
    else:
        status = "failed"
    return OutcomeAssessment(status=status, score=score, reason_codes=reason_codes)


def _attribution(
    store: RunStore,
    runs: list[dict[str, Any]],
    measurements: list[RunMeasurement],
) -> DelegationAttribution:
    workdir = _single_workdir(runs)
    final_dirty = _final_dirty_files(Path(workdir)) if workdir else []
    files_by_runs = sorted({path for item in measurements for path in item.changed_files})
    accepted_files = sorted({path for item in measurements if item.accepted or item.accepted_candidate for path in item.changed_files})
    rejected_files = sorted(
        {
            path
            for item in measurements
            if item.rejected or item.status in {"failed", "cancelled", "interrupted", "blocked"}
            for path in item.changed_files
        }
    )
    generated = _generated_artifacts(Path(workdir)) if workdir else []
    file_records = _file_records_from_measurements(measurements)
    return DelegationAttribution(
        final_dirty_files=final_dirty,
        files_changed_by_runs=files_by_runs,
        files_changed_by_accepted_runs=accepted_files,
        files_changed_by_rejected_runs=rejected_files,
        unattributed_final_files=_unattributed_files(final_dirty, files_by_runs, generated),
        rejected_files_still_present=sorted((set(final_dirty) - set(generated)) & set(rejected_files) - set(accepted_files)),
        generated_artifacts=generated,
        file_records=file_records,
        confidence_counts=_confidence_counts(file_records),
    )


def _report_warnings(
    measurements: list[RunMeasurement],
    runs: list[dict[str, Any]],
    workdir: str | None,
) -> list[RunWarning]:
    warnings: list[RunWarning] = []
    if not measurements:
        warnings.append(RunWarning(code="no_runs", message="No task runs matched the delegation report query."))
        return warnings
    if len({item.profile_id for item in measurements}) > 1:
        warnings.append(RunWarning(code="mixed_profiles", message="Delegation report includes multiple secondary profiles."))
    time_summary = _time_summary(measurements)
    if any("policy_violation" in item.warning_codes for item in measurements):
        warnings.append(RunWarning(code="policy_violations", message="One or more delegated runs hit server policy violations.", severity="error"))
    if _attribution_placeholder_needs_warning(runs, measurements, workdir):
        warnings.append(RunWarning(code="unattributed_final_files", message="Some final dirty files were not attributed to selected delegated runs."))
    return warnings


def _workflow_summary(session: dict[str, Any] | None, measurements: list[RunMeasurement]) -> dict[str, Any]:
    if not session:
        return {
            "known": False,
            "reason": "No delegation session was provided.",
        }
    requirements = list(session.get("requirements", []))
    tickets = list(session.get("tickets", []))
    attempts = list(session.get("attempts", []))
    satisfied = [
        str(item.get("requirement_id"))
        for item in requirements
        if item.get("status") == "satisfied"
    ]
    unsatisfied = [
        str(item.get("requirement_id"))
        for item in requirements
        if item.get("status") != "satisfied"
    ]
    pending_attempts = [
        str(item.get("run_id"))
        for item in attempts
        if item.get("decision") == "pending"
    ]
    measured_run_ids = {item.run_id for item in measurements}
    attempted_run_ids = {str(item.get("run_id")) for item in attempts}
    return {
        "known": True,
        "requirement_count": len(requirements),
        "satisfied_requirement_ids": sorted(satisfied),
        "unsatisfied_requirement_ids": sorted(unsatisfied),
        "ticket_count": len(tickets),
        "attempt_count": len(attempts),
        "pending_attempt_run_ids": sorted(pending_attempts),
        "attempts_missing_from_report": sorted(attempted_run_ids - measured_run_ids),
        "session_warning_count": len(session.get("session_warnings", [])),
    }


def _attribution_placeholder_needs_warning(
    runs: list[dict[str, Any]],
    measurements: list[RunMeasurement],
    workdir: str | None,
) -> bool:
    if not workdir and not _single_workdir(runs):
        return False
    attribution = _attribution_placeholder(runs, measurements, workdir)
    return bool(attribution.unattributed_final_files)


def _attribution_placeholder(
    runs: list[dict[str, Any]],
    measurements: list[RunMeasurement],
    workdir: str | None,
) -> DelegationAttribution:
    selected_workdir = workdir or _single_workdir(runs)
    if not selected_workdir:
        return DelegationAttribution()
    final_dirty = _final_dirty_files(Path(selected_workdir))
    files_by_runs = sorted({path for item in measurements for path in item.changed_files})
    generated = _generated_artifacts(Path(selected_workdir))
    file_records = _file_records_from_measurements(measurements)
    return DelegationAttribution(
        final_dirty_files=final_dirty,
        files_changed_by_runs=files_by_runs,
        unattributed_final_files=_unattributed_files(final_dirty, files_by_runs, generated),
        generated_artifacts=generated,
        file_records=file_records,
        confidence_counts=_confidence_counts(file_records),
    )


def _file_records_from_measurements(measurements: list[RunMeasurement]) -> list[FileAttributionRecord]:
    records: dict[str, FileAttributionRecord] = {}
    for item in measurements:
        for record in item.file_attribution:
            existing = records.get(record.path)
            if existing is None or _confidence_rank(record.confidence) > _confidence_rank(existing.confidence):
                records[record.path] = record
        for path in item.changed_files:
            records.setdefault(
                path,
                FileAttributionRecord(
                    path=path,
                    change_type="unknown",
                    attribution="changed_by_selected_run",
                    confidence="unknown",
                    notes=["Detailed per-run attribution was not available in this measurement."],
                ),
            )
    return sorted(records.values(), key=lambda item: item.path)


def _confidence_counts(records: list[FileAttributionRecord]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    for record in records:
        counts[record.confidence] = counts.get(record.confidence, 0) + 1
    return counts


def _confidence_rank(value: str) -> int:
    return {"unknown": 0, "low": 1, "medium": 2, "high": 3}.get(value, 0)


def _profile_mix(measurements: list[RunMeasurement]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for item in measurements:
        mix[item.profile_id] = mix.get(item.profile_id, 0) + 1
    return dict(sorted(mix.items()))


def _single_workdir(runs: list[dict[str, Any]]) -> str | None:
    workdirs = sorted({str(run.get("workdir")) for run in runs if run.get("workdir")})
    return workdirs[0] if len(workdirs) == 1 else None


def _generated_artifacts(workdir: Path) -> list[str]:
    if not workdir.exists():
        return []
    generated: list[str] = []
    for path in workdir.rglob("*"):
        if not path.exists():
            continue
        rel_parts = path.relative_to(workdir).parts
        if any(part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"} for part in rel_parts):
            generated.append(path.relative_to(workdir).as_posix())
    return sorted(generated)


def _unattributed_files(final_dirty: list[str], files_by_runs: list[str], generated: list[str]) -> list[str]:
    return sorted(set(final_dirty) - set(files_by_runs) - set(generated))


def _final_dirty_files(workdir: Path) -> list[str]:
    if not (workdir / ".git").exists():
        return []
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=workdir,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    files: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) > 3:
            files.append(line[3:].strip())
    return sorted(files)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
