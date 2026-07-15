from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FEATURE_STATES = {"observed", "missing", "not_applicable", "capability_gap"}


@dataclass
class AcpConformanceExpectation:
    client_methods: list[str] = field(default_factory=list)
    server_methods: list[str] = field(default_factory=list)
    session_updates: list[str] = field(default_factory=list)
    normalized_features: list[str] = field(default_factory=list)
    result_statuses: list[str] = field(default_factory=list)
    permission_option_ids: list[str] = field(default_factory=list)
    permission_request_option_ids: list[str] = field(default_factory=list)
    unknown_methods: list[str] = field(default_factory=list)
    unknown_session_updates: list[str] = field(default_factory=list)
    malformed_line_numbers: list[int] = field(default_factory=list)
    permission_behavior: str | None = None
    min_permission_request_count: int = 0
    min_permission_resolution_count: int = 0
    min_permission_request_missing_option_id_count: int = 0
    min_jsonrpc_error_count: int = 0
    require_usage_payload: bool = False
    require_model_metadata: bool = False
    require_stderr: bool = False
    feature_states: dict[str, str] = field(default_factory=dict)


@dataclass
class AcpConformanceFixture:
    fixture_id: str
    profile_id: str
    runtime_family: str
    transcript: str
    expectation: AcpConformanceExpectation


REQUIRED_FIXTURE_FIELDS = {
    "fixture_id",
    "profile_id",
    "runtime_family",
    "transcript_lines",
    "expectation",
}


SUPPORTED_PERMISSION_BEHAVIORS = {"round_trip", "multi_round_trip", "capability_gap", "not_applicable"}


def evaluate_acp_conformance(transcript: str, expectation: AcpConformanceExpectation) -> dict[str, Any]:
    messages = parse_acp_transcript(transcript)
    observed = _observed_features(messages)
    capabilities = capability_matrix(observed)
    feature_states = feature_state_matrix(observed, expectation)
    raw_refs = raw_reference_matrix(messages, feature_states)
    missing = {
        "client_methods": _missing(expectation.client_methods, observed["client_methods"]),
        "server_methods": _missing(expectation.server_methods, observed["server_methods"]),
        "session_updates": _missing(expectation.session_updates, observed["session_updates"]),
        "normalized_features": _missing(expectation.normalized_features, observed["normalized_features"]),
        "result_statuses": _missing(expectation.result_statuses, observed["result_statuses"]),
        "permission_option_ids": _missing(expectation.permission_option_ids, observed["permission_option_ids"]),
        "permission_request_option_ids": _missing(
            expectation.permission_request_option_ids,
            observed["permission_request_option_ids"],
        ),
        "unknown_methods": _missing(expectation.unknown_methods, observed["unknown_methods"]),
        "unknown_session_updates": _missing(expectation.unknown_session_updates, observed["unknown_session_updates"]),
        "malformed_lines": _missing_ints(expectation.malformed_line_numbers, observed["malformed_lines"]),
        "usage_payload": ["usage_payload"] if expectation.require_usage_payload and not observed["usage_payload_count"] else [],
        "model_metadata": ["model_metadata"] if expectation.require_model_metadata and not observed["models"] else [],
        "stderr": ["stderr"] if expectation.require_stderr and not observed["stderr_lines"] else [],
        "permission_behavior": _missing_permission_behavior(expectation.permission_behavior, observed),
        "permission_request_count": _missing_min_count(
            "permission_request_count",
            expectation.min_permission_request_count,
            observed["permission_request_count"],
        ),
        "permission_resolution_count": _missing_min_count(
            "permission_resolution_count",
            expectation.min_permission_resolution_count,
            observed["permission_resolution_count"],
        ),
        "permission_request_missing_option_id_count": _missing_min_count(
            "permission_request_missing_option_id_count",
            expectation.min_permission_request_missing_option_id_count,
            observed["permission_request_missing_option_id_count"],
        ),
        "jsonrpc_error_count": _missing_min_count(
            "jsonrpc_error_count",
            expectation.min_jsonrpc_error_count,
            observed["jsonrpc_error_count"],
        ),
    }
    unexpected_malformed_lines = _unexpected_ints(expectation.malformed_line_numbers, observed["malformed_lines"])
    return {
        "schema_version": 1,
        "ok": not any(missing.values()) and not unexpected_malformed_lines,
        "observed": observed,
        "missing": missing,
        "unexpected": {"malformed_lines": unexpected_malformed_lines},
        "capabilities": capabilities,
        "feature_states": feature_states,
        "raw_refs": raw_refs,
    }


