from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from orbital_mcp.models import TaskInput
from orbital_mcp.server import build_service


TERMINAL = {"completed", "failed", "blocked", "cancelled", "interrupted", "unknown"}


def main() -> None:
    base_dir = Path(_required_env("ORBITAL_TOKEN_SMOKE_BASE")).resolve()
    workdir = Path(_required_env("ORBITAL_TOKEN_SMOKE_WORKDIR")).resolve()
    profile_id = _required_env("ORBITAL_TOKEN_SMOKE_PROFILE")
    timeout = float(os.environ.get("ORBITAL_TOKEN_SMOKE_TIMEOUT", "120"))
    token_wait = float(os.environ.get("ORBITAL_TOKEN_SMOKE_TOKEN_WAIT", "30"))
    payload = asyncio.run(_run(base_dir, workdir, profile_id, timeout, token_wait))
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload["result"] != "pass":
        raise SystemExit(1)


async def _run(base_dir: Path, workdir: Path, profile_id: str, timeout: float, token_wait: float) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    _init_git_repo_if_available(workdir)
    service = build_service(base_dir)
    task = TaskInput(
        title=f"Canonical token smoke {profile_id}",
        objective=(
            "Create TOKEN_SMOKE.md containing one sentence that says this run exists "
            "to verify Orbital canonical token telemetry."
        ),
        allowed_paths=["TOKEN_SMOKE.md"],
        acceptance_hints=["TOKEN_SMOKE.md exists"],
    )
    response = await service.start_task_run(workdir, task, profile_id=profile_id)
    run_id = response["run_id"]
    deadline = asyncio.get_running_loop().time() + timeout

    summary: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() < deadline:
        summary = service.get_run_summary(run_id, max_events=200)
        if summary["status"] in TERMINAL:
            break
        await asyncio.sleep(0.25)
    else:
        return _result("timeout_waiting_for_terminal", service, run_id)

    assert summary is not None
    if summary["status"] != "completed":
        return _result("run_not_completed", service, run_id)

    token_deadline = asyncio.get_running_loop().time() + token_wait
    while asyncio.get_running_loop().time() < token_deadline:
        summary = service.get_run_summary(run_id, max_events=200)
        tokens = summary.get("tokens") or {}
        external = (summary.get("token_sources") or {}).get("external_agent_logs") or {}
        records = external.get("records") or []
        if (
            tokens.get("known")
            and tokens.get("source") == "external_agent_logs"
            and tokens.get("total")
            and len(records) == 1
        ):
            return _result("pass", service, run_id)
        await asyncio.sleep(0.5)

    return _result("canonical_tokens_not_uniquely_correlated", service, run_id)


def _result(result: str, service, run_id: str) -> dict[str, Any]:
    summary = service.get_run_summary(run_id, max_events=200)
    return {
        "result": result,
        "run_id": run_id,
        "status": summary.get("status"),
        "tokens": summary.get("tokens"),
        "token_sources": summary.get("token_sources"),
        "log_refs": summary.get("log_refs"),
        "transcript_tail": service.get_run_log_tail(run_id, "transcript.log", max_bytes=20_000),
        "stderr_tail": service.get_run_log_tail(run_id, "stderr.log", max_bytes=10_000),
    }


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _init_git_repo_if_available(workdir: Path) -> None:
    if (workdir / ".git").exists() or shutil.which("git") is None:
        return
    subprocess.run(["git", "init"], cwd=workdir, check=False, capture_output=True, text=True)


if __name__ == "__main__":
    main()
