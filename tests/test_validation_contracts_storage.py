from __future__ import annotations

import unittest
from pathlib import Path

from orbital_test_helpers import ROOT, remove_tree

from orbital_mcp.errors import error_response, ok_response  # noqa: E402
from orbital_mcp.models import (  # noqa: E402
    HarnessRunMetadata,
    PermissionRequest,
    RunCounts,
    SessionMetadata,
    TaskInput,
    TaskRun,
)
from orbital_mcp.profiles import HarnessRegistry  # noqa: E402
from orbital_mcp.config import load_config  # noqa: E402
from orbital_mcp.service import TaskRunService  # noqa: E402
from orbital_mcp.store import RunStore  # noqa: E402


class ContractAndStorageValidationTests(unittest.TestCase):
    def test_success_and_error_envelopes_have_stable_contract_shape(self) -> None:
        success = ok_response({"schema_version": 1, "value": "ok"})
        failure = error_response(ValueError("unknown permission: perm-1"))

        self.assertEqual(success, {"ok": True, "schema_version": 1, "value": "ok"})
        self.assertFalse(failure["ok"])
        self.assertEqual(failure["error"]["code"], "unknown_permission")
        for key in ["code", "message", "details", "retryable", "user_action"]:
            self.assertIn(key, failure["error"])

    def test_append_only_permission_log_uses_latest_state_for_summary_and_verdict(self) -> None:
        tmp = ROOT / ".tmp-test-contract-permission-latest"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-contract-permission", tmp, status="failed")
        try:
            store.create_run(run)
            pending = PermissionRequest(
                permission_id="perm-task-run-contract-permission-1",
                run_id=run.run_id,
                adapter_request_id="1",
                summary="Edit fake_output.txt",
            )
            denied = PermissionRequest(
                permission_id=pending.permission_id,
                run_id=run.run_id,
                adapter_request_id="1",
                summary="Edit fake_output.txt",
                status="denied",
                resolved_option_id="deny",
            )
            store.append_permission(pending)
            store.append_permission(denied)
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            summary = service.get_run_summary(run.run_id)
            verdict = service.get_run_policy_verdict(run.run_id)

            self.assertEqual(summary["pending_permission_requests"], [])
            self.assertEqual(summary["evidence"]["permissions"]["denied"], 1)
            self.assertIn("permission_denied_or_cancelled", summary["failure_classification"])
            self.assertNotEqual(verdict["policy_verdict"], "blocked")
        finally:
            remove_tree(tmp)

    def test_malformed_final_report_is_diagnostic_and_does_not_break_primary_safe_summary(self) -> None:
        tmp = ROOT / ".tmp-test-contract-malformed-report"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-contract-malformed-report", tmp, status="completed")
        try:
            store.create_run(run)
            (store.run_dir(run.run_id) / "final_report.json").write_text("{bad json", encoding="utf-8")
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            diagnostics = store.storage_diagnostics(run.run_id)
            summary = service.get_run_summary(run.run_id)

            self.assertIn("malformed_json", [issue["code"] for issue in diagnostics["issues"]])
            self.assertEqual(summary["status"], "completed")
            self.assertIn("malformed_final_report", [warning["code"] for warning in summary["warning_details"]])
            self.assertTrue(
                any(
                    item["warning_code"] == "malformed_final_report"
                    and item["artifact_ref"].endswith("final_report.json")
                    for item in summary["diagnostic_timeline"]
                )
            )
            self.assertTrue(
                any(
                    item["code"] == "inspect_malformed_final_report"
                    and item["artifact_ref"].endswith("final_report.json")
                    for item in summary["diagnostic_explainability"]["diagnostic_next_steps"]
                )
            )
        finally:
            remove_tree(tmp)

    def test_session_warnings_persist_across_service_restart(self) -> None:
        tmp = ROOT / ".tmp-test-contract-session-persistence"
        try:
            tmp.mkdir(exist_ok=True)
            store = RunStore(tmp / ".orbital")
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)
            session = service.start_delegation_session(tmp, "Persistence")
            session_id = session["session"]["session_id"]
            service.create_requirement(session_id, "REQ-1", "Thing is done", "Evidence exists")
            service.create_delegation_ticket(
                session_id,
                "task-1",
                "Do thing",
                "Do the thing.",
                requirement_ids=["REQ-1"],
            )
            service.finish_delegation_session(session_id, "partial_success")

            restarted = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)
            payload = restarted.get_delegation_session(session_id)

            self.assertIn("unsatisfied_requirements", [item["code"] for item in payload["session"]["session_warnings"]])
            self.assertEqual(payload["session"]["requirements"][0]["status"], "in_progress")
        finally:
            remove_tree(tmp)

    def test_recovered_pending_permission_is_visible_stale_and_not_resolvable(self) -> None:
        tmp = ROOT / ".tmp-test-contract-stale-permission"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-contract-stale-permission", tmp, status="waiting_for_permission")
        try:
            store.create_run(run)
            store.append_permission(
                PermissionRequest(
                    permission_id="perm-task-run-contract-stale-permission-1",
                    run_id=run.run_id,
                    adapter_request_id="1",
                    summary="Edit fake_output.txt",
                )
            )

            recovered = store.recover_interrupted_runs()
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)
            diagnostics = store.storage_diagnostics(run.run_id)
            summary = service.get_run_summary(run.run_id)

            self.assertEqual(recovered[0]["status"], "interrupted")
            stale = [issue for issue in diagnostics["issues"] if issue["code"] == "stale_pending_permission"]
            self.assertEqual(stale[0]["permission_id"], "perm-task-run-contract-stale-permission-1")
            self.assertEqual(stale[0]["recoverability"], "not_resolvable_without_adapter_reattachment")
            self.assertEqual(summary["status"], "interrupted")
            self.assertEqual(
                summary["pending_permission_requests"][0]["permission_id"],
                "perm-task-run-contract-stale-permission-1",
            )
            with self.assertRaisesRegex(ValueError, "permission_not_resolvable_after_restart"):
                _run_async(
                    service.resolve_permission(
                        run.run_id,
                        "perm-task-run-contract-stale-permission-1",
                        "approve",
                    )
                )
        finally:
            remove_tree(tmp)


def _run(run_id: str, workdir: Path, status: str = "running") -> TaskRun:
    return TaskRun(
        schema_version=1,
        run_id=run_id,
        status=status,
        workdir=str(workdir),
        task=TaskInput(title="Task", objective="Do work"),
        harness=HarnessRunMetadata(
            profile_id="fake",
            runtime_family="generic",
            adapter="acp",
            auth_mode="local_subscription",
            cost_posture="subscription_preferred",
            metered_api=False,
        ),
        session=SessionMetadata(),
        counts=RunCounts(),
    )


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
