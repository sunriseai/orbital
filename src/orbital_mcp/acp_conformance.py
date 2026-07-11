from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AcpConformanceExpectation:
    client_methods: list[str] = field(default_factory=list)
    server_methods: list[str] = field(default_factory=list)
    session_updates: list[str] = field(default_factory=list)
    normalized_features: list[str] = field(default_factory=list)
    result_statuses: list[str] = field(default_factory=list)
    permission_option_ids: list[str] = field(default_factory=list)
    permission_behavior: str | None = None
    require_usage_payload: bool = False
    require_model_metadata: bool = False


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


SUPPORTED_PERMISSION_BEHAVIORS = {"round_trip", "capability_gap", "not_applicable"}


def evaluate_acp_conformance(transcript: str, expectation: AcpConformanceExpectation) -> dict[str, Any]:
    messages = parse_acp_transcript(transcript)
    observed = _observed_features(messages)
    missing = {
        "client_methods": _missing(expectation.client_methods, observed["client_methods"]),
        "server_methods": _missing(expectation.server_methods, observed["server_methods"]),
        "session_updates": _missing(expectation.session_updates, observed["session_updates"]),
        "normalized_features": _missing(expectation.normalized_features, observed["normalized_features"]),
        "result_statuses": _missing(expectation.result_statuses, observed["result_statuses"]),
        "permission_option_ids": _missing(expectation.permission_option_ids, observed["permission_option_ids"]),
        "usage_payload": ["usage_payload"] if expectation.require_usage_payload and not observed["usage_payload_count"] else [],
        "model_metadata": ["model_metadata"] if expectation.require_model_metadata and not observed["models"] else [],
        "permission_behavior": _missing_permission_behavior(expectation.permission_behavior, observed),
    }
    return {
        "schema_version": 1,
        "ok": not any(missing.values()) and not observed["malformed_lines"],
        "observed": observed,
        "missing": missing,
        "capabilities": capability_matrix(observed),
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
            permission_behavior=permission_behavior,
            require_usage_payload=bool(expectation.get("require_usage_payload", False)),
            require_model_metadata=bool(expectation.get("require_model_metadata", False)),
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
        "stop_or_cancel": "stop_or_cancel" in features,
        "stderr": "stderr" in features,
        "model_metadata": bool(observed.get("models")),
        "adapter_usage_payload": bool(observed.get("usage_payload_count")),
        "terminal_result": "terminal_result" in features,
    }


def parse_acp_transcript(transcript: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for line_number, line in enumerate(transcript.splitlines(), start=1):
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
        "models": [],
        "usage_payload_count": 0,
        "malformed_lines": [],
        "message_count": len(messages),
    }
    for item in messages:
        if item.get("malformed"):
            observed["malformed_lines"].append(item["line_number"])
            continue
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        direction = item.get("direction")
        method = message.get("method")
        if direction == ">" and method:
            _append_unique(observed["client_methods"], str(method))
        elif direction == "<" and method:
            _append_unique(observed["server_methods"], str(method))
        if str(method) in {"session/cancel", "session/stop"}:
            _append_unique(observed["normalized_features"], "stop_or_cancel")
        if str(method) in {"requestPermission", "session/requestPermission", "session.requestPermission", "session/request_permission", "permission/request"}:
            _append_unique(observed["normalized_features"], "permissions")

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

        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        update = params.get("update") if isinstance(params.get("update"), dict) else {}
        session_update = update.get("sessionUpdate")
        if isinstance(session_update, str):
            _append_unique(observed["session_updates"], session_update)
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


def _missing_permission_behavior(expected: str | None, observed: dict[str, Any]) -> list[str]:
    if expected is None:
        return []
    features = set(observed.get("normalized_features") or [])
    if expected == "round_trip":
        return [] if "permissions" in features and observed.get("permission_option_ids") else ["round_trip"]
    if expected == "capability_gap":
        return [] if "permissions" not in features and not observed.get("permission_option_ids") else ["capability_gap"]
    if expected == "not_applicable":
        return []
    return [expected]


def _missing(expected: list[str], observed: list[str]) -> list[str]:
    return [item for item in expected if item not in observed]


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
