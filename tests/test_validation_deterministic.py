from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orbital_test_helpers import ROOT, remove_tree

from orbital_mcp.dialogue import new_event  # noqa: E402
from orbital_mcp.events import AGENT_MESSAGE_CHUNK, TOOL_CALL_COMPLETED  # noqa: E402
from orbital_mcp.liveness import LivenessThresholds, analyze_run_liveness  # noqa: E402
from orbital_mcp.models import HarnessRunMetadata, RunCounts, SessionMetadata, TaskInput, TaskRun  # noqa: E402
from orbital_mcp.profiles import HarnessRegistry  # noqa: E402
from orbital_mcp.config import load_config  # noqa: E402
from orbital_mcp.service import TaskRunService  # noqa: E402
from orbital_mcp.store import RunStore  # noqa: E402


class DeterministicValidationTests(unittest.TestCase):
    def test_primary_safe_dialogue_omits_raw_and_agent_chunks_but_debug_can_include_them(self) -> None:
        tmp = ROOT / ".tmp-test-validation-dialogue"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-validation-dialogue", tmp, status="running")
        try:
            store.create_run(run)
            store.append_dialogue(new_event(run.run_id, AGENT_MESSAGE_CHUNK, "worker", "chunk", raw={"secret": "raw"}))
            store.append_dialogue(
                new_event(
                    run.run_id,
                    TOOL_CALL_COMPLETED,
                    "worker",
                    "x" * 800,
                    raw={"tool": {"large": True}},
                )
            )
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            primary_safe = service.get_dialogue(run.run_id)
            debug = service.get_dialogue(run.run_id, include_raw=True, include_agent_chunks=True, max_chars=700)

            self.assertTrue(primary_safe["raw_events_omitted"])
            self.assertTrue(primary_safe["agent_chunks_omitted"])
            self.assertEqual([event["kind"] for event in primary_safe["events"]], [TOOL_CALL_COMPLETED])
            self.assertTrue(all("raw" not in event for event in primary_safe["events"]))
            self.assertEqual(debug["events"][0]["kind"], AGENT_MESSAGE_CHUNK)
            self.assertIn("raw", debug["events"][0])
            self.assertTrue(debug["has_more"])
        finally:
            remove_tree(tmp)

    def test_status_digest_has_stable_primary_safe_contract_fields(self) -> None:
        tmp = ROOT / ".tmp-test-validation-digest"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-validation-digest", tmp, status="completed")
        try:
            store.create_run(run)
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            digest = service.get_run_status_digest(run.run_id)

            for key in [
                "schema_version",
                "run_id",
                "status",
                "selected_profile",
                "warning_codes",
                "failure_classification",
                "policy_verdict",
                "recommended_action",
                "log_refs",
            ]:
                self.assertIn(key, digest)
            self.assertEqual(digest["schema_version"], 1)
            self.assertEqual(digest["status"], "completed")
            self.assertNotIn("events", digest)
            self.assertTrue(digest["raw_events_omitted"])
        finally:
            remove_tree(tmp)

    def test_prose_only_completion_is_repair_needed_evidence_gap(self) -> None:
        tmp = ROOT / ".tmp-test-validation-evidence-gap"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-validation-evidence-gap", tmp, status="completed")
        run.last_agent_message = "Done. Everything is complete."
        try:
            store.create_run(run)
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            summary = service.get_run_summary(run.run_id)
            digest = service.get_run_status_digest(run.run_id)
            verdict = service.get_run_policy_verdict(run.run_id)
            warning_codes = {warning["code"] for warning in summary["warning_details"]}

            self.assertEqual(summary["evidence_status"], "repair_needed")
            self.assertLess(summary["evidence_score"], 100)
            self.assertIn("no_changed_files", warning_codes)
            self.assertIn("no_completed_tool_calls", warning_codes)
            self.assertIn("worker_claim_without_evidence", warning_codes)
            self.assertIn("worker_claim_without_evidence", summary["failure_classification"])
            self.assertEqual(digest["evidence_status"], "repair_needed")
            self.assertEqual(verdict["policy_verdict"], "needs_repair")
            self.assertEqual(verdict["repair_seed"]["title"], f"Repair {run.run_id}")
        finally:
            remove_tree(tmp)

    def test_missing_requested_check_uses_stable_evidence_gap_code(self) -> None:
        tmp = ROOT / ".tmp-test-validation-missing-check"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-validation-missing-check", tmp, status="completed")
        run.task = TaskInput(title="Task", objective="Do work", checks=["python3 -m pytest -q"])
        try:
            store.create_run(run)
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            summary = service.get_run_summary(run.run_id)
            warning_codes = {warning["code"] for warning in summary["warning_details"]}

            self.assertIn("missing_requested_check", warning_codes)
            self.assertNotIn("requested_check_missing", warning_codes)
            self.assertIn("missing_requested_check", summary["failure_classification"])
            self.assertEqual(summary["evidence"]["checks"][0]["status"], "missing")
        finally:
            remove_tree(tmp)

    def test_liveness_stop_safe_requires_quiet_past_threshold_without_process_or_permission(self) -> None:
        tmp = ROOT / ".tmp-test-validation-liveness"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-validation-liveness", tmp, status="running")
        try:
            store.create_run(run)
            old = datetime.now(UTC) - timedelta(seconds=10)
            event = {
                "event_id": "evt-old",
                "run_id": run.run_id,
                "timestamp": old.isoformat().replace("+00:00", "Z"),
                "kind": "agent_message_chunk",
                "speaker": "worker",
                "text": "old activity",
            }
            (store.run_dir(run.run_id) / "dialogue.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

            payload = analyze_run_liveness(
                store.root,
                run.run_id,
                inspect_process=False,
                thresholds=LivenessThresholds(
                    orbital_quiet_seconds=1,
                    model_active_seconds=1,
                    stop_safe_seconds=2,
                ),
            )

            self.assertEqual(payload["verdict"], "stop_safe")
            self.assertTrue(payload["recommendation"]["stop_allowed"])
            self.assertEqual(payload["signals"]["run_status"], "running")
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


if __name__ == "__main__":
    unittest.main()
