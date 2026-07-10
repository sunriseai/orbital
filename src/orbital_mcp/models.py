from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Literal

from .telemetry import ModelTelemetry, TokenUsage


Status = Literal[
    "created",
    "launching",
    "running",
    "waiting_for_permission",
    "stopping",
    "completed",
    "failed",
    "blocked",
    "cancelled",
    "interrupted",
    "unknown",
]

LEGACY_STATUS_MAP = {
    "starting": "launching",
    "passed": "completed",
    "stopped": "cancelled",
}


def normalize_run_status(status: Any) -> Status:
    value = str(status or "unknown")
    value = LEGACY_STATUS_MAP.get(value, value)
    if value in {
        "created",
        "launching",
        "running",
        "waiting_for_permission",
        "stopping",
        "completed",
        "failed",
        "blocked",
        "cancelled",
        "interrupted",
        "unknown",
    }:
        return value  # type: ignore[return-value]
    return "unknown"


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


@dataclass
class TaskInput:
    title: str
    objective: str
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    acceptance_hints: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    runtime_mode: str | None = None
    allow_metered_api: bool = False


@dataclass
class ProfileClassification:
    task_tags: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    max_recommended_scope: str | None = None
    cost_preference: str | None = None
    locality: str = "unknown"


@dataclass
class ProfileSupport:
    tier: Literal["known_good_acp", "experimental_acp", "profile_template", "cli_fallback"] = "profile_template"
    notes: list[str] = field(default_factory=list)


@dataclass
class HarnessProfile:
    id: str
    display_name: str
    adapter: str
    runtime_family: str
    command: list[str] = field(default_factory=list)
    auth_mode: str = "unknown"
    cost_posture: str = "unknown"
    enabled: bool = True
    capabilities: list[str] = field(default_factory=list)
    permission_behavior: str = "manual"
    classification: ProfileClassification = field(default_factory=ProfileClassification)
    support: ProfileSupport = field(default_factory=ProfileSupport)
    env: dict[str, str] = field(default_factory=dict)
    block_mcp_servers: str | None = None

    @property
    def metered_api(self) -> bool:
        return self.cost_posture == "metered_api" or self.auth_mode == "api_key"


@dataclass
class HarnessConfig:
    schema_version: int = 1
    default_profile: str | None = "opencode_acp_glm52"
    allow_api_fallback: bool = False
    storage_root: str = ".orbital"
    profiles: list[HarnessProfile] = field(default_factory=list)


@dataclass
class ReadinessResult:
    profile_id: str
    ready: bool
    status: str
    missing_prerequisites: list[str] = field(default_factory=list)


@dataclass
class ProfileCapabilities:
    supports_dialogue: bool
    supports_permissions: bool
    supports_tool_events: bool
    supports_stop: bool
    supports_followup_messages: bool
    subscription_auth_verified: bool


@dataclass
class DialogueEvent:
    event_id: str
    run_id: str
    timestamp: str
    kind: str
    speaker: str
    text: str | None = None
    raw_ref: str | None = None
    raw: dict[str, Any] | str | None = None


@dataclass
class PermissionOption:
    option_id: str
    label: str
    kind: str | None = None


@dataclass
class PermissionRequest:
    permission_id: str
    run_id: str
    adapter_request_id: str
    schema_version: int = 1
    status: Literal["pending", "approved", "denied", "cancelled"] = "pending"
    summary: str = ""
    risk: str = "unknown"
    command_or_action: str | None = None
    action: str | None = None
    command: str | None = None
    paths: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    options: list[PermissionOption] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    raw_ref: str | None = None
    requested_at: str | None = None
    resolved_at: str | None = None
    decision: Literal["approve", "deny"] | None = None
    resolved_option_id: str | None = None
    decision_rationale: str | None = None
    deciding_primary: str | None = None
    adapter_resolution_status: Literal["accepted", "rejected", "ignored", "failed"] | None = None
    adapter_result: dict[str, Any] | None = None


@dataclass
class HarnessRunMetadata:
    profile_id: str
    runtime_family: str
    adapter: str
    auth_mode: str
    cost_posture: str
    metered_api: bool


@dataclass
class SessionMetadata:
    adapter_session_id: str | None = None
    process_id: int | None = None


@dataclass
class RunCounts:
    prompt_count: int = 0
    permission_count: int = 0
    approved_permission_count: int = 0
    denied_permission_count: int = 0
    cancelled_permission_count: int = 0


@dataclass
class LogRefs:
    dialogue: str
    transcript: str
    stderr: str
    permissions: str
    final_report: str


@dataclass
class FileAttributionRecord:
    path: str
    change_type: str
    attribution: str
    confidence: Literal["high", "medium", "low", "unknown"]
    notes: list[str] = field(default_factory=list)


