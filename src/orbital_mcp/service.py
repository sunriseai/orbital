from __future__ import annotations

import asyncio
import fnmatch
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .adapters.acp import AcpWorkerController
from .adapters.base import AdapterSink
from .adapters.claude_cli import ClaudeCliController
from .agent_log_telemetry import agent_log_token_usage, run_time_window, scan_external_agent_token_telemetry
from .delegation_report import build_delegation_report
from .dialogue import new_event
from .events import (
    ACCEPTANCE_CHECK_FAILED,
    AGENT_MESSAGE_CHUNK,
    HOST_MESSAGE,
    PERMISSION_APPROVED,
    PERMISSION_CANCELLED,
    PERMISSION_DENIED,
    PERMISSION_REQUESTED,
    POLICY_VIOLATION,
    RUN_ERROR,
    RUN_STOPPED,
    STDERR,
    STARTUP_PROMPT_SENT,
    TASK_SUBMITTED,
    TERMINAL_STATUSES,
    TOOL_EVENT_KINDS,
    WARNING_EVENT_KINDS,
)
from .liveness import analyze_run_liveness
from .models import (
    CheckEvidence,
    DiagnosticEntry,
    DiagnosticExplainability,
    DiagnosticTimelineItem,
    DelegationRunAssessment,
    DelegationSession,
    DelegationRequirement,
    DelegationTicket,
    DelegationTicketAttempt,
    FinalReport,
    FileAttributionRecord,
    HarnessProfile,
    HarnessRunMetadata,
    LogRefs,
    PermissionOption,
    PermissionRequest,
    PermissionEvidence,
    ProfileCapabilities,
    RepairSeed,
    RunCounts,
    RunEvidence,
    RunPolicyVerdict,
    RunSummary,
    RunStatusDigest,
    RunWarning,
    SessionMetadata,
    TaskInput,
    TaskRun,
    ToolCallEvidence,
    ToolTimelineItem,
    normalize_run_status,
    to_jsonable,
)
from .permissions import choose_option
from .profiles import HarnessRegistry
from .snapshots import FileSnapshot, compare_snapshots, snapshot_workdir
from .store import RunStore
from .task_prompt import render_startup_prompt
from .telemetry import extract_run_telemetry


