from __future__ import annotations

from typing import Any

from .models import PermissionOption, PermissionRequest


ALLOW_HINTS = ("allow", "approve", "approved", "yes", "accept", "code", "edit")
DENY_HINTS = ("deny", "reject", "rejected", "no", "decline", "cancel")


def normalize_permission(run_id: str, adapter_request_id: str, raw: dict[str, Any]) -> PermissionRequest:
    params = raw.get("params", raw)
    tool_call = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
    options_data = params.get("options") or [
        {"id": "allow", "label": "Allow", "kind": "allow"},
        {"id": "deny", "label": "Deny", "kind": "deny"},
    ]
    options = [
        PermissionOption(
            option_id=str(item.get("id") or item.get("option_id") or item.get("optionId") or item.get("kind") or idx),
            label=str(item.get("label") or item.get("name") or item.get("title") or item.get("id") or item.get("optionId") or item.get("kind") or idx),
            kind=(str(item.get("kind")) if item.get("kind") is not None else None),
        )
        for idx, item in enumerate(options_data)
    ]
    paths = _extract_paths(params, tool_call)
    return PermissionRequest(
        permission_id=f"perm-{run_id}-{adapter_request_id}",
        run_id=run_id,
        adapter_request_id=str(adapter_request_id),
        summary=str(params.get("summary") or params.get("title") or tool_call.get("title") or "Harness requested permission"),
        risk=str(params.get("risk") or params.get("type") or tool_call.get("kind") or "unknown"),
        paths=paths,
        options=options,
        raw=raw,
    )


def choose_option(request: PermissionRequest, decision: str, explicit_option_id: str | None = None) -> str:
    if explicit_option_id:
        if any(option.option_id == explicit_option_id for option in request.options):
            return explicit_option_id
        raise ValueError(f"unknown option_id for permission {request.permission_id}: {explicit_option_id}")

    hints = ALLOW_HINTS if decision == "approve" else DENY_HINTS
    matches: list[str] = []
    for option in request.options:
        haystack = " ".join(
            part.lower()
            for part in [option.option_id, option.label, option.kind]
            if part is not None
        )
        if any(hint in haystack for hint in hints):
            matches.append(option.option_id)

    unique = sorted(set(matches))
    if len(unique) == 1:
        return unique[0]
    if not unique:
        raise ValueError(f"could not infer {decision} option for permission {request.permission_id}")
    raise ValueError(f"ambiguous {decision} options for permission {request.permission_id}: {unique}")


def _extract_paths(params: dict[str, Any], tool_call: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    paths.extend(str(p) for p in params.get("paths", []) if p)

    for location in tool_call.get("locations", []):
        if isinstance(location, dict) and location.get("path"):
            paths.append(str(location["path"]))

    for item in tool_call.get("content", []):
        if isinstance(item, dict) and item.get("path"):
            paths.append(str(item["path"]))

    raw_input = tool_call.get("rawInput")
    if isinstance(raw_input, dict):
        cwd = raw_input.get("cwd")
        if cwd:
            paths.append(str(cwd))
        for path in raw_input.get("changes", {}).keys():
            paths.append(str(path))

    return sorted(set(paths))