@dataclass
class TaskRun:
    schema_version: int
    run_id: str
    status: Status
    workdir: str
    task: TaskInput
    harness: HarnessRunMetadata
    session: SessionMetadata
    counts: RunCounts
    changed_files: list[str] = field(default_factory=list)
    pre_existing_changed_files: list[str] = field(default_factory=list)
    changed_since_run_start: list[str] = field(default_factory=list)
    file_attribution: list[FileAttributionRecord] = field(default_factory=list)
    last_agent_message: str | None = None
    last_error: str | None = None
    adapter_status: str | None = None
    log_refs: LogRefs | None = None


@dataclass
class FinalReport:
    schema_version: int
    run_id: str
    status: Status
    changed_files: list[str]
    pre_existing_changed_files: list[str]
    changed_since_run_start: list[str]
    file_attribution: list[FileAttributionRecord]
    final_response: str | None
    last_error: str | None
    harness: HarnessRunMetadata
    adapter_status: str | None = None


@dataclass
class ToolTimelineItem:
    event_id: str
    timestamp: str
    kind: str
    speaker: str
    text: str | None = None


@dataclass
class RunWarning:
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"
    event_id: str | None = None


@dataclass
class CheckEvidence:
    command: str
    observed: bool
    exit_code: int | None = None
    status: Literal["passed", "failed", "unknown", "missing"] = "missing"
    event_id: str | None = None
    summary: str | None = None


@dataclass
class ToolCallEvidence:
    started: int = 0
    updated: int = 0
    completed: int = 0
    failed: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    completed_write_or_edit_count: int = 0
    completed_execute_count: int = 0


@dataclass
class PermissionEvidence:
    requested: int = 0
    approved: int = 0
    denied: int = 0
    cancelled: int = 0
    pending: int = 0


@dataclass
class RunEvidence:
    tool_calls: ToolCallEvidence
    checks: list[CheckEvidence] = field(default_factory=list)
    permissions: PermissionEvidence = field(default_factory=PermissionEvidence)
    policy_violations: list[RunWarning] = field(default_factory=list)


@dataclass
class RunSummary:
    schema_version: int
    run_id: str
    status: Status
    status_reason: str | None
    selected_profile: HarnessRunMetadata
    workdir: str
    changed_files: list[str]
    pre_existing_changed_files: list[str]
    changed_since_run_start: list[str]
    file_attribution: list[FileAttributionRecord]
    final_response: str | None
    latest_agent_response: str | None
    pending_permission_requests: list[PermissionRequest]
    permission_counts: RunCounts
    tool_timeline: list[ToolTimelineItem]
    evidence: RunEvidence
    evidence_status: Literal["complete", "review_needed", "repair_needed", "blocked"]
    evidence_score: int
    evidence_groups: dict[str, list[RunWarning]]
    tokens: TokenUsage
    token_sources: dict[str, Any]
    model: ModelTelemetry
    warnings: list[str]
    warning_details: list[RunWarning]
    failure_classification: list[str] = field(default_factory=list)
    log_refs: LogRefs | None = None


@dataclass
class RunStatusDigest:
    schema_version: int
    run_id: str
    status: Status
    selected_profile: HarnessRunMetadata
    changed_files: list[str]
    changed_file_count: int
    warning_codes: list[str]
    failure_classification: list[str]
    evidence_status: Literal["complete", "review_needed", "repair_needed", "blocked"]
    evidence_score: int
    requested_checks: list[CheckEvidence]
    pending_permission_count: int
    tool_counts: ToolCallEvidence
    tokens_known: bool
    model_known: bool
    policy_verdict: str
    policy_reason_codes: list[str]
    recommended_action: str
    raw_events_omitted: bool = True
    log_refs: LogRefs | None = None


@dataclass
class RepairSeed:
    title: str
    objective: str
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    acceptance_hints: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)


@dataclass
class RunPolicyVerdict:
    schema_version: int
    run_id: str
    policy_verdict: Literal["accept_candidate", "needs_repair", "reject", "blocked", "requires_primary_review"]
    reason_codes: list[str]
    recommended_action: str
    repair_seed: RepairSeed | None = None
    raw_events_omitted: bool = True


@dataclass
class RunMeasurement:
    run_id: str
    status: Status
    profile_id: str
    runtime_family: str
    started_at: str | None
    ended_at: str | None
    duration_seconds: float | None
    accepted: bool
    rejected: bool
    accepted_candidate: bool
    changed_files: list[str]
    warning_codes: list[str]
    check_statuses: list[str]
    failure_classification: list[str]
    permission_requests: int
    tool_calls_completed: int
    write_edit_calls_completed: int
    execute_calls_completed: int
    tokens: TokenUsage
    model: ModelTelemetry
    token_sources: dict[str, Any] = field(default_factory=dict)
    policy_verdict: str | None = None
    policy_reason_codes: list[str] = field(default_factory=list)
    file_attribution: list[FileAttributionRecord] = field(default_factory=list)


