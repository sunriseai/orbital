from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from orbital_mcp.models import TaskInput
from orbital_mcp.server import build_service


TERMINAL = {"completed", "failed", "blocked", "cancelled", "interrupted", "unknown"}


def main() -> None:
    base_dir = Path(_required_env("ORBITAL_PERMISSION_SMOKE_BASE")).resolve()
    workdir = Path(_required_env("ORBITAL_PERMISSION_SMOKE_WORKDIR")).resolve()
    profile_id = _required_env("ORBITAL_PERMISSION_SMOKE_PROFILE")
    timeout = float(os.environ.get("ORBITAL_PERMISSION_SMOKE_TIMEOUT", "120"))
    payload = asyncio.run(_run(base_dir, workdir, profile_id, timeout))
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload["result"] not in {"pass", "permission_capability_gap"}:
        raise SystemExit(1)


async def _run(base_dir: Path, workdir: Path, profile_id: str, timeout: float) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    _init_git_repo_if_available(workdir)
    service = build_service(base_dir)
    task = TaskInput(
        title=os.environ.get("ORBITAL_PERMISSION_SMOKE_TITLE") or f"Permission smoke {profile_id}",
        objective=os.environ.get("ORBITAL_PERMISSION_SMOKE_OBJECTIVE") or _default_objective(),
        allowed_paths=_list_env("ORBITAL_PERMISSION_SMOKE_ALLOWED_PATHS", ["PERMISSION_SMOKE.md"]),
        acceptance_hints=_list_env("ORBITAL_PERMISSION_SMOKE_ACCEPTANCE_HINTS", ["PERMISSION_SMOKE.md exists"]),
    )
    response = await service.start_task_run(workdir, task, profile_id=profile_id)
    run_id = response["run_id"]
    deadline = asyncio.get_running_loop().time() + timeout
    permission_id: str | None = None
    resolution: dict[str, Any] | None = None

    while asyncio.get_running_loop().time() < deadline:
        summary = service.get_run_summary(run_id)
        pending = summary.get("pending_permission_requests") or []
        if pending:
            permission = pending[0]
            permission_id = permission["permission_id"]
            option_id = _choose_allow_option(permission)
            print("Observed pending permission:")
            print(json.dumps(permission, indent=2, sort_keys=True))
            resolution = await service.resolve_permission(
                run_id,
                permission_id,
                "approve",
                option_id=option_id,
                rationale="manual permission smoke approval",
            )
            print("Resolution:")
            print(json.dumps(resolution["permission"], indent=2, sort_keys=True))
            break
        if summary["status"] in TERMINAL:
            result = "permission_capability_gap" if _completed_without_permission(summary) else "no_permission_observed"
            return _result(result, service, run_id, permission_id, resolution)
        await asyncio.sleep(0.25)

    if permission_id is None:
        return _result("timeout_waiting_for_permission", service, run_id, permission_id, resolution)

    while asyncio.get_running_loop().time() < deadline:
        summary = service.get_run_summary(run_id)
        if summary["status"] in TERMINAL:
            return _result("pass" if _passed(summary) else "permission_observed_but_run_failed", service, run_id, permission_id, resolution)
        await asyncio.sleep(0.25)

    return _result("timeout_after_permission", service, run_id, permission_id, resolution)


def _choose_allow_option(permission: dict[str, Any]) -> str | None:
    options = permission.get("options") or []
    for option in options:
        haystack = " ".join(
            str(option.get(key, "")).lower()
            for key in ["option_id", "label", "kind"]
        )
        if any(token in haystack for token in ["allow", "approve", "yes", "accept"]):
            return option.get("option_id")
    return options[0].get("option_id") if options else None


def _passed(summary: dict[str, Any]) -> bool:
    counts = summary.get("permission_counts") or {}
    return summary.get("status") == "completed" and counts.get("approved_permission_count", 0) >= 1


def _completed_without_permission(summary: dict[str, Any]) -> bool:
    counts = summary.get("permission_counts") or {}
    return summary.get("status") == "completed" and counts.get("permission_count", 0) == 0


def _result(
    result: str,
    service,
    run_id: str,
    permission_id: str | None,
    resolution: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = service.get_run_summary(run_id, max_events=200)
    notes = []
    if result == "permission_capability_gap":
        notes.append(
            "The secondary ACP harness completed the task without emitting a permission request. "
            "Orbital's permission mediation path was not exercised by this real-runtime run."
        )
    return {
        "result": result,
        "result_notes": notes,
        "run_id": run_id,
        "permission_id": permission_id,
        "resolution": resolution,
        "summary": summary,
        "transcript_tail": service.get_run_log_tail(run_id, "transcript.log", max_bytes=20_000),
        "stderr_tail": service.get_run_log_tail(run_id, "stderr.log", max_bytes=10_000),
    }


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _list_env(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _default_objective() -> str:
    return (
        "Create PERMISSION_SMOKE.md by running a shell command rather than by direct file editing. "
        "If your harness asks for approval, request approval and wait. The file should contain one "
        "sentence explaining that the worker executed a permission smoke through Orbital MCP."
    )


def _init_git_repo_if_available(workdir: Path) -> None:
    if (workdir / ".git").exists() or shutil.which("git") is None:
        return
    subprocess.run(["git", "init"], cwd=workdir, check=False, capture_output=True, text=True)


if __name__ == "__main__":
    main()
