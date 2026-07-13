from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import asyncio

from orbital_test_helpers import (
    ROOT,
    fake_acp_service,
    remove_tree,
    run_async,
    task,
    wait_for_permission,
    wait_for_terminal_summary,
)


class FakeAcpValidationTests(unittest.TestCase):
    def test_permission_denial_is_recorded_and_classified_without_human_intervention(self) -> None:
        tmp = ROOT / ".tmp-test-validation-denial"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            summary = run_async(_deny_permission_flow(service, tmp))

            self.assertIn(summary["status"], {"failed", "blocked"})
            self.assertEqual(summary["permission_counts"]["permission_count"], 1)
            self.assertEqual(summary["permission_counts"]["denied_permission_count"], 1)
            self.assertIn("permission_denied_or_cancelled", summary["failure_classification"])
            self.assertTrue(any(item["phase"] == "permission" for item in summary["diagnostic_timeline"]))
            self.assertTrue(
                any(
                    item["code"] == "inspect_permission_outcome"
                    and item["artifact_ref"].endswith("permissions.jsonl")
                    for item in summary["diagnostic_explainability"]["diagnostic_next_steps"]
                )
            )
            verdict = service.get_run_policy_verdict(summary["run_id"])
            self.assertEqual(verdict["policy_verdict"], "needs_repair")
        finally:
            remove_tree(tmp)

    def test_failed_requested_check_is_evidence_and_repair_verdict(self) -> None:
        tmp = ROOT / ".tmp-test-validation-failed-check"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            summary = run_async(
                service.run_task_and_wait(
                    tmp,
                    task(
                        "Create fake_output.txt. FAILED_CHECK",
                        allowed_paths=["fake_output.txt"],
                        checks=["python3 -m pytest -q"],
                    ),
                    profile_id="fake_acp",
                    timeout_seconds=5,
                )
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["evidence"]["checks"][0]["status"], "failed")
            self.assertIn("failed_requested_check", summary["failure_classification"])
            verdict = service.get_run_policy_verdict(summary["run_id"])
            self.assertEqual(verdict["policy_verdict"], "needs_repair")
            self.assertEqual(verdict["repair_seed"]["checks"], ["python3 -m pytest -q"])
        finally:
            remove_tree(tmp)

    def test_forbidden_and_outside_allowed_path_changes_are_visible_policy_evidence(self) -> None:
        tmp = ROOT / ".tmp-test-validation-path-policy"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            summary = run_async(
                service.run_task_and_wait(
                    tmp,
                    task(
                        "Create fake_output.txt. FORBIDDEN_PATH OUTSIDE_ALLOWED",
                        allowed_paths=["fake_output.txt"],
                        forbidden_paths=["secret.txt"],
                    ),
                    profile_id="fake_acp",
                    timeout_seconds=5,
                )
            )

            self.assertEqual(summary["status"], "completed")
            self.assertIn("secret.txt", summary["changed_files"])
            self.assertIn("outside.txt", summary["changed_files"])
            self.assertIn("changed_forbidden_paths", summary["failure_classification"])
            self.assertIn("changed_outside_allowed_paths", summary["failure_classification"])
            verdict = service.get_run_policy_verdict(summary["run_id"])
            self.assertEqual(verdict["policy_verdict"], "reject")
        finally:
            remove_tree(tmp)

    def test_hung_fake_worker_can_be_stopped_and_reports_cancelled(self) -> None:
        tmp = ROOT / ".tmp-test-validation-stop"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            summary = run_async(_stop_sleeping_run(service, tmp))

            self.assertEqual(summary["status"], "cancelled")
            self.assertIn("cancelled", summary["failure_classification"])
            final_report = service.store.load_final_report(summary["run_id"])
            self.assertEqual(final_report["status"], "cancelled")
        finally:
            remove_tree(tmp)

    def test_stubborn_fake_worker_records_forced_kill_stop_evidence(self) -> None:
        tmp = ROOT / ".tmp-test-validation-kill-stop"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            summary = run_async(_stop_stubborn_run(service, tmp))
            dialogue = service.get_dialogue(summary["run_id"], include_agent_chunks=True)

            self.assertEqual(summary["status"], "cancelled")
            self.assertTrue(any("stop_method=kill" in str(event.get("text")) for event in dialogue["events"]))
        finally:
            remove_tree(tmp)

    def test_nonzero_exit_and_jsonrpc_error_fail_without_hanging(self) -> None:
        tmp = ROOT / ".tmp-test-validation-process-failures"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            nonzero = run_async(
                service.run_task_and_wait(
                    tmp,
                    task("EXIT_NONZERO", allowed_paths=["fake_output.txt"]),
                    profile_id="fake_acp",
                    timeout_seconds=5,
                )
            )
            jsonrpc = run_async(
                service.run_task_and_wait(
                    tmp,
                    task("JSONRPC_ERROR", allowed_paths=["fake_output.txt"]),
                    profile_id="fake_acp",
                    timeout_seconds=5,
                )
            )

            self.assertEqual(nonzero["status"], "failed")
            self.assertIn("ACP process exited before response", nonzero["status_reason"])
            self.assertEqual(jsonrpc["status"], "failed")
            self.assertIn("Fake JSON-RPC failure", jsonrpc["status_reason"])
        finally:
            remove_tree(tmp)

    def test_ambiguous_permission_options_require_explicit_adapter_option(self) -> None:
        tmp = ROOT / ".tmp-test-validation-ambiguous-permission"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            error = run_async(_ambiguous_permission_flow(service, tmp))

            self.assertIn("ambiguous approve options", error)
        finally:
            remove_tree(tmp)

    def test_send_task_message_followup_can_drive_active_fake_worker(self) -> None:
        tmp = ROOT / ".tmp-test-validation-followup"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            summary = run_async(_followup_flow(service, tmp))

            self.assertEqual(summary["status"], "completed")
            self.assertIn("followup_output.txt", summary["changed_files"])
            phases = {item["phase"] for item in summary["diagnostic_timeline"]}
            observed_codes = {item["code"] for item in summary["diagnostic_explainability"]["observed"]}
            self.assertIn("tool", phases)
            self.assertIn("terminal", phases)
            self.assertIn("changed_files", observed_codes)
            self.assertTrue((tmp / "followup_output.txt").exists())
        finally:
            remove_tree(tmp)

    def test_smoke_cli_runs_fake_profile_from_local_config_without_real_harness(self) -> None:
        tmp = ROOT / ".tmp-test-validation-smoke"
        workdir = tmp / "work"
        try:
            workdir.mkdir(parents=True, exist_ok=True)
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
            (tmp / "orbital.config.json").write_text(json.dumps(config), encoding="utf-8")
            env = {
                **os.environ,
                "PYTHONPATH": str(ROOT / "src"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "orbital_mcp.smoke",
                    "--base-dir",
                    str(tmp),
                    "--profile",
                    "fake_acp",
                    "--workdir",
                    str(workdir),
                    "--timeout-seconds",
                    "5",
                ],
                cwd=ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "completed")
            self.assertTrue((workdir / "ORBITAL_SMOKE.md").exists())
        finally:
            remove_tree(tmp)