def load_acp_conformance_fixture(path: Path | str) -> AcpConformanceFixture:
    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_FIXTURE_FIELDS - set(payload))
    if missing:
        raise ValueError(f"ACP conformance fixture missing required fields: {', '.join(missing)}")
    expectation = payload.get("expectation")
    if not isinstance(expectation, dict):
        raise ValueError("ACP conformance fixture expectation must be an object")
    transcript_lines = payload.get("transcript_lines")
    if not isinstance(transcript_lines, list) or not all(isinstance(item, str) for item in transcript_lines):
        raise ValueError("ACP conformance fixture transcript_lines must be a list of strings")
    permission_behavior = expectation.get("permission_behavior")
    if permission_behavior is not None and permission_behavior not in SUPPORTED_PERMISSION_BEHAVIORS:
        raise ValueError(f"unsupported permission_behavior: {permission_behavior}")
    feature_states = _feature_states(expectation.get("feature_states"))
    return AcpConformanceFixture(
        fixture_id=str(payload["fixture_id"]),
        profile_id=str(payload["profile_id"]),
        runtime_family=str(payload["runtime_family"]),
        transcript="\n".join(transcript_lines) + "\n",
        expectation=AcpConformanceExpectation(
            client_methods=_string_list(expectation.get("client_methods")),
            server_methods=_string_list(expectation.get("server_methods")),
            session_updates=_string_list(expectation.get("session_updates")),
            normalized_features=_string_list(expectation.get("normalized_features")),
            result_statuses=_string_list(expectation.get("result_statuses")),
            permission_option_ids=_string_list(expectation.get("permission_option_ids")),
            permission_request_option_ids=_string_list(expectation.get("permission_request_option_ids")),
            unknown_methods=_string_list(expectation.get("unknown_methods")),
            unknown_session_updates=_string_list(expectation.get("unknown_session_updates")),
            malformed_line_numbers=_int_list(expectation.get("malformed_line_numbers")),
            permission_behavior=permission_behavior,
            min_permission_request_count=int(expectation.get("min_permission_request_count", 0) or 0),
            min_permission_resolution_count=int(expectation.get("min_permission_resolution_count", 0) or 0),
            min_permission_request_missing_option_id_count=int(
                expectation.get("min_permission_request_missing_option_id_count", 0) or 0
            ),
            min_jsonrpc_error_count=int(expectation.get("min_jsonrpc_error_count", 0) or 0),
            require_usage_payload=bool(expectation.get("require_usage_payload", False)),
            require_model_metadata=bool(expectation.get("require_model_metadata", False)),
            require_stderr=bool(expectation.get("require_stderr", False)),
            feature_states=feature_states,
        ),
    )


def evaluate_acp_conformance_fixture(path: Path | str) -> dict[str, Any]:
    fixture = load_acp_conformance_fixture(path)
    report = evaluate_acp_conformance(fixture.transcript, fixture.expectation)
    return {
        **report,
        "fixture_id": fixture.fixture_id,
        "profile_id": fixture.profile_id,
        "runtime_family": fixture.runtime_family,
    }