class TaskRunService:
    LIVENESS_STOP_CHECK_MAX_AGE_SECONDS = 120.0

    def __init__(self, registry: HarnessRegistry, store: RunStore):
        self.registry = registry
        self.store = store
        self._controllers: dict[str, AcpWorkerController | ClaudeCliController] = {}
        self._runs: dict[str, TaskRun] = {}
        self._permissions: dict[str, PermissionRequest] = {}
        self._snapshots: dict[str, FileSnapshot] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._message_buffers: dict[str, str] = {}

    def preflight(self, workdir: Path, task: TaskInput | None = None, profile_id: str | None = None) -> dict[str, Any]:
        profile, readiness = self.registry.select(workdir, task=task, profile_id=profile_id)
        capabilities = self.registry.capabilities(profile, readiness)
        return {
            "passed": readiness.ready,
            "selected_profile": to_jsonable(profile),
            "readiness": to_jsonable(readiness),
            "support": to_jsonable(profile.support),
            "classification": to_jsonable(profile.classification),
            "normalized_capabilities": to_jsonable(capabilities),
            "capability_gaps": _preflight_capability_gaps(task, capabilities),
            "expected_auth_mode": profile.auth_mode,
            "expected_cost_posture": profile.cost_posture,
            "metered_api": profile.metered_api,
            "detected_repo_state": {
                "workdir_exists": workdir.exists(),
                "is_git_repo": (workdir / ".git").exists(),
            },
        }

    async def start_task_run(
        self,
        workdir: Path,
        task: TaskInput,
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        profile, readiness = self.registry.select(workdir, task=task, profile_id=profile_id)
        if not readiness.ready:
            raise ValueError(f"profile is not ready: {profile.id}: {readiness.missing_prerequisites}")

        run_id = f"task-run-{uuid.uuid4().hex[:16]}"
        harness = _harness_metadata(profile)
        run = TaskRun(
            schema_version=1,
            run_id=run_id,
            status="launching",
            workdir=str(workdir),
            task=task,
            harness=harness,
            session=SessionMetadata(),
            counts=RunCounts(),
            log_refs=None,
        )
        run.log_refs = self.store.log_refs(run_id)
        self.store.create_run(run)
        self._runs[run_id] = run
        self._snapshots[run_id] = snapshot_workdir(workdir)
        await self._append_event(run_id, TASK_SUBMITTED, "host", task.objective)
        task_handle = asyncio.create_task(self._run_harness(run_id, profile, workdir))
        task_handle.add_done_callback(self._background_tasks.discard)
        self._background_tasks.add(task_handle)
        return self._public_run_response(run_id)

    async def send_task_message(self, run_id: str, message: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        controller = self._controllers.get(run_id)
        if not controller:
            raise ValueError(f"run is not active: {run_id}")
        await self._append_event(run_id, HOST_MESSAGE, "host", message)
        run.counts.prompt_count += 1
        self.store.save_run(run)
        result = await controller.send_prompt(message)
        if result.text:
            run.last_agent_message = result.text
        self.store.save_run(run)
        return self._public_run_response(run_id)

    def get_task_run(self, run_id: str) -> dict[str, Any]:
        if run_id in self._runs:
            return self._public_run_response(run_id)
        return self.store.load_run(run_id)

    def list_task_runs(self) -> dict[str, Any]:
        return {"runs": self.store.list_runs()}

    def get_dialogue(
        self,
        run_id: str,
        since_event_id: str | None = None,
        max_events: int = 100,
        include_raw: bool = False,
        include_agent_chunks: bool = False,
        event_kinds: list[str] | None = None,
        max_chars: int = 20_000,
    ) -> dict[str, Any]:
        payload = self.store.read_dialogue(run_id, since_event_id, max_events=1_000_000)
        allowed_kinds = set(event_kinds or [])
        events: list[dict[str, Any]] = []
        total_chars = 0
        for event in payload["events"]:
            if allowed_kinds and event.get("kind") not in allowed_kinds:
                continue
            if not include_agent_chunks and event.get("kind") == AGENT_MESSAGE_CHUNK:
                continue
            safe_event = dict(event)
            if not include_raw:
                safe_event.pop("raw", None)
            text = safe_event.get("text")
            if isinstance(text, str) and len(text) > 500:
                safe_event["text"] = text[:497].rstrip() + "..."
            event_chars = len(str(safe_event))
            if len(events) >= max_events or total_chars + event_chars > max_chars:
                return {
                    "events": events,
                    "has_more": True,
                    "raw_events_omitted": not include_raw,
                    "agent_chunks_omitted": not include_agent_chunks,
                    "max_chars": max_chars,
                }
            total_chars += event_chars
            events.append(safe_event)
        return {
            "events": events,
            "has_more": payload["has_more"] or len(events) < len(payload["events"]),
            "raw_events_omitted": not include_raw,
            "agent_chunks_omitted": not include_agent_chunks,
            "max_chars": max_chars,
        }

    def get_run_log_tail(self, run_id: str, name: str, max_bytes: int = 64 * 1024) -> dict[str, Any]:
        return self.store.read_log_tail(run_id, name, max_bytes=max_bytes)

    def get_storage_diagnostics(self, run_id: str) -> dict[str, Any]:
        return self.store.storage_diagnostics(run_id)

    def get_run_summary(self, run_id: str, max_events: int = 100) -> dict[str, Any]:
        return to_jsonable(self._run_summary(run_id, max_events=max_events))

    def get_run_policy_verdict(self, run_id: str) -> dict[str, Any]:
        return to_jsonable(self._run_policy_verdict(self._run_summary(run_id, max_events=0)))

    def get_run_status_digest(self, run_id: str) -> dict[str, Any]:
        summary = self._run_summary(run_id, max_events=0)
        verdict = self._run_policy_verdict(summary)
        next_steps = summary.diagnostic_explainability.diagnostic_next_steps
        return to_jsonable(
            RunStatusDigest(
                schema_version=1,
                run_id=run_id,
                status=summary.status,
                selected_profile=summary.selected_profile,
                changed_files=summary.changed_files,
                changed_file_count=len(summary.changed_files),
                warning_codes=[warning.code for warning in summary.warning_details],
                failure_classification=summary.failure_classification,
                evidence_status=summary.evidence_status,
                evidence_score=summary.evidence_score,
                requested_checks=summary.evidence.checks,
                pending_permission_count=len(summary.pending_permission_requests),
                tool_counts=summary.evidence.tool_calls,
                tokens_known=summary.tokens.known,
                model_known=summary.model.known,
                policy_verdict=verdict.policy_verdict,
                policy_reason_codes=verdict.reason_codes,
                recommended_action=verdict.recommended_action,
                diagnostic_timeline_count=len(summary.diagnostic_timeline),
                diagnostic_unknown_count=len(summary.diagnostic_explainability.unknown),
                diagnostic_next_step_count=len(next_steps),
                diagnostic_top_next_step=next_steps[0] if next_steps else None,
                log_refs=summary.log_refs,
            )
        )

    def get_run_liveness(self, run_id: str, model_log_path: str | None = None) -> dict[str, Any]:
        payload = analyze_run_liveness(self.store.root, run_id, model_log_path=model_log_path)
        self._record_liveness_check(run_id, payload)
        return payload

    def get_delegation_report(
        self,
        session_id: str | None = None,
        workdir: str | None = None,
        run_ids: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        objective: str | None = None,
        accepted_run_ids: list[str] | None = None,
        rejected_run_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        report_objective = objective
        if session_id:
            session = self.store.load_session(session_id)
            workdir = workdir or session.get("workdir")
            run_ids = run_ids or list(session.get("run_ids", []))
            report_objective = report_objective or session.get("objective")
            accepted_run_ids = accepted_run_ids or _assessed_run_ids(session, "accepted")
            rejected_run_ids = rejected_run_ids or _assessed_run_ids(session, "rejected")
        report = build_delegation_report(
            self.store,
            lambda run_id: self._run_summary(run_id, max_events=1_000_000),
            session_id=session_id,
            workdir=workdir,
            run_ids=run_ids,
            since=since,
            until=until,
            objective=report_objective,
            accepted_run_ids=accepted_run_ids,
            rejected_run_ids=rejected_run_ids,
        )
        return to_jsonable(report)

    def start_delegation_session(
        self,
        workdir: Path,
        objective: str,
        preferred_profile_id: str | None = None,
        primary_harness: str | None = None,
        max_runs: int | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        session = DelegationSession(
            schema_version=1,
            session_id=f"delegation-session-{uuid.uuid4().hex[:16]}",
            status="active",
            objective=objective,
            workdir=str(workdir),
            preferred_profile_id=preferred_profile_id,
            primary_harness=primary_harness,
            max_runs=max_runs,
            created_at=now,
            updated_at=now,
        )
        self.store.save_session(session)
        profile = None
        readiness = None
        if preferred_profile_id:
            profile, readiness = self.registry.select(workdir, profile_id=preferred_profile_id)
        return {
            "session": to_jsonable(session),
            "preferred_profile": to_jsonable(profile) if profile else None,
            "readiness": to_jsonable(readiness) if readiness else None,
            "recommended_next_calls": [
                "list_harness_profiles",
                "create_requirement",
                "create_delegation_ticket",
                "start_ticket_run",
                "start_task_run",
                "record_attempt_review",
                "record_delegation_run_assessment",
                "get_delegation_session",
                "finish_delegation_session",
            ],
        }

    def create_requirement(
        self,
        session_id: str,
        requirement_id: str,
        statement: str,
        proof_needed: str,
    ) -> dict[str, Any]:
        session = _session_from_dict(self.store.load_session(session_id))
        if not requirement_id.strip():
            raise ValueError("requirement_id is required")
        if not statement.strip():
            raise ValueError("statement is required")
        if not proof_needed.strip():
            raise ValueError("proof_needed is required")
        now = _utc_now()
        requirement = DelegationRequirement(
            requirement_id=requirement_id.strip(),
            statement=statement.strip(),
            proof_needed=proof_needed.strip(),
            updated_at=now,
        )
        session.requirements = [
            existing for existing in session.requirements if existing.requirement_id != requirement.requirement_id
        ]
        session.requirements.append(requirement)
        session.requirements.sort(key=lambda item: item.requirement_id)
        session.updated_at = now
        self._refresh_session_warnings(session)
        self.store.save_session(session)
        return self.get_delegation_session(session_id)

    def update_requirement_status(
        self,
        session_id: str,
        requirement_id: str,
        status: str,
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        if status not in {"not_started", "in_progress", "satisfied", "blocked"}:
            raise ValueError("status must be not_started, in_progress, satisfied, or blocked")
        session = _session_from_dict(self.store.load_session(session_id))
        for requirement in session.requirements:
            if requirement.requirement_id == requirement_id:
                requirement.status = status  # type: ignore[assignment]
                requirement.evidence = evidence or requirement.evidence
                requirement.updated_at = _utc_now()
                session.updated_at = requirement.updated_at
                self._refresh_session_warnings(session)
                self.store.save_session(session)
                return self.get_delegation_session(session_id)
        raise ValueError(f"unknown requirement_id: {requirement_id}")

    def create_delegation_ticket(
        self,
        session_id: str,
        ticket_id: str,
        title: str,
        objective: str,
        requirement_ids: list[str] | None = None,
        allowed_paths: list[str] | None = None,
        forbidden_paths: list[str] | None = None,
        checks: list[str] | None = None,
        acceptance_hints: list[str] | None = None,
        rules: list[str] | None = None,
    ) -> dict[str, Any]:
        session = _session_from_dict(self.store.load_session(session_id))
        if not ticket_id.strip():
            raise ValueError("ticket_id is required")
        if not title.strip():
            raise ValueError("title is required")
        if not objective.strip():
            raise ValueError("objective is required")
        missing = sorted(set(requirement_ids or []) - {item.requirement_id for item in session.requirements})
        if missing:
            raise ValueError("unknown requirement_id(s): " + ", ".join(missing))
        now = _utc_now()
        ticket = DelegationTicket(
            ticket_id=ticket_id.strip(),
            title=title.strip(),
            objective=objective.strip(),
            requirement_ids=requirement_ids or [],
            allowed_paths=allowed_paths or [],
            forbidden_paths=forbidden_paths or [],
            checks=checks or [],
            acceptance_hints=acceptance_hints or [],
            rules=rules or [],
            created_at=now,
            updated_at=now,
        )
        session.tickets = [existing for existing in session.tickets if existing.ticket_id != ticket.ticket_id]
        session.tickets.append(ticket)
        session.tickets.sort(key=lambda item: item.ticket_id)
        for requirement in session.requirements:
            if requirement.requirement_id in ticket.requirement_ids and requirement.status == "not_started":
                requirement.status = "in_progress"
                requirement.updated_at = now
        session.updated_at = now
        self._refresh_session_warnings(session)
        self.store.save_session(session)
        return self.get_delegation_session(session_id)

    async def start_ticket_run(
        self,
        session_id: str,
        ticket_id: str,
        harness_profile_id: str | None = None,
    ) -> dict[str, Any]:
        session = _session_from_dict(self.store.load_session(session_id))
        ticket = _ticket_by_id(session, ticket_id)
        profile_id = harness_profile_id or session.preferred_profile_id
        if session.preferred_profile_id and profile_id and profile_id != session.preferred_profile_id:
            raise ValueError(
                f"harness_profile_id {profile_id} does not match session preferred profile {session.preferred_profile_id}"
            )
        task = TaskInput(
            title=ticket.title,
            objective=ticket.objective,
            allowed_paths=ticket.allowed_paths,
            forbidden_paths=ticket.forbidden_paths,
            acceptance_hints=ticket.acceptance_hints,
            checks=ticket.checks,
            rules=ticket.rules,
        )
        response = await self.start_task_run(Path(session.workdir), task, profile_id=profile_id)
        run_id = response["run_id"]
        attempt = DelegationTicketAttempt(
            ticket_id=ticket.ticket_id,
            run_id=run_id,
            attempt_number=1 + sum(1 for item in session.attempts if item.ticket_id == ticket.ticket_id),
            created_at=_utc_now(),
        )
        session.run_ids = [existing for existing in session.run_ids if existing != run_id]
        session.run_ids.append(run_id)
        session.attempts.append(attempt)
        ticket.status = "running"
        ticket.updated_at = attempt.created_at
        session.updated_at = attempt.created_at
        self._refresh_session_warnings(session)
        self.store.save_session(session)
        response["ticket"] = to_jsonable(ticket)
        response["attempt"] = to_jsonable(attempt)
        return response

    def record_delegation_run_assessment(
        self,
        session_id: str,
        run_id: str,
        decision: str,
        rationale: str,
        inspected_files: list[str] | None = None,
        verification_commands: list[str] | None = None,
        repair_prompt: str | None = None,
    ) -> dict[str, Any]:
        if decision not in {"accepted", "rejected", "needs_repair"}:
            raise ValueError("decision must be accepted, rejected, or needs_repair")
        session = _session_from_dict(self.store.load_session(session_id))
        self.store.load_run(run_id)
        assessment = DelegationRunAssessment(
            run_id=run_id,
            decision=decision,  # type: ignore[arg-type]
            rationale=rationale,
            inspected_files=inspected_files or [],
            verification_commands=verification_commands or [],
            repair_prompt=repair_prompt,
            created_at=_utc_now(),
        )
        session.run_ids = [existing for existing in session.run_ids if existing != run_id]
        session.run_ids.append(run_id)
        session.assessments = [existing for existing in session.assessments if existing.run_id != run_id]
        session.assessments.append(assessment)
        session.updated_at = _utc_now()
        self._apply_review_to_attempts(session, run_id, decision)
        self._refresh_session_warnings(session)
        self.store.save_session(session)
        return self.get_delegation_session(session_id)

    def record_attempt_review(
        self,
        session_id: str,
        ticket_id: str,
        run_id: str,
        decision: str,
        rationale: str,
        inspected_files: list[str] | None = None,
        verification_commands: list[str] | None = None,
        repair_prompt: str | None = None,
    ) -> dict[str, Any]:
        session = _session_from_dict(self.store.load_session(session_id))
        _ticket_by_id(session, ticket_id)
        if not any(attempt.ticket_id == ticket_id and attempt.run_id == run_id for attempt in session.attempts):
            raise ValueError(f"run_id is not an attempt for ticket_id: {ticket_id}")
        result = self.record_delegation_run_assessment(
            session_id,
            run_id,
            decision,
            rationale,
            inspected_files=inspected_files,
            verification_commands=verification_commands,
            repair_prompt=repair_prompt,
        )
        return result

    def create_repair_ticket_from_run(
        self,
        session_id: str,
        ticket_id: str,
        run_id: str,
        repair_ticket_id: str | None = None,
    ) -> dict[str, Any]:
        session = _session_from_dict(self.store.load_session(session_id))
        original = _ticket_by_id(session, ticket_id)
        if not any(attempt.ticket_id == ticket_id and attempt.run_id == run_id for attempt in session.attempts):
            raise ValueError(f"run_id is not an attempt for ticket_id: {ticket_id}")
        verdict = self._run_policy_verdict(self._run_summary(run_id, max_events=0), source_ticket=original)
        if not verdict.repair_seed:
            raise ValueError(f"run does not have a deterministic repair seed: {verdict.policy_verdict}")
        new_id = repair_ticket_id or f"{ticket_id}-repair-{1 + sum(1 for item in session.tickets if item.ticket_id.startswith(ticket_id + '-repair-'))}"
        self._apply_review_to_attempts(
            session,
            run_id,
            "rejected" if verdict.policy_verdict == "reject" else "needs_repair",
        )
        session.updated_at = _utc_now()
        self._refresh_session_warnings(session)
        self.store.save_session(session)
        return self.create_delegation_ticket(
            session_id,
            new_id,
            verdict.repair_seed.title,
            verdict.repair_seed.objective,
            requirement_ids=original.requirement_ids,
            allowed_paths=verdict.repair_seed.allowed_paths,
            forbidden_paths=verdict.repair_seed.forbidden_paths,
            checks=verdict.repair_seed.checks,
            acceptance_hints=verdict.repair_seed.acceptance_hints,
            rules=verdict.repair_seed.rules,
        )

    def get_next_recommended_action(self, session_id: str) -> dict[str, Any]:
        session = _session_from_dict(self.store.load_session(session_id))
        self._refresh_session_warnings(session)
        self.store.save_session(session)
        action = self._next_action(session)
        return {
            "session_id": session_id,
            "recommended_action": action,
            "session_warnings": to_jsonable(session.session_warnings),
        }

    def get_delegation_session(self, session_id: str) -> dict[str, Any]:
        session_obj = _session_from_dict(self.store.load_session(session_id))
        self._refresh_session_warnings(session_obj)
        self.store.save_session(session_obj)
        session = self.store.load_session(session_id)
        report = self.get_delegation_report(session_id=session_id)
        return {
            "session": session,
            "report": report,
            "pending_run_ids": report["unassessed_run_ids"],
            "next_recommended_action": self._next_action(session_obj),
            "session_health": _session_health(session_obj),
        }

    def finish_delegation_session(
        self,
        session_id: str,
        final_status: str,
        final_summary: str | None = None,
        final_verification: str | None = None,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        if final_status not in {"success", "partial_success", "failed", "blocked", "inconclusive"}:
            raise ValueError("final_status must be success, partial_success, failed, blocked, or inconclusive")
        session = _session_from_dict(self.store.load_session(session_id))
        if final_status == "success" and not override_reason:
            unsatisfied = [req.requirement_id for req in session.requirements if req.status != "satisfied"]
            unreviewed = [attempt.run_id for attempt in session.attempts if attempt.decision == "pending"]
            if unsatisfied:
                raise ValueError("cannot finish success with unsatisfied requirements without override_reason")
            if unreviewed:
                raise ValueError("cannot finish success with unreviewed attempts without override_reason")
        session.status = "finished"
        session.final_status = final_status
        session.final_summary = final_summary
        if override_reason:
            suffix = f"Override reason: {override_reason}"
            session.final_verification = f"{final_verification}\n{suffix}" if final_verification else suffix
        else:
            session.final_verification = final_verification
        session.updated_at = _utc_now()
        session.finished_at = session.updated_at
        self.store.save_session(session)
        return self.get_delegation_session(session_id)

    async def run_task_and_wait(
        self,
        workdir: Path,
        task: TaskInput,
        profile_id: str | None = None,
        timeout_seconds: float = 120,
        poll_interval_ms: int = 250,
        max_events: int = 100,
    ) -> dict[str, Any]:
        response = await self.start_task_run(workdir, task, profile_id=profile_id)
        run_id = response["run_id"]
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            run = self.store.load_run(run_id)
            if normalize_run_status(run.get("status")) in TERMINAL_STATUSES:
                return self.get_run_summary(run_id, max_events=max_events)
            if asyncio.get_running_loop().time() >= deadline:
                summary = self.get_run_summary(run_id, max_events=max_events)
                summary["timed_out"] = True
                summary["warnings"] = [
                    *summary.get("warnings", []),
                    f"Run did not reach a terminal status within {timeout_seconds:g} seconds",
                ]
                return summary
            await asyncio.sleep(max(poll_interval_ms, 10) / 1000)

    async def resolve_permission(
        self,
        run_id: str,
        permission_id: str,
        decision: str,
        option_id: str | None = None,
        rationale: str | None = None,
        adapter_request_id: str | None = None,
        deciding_primary: str | None = None,
    ) -> dict[str, Any]:
        if decision not in {"approve", "deny"}:
            raise ValueError("decision must be approve or deny")
        permission = self._permissions.get(permission_id)
        if not permission or permission.run_id != run_id:
            stored = [
                item
                for item in self.store.read_permissions(run_id)
                if item.get("permission_id") == permission_id and item.get("status") == "pending"
            ]
            if stored:
                raise ValueError("permission_not_resolvable_after_restart")
            raise ValueError(f"unknown permission: {permission_id}")
        if permission.status != "pending":
            raise ValueError(f"permission is already resolved: {permission.status}")
        if adapter_request_id is not None and str(adapter_request_id) != permission.adapter_request_id:
            raise ValueError(
                f"unknown adapter request for permission {permission.permission_id}: {adapter_request_id}"
            )
        selected = choose_option(permission, decision, option_id)
        controller = self._controllers.get(run_id)
        if not controller:
            raise ValueError(f"run is not active: {run_id}")
        try:
            adapter_result = await controller.resolve_permission(permission.adapter_request_id, selected)
        except Exception as exc:
            permission.decision = decision  # type: ignore[assignment]
            permission.resolved_option_id = selected
            permission.decision_rationale = rationale.strip() if isinstance(rationale, str) and rationale.strip() else None
            permission.deciding_primary = _clean_optional_text(deciding_primary)
            permission.resolved_at = _utc_now()
            permission.adapter_resolution_status = "failed"
            permission.adapter_result = {
                "error": str(exc) or exc.__class__.__name__,
                "exception_type": exc.__class__.__name__,
            }
            self.store.append_permission(permission)
            raise ValueError(f"adapter_permission_resolution_failed: {permission.permission_id}: {exc}") from exc
        permission.status = "approved" if decision == "approve" else "denied"
        permission.decision = decision  # type: ignore[assignment]
        permission.resolved_option_id = selected
        permission.decision_rationale = rationale.strip() if isinstance(rationale, str) and rationale.strip() else None
        permission.deciding_primary = _clean_optional_text(deciding_primary)
        permission.resolved_at = _utc_now()
        permission.adapter_resolution_status = _adapter_resolution_status(adapter_result, selected)
        permission.adapter_result = adapter_result if isinstance(adapter_result, dict) else None
        run = self._get_run(run_id)
        if permission.status == "approved":
            run.counts.approved_permission_count += 1
            run.status = "running"
        else:
            run.counts.denied_permission_count += 1
            run.status = "blocked"
        self.store.append_permission(permission)
        self.store.save_run(run)
        await self._append_event(
            run_id,
            f"permission_{permission.status}",
            "host",
            permission.summary,
            {
                "permission_id": permission.permission_id,
                "adapter_request_id": permission.adapter_request_id,
                "resolved_option_id": permission.resolved_option_id,
                "decision": permission.decision,
                "decision_rationale": permission.decision_rationale,
                "deciding_primary": permission.deciding_primary,
                "adapter_resolution_status": permission.adapter_resolution_status,
                "adapter_result": permission.adapter_result,
            },
        )
        return {"permission": to_jsonable(permission), "run": self._public_run_response(run_id)}

    async def stop_task_run(self, run_id: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        self._warn_if_stop_without_liveness(run_id)
        controller = self._controllers.get(run_id)
        for permission in self._permissions.values():
            if permission.run_id == run_id and permission.status == "pending":
                permission.status = "cancelled"
                run.counts.cancelled_permission_count += 1
                self.store.append_permission(permission)
                controller = self._controllers.get(run_id)
                if controller:
                    try:
                        await controller.cancel_permission(permission.adapter_request_id)
                    except Exception:
                        pass
        if controller:
            await controller.stop()
        stop_method = getattr(controller, "last_stop_method", None) if controller else None
        run.status = "cancelled"
        self._finalize_changed_files(run)
        self._write_final_report(run)
        self.store.save_run(run)
        stop_text = f"Run stopped (stop_method={stop_method})" if stop_method else "Run stopped"
        await self._append_event(run_id, RUN_STOPPED, "server", stop_text)
        return self._public_run_response(run_id)

    async def _run_harness(self, run_id: str, profile: HarnessProfile, workdir: Path) -> None:
        run = self._get_run(run_id)
        sink = _ServiceSink(self, run_id)
        controller = _controller_for_profile(run_id, sink, profile)
        self._controllers[run_id] = controller
        try:
            run.status = "running"
            self.store.save_run(run)
            await controller.launch(profile, workdir)
            session = await controller.initialize()
            run.session.adapter_session_id = session.session_id
            run.session.process_id = session.process_id
            self.store.save_run(run)
            prompt = render_startup_prompt(run.task, workdir)
            await self._append_event(run_id, STARTUP_PROMPT_SENT, "server", prompt)
            run.counts.prompt_count += 1
            self.store.save_run(run)
            result = await controller.send_prompt(prompt)
            if result.text and not self._message_buffers.get(run_id):
                run.last_agent_message = result.text
            run.adapter_status = result.status
            run.status = "completed" if result.status in {"passed", "completed", "ok", "success"} else "failed"
        except asyncio.CancelledError:
            if run.status != "cancelled":
                run.status = "interrupted"
            raise
        except Exception as exc:
            if run.status != "cancelled":
                run.status = "failed"
                run.last_error = str(exc)
                await self._append_event(run_id, RUN_ERROR, "server", str(exc))
        finally:
            self._finalize_changed_files(run)
            if run.status == "completed":
                acceptance_error = _validate_expected_outputs(run)
                if acceptance_error:
                    run.status = "failed"
                    run.last_error = acceptance_error
                    await self._append_event(run_id, ACCEPTANCE_CHECK_FAILED, "server", acceptance_error)
            self._write_final_report(run)
            self.store.save_run(run)
            self._controllers.pop(run_id, None)
            if run.status not in {"cancelled", "interrupted"}:
                try:
                    await controller.stop()
                except Exception:
                    pass

    async def _append_event(self, run_id: str, kind: str, speaker: str, text: str | None, raw: Any = None) -> None:
        event = new_event(run_id, kind, speaker, text=text, raw=raw)
        self.store.append_dialogue(event)

    def _public_run_response(self, run_id: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        pending = [
            permission
            for permission in self._permissions.values()
            if permission.run_id == run_id and permission.status == "pending"
        ]
        digest = self.get_run_status_digest(run_id)
        return {
            "run_id": run_id,
            "selected_profile": to_jsonable(run.harness),
            "status": normalize_run_status(run.status),
            "status_digest": digest,
            "raw_events_omitted": True,
            "pending_permission_requests": to_jsonable(pending),
            "log_refs": to_jsonable(run.log_refs),
        }

    def _get_run(self, run_id: str) -> TaskRun:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise ValueError(f"unknown run_id: {run_id}") from exc

    def _finalize_changed_files(self, run: TaskRun) -> None:
        start = self._snapshots.get(run.run_id)
        if not start:
            return
        attribution = compare_snapshots(start, snapshot_workdir(Path(run.workdir)))
        run.pre_existing_changed_files = attribution.pre_existing_changed_files
        run.changed_since_run_start = attribution.changed_since_run_start
        run.changed_files = attribution.changed_files
        run.file_attribution = [
            FileAttributionRecord(
                path=item.path,
                change_type=item.change_type,
                attribution=item.attribution,
                confidence=item.confidence,  # type: ignore[arg-type]
                notes=list(item.notes),
            )
            for item in attribution.files
        ]

    def _write_final_report(self, run: TaskRun) -> None:
        self.store.save_final_report(
            FinalReport(
                schema_version=1,
                run_id=run.run_id,
                status=run.status,
                changed_files=run.changed_files,
                pre_existing_changed_files=run.pre_existing_changed_files,
                changed_since_run_start=run.changed_since_run_start,
                file_attribution=run.file_attribution,
                final_response=run.last_agent_message,
                last_error=run.last_error,
                harness=run.harness,
                adapter_status=run.adapter_status,
            )
        )

    def _record_liveness_check(self, run_id: str, payload: dict[str, Any]) -> None:
        for session in self._sessions_containing_run(run_id):
            session.last_liveness_checks[run_id] = {
                "timestamp": _utc_now(),
                "verdict": payload.get("verdict"),
                "recommendation": payload.get("recommendation"),
                "stop_safe": payload.get("stop_safe"),
            }
            self._refresh_session_warnings(session)
            self.store.save_session(session)

    def _warn_if_stop_without_liveness(self, run_id: str) -> None:
        for session in self._sessions_containing_run(run_id):
            check = session.last_liveness_checks.get(run_id) or {}
            recommendation = check.get("recommendation") if isinstance(check.get("recommendation"), dict) else {}
            check_age = _seconds_since_iso(check.get("timestamp"))
            recent = check_age is not None and check_age <= self.LIVENESS_STOP_CHECK_MAX_AGE_SECONDS
            if recent and (recommendation.get("stop_allowed") is True or recommendation.get("action") == "stop"):
                continue
            reason_bits = [
                f"last_verdict={check.get('verdict') or 'none'}",
                f"last_action={recommendation.get('action') or 'none'}",
                f"last_check_age_seconds={check_age:.1f}" if check_age is not None else "last_check_age_seconds=unknown",
            ]
            _add_session_warning(
                session,
                "stop_without_liveness_check",
                f"Run {run_id} was stopped without a recent stop-allowed liveness recommendation ({', '.join(reason_bits)}).",
                severity="warning",
            )
            self.store.save_session(session)

    def _sessions_containing_run(self, run_id: str) -> list[DelegationSession]:
        sessions: list[DelegationSession] = []
        for value in self.store.list_sessions():
            session = _session_from_dict(value)
            if run_id in session.run_ids or any(attempt.run_id == run_id for attempt in session.attempts):
                sessions.append(session)
        return sessions

    def _apply_review_to_attempts(self, session: DelegationSession, run_id: str, decision: str) -> None:
        now = _utc_now()
        for attempt in session.attempts:
            if attempt.run_id != run_id:
                continue
            attempt.decision = decision  # type: ignore[assignment]
            attempt.reviewed_at = now
            try:
                ticket = _ticket_by_id(session, attempt.ticket_id)
            except ValueError:
                continue
            ticket.status = decision  # type: ignore[assignment]
            ticket.updated_at = now

    def _refresh_session_warnings(self, session: DelegationSession) -> None:
        existing = [
            warning
            for warning in session.session_warnings
            if warning.code
            not in {
                "changed_outside_allowed_paths",
                "changed_forbidden_paths",
                "profile_mismatch",
                "accepted_missing_review_evidence",
                "unsatisfied_requirements",
                "unreviewed_attempts",
            }
        ]
        session.session_warnings = existing
        self._add_attempt_warnings(session)
        if session.status == "finished":
            unsatisfied = [
                requirement.requirement_id
                for requirement in session.requirements
                if requirement.status != "satisfied"
            ]
            if unsatisfied:
                _add_session_warning(
                    session,
                    "unsatisfied_requirements",
                    "Finished session has unsatisfied requirement(s): " + ", ".join(sorted(unsatisfied)),
                )
        unreviewed = [attempt.run_id for attempt in session.attempts if attempt.decision == "pending"]
        if unreviewed:
            _add_session_warning(
                session,
                "unreviewed_attempts",
                "Session has unreviewed ticket attempt(s): " + ", ".join(sorted(unreviewed)),
            )

    def _add_attempt_warnings(self, session: DelegationSession) -> None:
        ticket_by_id = {ticket.ticket_id: ticket for ticket in session.tickets}
        assessment_by_run = {assessment.run_id: assessment for assessment in session.assessments}
        for attempt in session.attempts:
            ticket = ticket_by_id.get(attempt.ticket_id)
            if not ticket:
                continue
            try:
                run = self.store.load_run(attempt.run_id)
            except (OSError, ValueError, FileNotFoundError):
                continue
            profile_id = ((run.get("harness") or {}).get("profile_id")) if isinstance(run.get("harness"), dict) else None
            if session.preferred_profile_id and profile_id and profile_id != session.preferred_profile_id:
                _add_session_warning(
                    session,
                    "profile_mismatch",
                    f"Run {attempt.run_id} used {profile_id}, not preferred profile {session.preferred_profile_id}.",
                )
            changed = self._run_changed_files(attempt.run_id, run)
            outside = _paths_outside_allowed(changed, ticket.allowed_paths)
            if outside:
                _add_session_warning(
                    session,
                    "changed_outside_allowed_paths",
                    f"Run {attempt.run_id} changed path(s) outside allowed_paths: " + ", ".join(outside),
                )
            forbidden = _paths_matching(changed, ticket.forbidden_paths)
            if forbidden:
                _add_session_warning(
                    session,
                    "changed_forbidden_paths",
                    f"Run {attempt.run_id} changed forbidden path(s): " + ", ".join(forbidden),
                    severity="error",
                )
            assessment = assessment_by_run.get(attempt.run_id)
            if assessment and assessment.decision == "accepted":
                if not assessment.inspected_files or not assessment.verification_commands:
                    _add_session_warning(
                        session,
                        "accepted_missing_review_evidence",
                        f"Accepted run {attempt.run_id} is missing inspected files or verification commands.",
                    )

    def _run_changed_files(self, run_id: str, run: dict[str, Any]) -> list[str]:
        final_report_error = None
        try:
            final_report = self.store.load_final_report(run_id) or {}
        except Exception as exc:
            final_report = {}
            final_report_error = str(exc)
        return list(final_report.get("changed_files", run.get("changed_files", [])))

    def _run_summary(self, run_id: str, max_events: int = 100) -> RunSummary:
        run = self.store.load_run(run_id)
        final_report_error = None
        try:
            final_report = self.store.load_final_report(run_id) or {}
        except Exception as exc:
            final_report = {}
            final_report_error = str(exc)
        all_dialogue = self.store.read_dialogue(run_id, max_events=1_000_000)["events"]
        dialogue = self.store.read_dialogue(run_id, max_events=max_events)["events"]
        permissions = self.store.read_permissions(run_id)
        latest_permissions: dict[str, dict[str, Any]] = {}
        for permission in permissions:
            permission_id = str(permission.get("permission_id") or "")
            if permission_id:
                latest_permissions[permission_id] = permission
        pending_permissions = [
            _permission_from_dict(permission)
            for permission in latest_permissions.values()
            if permission.get("status") == "pending"
        ]
        seen_permission_ids = {permission.permission_id for permission in pending_permissions}
        for permission in self._permissions.values():
            if (
                permission.run_id == run_id
                and permission.status == "pending"
                and permission.permission_id not in seen_permission_ids
            ):
                pending_permissions.append(permission)

        tool_timeline = [
            ToolTimelineItem(
                event_id=str(event["event_id"]),
                timestamp=str(event["timestamp"]),
                kind=str(event["kind"]),
                speaker=str(event["speaker"]),
                text=event.get("text"),
            )
            for event in dialogue
            if event.get("kind") in TOOL_EVENT_KINDS
        ]
        changed_files = final_report.get("changed_files", run.get("changed_files", []))
        changed_since_run_start = final_report.get(
            "changed_since_run_start",
            run.get("changed_since_run_start", []),
        )
        file_attribution = [
            _file_attribution_from_dict(item)
            for item in final_report.get("file_attribution", run.get("file_attribution", []))
        ]
        evidence = _run_evidence(run, all_dialogue, permissions)
        adapter_telemetry = extract_run_telemetry(self.store.run_dir(run_id), all_dialogue)
        since, until = run_time_window(all_dialogue)
        external_agent_logs = scan_external_agent_token_telemetry(
            project=run.get("workdir"),
            since=since,
            until=until,
            require_unique=True,
        )
        canonical_tokens = agent_log_token_usage(external_agent_logs)
        token_sources = {
            "external_agent_logs": external_agent_logs,
            "adapter_payloads": adapter_telemetry.tokens,
        }
        warning_details = _run_warning_details(
            run=run,
            final_report=final_report,
            events=all_dialogue,
            evidence=evidence,
            changed_files=changed_files,
            changed_since_run_start=changed_since_run_start,
            final_report_error=final_report_error,
        )
        warnings = [warning.message for warning in warning_details]
        if run.get("last_error") and run["last_error"] not in warnings:
            warnings.append(run["last_error"])
        evidence_groups = _evidence_groups(warning_details)
        evidence_status = _evidence_status(evidence_groups)
        evidence_score = _evidence_score(evidence_groups)
        status = normalize_run_status(run.get("status"))
        normalized_run = {**run, "status": status}
        failure_classification = _failure_classification(
            run=normalized_run,
            evidence=evidence,
            warning_details=warning_details,
            changed_files=changed_files,
            changed_since_run_start=changed_since_run_start,
        )
        log_refs = _log_refs_from_dict(run.get("log_refs")) or self.store.log_refs(run_id)

        diagnostic_timeline = _diagnostic_timeline(
            run=normalized_run,
            events=all_dialogue,
            permissions=permissions,
            evidence=evidence,
            warning_details=warning_details,
            token_sources=token_sources,
            log_refs=log_refs,
        )
        diagnostic_explainability = _diagnostic_explainability(
            run=normalized_run,
            evidence=evidence,
            evidence_status=evidence_status,
            evidence_score=evidence_score,
            warning_details=warning_details,
            failure_classification=failure_classification,
            changed_files=changed_files,
            changed_since_run_start=changed_since_run_start,
            tokens=canonical_tokens,
            model=adapter_telemetry.model,
            token_sources=token_sources,
            log_refs=log_refs,
        )
        return RunSummary(
            schema_version=1,
            run_id=run_id,
            status=status,
            status_reason=_status_reason(normalized_run, final_report, warnings),
            selected_profile=_harness_metadata_from_dict(run["harness"]),
            workdir=run["workdir"],
            changed_files=changed_files,
            pre_existing_changed_files=final_report.get(
                "pre_existing_changed_files",
                run.get("pre_existing_changed_files", []),
            ),
            changed_since_run_start=changed_since_run_start,
            file_attribution=file_attribution,
            final_response=final_report.get("final_response", run.get("last_agent_message")),
            latest_agent_response=_latest_agent_response(all_dialogue) or run.get("last_agent_message"),
            pending_permission_requests=pending_permissions,
            permission_counts=_run_counts_from_dict(run.get("counts", {})),
            tool_timeline=tool_timeline,
            evidence=evidence,
            evidence_status=evidence_status,
            evidence_score=evidence_score,
            evidence_groups=evidence_groups,
            tokens=canonical_tokens,
            token_sources=token_sources,
            model=adapter_telemetry.model,
            warnings=warnings,
            warning_details=warning_details,
            diagnostic_timeline=diagnostic_timeline,
            diagnostic_explainability=diagnostic_explainability,
            failure_classification=failure_classification,
            log_refs=log_refs,
        )

    def _run_policy_verdict(
        self,
        summary: RunSummary,
        source_ticket: DelegationTicket | None = None,
    ) -> RunPolicyVerdict:
        reason_codes = list(summary.failure_classification)
        warning_codes = {warning.code for warning in summary.warning_details}
        if summary.pending_permission_requests:
            return RunPolicyVerdict(
                schema_version=1,
                run_id=summary.run_id,
                policy_verdict="blocked",
                reason_codes=["pending_permission"],
                recommended_action="resolve_permission",
            )
        if summary.status in {"created", "launching", "running", "waiting_for_permission", "stopping"}:
            return RunPolicyVerdict(
                schema_version=1,
                run_id=summary.run_id,
                policy_verdict="requires_primary_review",
                reason_codes=["run_active"],
                recommended_action="poll_digest_or_liveness",
            )
        if "changed_forbidden_paths" in reason_codes:
            return RunPolicyVerdict(
                schema_version=1,
                run_id=summary.run_id,
                policy_verdict="reject",
                reason_codes=sorted(set(reason_codes)),
                recommended_action="reject_and_create_policy_compliant_repair",
                repair_seed=_repair_seed(summary, source_ticket),
            )
        if "policy_violation" in reason_codes:
            return RunPolicyVerdict(
                schema_version=1,
                run_id=summary.run_id,
                policy_verdict="requires_primary_review",
                reason_codes=sorted(set(reason_codes)),
                recommended_action="review_policy_risk_and_decide",
            )
        repair_reasons = {
            "acceptance_check_failed",
            "missing_requested_check",
            "failed_requested_check",
            "unknown_requested_check",
            "worker_claim_without_evidence",
            "no_op_pass",
            "no_completed_tool_calls",
            "changed_outside_allowed_paths",
            "worker_error",
            "cancelled",
            "interrupted",
            "permission_denied_or_cancelled",
            "incomplete_changed_files",
        }
        matched_repair = sorted(set(reason_codes) & repair_reasons)
        if summary.evidence_status == "blocked":
            blocking_codes = [warning.code for warning in summary.evidence_groups.get("blocking", [])]
            return RunPolicyVerdict(
                schema_version=1,
                run_id=summary.run_id,
                policy_verdict="reject",
                reason_codes=sorted(set(reason_codes or blocking_codes)),
                recommended_action="reject_and_create_policy_compliant_repair",
                repair_seed=_repair_seed(summary, source_ticket),
            )
        if matched_repair or summary.evidence_status == "repair_needed" or any(warning.severity == "error" for warning in summary.warning_details):
            return RunPolicyVerdict(
                schema_version=1,
                run_id=summary.run_id,
                policy_verdict="needs_repair",
                reason_codes=matched_repair or sorted(warning_codes),
                recommended_action=_repair_action(matched_repair or sorted(warning_codes)),
                repair_seed=_repair_seed(summary, source_ticket),
            )
        if summary.status == "completed":
            if summary.evidence.checks and not all(check.status == "passed" for check in summary.evidence.checks):
                return RunPolicyVerdict(
                    schema_version=1,
                    run_id=summary.run_id,
                    policy_verdict="needs_repair",
                    reason_codes=["requested_check_not_passed"],
                    recommended_action="create_repair_ticket",
                    repair_seed=_repair_seed(summary, source_ticket),
                )
            return RunPolicyVerdict(
                schema_version=1,
                run_id=summary.run_id,
                policy_verdict="accept_candidate",
                reason_codes=[],
                recommended_action="primary_review_acceptance_candidate",
            )
        return RunPolicyVerdict(
            schema_version=1,
            run_id=summary.run_id,
            policy_verdict="requires_primary_review",
            reason_codes=reason_codes or [summary.status],
            recommended_action="inspect_digest_then_decide",
        )

    def _next_action(self, session: DelegationSession) -> dict[str, Any]:
        health = _session_health(session)
        if not session.requirements:
            return {"action": "create_requirement", "reason": "No requirements have been recorded."}
        if not session.tickets:
            return {"action": "create_delegation_ticket", "reason": "Requirements exist but no tickets have been created."}
        pending = [attempt for attempt in session.attempts if attempt.decision == "pending"]
        if pending:
            latest = pending[-1]
            try:
                summary = self._run_summary(latest.run_id, max_events=0)
                verdict = self._run_policy_verdict(summary, source_ticket=_ticket_by_id(session, latest.ticket_id))
            except Exception:
                return {"action": "review_run", "run_id": latest.run_id, "reason": "A ticket attempt is pending review."}
            if summary.status in {"created", "launching", "running", "waiting_for_permission", "stopping"}:
                return {
                    "action": verdict.recommended_action,
                    "run_id": latest.run_id,
                    "ticket_id": latest.ticket_id,
                    "policy_verdict": to_jsonable(verdict),
                }
            if verdict.policy_verdict in {"needs_repair", "reject"}:
                return {
                    "action": "create_repair_ticket_from_run",
                    "run_id": latest.run_id,
                    "ticket_id": latest.ticket_id,
                    "policy_verdict": to_jsonable(verdict),
                    "reason": "Server policy found routine repair/rejection signals.",
                }
            return {
                "action": "review_run",
                "run_id": latest.run_id,
                "ticket_id": latest.ticket_id,
                "policy_verdict": to_jsonable(verdict),
                "reason": "Terminal attempt is ready for primary acceptance review.",
            }
        running = [ticket for ticket in session.tickets if ticket.status == "running"]
        if running:
            return {"action": "poll_digest_or_liveness", "reason": "A ticket is currently running."}
        repair = [ticket for ticket in session.tickets if ticket.status == "needs_repair"]
        if repair:
            return {"action": "create_repair_ticket_from_run", "reason": "A ticket is marked needs_repair."}
        unstarted = [ticket for ticket in session.tickets if ticket.status == "not_started"]
        if unstarted:
            return {"action": "start_ticket_run", "ticket_id": unstarted[0].ticket_id}
        if health["unsatisfied_requirement_ids"]:
            return {
                "action": "create_delegation_ticket",
                "reason": "Some requirements are not satisfied.",
                "requirement_ids": health["unsatisfied_requirement_ids"],
            }
        return {"action": "finish_delegation_session", "reason": "All requirements are satisfied and attempts are reviewed."}


class _ServiceSink(AdapterSink):
    def __init__(self, service: TaskRunService, run_id: str):
        self.service = service
        self.run_id = run_id

    async def agent_text(self, text: str, raw: dict[str, Any] | None = None) -> None:
        run = self.service._get_run(self.run_id)
        self.service._message_buffers[self.run_id] = self.service._message_buffers.get(self.run_id, "") + text
        run.last_agent_message = self.service._message_buffers[self.run_id]
        self.service.store.save_run(run)
        await self.service._append_event(self.run_id, AGENT_MESSAGE_CHUNK, run.harness.runtime_family, text, raw)

    async def tool_update(self, kind: str, text: str, raw: dict[str, Any] | None = None) -> None:
        run = self.service._get_run(self.run_id)
        await self.service._append_event(self.run_id, kind, run.harness.runtime_family, text, raw)

    async def policy_violation(self, reason: str, raw: dict[str, Any] | None = None) -> None:
        await self.service._append_event(self.run_id, POLICY_VIOLATION, "server", reason, raw)

    async def permission_requested(self, permission: PermissionRequest) -> None:
        run = self.service._get_run(self.run_id)
        run.counts.permission_count += 1
        run.status = "waiting_for_permission"
        permission.requested_at = permission.requested_at or _utc_now()
        permission.raw_ref = permission.raw_ref or str(run.log_refs.permissions if run.log_refs else "")
        self.service._permissions[permission.permission_id] = permission
        self.service.store.append_permission(permission)
        self.service.store.save_run(run)
        await self.service._append_event(self.run_id, PERMISSION_REQUESTED, "harness", permission.summary, permission.raw)

    async def stderr(self, text: str) -> None:
        self.service.store.append_stderr(self.run_id, text)
        if _suppress_display_stderr(text):
            return
        await self.service._append_event(self.run_id, STDERR, "harness", text)

    async def transcript(self, text: str) -> None:
        self.service.store.append_transcript(self.run_id, text)


def _harness_metadata(profile: HarnessProfile) -> HarnessRunMetadata:
    return HarnessRunMetadata(
        profile_id=profile.id,
        runtime_family=profile.runtime_family,
        adapter=profile.adapter,
        auth_mode=profile.auth_mode,
        cost_posture=profile.cost_posture,
        metered_api=profile.metered_api,
    )


def _preflight_capability_gaps(task: TaskInput | None, capabilities: ProfileCapabilities) -> list[str]:
    if not task:
        return []
    required: set[str] = set()
    if task.checks:
        required.add("tool_events")
    if any("permission" in item.lower() for item in [task.objective, *task.constraints, *task.rules]):
        required.add("permissions")
    capability_map = {
        "dialogue": capabilities.supports_dialogue,
        "permissions": capabilities.supports_permissions,
        "tool_events": capabilities.supports_tool_events,
        "stop": capabilities.supports_stop,
        "followup_messages": capabilities.supports_followup_messages,
    }
    return sorted(capability for capability in required if not capability_map.get(capability))


def _controller_for_profile(
    run_id: str,
    sink: AdapterSink,
    profile: HarnessProfile,
) -> AcpWorkerController | ClaudeCliController:
    if profile.adapter == "cli" and profile.runtime_family == "claude_code":
        return ClaudeCliController(run_id, sink)
    return AcpWorkerController(run_id, sink)


def _suppress_display_stderr(text: str) -> bool:
    return (
        "api.githubcopilot.com/.well-known/oauth-protected-resource/mcp/" in text
        and "No access token was provided" in text
    )


def _harness_metadata_from_dict(value: dict[str, Any]) -> HarnessRunMetadata:
    return HarnessRunMetadata(
        profile_id=value["profile_id"],
        runtime_family=value["runtime_family"],
        adapter=value["adapter"],
        auth_mode=value["auth_mode"],
        cost_posture=value["cost_posture"],
        metered_api=bool(value["metered_api"]),
    )


def _run_counts_from_dict(value: dict[str, Any]) -> RunCounts:
    return RunCounts(
        prompt_count=int(value.get("prompt_count", 0)),
        permission_count=int(value.get("permission_count", 0)),
        approved_permission_count=int(value.get("approved_permission_count", 0)),
        denied_permission_count=int(value.get("denied_permission_count", 0)),
        cancelled_permission_count=int(value.get("cancelled_permission_count", 0)),
    )


def _log_refs_from_dict(value: dict[str, Any] | None) -> LogRefs | None:
    if not value:
        return None
    return LogRefs(
        dialogue=value["dialogue"],
        transcript=value["transcript"],
        stderr=value["stderr"],
        permissions=value["permissions"],
        final_report=value["final_report"],
    )


def _file_attribution_from_dict(value: dict[str, Any]) -> FileAttributionRecord:
    confidence = str(value.get("confidence", "unknown"))
    if confidence not in {"high", "medium", "low", "unknown"}:
        confidence = "unknown"
    return FileAttributionRecord(
        path=str(value.get("path", "")),
        change_type=str(value.get("change_type", "unknown")),
        attribution=str(value.get("attribution", "unknown")),
        confidence=confidence,  # type: ignore[arg-type]
        notes=[str(item) for item in value.get("notes", [])],
    )


def _permission_from_dict(value: dict[str, Any]) -> PermissionRequest:
    return PermissionRequest(
        permission_id=value["permission_id"],
        run_id=value["run_id"],
        adapter_request_id=str(value["adapter_request_id"]),
        schema_version=int(value.get("schema_version", 1)),
        status=value.get("status", "pending"),
        summary=value.get("summary", ""),
        risk=value.get("risk", "unknown"),
        command_or_action=value.get("command_or_action"),
        action=value.get("action"),
        command=value.get("command"),
        paths=list(value.get("paths", [])),
        resources=list(value.get("resources", [])),
        options=[
            PermissionOption(
                option_id=option["option_id"],
                label=option["label"],
                kind=option.get("kind"),
            )
            for option in value.get("options", [])
        ],
        raw=value.get("raw", {}),
        raw_ref=value.get("raw_ref"),
        requested_at=value.get("requested_at"),
        resolved_at=value.get("resolved_at"),
        decision=value.get("decision"),
        resolved_option_id=value.get("resolved_option_id"),
        decision_rationale=value.get("decision_rationale"),
        deciding_primary=value.get("deciding_primary"),
        adapter_resolution_status=value.get("adapter_resolution_status"),
        adapter_result=value.get("adapter_result"),
    )


def _latest_agent_response(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("kind") == AGENT_MESSAGE_CHUNK and event.get("text"):
            return str(event["text"])
    return None


def _repair_action(reason_codes: list[str]) -> str:
    reasons = set(reason_codes)
    if "no_op_pass" in reasons or "no_completed_tool_calls" in reasons:
        return "create_mechanical_progress_ticket"
    if "changed_forbidden_paths" in reasons:
        return "reject_and_create_policy_compliant_repair"
    if "policy_violation" in reasons:
        return "review_policy_risk_and_decide"
    return "create_repair_ticket"


def _repair_seed(summary: RunSummary, source_ticket: DelegationTicket | None = None) -> RepairSeed:
    check_commands = [check.command for check in summary.evidence.checks] if summary.evidence.checks else []
    allowed_paths = source_ticket.allowed_paths if source_ticket else summary.changed_files
    forbidden_paths = source_ticket.forbidden_paths if source_ticket else []
    title = f"Repair {source_ticket.title}" if source_ticket else f"Repair {summary.run_id}"
    reasons = ", ".join(summary.failure_classification) or "server policy gaps"
    objective = (
        f"Repair the previous delegated attempt {summary.run_id}. "
        f"Address these server-classified issues: {reasons}. "
        "Keep the change narrowly scoped and rerun the requested checks."
    )
    rules = list(source_ticket.rules if source_ticket else [])
    rules.extend(
        [
            "Do not perform broad exploration.",
            "Do not change files outside allowed_paths.",
            "Focus only on repairing the previous attempt's classified gaps.",
        ]
    )
    return RepairSeed(
        title=title,
        objective=objective,
        allowed_paths=list(allowed_paths),
        forbidden_paths=list(forbidden_paths),
        checks=check_commands or (list(source_ticket.checks) if source_ticket else []),
        acceptance_hints=list(source_ticket.acceptance_hints) if source_ticket else [],
        rules=rules,
    )


def _run_evidence(
    run: dict[str, Any],
    events: list[dict[str, Any]],
    permissions: list[dict[str, Any]],
) -> RunEvidence:
    tool_calls = ToolCallEvidence()
    for event in events:
        kind = event.get("kind")
        if kind == "tool_call_started":
            tool_calls.started += 1
        elif kind == "tool_call_updated":
            tool_calls.updated += 1
        elif kind == "tool_call_completed":
            tool_calls.completed += 1
        elif kind == "tool_call_failed":
            tool_calls.failed += 1

        if kind in TOOL_EVENT_KINDS:
            tool_kind = _tool_kind(event)
            tool_calls.by_kind[tool_kind] = tool_calls.by_kind.get(tool_kind, 0) + 1
            if kind == "tool_call_completed":
                if tool_kind in {"edit", "write"}:
                    tool_calls.completed_write_or_edit_count += 1
                if tool_kind == "execute":
                    tool_calls.completed_execute_count += 1

    return RunEvidence(
        tool_calls=tool_calls,
        checks=_check_evidence(run, events),
        permissions=_permission_evidence(events, permissions),
        policy_violations=[
            RunWarning(
                code="policy_violation",
                message=str(event.get("text") or "Delegated run hit a server policy violation"),
                severity="error",
                event_id=str(event.get("event_id")) if event.get("event_id") else None,
            )
            for event in events
            if event.get("kind") == POLICY_VIOLATION
        ],
    )


def _permission_evidence(events: list[dict[str, Any]], permissions: list[dict[str, Any]]) -> PermissionEvidence:
    latest_by_id: dict[str, dict[str, Any]] = {}
    for permission in permissions:
        permission_id = str(permission.get("permission_id") or "")
        if permission_id:
            latest_by_id[permission_id] = permission

    evidence = PermissionEvidence()
    for event in events:
        kind = event.get("kind")
        if kind == PERMISSION_REQUESTED:
            evidence.requested += 1

    if latest_by_id:
        if evidence.requested == 0:
            evidence.requested = len(latest_by_id)
        for permission in latest_by_id.values():
            status = str(permission.get("status") or "pending")
            if status == "approved":
                evidence.approved += 1
            elif status == "denied":
                evidence.denied += 1
            elif status == "cancelled":
                evidence.cancelled += 1
            elif status == "pending":
                evidence.pending += 1
    else:
        for event in events:
            kind = event.get("kind")
            if kind == PERMISSION_APPROVED:
                evidence.approved += 1
            elif kind == PERMISSION_DENIED:
                evidence.denied += 1
            elif kind == PERMISSION_CANCELLED:
                evidence.cancelled += 1
    return evidence


def _check_evidence(run: dict[str, Any], events: list[dict[str, Any]]) -> list[CheckEvidence]:
    task = run.get("task") if isinstance(run.get("task"), dict) else {}
    requested_checks = [str(check) for check in task.get("checks", []) if str(check).strip()]
    evidence: list[CheckEvidence] = []
    for check in requested_checks:
        matched = _latest_check_event(check, events)
        if not matched:
            evidence.append(CheckEvidence(command=check, observed=False))
            continue
        event, exit_code = matched
        if exit_code == 0:
            status = "passed"
        elif exit_code is None:
            status = "unknown"
        else:
            status = "failed"
        evidence.append(
            CheckEvidence(
                command=check,
                observed=True,
                exit_code=exit_code,
                status=status,
                event_id=str(event.get("event_id")) if event.get("event_id") else None,
                summary=_truncate_text(str(event.get("text") or ""), 500),
            )
        )
    return evidence


def _latest_check_event(check: str, events: list[dict[str, Any]]) -> tuple[dict[str, Any], int | None] | None:
    normalized_check = _normalize_check_text(check)
    for event in reversed(events):
        if event.get("kind") not in TOOL_EVENT_KINDS:
            continue
        command = _tool_command(event) or str(event.get("text") or "")
        if normalized_check and normalized_check in _normalize_check_text(command):
            return event, _tool_exit_code(event)
    return None


def _diagnostic_timeline(
    *,
    run: dict[str, Any],
    events: list[dict[str, Any]],
    permissions: list[dict[str, Any]],
    evidence: RunEvidence,
    warning_details: list[RunWarning],
    token_sources: dict[str, Any],
    log_refs: LogRefs | None,
) -> list[DiagnosticTimelineItem]:
    timeline: list[DiagnosticTimelineItem] = [
        DiagnosticTimelineItem(
            phase="launch",
            label="Run record loaded",
            source="run",
            status=str(run.get("status") or "unknown"),
            artifact_ref=_artifact_ref(log_refs, "run"),
        )
    ]

    for event in events:
        kind = str(event.get("kind") or "unknown")
        timeline.append(
            DiagnosticTimelineItem(
                phase=_diagnostic_phase_for_event(kind),
                label=_diagnostic_label_for_event(kind),
                source="dialogue",
                timestamp=str(event.get("timestamp")) if event.get("timestamp") else None,
                event_id=str(event.get("event_id")) if event.get("event_id") else None,
                artifact_ref=_artifact_ref(log_refs, "dialogue"),
                status=kind,
            )
        )

    latest_permissions: dict[str, dict[str, Any]] = {}
    for permission in permissions:
        permission_id = str(permission.get("permission_id") or "")
        if permission_id:
            latest_permissions[permission_id] = permission
    for permission_id, permission in latest_permissions.items():
        timeline.append(
            DiagnosticTimelineItem(
                phase="permission",
                label=f"Permission {permission.get('status', 'unknown')}",
                source="permissions",
                permission_id=permission_id,
                artifact_ref=_artifact_ref(log_refs, "permissions"),
                status=str(permission.get("status") or "unknown"),
            )
        )

    for check in evidence.checks:
        timeline.append(
            DiagnosticTimelineItem(
                phase="check",
                label=f"Requested check {check.status}",
                source="summary.evidence.checks",
                event_id=check.event_id,
                check_command=check.command,
                artifact_ref=_artifact_ref(log_refs, "transcript"),
                status=check.status,
            )
        )

    for warning in warning_details:
        timeline.append(
            DiagnosticTimelineItem(
                phase="warning",
                label=warning.message,
                source="summary.warning_details",
                event_id=warning.event_id,
                warning_code=warning.code,
                artifact_ref=_artifact_for_warning(log_refs, warning.code),
                status=warning.severity,
            )
        )

    external = token_sources.get("external_agent_logs")
    known = bool(external.get("known")) if isinstance(external, dict) else False
    timeline.append(
        DiagnosticTimelineItem(
            phase="telemetry",
            label="Canonical token telemetry " + ("correlated" if known else "unknown"),
            source="token_sources.external_agent_logs",
            artifact_ref="token_sources.external_agent_logs",
            status="known" if known else "unknown",
        )
    )
    timeline.append(
        DiagnosticTimelineItem(
            phase="terminal",
            label=f"Run status {run.get('status', 'unknown')}",
            source="run",
            artifact_ref=_artifact_ref(log_refs, "final_report"),
            status=str(run.get("status") or "unknown"),
        )
    )
    return timeline


def _diagnostic_explainability(
    *,
    run: dict[str, Any],
    evidence: RunEvidence,
    evidence_status: str,
    evidence_score: int,
    warning_details: list[RunWarning],
    failure_classification: list[str],
    changed_files: list[str],
    changed_since_run_start: list[str],
    tokens: Any,
    model: Any,
    token_sources: dict[str, Any],
    log_refs: LogRefs | None,
) -> DiagnosticExplainability:
    observed = [
        DiagnosticEntry(
            code="run_status",
            message=f"Run status is {run.get('status', 'unknown')}.",
            source="run",
            artifact_ref=_artifact_ref(log_refs, "run"),
        ),
        DiagnosticEntry(
            code="changed_files",
            message=f"Orbital observed {len(changed_files)} changed file(s), {len(changed_since_run_start)} changed since run start.",
            source="final_report",
            artifact_ref=_artifact_ref(log_refs, "final_report"),
        ),
        DiagnosticEntry(
            code="tool_calls",
            message=f"Orbital observed {evidence.tool_calls.completed} completed tool call(s).",
            source="dialogue",
            artifact_ref=_artifact_ref(log_refs, "dialogue"),
        ),
        DiagnosticEntry(
            code="permissions",
            message=f"Orbital observed {evidence.permissions.requested} permission request(s).",
            source="permissions",
            artifact_ref=_artifact_ref(log_refs, "permissions"),
        ),
    ]
    if evidence.checks:
        observed.append(
            DiagnosticEntry(
                code="requested_checks",
                message=f"Orbital tracked {len(evidence.checks)} requested check(s).",
                source="summary.evidence.checks",
                artifact_ref=_artifact_ref(log_refs, "transcript"),
            )
        )

    inferred = [
        DiagnosticEntry(
            code="evidence_status",
            message=f"Evidence status is {evidence_status} with score {evidence_score}.",
            source="summary.evidence_groups",
        )
    ]
    if warning_details:
        inferred.append(
            DiagnosticEntry(
                code="warnings",
                message=f"Orbital inferred {len(warning_details)} warning(s).",
                source="summary.warning_details",
            )
        )
    if failure_classification:
        inferred.append(
            DiagnosticEntry(
                code="failure_classification",
                message="Failure classification: " + ", ".join(failure_classification),
                source="summary.failure_classification",
            )
        )

    unknown: list[DiagnosticEntry] = []
    if not getattr(tokens, "known", False):
        unknown.append(
            DiagnosticEntry(
                code="token_telemetry_unknown",
                message="Canonical token telemetry was not uniquely correlated.",
                source="token_sources.external_agent_logs",
                artifact_ref="token_sources",
            )
        )
    if not getattr(model, "known", False):
        unknown.append(
            DiagnosticEntry(
                code="model_unknown",
                message="Exact model metadata was not observed.",
                source="summary.model",
            )
        )
    warning_codes = {warning.code for warning in warning_details}
    if "missing_requested_check" in warning_codes:
        unknown.append(
            DiagnosticEntry(
                code="requested_check_missing",
                message="A requested check was not observed in run evidence.",
                source="summary.warning_details",
                artifact_ref=_artifact_ref(log_refs, "transcript"),
            )
        )
    if "worker_claim_without_evidence" in warning_codes:
        unknown.append(
            DiagnosticEntry(
                code="worker_claim_unverified",
                message="Worker completion prose was not backed by edits, completed tool calls, or passed checks.",
                source="summary.warning_details",
                artifact_ref=_artifact_ref(log_refs, "dialogue"),
            )
        )

    return DiagnosticExplainability(
        observed=observed,
        inferred=inferred,
        unknown=unknown,
        diagnostic_next_steps=_diagnostic_next_steps(
            warning_details=warning_details,
            evidence=evidence,
            token_sources=token_sources,
            tokens_known=bool(getattr(tokens, "known", False)),
            model_known=bool(getattr(model, "known", False)),
            log_refs=log_refs,
        ),
    )


def _diagnostic_next_steps(
    *,
    warning_details: list[RunWarning],
    evidence: RunEvidence,
    token_sources: dict[str, Any],
    tokens_known: bool,
    model_known: bool,
    log_refs: LogRefs | None,
) -> list[DiagnosticEntry]:
    steps: list[DiagnosticEntry] = []
    if evidence.permissions.pending:
        steps.append(
            DiagnosticEntry(
                code="resolve_pending_permission",
                message="Inspect and resolve pending permission requests.",
                source="permissions",
                artifact_ref=_artifact_ref(log_refs, "permissions"),
            )
        )
    if evidence.permissions.denied or evidence.permissions.cancelled:
        steps.append(
            DiagnosticEntry(
                code="inspect_permission_outcome",
                message="Inspect denied or cancelled permission outcomes before retrying.",
                source="permissions",
                artifact_ref=_artifact_ref(log_refs, "permissions"),
            )
        )

    for warning in warning_details:
        steps.append(
            DiagnosticEntry(
                code=f"inspect_{warning.code}",
                message=f"Inspect diagnostic evidence for warning: {warning.code}.",
                source="summary.warning_details",
                artifact_ref=_artifact_for_warning(log_refs, warning.code),
                event_id=warning.event_id,
            )
        )

    external = token_sources.get("external_agent_logs")
    ambiguous = (
        isinstance(external, dict)
        and bool(external.get("ambiguity"))
        or bool(getattr(external, "records", [])) and len(getattr(external, "records", [])) > 1
    )
    if not tokens_known:
        steps.append(
            DiagnosticEntry(
                code="inspect_token_sources",
                message="Inspect token source diagnostics; canonical telemetry is unknown or ambiguous.",
                source="token_sources.external_agent_logs",
                artifact_ref="token_sources",
            )
        )
    if ambiguous:
        steps.append(
            DiagnosticEntry(
                code="isolate_token_workspace",
                message="Rerun with an isolated token workspace to remove telemetry ambiguity.",
                source="token_sources.external_agent_logs",
                artifact_ref="token_sources",
            )
        )
    if not model_known:
        steps.append(
            DiagnosticEntry(
                code="inspect_model_metadata",
                message="Inspect adapter transcript for exact model metadata if model identity matters.",
                source="summary.model",
                artifact_ref=_artifact_ref(log_refs, "transcript"),
            )
        )
    return _dedupe_diagnostic_entries(steps)


def _diagnostic_phase_for_event(kind: str) -> str:
    if kind in {TASK_SUBMITTED, STARTUP_PROMPT_SENT, HOST_MESSAGE}:
        return "prompt"
    if kind in TOOL_EVENT_KINDS:
        return "tool"
    if kind in {PERMISSION_REQUESTED, PERMISSION_APPROVED, PERMISSION_DENIED, PERMISSION_CANCELLED}:
        return "permission"
    if kind in WARNING_EVENT_KINDS:
        return "warning"
    if kind == RUN_STOPPED:
        return "terminal"
    if kind == AGENT_MESSAGE_CHUNK:
        return "dialogue"
    return "event"


def _diagnostic_label_for_event(kind: str) -> str:
    labels = {
        TASK_SUBMITTED: "Task submitted",
        STARTUP_PROMPT_SENT: "Startup prompt sent",
        HOST_MESSAGE: "Host message sent",
        AGENT_MESSAGE_CHUNK: "Agent message observed",
        PERMISSION_REQUESTED: "Permission requested",
        PERMISSION_APPROVED: "Permission approved",
        PERMISSION_DENIED: "Permission denied",
        PERMISSION_CANCELLED: "Permission cancelled",
        STDERR: "stderr observed",
        RUN_ERROR: "Run error observed",
        RUN_STOPPED: "Run stopped",
        ACCEPTANCE_CHECK_FAILED: "Acceptance check failed",
        POLICY_VIOLATION: "Policy violation observed",
    }
    if kind in TOOL_EVENT_KINDS:
        return "Tool event observed"
    return labels.get(kind, kind)


def _artifact_for_warning(log_refs: LogRefs | None, code: str) -> str | None:
    if code == "malformed_final_report":
        return _artifact_ref(log_refs, "final_report")
    if code in {"permission_denied_or_cancelled", "pending_permission"}:
        return _artifact_ref(log_refs, "permissions")
    if code in {"stderr", "last_error", RUN_ERROR}:
        return _artifact_ref(log_refs, "stderr") or _artifact_ref(log_refs, "transcript")
    if code in {"missing_requested_check", "failed_requested_check", "unknown_requested_check"}:
        return _artifact_ref(log_refs, "transcript")
    return "summary.warning_details"


def _artifact_ref(log_refs: LogRefs | None, name: str) -> str | None:
    if log_refs is None:
        return None
    return getattr(log_refs, name, None)


def _dedupe_diagnostic_entries(entries: list[DiagnosticEntry]) -> list[DiagnosticEntry]:
    seen: set[tuple[str, str | None]] = set()
    result: list[DiagnosticEntry] = []
    for entry in entries:
        key = (entry.code, entry.artifact_ref)
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def _run_warning_details(
    run: dict[str, Any],
    final_report: dict[str, Any],
    events: list[dict[str, Any]],
    evidence: RunEvidence,
    changed_files: list[str],
    changed_since_run_start: list[str],
    final_report_error: str | None = None,
) -> list[RunWarning]:
    warnings: list[RunWarning] = []
    seen_codes: set[str] = set()

    def add(code: str, message: str, severity: str = "warning", event_id: str | None = None) -> None:
        key = f"{code}:{message}"
        if key in seen_codes:
            return
        seen_codes.add(key)
        warnings.append(RunWarning(code=code, message=message, severity=severity, event_id=event_id))  # type: ignore[arg-type]

    for event in events:
        if event.get("kind") not in WARNING_EVENT_KINDS:
            continue
        message = str(event.get("text") or event.get("kind"))
        severity = "error" if event.get("kind") in {POLICY_VIOLATION, RUN_ERROR, ACCEPTANCE_CHECK_FAILED} else "warning"
        add(str(event.get("kind")), message, severity, str(event.get("event_id")) if event.get("event_id") else None)

    status = normalize_run_status(run.get("status"))
    if status == "completed":
        if not changed_since_run_start:
            add("no_changed_files", "Run reported success but changed no files.")
        if evidence.tool_calls.completed == 0:
            add("no_completed_tool_calls", "Run reported success but no completed tool calls were observed.")

    task = run.get("task") if isinstance(run.get("task"), dict) else {}
    if task.get("checks") and status in {"completed", "failed", "cancelled", "interrupted", "blocked", "unknown"}:
        for check in evidence.checks:
            if not check.observed:
                add(
                    "missing_requested_check",
                    f"Requested check was not observed: {check.command}",
                )
            elif check.status == "failed":
                add(
                    "failed_requested_check",
                    f"Requested check failed: {check.command}",
                    "error",
                )
            elif check.status == "unknown":
                add(
                    "unknown_requested_check",
                    f"Requested check result was not structured: {check.command}",
                    "info",
                )

    if final_report.get("last_error"):
        add("last_error", str(final_report["last_error"]), "error")
    elif run.get("last_error"):
        add("last_error", str(run["last_error"]), "error")
    if final_report_error:
        add("malformed_final_report", f"Final report could not be read: {final_report_error}", "error")

    task = run.get("task") if isinstance(run.get("task"), dict) else {}
    outside_allowed = _paths_outside_allowed(changed_files, list(task.get("allowed_paths", [])))
    if outside_allowed:
        add(
            "changed_outside_allowed_paths",
            "Run changed path(s) outside allowed_paths: " + ", ".join(outside_allowed),
        )
    forbidden_changes = _paths_matching(changed_files, list(task.get("forbidden_paths", [])))
    if forbidden_changes:
        add(
            "changed_forbidden_paths",
            "Run changed forbidden path(s): " + ", ".join(forbidden_changes),
            "error",
        )

    if not changed_files and status in {"failed", "cancelled"} and evidence.tool_calls.completed_write_or_edit_count:
        add(
            "writes_without_detected_file_changes",
            "Run had completed write/edit tool calls but no file changes were detected.",
        )
    if (
        status == "completed"
        and (final_report.get("final_response") or run.get("last_agent_message"))
        and not changed_since_run_start
        and evidence.tool_calls.completed == 0
        and not any(check.status == "passed" for check in evidence.checks)
    ):
        add(
            "worker_claim_without_evidence",
            "Worker reported completion, but Orbital found no edits, completed tool calls, or passed requested checks.",
        )
    return warnings


BLOCKING_EVIDENCE_WARNING_CODES = {
    "changed_forbidden_paths",
    "policy_violation",
}

REPAIR_EVIDENCE_WARNING_CODES = {
    "acceptance_check_failed",
    "failed_requested_check",
    "missing_requested_check",
    "no_changed_files",
    "no_completed_tool_calls",
    "unknown_requested_check",
    "worker_claim_without_evidence",
    "changed_outside_allowed_paths",
    "writes_without_detected_file_changes",
    "malformed_final_report",
    "last_error",
}


def _evidence_groups(warnings: list[RunWarning]) -> dict[str, list[RunWarning]]:
    groups: dict[str, list[RunWarning]] = {
        "blocking": [],
        "repair": [],
        "review": [],
        "info": [],
    }
    for warning in warnings:
        if warning.code in BLOCKING_EVIDENCE_WARNING_CODES:
            groups["blocking"].append(warning)
        elif warning.code in REPAIR_EVIDENCE_WARNING_CODES or warning.severity == "error":
            groups["repair"].append(warning)
        elif warning.severity == "info":
            groups["info"].append(warning)
        else:
            groups["review"].append(warning)
    return groups


def _evidence_status(groups: dict[str, list[RunWarning]]) -> str:
    if groups.get("blocking"):
        return "blocked"
    if groups.get("repair"):
        return "repair_needed"
    if groups.get("review") or groups.get("info"):
        return "review_needed"
    return "complete"


def _evidence_score(groups: dict[str, list[RunWarning]]) -> int:
    penalty = (
        60 * len(groups.get("blocking", []))
        + 25 * len(groups.get("repair", []))
        + 10 * len(groups.get("review", []))
        + 5 * len(groups.get("info", []))
    )
    return max(0, 100 - penalty)


def _tool_kind(event: dict[str, Any]) -> str:
    update = _raw_tool_update(event)
    if update and update.get("kind"):
        return str(update["kind"]).lower()
    text = str(event.get("text") or "")
    match = re.search(r"\[([^;\]]+)", text)
    if match:
        return match.group(1).strip().lower()
    return "unknown"


def _tool_command(event: dict[str, Any]) -> str | None:
    update = _raw_tool_update(event)
    if update:
        raw_input = update.get("rawInput")
        if isinstance(raw_input, dict):
            command = raw_input.get("command")
            if isinstance(command, list):
                return " ".join(str(part) for part in command)
            if isinstance(command, str):
                return command
        title = update.get("title")
        if isinstance(title, str):
            return title
    text = event.get("text")
    return str(text) if text else None


def _tool_exit_code(event: dict[str, Any]) -> int | None:
    update = _raw_tool_update(event)
    raw_output = update.get("rawOutput") if update else None
    if isinstance(raw_output, dict):
        for key in ("exit", "exit_code", "returncode"):
            if key in raw_output:
                try:
                    return int(raw_output[key])
                except (TypeError, ValueError):
                    return None
        metadata = raw_output.get("metadata")
        if isinstance(metadata, dict):
            for key in ("exit", "exit_code", "returncode"):
                if key in metadata:
                    try:
                        return int(metadata[key])
                    except (TypeError, ValueError):
                        return None

    text = str(event.get("text") or "")
    match = re.search(r"exit(?:_code)?:\s*(-?\d+)", text)
    if match:
        return int(match.group(1))
    if " passed" in text and event.get("kind") == "tool_call_completed":
        return 0
    return None


def _raw_tool_update(event: dict[str, Any]) -> dict[str, Any] | None:
    raw = event.get("raw")
    if not isinstance(raw, dict):
        return None
    params = raw.get("params")
    if not isinstance(params, dict):
        return None
    update = params.get("update")
    return update if isinstance(update, dict) else None


def _normalize_check_text(value: str) -> str:
    return " ".join(value.strip().split())


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def _status_reason(run: dict[str, Any], final_report: dict[str, Any], warnings: list[str]) -> str | None:
    if final_report.get("last_error"):
        return str(final_report["last_error"])
    if run.get("last_error"):
        return str(run["last_error"])
    if warnings:
        return warnings[-1]
    status = normalize_run_status(run.get("status"))
    if status == "completed":
        return "Run completed successfully"
    if status == "running":
        return "Run is still active"
    if status == "launching":
        return "Run is launching"
    if status == "waiting_for_permission":
        return "Run is waiting for a permission decision"
    if status == "stopping":
        return "Run is stopping"
    return None


def _failure_classification(
    *,
    run: dict[str, Any],
    evidence: RunEvidence,
    warning_details: list[RunWarning],
    changed_files: list[str],
    changed_since_run_start: list[str],
) -> list[str]:
    codes: set[str] = set()
    status = normalize_run_status(run.get("status"))
    warning_codes = {warning.code for warning in warning_details}
    if status == "cancelled":
        codes.add("cancelled")
    elif status == "interrupted":
        codes.add("interrupted")
    elif status == "failed":
        codes.add("worker_error")
    if evidence.policy_violations or "policy_violation" in warning_codes:
        codes.add("policy_violation")
        codes.discard("worker_error")
    if "acceptance_check_failed" in warning_codes:
        codes.add("acceptance_check_failed")
    if "missing_requested_check" in warning_codes or "requested_check_missing" in warning_codes:
        codes.add("missing_requested_check")
    if "failed_requested_check" in warning_codes or "requested_check_failed" in warning_codes:
        codes.add("failed_requested_check")
    if "unknown_requested_check" in warning_codes or "requested_check_unknown" in warning_codes:
        codes.add("unknown_requested_check")
    if "worker_claim_without_evidence" in warning_codes:
        codes.add("worker_claim_without_evidence")
    if "no_changed_files" in warning_codes:
        codes.add("no_op_pass")
    if "no_completed_tool_calls" in warning_codes:
        codes.add("no_completed_tool_calls")
    if "changed_outside_allowed_paths" in warning_codes:
        codes.add("changed_outside_allowed_paths")
    if "changed_forbidden_paths" in warning_codes:
        codes.add("changed_forbidden_paths")
    if evidence.permissions.denied or evidence.permissions.cancelled:
        codes.add("permission_denied_or_cancelled")
    if not changed_files and changed_since_run_start:
        codes.add("incomplete_changed_files")
    return sorted(codes)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _seconds_since_iso(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - timestamp.astimezone(UTC)).total_seconds())


def _clean_optional_text(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _adapter_resolution_status(adapter_result: Any, selected_option_id: str) -> str:
    if not isinstance(adapter_result, dict):
        return "ignored"
    if adapter_result.get("error"):
        return "failed"
    outcome = adapter_result.get("outcome")
    if isinstance(outcome, dict):
        if outcome.get("optionId") == selected_option_id and outcome.get("outcome") in {None, "selected"}:
            return "accepted"
        if outcome.get("outcome") in {"rejected", "failed", "error"}:
            return "rejected"
    return "ignored"


def _assessment_from_dict(value: dict[str, Any]) -> DelegationRunAssessment:
    return DelegationRunAssessment(
        run_id=str(value["run_id"]),
        decision=value["decision"],
        rationale=str(value.get("rationale") or ""),
        inspected_files=list(value.get("inspected_files", [])),
        verification_commands=list(value.get("verification_commands", [])),
        repair_prompt=value.get("repair_prompt"),
        created_at=value.get("created_at"),
    )


def _requirement_from_dict(value: dict[str, Any]) -> DelegationRequirement:
    return DelegationRequirement(
        requirement_id=str(value["requirement_id"]),
        statement=str(value.get("statement") or ""),
        proof_needed=str(value.get("proof_needed") or ""),
        status=value.get("status", "not_started"),
        evidence=list(value.get("evidence", [])),
        updated_at=value.get("updated_at"),
    )


def _ticket_from_dict(value: dict[str, Any]) -> DelegationTicket:
    return DelegationTicket(
        ticket_id=str(value["ticket_id"]),
        title=str(value.get("title") or ""),
        objective=str(value.get("objective") or ""),
        requirement_ids=list(value.get("requirement_ids", [])),
        allowed_paths=list(value.get("allowed_paths", [])),
        forbidden_paths=list(value.get("forbidden_paths", [])),
        checks=list(value.get("checks", [])),
        acceptance_hints=list(value.get("acceptance_hints", [])),
        rules=list(value.get("rules", [])),
        status=value.get("status", "not_started"),
        created_at=value.get("created_at"),
        updated_at=value.get("updated_at"),
    )


def _attempt_from_dict(value: dict[str, Any]) -> DelegationTicketAttempt:
    return DelegationTicketAttempt(
        ticket_id=str(value["ticket_id"]),
        run_id=str(value["run_id"]),
        attempt_number=int(value.get("attempt_number", 1)),
        decision=value.get("decision", "pending"),
        created_at=value.get("created_at"),
        reviewed_at=value.get("reviewed_at"),
    )


def _warning_from_dict(value: dict[str, Any]) -> RunWarning:
    return RunWarning(
        code=str(value.get("code") or "session_warning"),
        message=str(value.get("message") or ""),
        severity=value.get("severity", "warning"),
        event_id=value.get("event_id"),
    )


def _session_from_dict(value: dict[str, Any]) -> DelegationSession:
    return DelegationSession(
        schema_version=int(value.get("schema_version", 1)),
        session_id=str(value["session_id"]),
        status=value.get("status", "active"),
        objective=str(value.get("objective") or ""),
        workdir=str(value.get("workdir") or ""),
        preferred_profile_id=value.get("preferred_profile_id"),
        primary_harness=value.get("primary_harness"),
        max_runs=value.get("max_runs"),
        run_ids=list(value.get("run_ids", [])),
        assessments=[_assessment_from_dict(item) for item in value.get("assessments", [])],
        requirements=[_requirement_from_dict(item) for item in value.get("requirements", [])],
        tickets=[_ticket_from_dict(item) for item in value.get("tickets", [])],
        attempts=[_attempt_from_dict(item) for item in value.get("attempts", [])],
        last_liveness_checks=dict(value.get("last_liveness_checks", {})),
        session_warnings=[_warning_from_dict(item) for item in value.get("session_warnings", [])],
        final_status=value.get("final_status"),
        final_summary=value.get("final_summary"),
        final_verification=value.get("final_verification"),
        created_at=value.get("created_at"),
        updated_at=value.get("updated_at"),
        finished_at=value.get("finished_at"),
    )


def _ticket_by_id(session: DelegationSession, ticket_id: str) -> DelegationTicket:
    for ticket in session.tickets:
        if ticket.ticket_id == ticket_id:
            return ticket
    raise ValueError(f"unknown ticket_id: {ticket_id}")


def _add_session_warning(
    session: DelegationSession,
    code: str,
    message: str,
    *,
    severity: str = "warning",
) -> None:
    if any(warning.code == code and warning.message == message for warning in session.session_warnings):
        return
    session.session_warnings.append(RunWarning(code=code, message=message, severity=severity))  # type: ignore[arg-type]


def _session_health(session: DelegationSession) -> dict[str, Any]:
    unresolved = [requirement.requirement_id for requirement in session.requirements if requirement.status != "satisfied"]
    pending_attempts = [attempt.run_id for attempt in session.attempts if attempt.decision == "pending"]
    errors = [warning for warning in session.session_warnings if warning.severity == "error"]
    return {
        "status": "blocked" if errors else ("needs_review" if unresolved or pending_attempts else "ready"),
        "requirement_count": len(session.requirements),
        "unsatisfied_requirement_ids": sorted(unresolved),
        "ticket_count": len(session.tickets),
        "attempt_count": len(session.attempts),
        "pending_attempt_run_ids": sorted(pending_attempts),
        "warning_count": len(session.session_warnings),
        "error_count": len(errors),
    }


def _next_action(session: DelegationSession) -> dict[str, Any]:
    health = _session_health(session)
    if not session.requirements:
        return {"action": "create_requirement", "reason": "No structured requirements have been recorded."}
    if not session.tickets:
        return {"action": "create_delegation_ticket", "reason": "Requirements exist but no tickets have been created."}
    pending = [attempt for attempt in session.attempts if attempt.decision == "pending"]
    if pending:
        return {"action": "review_run", "run_id": pending[0].run_id, "ticket_id": pending[0].ticket_id}
    running = [ticket for ticket in session.tickets if ticket.status == "running"]
    if running:
        return {"action": "poll_run", "ticket_id": running[0].ticket_id, "reason": "A ticket run is active."}
    repair = [ticket for ticket in session.tickets if ticket.status == "needs_repair"]
    if repair:
        return {"action": "create_repair_ticket", "ticket_id": repair[0].ticket_id}
    unstarted = [ticket for ticket in session.tickets if ticket.status == "not_started"]
    if unstarted:
        return {"action": "start_ticket_run", "ticket_id": unstarted[0].ticket_id}
    if health["unsatisfied_requirement_ids"]:
        return {"action": "create_delegation_ticket", "reason": "Some requirements are not satisfied.", "requirement_ids": health["unsatisfied_requirement_ids"]}
    return {"action": "finish_delegation_session", "reason": "All requirements are satisfied and attempts are reviewed."}


def _paths_outside_allowed(paths: list[str], allowed_patterns: list[str]) -> list[str]:
    if not allowed_patterns:
        return []
    return sorted(path for path in paths if not _path_matches_any(path, allowed_patterns))


def _paths_matching(paths: list[str], patterns: list[str]) -> list[str]:
    if not patterns:
        return []
    return sorted(path for path in paths if _path_matches_any(path, patterns))


def _path_matches_any(path: str, patterns: list[str]) -> bool:
    return any(_path_matches(path, pattern) for pattern in patterns)


def _path_matches(path: str, pattern: str) -> bool:
    candidate = path.strip("/")
    normalized = pattern.strip().strip("/")
    if not normalized:
        return False
    if fnmatch.fnmatch(candidate, normalized):
        return True
    if any(char in normalized for char in "*?[]"):
        return False
    return candidate == normalized or candidate.startswith(normalized + "/")


def _assessed_run_ids(session: dict[str, Any], decision: str) -> list[str]:
    return [
        str(assessment["run_id"])
        for assessment in session.get("assessments", [])
        if assessment.get("decision") == decision
    ]


def _validate_token_count(name: str, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _validate_expected_outputs(run: TaskRun) -> str | None:
    expected = _expected_existing_paths(run.task)
    if not expected:
        return None

    workdir = Path(run.workdir)
    missing = [path for path in expected if not (workdir / path).exists()]
    if missing:
        return "Expected output path(s) were not created: " + ", ".join(missing)
    if run.task.allowed_paths and not run.changed_since_run_start:
        return "Expected task output was present but no file changes were detected during the run"
    return None


def _expected_existing_paths(task: TaskInput) -> list[str]:
    paths: list[str] = []
    for path in task.allowed_paths:
        if (
            _is_concrete_relative_file_path(path)
            and _is_fileish_path(path)
            and _task_expects_path_to_exist(task, path)
        ):
            paths.append(path)
    return sorted(set(paths))


def _task_expects_path_to_exist(task: TaskInput, path: str) -> bool:
    path_tokens = {path, f"`{path}`"}
    positive_markers = (
        "create",
        "creates",
        "created",
        "add",
        "adds",
        "added",
        "write",
        "writes",
        "wrote",
        "written",
        "exists",
        "should exist",
        "must exist",
        "containing",
    )
    negative_markers = (
        "remove",
        "removes",
        "removed",
        "delete",
        "deletes",
        "deleted",
        "absent",
        "not exist",
        "does not exist",
        "must not",
        "must remain absent",
        "should not",
        "prevent",
        "without creating",
        "no ",
    )
    fields = [task.objective, *task.acceptance_hints]
    for field in fields:
        for line in field.splitlines():
            lowered = line.lower()
            if not any(token.lower() in lowered for token in path_tokens):
                continue
            if any(marker in lowered for marker in negative_markers):
                continue
            if any(marker in lowered for marker in positive_markers):
                return True
    return False


def _is_concrete_relative_file_path(path: str) -> bool:
    candidate = path.strip()
    if not candidate or candidate.endswith("/"):
        return False
    if Path(candidate).is_absolute():
        return False
    if any(char in candidate for char in "*?[]{}"):
        return False
    if candidate in {".", ".."} or candidate.startswith("../"):
        return False
    return True


def _is_fileish_path(path: str) -> bool:
    name = Path(path).name
    return "." in name or name in {"Makefile", "Dockerfile", "LICENSE", "README"}
