from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AcpConformanceExpectation:
    client_methods: list[str] = field(default_factory=list)
    server_methods: list[str] = field(default_factory=list)
    session_updates: list[str] = field(default_factory=list)
    result_statuses: list[str] = field(default_factory=list)
    permission_option_ids: list[str] = field(default_factory=list)
    require_usage_payload: bool = False
    require_model_metadata: bool = False


def evaluate_acp_conformance(transcript: str, expectation: AcpConformanceExpectation) -> dict[str, Any]:
    messages = parse_acp_transcript(transcript)
    observed = _observed_features(messages)
    missing = {
        "client_methods": _missing(expectation.client_methods, observed["client_methods"]),
        "server_methods": _missing(expectation.server_methods, observed["server_methods"]),
        "session_updates": _missing(expectation.session_updates, observed["session_updates"]),
        "result_statuses": _missing(expectation.result_statuses, observed["result_statuses"]),
        "permission_option_ids": _missing(expectation.permission_option_ids, observed["permission_option_ids"]),
        "usage_payload": ["usage_payload"] if expectation.require_usage_payload and not observed["usage_payload_count"] else [],
        "model_metadata": ["model_metadata"] if expectation.require_model_metadata and not observed["models"] else [],
    }
    return {
        "schema_version": 1,
        "ok": not any(missing.values()) and not observed["malformed_lines"],
        "observed": observed,
        "missing": missing,
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

        result = message.get("result") if isinstance(message.get("result"), dict) else {}
        if isinstance(result.get("status"), str):
            _append_unique(observed["result_statuses"], result["status"])
        outcome = result.get("outcome") if isinstance(result.get("outcome"), dict) else {}
        if isinstance(outcome.get("optionId"), str):
            _append_unique(observed["permission_option_ids"], outcome["optionId"])

        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        update = params.get("update") if isinstance(params.get("update"), dict) else {}
        if isinstance(update.get("sessionUpdate"), str):
            _append_unique(observed["session_updates"], update["sessionUpdate"])
        if isinstance(update.get("usage"), dict):
            observed["usage_payload_count"] += 1
        if isinstance(update.get("model"), str):
            _append_unique(observed["models"], update["model"])
    return observed


def _missing(expected: list[str], observed: list[str]) -> list[str]:
    return [item for item in expected if item not in observed]


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
