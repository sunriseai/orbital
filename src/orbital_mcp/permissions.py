from __future__ import annotations

from typing import Any

from .models import PermissionOption, PermissionRequest


ALLOW_HINTS = ("allow", "approve", "approved", "yes", "accept", "code", "edit")
DENY_HINTS = ("deny", "reject", "rejected", "no", "decline", "cancel")


def normalize_permission(run_id: str, adapter_request_id: str, raw: dict[str, Any]) -> PermissionRequest:
    params = raw.get("params", raw)
    tool_call = params.get("toolCall") if isinstance(params.get("toolCall"), dict) else {}
    raw_input = _dict_value(params.get("rawInput")) or _dict_value(tool_call.get("rawInput")) or {}
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
    command_or_action = _extract_command_or_action(params, tool_call, raw_input)
    return PermissionRequest(
        permission_id=f"perm-{run_id}-{adapter_request_id}",
        run_id=run_id,
        adapter_request_id=str(adapter_request_id),
        summary=str(params.get("summary") or params.get("title") or tool_call.get("title") or "Harness requested permission"),
        risk=str(params.get("risk") or params.get("type") or tool_call.get("kind") or "unknown"),
        command_or_action=command_or_action,
        action=_extract_action(params, tool_call, raw_input, command_or_action),
        command=_extract_command(params, tool_call, raw_input),
        paths=paths,
        resources=_extract_resources(params, tool_call, raw_input),
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

    for raw_input in [_dict_value(params.get("rawInput")), _dict_value(tool_call.get("rawInput"))]:
        if not raw_input:
            continue
        cwd = raw_input.get("cwd")
        if cwd:
            paths.append(str(cwd))
        for key in ["filePath", "filepath", "path"]:
            value = raw_input.get(key)
            if value:
                paths.append(str(value))
        for path in raw_input.get("changes", {}).keys():
            paths.append(str(path))

    return sorted(set(paths))


def _extract_command_or_action(params: dict[str, Any], tool_call: dict[str, Any], raw_input: dict[str, Any]) -> str | None:
    for value in [
        params.get("command"),
        params.get("action"),
        params.get("operation"),
        tool_call.get("command"),
        tool_call.get("title"),
        raw_input.get("command"),
        raw_input.get("action"),
        raw_input.get("operation"),
        raw_input.get("description"),
    ]:
        text = _stringify_scalar_or_command(value)
        if text:
            return text
    return None


def _extract_action(
    params: dict[str, Any],
    tool_call: dict[str, Any],
    raw_input: dict[str, Any],
    fallback: str | None,
) -> str | None:
    for value in [
        params.get("action"),
        params.get("operation"),
        tool_call.get("title"),
        raw_input.get("action"),
        raw_input.get("operation"),
        raw_input.get("description"),
    ]:
        text = _stringify_scalar_or_command(value)
        if text:
            return text
    return fallback


def _extract_command(params: dict[str, Any], tool_call: dict[str, Any], raw_input: dict[str, Any]) -> str | None:
    for value in [params.get("command"), tool_call.get("command"), raw_input.get("command")]:
        text = _stringify_scalar_or_command(value)
        if text:
            return text
    return None


def _extract_resources(params: dict[str, Any], tool_call: dict[str, Any], raw_input: dict[str, Any]) -> list[str]:
    resources: list[str] = []
    for source in [params, tool_call, raw_input]:
        resources.extend(_strings_from_value(source.get("resources")))
        for key in ["resource", "url", "uri", "host", "server", "package", "registry", "mcpServer", "mcp_server"]:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                resources.append(value.strip())
    return sorted(set(resources))


def _dict_value(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _stringify_scalar_or_command(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return " ".join(parts) if parts else None
    return None


def _strings_from_value(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                values.append(item.strip())
            elif isinstance(item, dict):
                for key in ["id", "name", "url", "uri", "host", "server", "package", "resource"]:
                    nested = item.get(key)
                    if isinstance(nested, str) and nested.strip():
                        values.append(nested.strip())
                        break
        return values
    if isinstance(value, dict):
        return _strings_from_value(list(value.values()))
    return []