async def _deny_permission_flow(service, tmp):
    response = await service.start_task_run(
        tmp,
        task("Implement fake task with permission.", allowed_paths=["fake_output.txt"]),
        profile_id="fake_acp",
    )
    run_id = response["run_id"]
    permission_id = await wait_for_permission(service, run_id)
    await service.resolve_permission(run_id, permission_id, "deny")
    summary = await wait_for_terminal_summary(service, run_id)
    if run_id in service._controllers:
        await service.stop_task_run(run_id)
    return summary


async def _stop_sleeping_run(service, tmp):
    response = await service.start_task_run(
        tmp,
        task("Create fake_output.txt. SLEEP", allowed_paths=["fake_output.txt"]),
        profile_id="fake_acp",
    )
    run_id = response["run_id"]
    for _ in range(80):
        summary = service.get_run_summary(run_id)
        if summary["status"] == "running":
            break
        await __import__("asyncio").sleep(0.05)
    await service.stop_task_run(run_id)
    return service.get_run_summary(run_id)


async def _stop_stubborn_run(service, tmp):
    response = await service.start_task_run(
        tmp,
        task("Create fake_output.txt. STUBBORN_SLEEP", allowed_paths=["fake_output.txt"]),
        profile_id="fake_acp",
    )
    run_id = response["run_id"]
    for _ in range(80):
        summary = service.get_run_summary(run_id)
        if summary["status"] == "running":
            break
        await asyncio.sleep(0.05)
    await service.stop_task_run(run_id)
    return service.get_run_summary(run_id)


async def _ambiguous_permission_flow(service, tmp):
    response = await service.start_task_run(
        tmp,
        task(
            "Implement fake task with permission. AMBIGUOUS_PERMISSION",
            allowed_paths=["fake_output.txt"],
        ),
        profile_id="fake_acp",
    )
    run_id = response["run_id"]
    permission_id = await wait_for_permission(service, run_id)
    try:
        await service.resolve_permission(run_id, permission_id, "approve")
    except ValueError as exc:
        error = str(exc)
    else:
        error = ""
    await service.stop_task_run(run_id)
    return error


async def _followup_flow(service, tmp):
    response = await service.start_task_run(
        tmp,
        task("WAIT_FOR_FOLLOWUP", allowed_paths=["followup_output.txt"]),
        profile_id="fake_acp",
    )
    run_id = response["run_id"]
    for _ in range(80):
        summary = service.get_run_summary(run_id)
        if summary["status"] == "running":
            break
        await asyncio.sleep(0.05)
    await service.send_task_message(run_id, "FOLLOWUP_WRITE")
    return await wait_for_terminal_summary(service, run_id)


if __name__ == "__main__":
    unittest.main()
