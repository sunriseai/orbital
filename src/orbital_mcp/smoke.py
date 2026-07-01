from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .models import TaskInput
from .server import build_service


SMOKE_FILES = {
    "codex": "ORBITAL_SMOKE.md",
    "opencode": "OPENCODE_SMOKE.md",
    "claude_code": "CLAUDE_SMOKE.md",
    "generic": "ORBITAL_SMOKE.md",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an Orbital profile smoke test.")
    parser.add_argument("--base-dir", default=".", help="Directory containing orbital.config.json")
    parser.add_argument("--profile", required=True, help="Harness profile id to smoke")
    parser.add_argument("--workdir", help="Existing or new workdir. Defaults to a temporary directory.")
    parser.add_argument("--timeout-seconds", type=float, default=120)
    args = parser.parse_args()
    summary = asyncio.run(_run(args))
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] != "completed":
        raise SystemExit(1)


async def _run(args: argparse.Namespace) -> dict:
    base_dir = Path(args.base_dir).resolve()
    service = build_service(base_dir)
    profile = service.registry.get(args.profile)
    workdir = Path(args.workdir).resolve() if args.workdir else Path(tempfile.mkdtemp(prefix="orbital-smoke-"))
    workdir.mkdir(parents=True, exist_ok=True)
    _init_git_repo_if_available(workdir)

    target = SMOKE_FILES.get(profile.runtime_family, SMOKE_FILES["generic"])
    task = TaskInput(
        title=f"Smoke {profile.id}",
        objective=(
            f"Create {target} containing one paragraph explaining that the "
            f"{profile.display_name} worker executed this task through Orbital MCP."
        ),
        allowed_paths=[target],
        acceptance_hints=[f"{target} exists"],
    )
    return await service.run_task_and_wait(
        workdir,
        task,
        profile_id=profile.id,
        timeout_seconds=args.timeout_seconds,
        poll_interval_ms=250,
        max_events=100,
    )


def _init_git_repo_if_available(workdir: Path) -> None:
    if (workdir / ".git").exists() or shutil.which("git") is None:
        return
    subprocess.run(["git", "init"], cwd=workdir, check=False, capture_output=True, text=True)


if __name__ == "__main__":
    main()
