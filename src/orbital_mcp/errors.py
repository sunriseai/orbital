from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StableError:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    user_action: str | None = None


def stable_error(exc: BaseException) -> StableError:
    message = str(exc) or exc.__class__.__name__
    code = _code_for_message(message)
    return StableError(
        code=code,
        message=message,
        details={"exception_type": exc.__class__.__name__},
        retryable=code in {"run_active", "profile_not_ready", "temporary_io_error"},
        user_action=_user_action(code),
    )


def error_response(exc: BaseException) -> dict[str, Any]:
    error = stable_error(exc)
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
            "retryable": error.retryable,
            "user_action": error.user_action,
        },
    }


def ok_response(payload: dict[str, Any]) -> dict[str, Any]:
    if "ok" in payload:
        return payload
    return {"ok": True, **payload}


def _code_for_message(message: str) -> str:
    lowered = message.lower()
    if "permission_not_resolvable_after_restart" in lowered:
        return "permission_not_resolvable_after_restart"
    if "adapter_permission_resolution_failed" in lowered:
        return "adapter_permission_resolution_failed"
    if "unknown adapter request" in lowered:
        return "unknown_adapter_request"
    if "unknown permission" in lowered:
        return "unknown_permission"
    if "already resolved" in lowered:
        return "permission_already_resolved"
    if "ambiguous" in lowered and "option" in lowered:
        return "ambiguous_permission_option"
    if "could not infer" in lowered and "option" in lowered:
        return "permission_option_not_inferable"
    if "unknown run_id" in lowered:
        return "unknown_run"
    if "run is not active" in lowered:
        return "run_not_active"
    if "profile is not ready" in lowered:
        return "profile_not_ready"
    if "unknown harness profile" in lowered:
        return "unknown_profile"
    if "metered api profile is not allowed" in lowered:
        return "metered_api_not_allowed"
    if "invalid run_id" in lowered:
        return "invalid_run_id"
    if "invalid session_id" in lowered:
        return "invalid_session_id"
    if "no runs found" in lowered:
        return "no_runs"
    return "internal_error"


def _user_action(code: str) -> str | None:
    return {
        "permission_not_resolvable_after_restart": "Start a new run or reattach the adapter when supported.",
        "adapter_permission_resolution_failed": "Refresh the run summary; the decision was recorded but the adapter did not accept it.",
        "unknown_adapter_request": "Refresh the run summary and resolve the listed adapter_request_id for that permission.",
        "unknown_permission": "Refresh the run summary and use a listed pending permission_id.",
        "permission_already_resolved": "Refresh the run summary before sending another decision.",
        "ambiguous_permission_option": "Pass an explicit adapter option_id.",
        "permission_option_not_inferable": "Pass an explicit adapter option_id.",
        "unknown_run": "Refresh list_task_runs and retry with an existing run_id.",
        "run_not_active": "Inspect the run summary; follow-up messages require an active controller.",
        "profile_not_ready": "Run check_harness_profile and install or configure missing prerequisites.",
        "unknown_profile": "Call list_harness_profiles and choose an existing profile_id.",
        "metered_api_not_allowed": "Select the profile explicitly with allow_metered_api or enable API fallback in config.",
        "invalid_run_id": "Use the exact run_id returned by start_task_run or list_task_runs.",
        "invalid_session_id": "Use the exact session_id returned by start_delegation_session.",
        "no_runs": "Start a task run before requesting the latest run.",
    }.get(code)