def capability_matrix(observed: dict[str, Any]) -> dict[str, bool]:
    features = set(observed.get("normalized_features") or [])
    return {
        "dialogue": "dialogue" in features,
        "tools": "tools" in features,
        "permissions": "permissions" in features,
        "permission_round_trip": bool(observed.get("permission_option_ids")),
        "multi_permission_round_trip": int(observed.get("permission_request_count") or 0) >= 2
        and int(observed.get("permission_resolution_count") or 0) >= 2,
        "stop_or_cancel": "stop_or_cancel" in features,
        "stderr": "stderr" in features,
        "unknown_payloads": bool(observed.get("unknown_methods") or observed.get("unknown_session_updates")),
        "malformed_payloads": bool(observed.get("malformed_lines")),
        "jsonrpc_errors": bool(observed.get("jsonrpc_error_count")),
        "model_metadata": bool(observed.get("models")),
        "adapter_usage_payload": bool(observed.get("usage_payload_count")),
        "terminal_result": "terminal_result" in features,
    }


def feature_state_matrix(observed: dict[str, Any], expectation: AcpConformanceExpectation) -> dict[str, str]:
    features = set(observed.get("normalized_features") or [])
    states = {
        "initialize": _observed_or_missing("initialize" in set(observed.get("client_methods") or [])),
        "session_creation": _observed_or_missing("session/new" in set(observed.get("client_methods") or [])),
        "prompt_submission": _observed_or_missing("session/prompt" in set(observed.get("client_methods") or [])),
        "dialogue": _observed_or_missing("dialogue" in features),
        "tools": _observed_or_missing("tools" in features),
        "permissions": _observed_or_missing("permissions" in features),
        "permission_resolution": _observed_or_missing(bool(observed.get("permission_option_ids"))),
        "stop_cancel": _observed_or_missing("stop_or_cancel" in features),
        "stderr": _observed_or_missing("stderr" in features),
        "model_metadata": _observed_or_missing(bool(observed.get("models"))),
        "adapter_usage_payload": _observed_or_missing(bool(observed.get("usage_payload_count"))),
        "canonical_local_log_telemetry": "not_applicable",
        "malformed_payload_handling": _observed_or_missing(bool(observed.get("malformed_lines"))),
        "terminal_result_shape": _observed_or_missing("terminal_result" in features),
    }
    if expectation.permission_behavior == "capability_gap":
        states["permissions"] = "capability_gap"
        states["permission_resolution"] = "capability_gap"
    elif expectation.permission_behavior == "not_applicable":
        states["permissions"] = "not_applicable"
        states["permission_resolution"] = "not_applicable"
    for feature, state in expectation.feature_states.items():
        if feature in states:
            states[feature] = state
    return states


def raw_reference_matrix(messages: list[dict[str, Any]], feature_states: dict[str, str]) -> dict[str, Any]:
    refs: dict[str, Any] = {
        "malformed_payloads": [
            _raw_line_ref(item)
            for item in messages
            if item.get("malformed")
        ],
        "unknown_payloads": [
            _raw_line_ref(item)
            for item in messages
            if _is_unknown_payload(item)
        ],
        "stderr": [
            _raw_line_ref(item)
            for item in messages
            if item.get("stderr")
        ],
        "capability_gaps": [
            {"feature": feature, "ref": f"feature_states.{feature}"}
            for feature, state in feature_states.items()
            if state == "capability_gap"
        ],
    }
    return refs


