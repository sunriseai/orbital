from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from orbital_mcp.models import HarnessConfig, HarnessProfile, TaskInput  # noqa: E402
from orbital_mcp.profiles import HarnessRegistry  # noqa: E402
from orbital_mcp.service import TaskRunService  # noqa: E402
from orbital_mcp.store import RunStore  # noqa: E402


TERMINAL_STATUSES = {"completed", "failed", "blocked", "cancelled", "interrupted", "unknown"}


def fake_acp_service(tmp: Path) -> TaskRunService:
    profile = fake_acp_profile()
    config = HarnessConfig(default_profile="fake_acp", storage_root=".orbital", profiles=[profile])
    return TaskRunService(HarnessRegistry(config), RunStore(tmp / ".orbital"))


def fake_acp_profile() -> HarnessProfile:
    profile = HarnessProfile(
        id="fake_acp",
        display_name="Fake ACP",
        adapter="acp",
        runtime_family="fake",
        command=[sys.executable, str(ROOT / "tests" / "fixtures" / "fake_acp_harness.py")],
        auth_mode="local_subscription",
        cost_posture="subscription_preferred",
        capabilities=["dialogue", "permissions", "tool_events", "stop"],
    )
    profile.support.tier = "known_good_acp"
    return profile


def write_fake_acp_config(base_dir: Path) -> None:
    config = {
        "default_profile": "fake_acp",
        "storage_root": ".orbital",
        "profiles": [
            {
                "id": "fake_acp",
                "display_name": "Fake ACP",
                "adapter": "acp",
                "runtime_family": "fake",
                "command": [sys.executable, str(ROOT / "tests" / "fixtures" / "fake_acp_harness.py")],
                "auth_mode": "local_subscription",
                "cost_posture": "subscription_preferred",
                "capabilities": ["dialogue", "permissions", "tool_events", "stop"],
                "support": {"tier": "known_good_acp"},
            }
        ],
    }
    (base_dir / "orbital.config.json").write_text(json.dumps(config), encoding="utf-8")


async def wait_for_permission(service: TaskRunService, run_id: str) -> str:
    for _ in range(240):
        summary = service.get_run_summary(run_id)
        pending = summary.get("pending_permission_requests") or []
        if pending:
            return pending[0]["permission_id"]
        await asyncio.sleep(0.05)
    raise AssertionError("permission request did not arrive")


async def wait_for_terminal_summary(service: TaskRunService, run_id: str) -> dict:
    for _ in range(120):
        summary = service.get_run_summary(run_id)
        if summary["status"] in TERMINAL_STATUSES:
            return summary
        await asyncio.sleep(0.05)
    raise AssertionError("run did not reach terminal status")


def run_async(coro):
    return asyncio.run(coro)


def remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        else:
            child.rmdir()
    path.rmdir()


def task(
    objective: str,
    *,
    title: str = "Fake validation task",
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    checks: list[str] | None = None,
) -> TaskInput:
    return TaskInput(
        title=title,
        objective=objective,
        allowed_paths=allowed_paths or [],
        forbidden_paths=forbidden_paths or [],
        checks=checks or [],
    )