@dataclass
class DelegationTimeSummary:
    started_at: str | None = None
    ended_at: str | None = None
    wall_time_seconds: float | None = None
    secondary_run_seconds: float = 0.0
    primary_gap_seconds: float = 0.0
    primary_gap_ratio: float | None = None
    longest_secondary_run_seconds: float | None = None
    longest_primary_gap_seconds: float | None = None


@dataclass
class DelegationRunCounts:
    total: int = 0
    passed: int = 0
    failed: int = 0
    stopped: int = 0
    interrupted: int = 0
    accepted: int = 0
    rejected: int = 0
    accepted_candidates: int = 0


@dataclass
class DelegationEvidenceSummary:
    tool_calls_completed: int = 0
    write_edit_calls_completed: int = 0
    execute_calls_completed: int = 0
    checks_observed: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
    permission_requests: int = 0
    permission_approvals: int = 0
    permission_denials: int = 0
    policy_violations: int = 0
    failure_classification_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class DelegationAttribution:
    final_dirty_files: list[str] = field(default_factory=list)
    files_changed_by_runs: list[str] = field(default_factory=list)
    files_changed_by_accepted_runs: list[str] = field(default_factory=list)
    files_changed_by_rejected_runs: list[str] = field(default_factory=list)
    unattributed_final_files: list[str] = field(default_factory=list)
    rejected_files_still_present: list[str] = field(default_factory=list)
    generated_artifacts: list[str] = field(default_factory=list)
    file_records: list[FileAttributionRecord] = field(default_factory=list)
    confidence_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class OutcomeAssessment:
    status: Literal["success", "partial_success", "inconclusive", "failed"]
    score: float
    reason_codes: list[str] = field(default_factory=list)


@dataclass
class TokenAccounting:
    canonical: TokenUsage
    sources: dict[str, Any] = field(default_factory=dict)
    external_agent_logs_known: bool = False
    caveats: list[str] = field(default_factory=list)


@dataclass
class DelegationReport:
    schema_version: int
    session_id: str | None
    objective: str | None
    workdir: str | None
    run_ids: list[str]
    accepted_run_ids: list[str]
    rejected_run_ids: list[str]
    unassessed_run_ids: list[str]
    selected_profiles: list[str]
    profile_mix: dict[str, int]
    time: DelegationTimeSummary
    runs: DelegationRunCounts
    outcome: OutcomeAssessment
    tokens: TokenUsage
    models: ModelTelemetry
    token_accounting: TokenAccounting
    run_measurements: list[RunMeasurement]
    evidence: DelegationEvidenceSummary
    attribution: DelegationAttribution
    warnings: list[RunWarning]
    workflow: dict[str, Any] = field(default_factory=dict)


@dataclass
class DelegationRunAssessment:
    run_id: str
    decision: Literal["accepted", "rejected", "needs_repair"]
    rationale: str
    inspected_files: list[str] = field(default_factory=list)
    verification_commands: list[str] = field(default_factory=list)
    repair_prompt: str | None = None
    created_at: str | None = None


@dataclass
class DelegationRequirement:
    requirement_id: str
    statement: str
    proof_needed: str
    status: Literal["not_started", "in_progress", "satisfied", "blocked"] = "not_started"
    evidence: list[str] = field(default_factory=list)
    updated_at: str | None = None


@dataclass
class DelegationTicket:
    ticket_id: str
    title: str
    objective: str
    requirement_ids: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    acceptance_hints: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    status: Literal["not_started", "running", "needs_review", "accepted", "needs_repair", "rejected"] = "not_started"
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class DelegationTicketAttempt:
    ticket_id: str
    run_id: str
    attempt_number: int
    decision: Literal["pending", "accepted", "rejected", "needs_repair"] = "pending"
    created_at: str | None = None
    reviewed_at: str | None = None


@dataclass
class DelegationSession:
    schema_version: int
    session_id: str
    status: Literal["active", "finished"]
    objective: str
    workdir: str
    preferred_profile_id: str | None = None
    primary_harness: str | None = None
    max_runs: int | None = None
    run_ids: list[str] = field(default_factory=list)
    assessments: list[DelegationRunAssessment] = field(default_factory=list)
    requirements: list[DelegationRequirement] = field(default_factory=list)
    tickets: list[DelegationTicket] = field(default_factory=list)
    attempts: list[DelegationTicketAttempt] = field(default_factory=list)
    last_liveness_checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    session_warnings: list[RunWarning] = field(default_factory=list)
    final_status: str | None = None
    final_summary: str | None = None
    final_verification: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