def parse_acp_transcript(transcript: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for line_number, line in enumerate(transcript.splitlines(), start=1):
        if line.startswith("! "):
            messages.append({"direction": "!", "line_number": line_number, "stderr": True, "text": line[2:]})
            continue
        if not line.startswith(("> ", "< ")):
            continue
        try:
            payload = json.loads(line[2:])
        except json.JSONDecodeError as exc:
            messages.append(
                {
                    "direction": line[0],
                    "line_number": line_number,
                    "malformed": True,
                    "error": str(exc),
                }
            )
            continue
        messages.append({"direction": line[0], "line_number": line_number, "message": payload})
    return messages


def _observed_features(messages: list[dict[str, Any]]) -> dict[str, Any]:
    observed: dict[str, Any] = {
        "client_methods": [],
        "server_methods": [],
        "session_updates": [],
        "normalized_features": [],
        "result_statuses": [],
        "permission_option_ids": [],
        "permission_request_option_ids": [],
        "permission_request_count": 0,
        "permission_resolution_count": 0,
        "permission_request_missing_option_id_count": 0,
        "jsonrpc_error_count": 0,
        "models": [],
        "usage_payload_count": 0,
        "malformed_lines": [],
        "stderr_lines": [],
        "unknown_methods": [],
        "unknown_session_updates": [],
        "message_count": len(messages),
    }
    for item in messages:
        if item.get("malformed"):
            observed["malformed_lines"].append(item["line_number"])
            continue
        if item.get("stderr"):
            observed["stderr_lines"].append(item["line_number"])
            _append_unique(observed["normalized_features"], "stderr")
            continue
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        if isinstance(message.get("error"), dict):
            observed["jsonrpc_error_count"] += 1
            _append_unique(observed["normalized_features"], "jsonrpc_error")
        direction = item.get("direction")
        method = message.get("method")
        if direction == ">" and method:
            _append_unique(observed["client_methods"], str(method))
        elif direction == "<" and method:
            _append_unique(observed["server_methods"], str(method))
        if method and str(method) not in _KNOWN_METHODS:
            _append_unique(observed["unknown_methods"], str(method))
        if str(method) in {"session/cancel", "session/stop"}:
            _append_unique(observed["normalized_features"], "stop_or_cancel")
        if str(method) in {"requestPermission", "session/requestPermission", "session.requestPermission", "session/request_permission", "permission/request"}:
            _append_unique(observed["normalized_features"], "permissions")
            observed["permission_request_count"] += 1
            _append_permission_request_options(observed, message)

        result = message.get("result") if isinstance(message.get("result"), dict) else {}
        if isinstance(result.get("status"), str):
            _append_unique(observed["result_statuses"], result["status"])
            _append_unique(observed["normalized_features"], "terminal_result")
        if isinstance(result.get("stopReason"), str):
            _append_unique(observed["result_statuses"], result["stopReason"])
            _append_unique(observed["normalized_features"], "terminal_result")
        outcome = result.get("outcome") if isinstance(result.get("outcome"), dict) else {}
        if isinstance(outcome.get("optionId"), str):
            _append_unique(observed["permission_option_ids"], outcome["optionId"])
            _append_unique(observed["normalized_features"], "permissions")
            observed["permission_resolution_count"] += 1

        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        update = params.get("update") if isinstance(params.get("update"), dict) else {}
        session_update = update.get("sessionUpdate")
        if isinstance(session_update, str):
            _append_unique(observed["session_updates"], session_update)
            if session_update not in _KNOWN_SESSION_UPDATES:
                _append_unique(observed["unknown_session_updates"], session_update)
            if session_update == "agent_message_chunk":
                _append_unique(observed["normalized_features"], "dialogue")
            if session_update in {"tool_call", "tool_call_update"}:
                _append_unique(observed["normalized_features"], "tools")
            if session_update == "usage_update":
                observed["usage_payload_count"] += 1
        if isinstance(update.get("usage"), dict):
            observed["usage_payload_count"] += 1
        if isinstance(result.get("usage"), dict):
            observed["usage_payload_count"] += 1
        if isinstance(result.get("_meta"), dict):
            _append_models_from_value(observed["models"], result["_meta"])
        if isinstance(update.get("model"), str):
            _append_unique(observed["models"], update["model"])
        _append_models_from_value(observed["models"], update)
    return observed


def _observed_or_missing(observed: bool) -> str:
    return "observed" if observed else "missing"


def _raw_line_ref(item: dict[str, Any]) -> dict[str, Any]:
    ref: dict[str, Any] = {"line": item.get("line_number")}
    if item.get("direction"):
        ref["direction"] = item["direction"]
    if item.get("malformed"):
        ref["kind"] = "malformed"
    elif item.get("stderr"):
        ref["kind"] = "stderr"
    else:
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        method = message.get("method")
        if isinstance(method, str):
            ref["method"] = method
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        update = params.get("update") if isinstance(params.get("update"), dict) else {}
        session_update = update.get("sessionUpdate")
        if isinstance(session_update, str):
            ref["session_update"] = session_update
    return ref


def _is_unknown_payload(item: dict[str, Any]) -> bool:
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    method = message.get("method")
    if isinstance(method, str) and method not in _KNOWN_METHODS:
        return True
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    update = params.get("update") if isinstance(params.get("update"), dict) else {}
    session_update = update.get("sessionUpdate")
    return isinstance(session_update, str) and session_update not in _KNOWN_SESSION_UPDATES


def _missing_permission_behavior(expected: str | None, observed: dict[str, Any]) -> list[str]:
    if expected is None:
        return []
    features = set(observed.get("normalized_features") or [])
    if expected == "round_trip":
        return [] if "permissions" in features and observed.get("permission_option_ids") else ["round_trip"]
    if expected == "multi_round_trip":
        if (
            "permissions" in features
            and int(observed.get("permission_request_count") or 0) >= 2
            and int(observed.get("permission_resolution_count") or 0) >= 2
        ):
            return []
        return ["multi_round_trip"]
    if expected == "capability_gap":
        return [] if "permissions" not in features and not observed.get("permission_option_ids") else ["capability_gap"]
    if expected == "not_applicable":
        return []
    return [expected]


def _missing(expected: list[str], observed: list[str]) -> list[str]:
    return [item for item in expected if item not in observed]


def _missing_min_count(name: str, expected: int, observed: int) -> list[str]:
    if expected <= 0 or observed >= expected:
        return []
    return [f"{name}>={expected}"]


def _missing_ints(expected: list[int], observed: list[int]) -> list[int]:
    return [item for item in expected if item not in observed]


def _unexpected_ints(expected: list[int], observed: list[int]) -> list[int]:
    return [item for item in observed if item not in expected]


def _append_permission_request_options(observed: dict[str, Any], message: dict[str, Any]) -> None:
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    options = params.get("options") if isinstance(params.get("options"), list) else []
    for option in options:
        if not isinstance(option, dict):
            observed["permission_request_missing_option_id_count"] += 1
            continue
        option_id = option.get("optionId") or option.get("option_id") or option.get("id")
        if isinstance(option_id, str) and option_id:
            _append_unique(observed["permission_request_option_ids"], option_id)
        else:
            observed["permission_request_missing_option_id_count"] += 1


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _append_models_from_value(models: list[str], value: Any) -> None:
    if isinstance(value, dict):
        for key in ("model", "model_id", "modelId", "model_name", "modelName"):
            model = value.get(key)
            if isinstance(model, str) and model:
                _append_unique(models, model)
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                _append_models_from_value(models, nested)
    elif isinstance(value, list):
        for item in value:
            _append_models_from_value(models, item)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    values: list[int] = []
    for item in value:
        try:
            values.append(int(item))
        except (TypeError, ValueError):
            continue
    return values


def _feature_states(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    states: dict[str, str] = {}
    for feature, state in value.items():
        if isinstance(feature, str) and isinstance(state, str) and state in FEATURE_STATES:
            states[feature] = state
    return states


_KNOWN_METHODS = {
    "initialize",
    "session/new",
    "session/prompt",
    "session/set_model",
    "session/cancel",
    "session/stop",
    "requestPermission",
    "session/requestPermission",
    "session.requestPermission",
    "session/request_permission",
    "permission/request",
}

_KNOWN_SESSION_UPDATES = {
    "agent_message_chunk",
    "available_commands_update",
    "session_info_update",
    "tool_call",
    "tool_call_update",
    "usage_update",
}
