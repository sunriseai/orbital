from __future__ import annotations

TASK_SUBMITTED = "task_submitted"
STARTUP_PROMPT_SENT = "startup_prompt_sent"
HOST_MESSAGE = "host_message"
AGENT_MESSAGE_CHUNK = "agent_message_chunk"
TOOL_CALL_STARTED = "tool_call_started"
TOOL_CALL_UPDATED = "tool_call_updated"
TOOL_CALL_COMPLETED = "tool_call_completed"
TOOL_CALL_FAILED = "tool_call_failed"
PERMISSION_REQUESTED = "permission_requested"
PERMISSION_APPROVED = "permission_approved"
PERMISSION_DENIED = "permission_denied"
PERMISSION_CANCELLED = "permission_cancelled"
STDERR = "stderr"
RUN_ERROR = "run_error"
RUN_STOPPED = "run_stopped"
ACCEPTANCE_CHECK_FAILED = "acceptance_check_failed"
POLICY_VIOLATION = "policy_violation"

TOOL_EVENT_KINDS = {
    TOOL_CALL_STARTED,
    TOOL_CALL_UPDATED,
    TOOL_CALL_COMPLETED,
    TOOL_CALL_FAILED,
}

WARNING_EVENT_KINDS = {
    STDERR,
    RUN_ERROR,
    ACCEPTANCE_CHECK_FAILED,
    POLICY_VIOLATION,
}

TERMINAL_STATUSES = {"completed", "failed", "blocked", "cancelled", "interrupted", "unknown"}
