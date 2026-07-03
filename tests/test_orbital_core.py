from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from orbital_mcp.config import load_config
from orbital_mcp.dialogue import new_event  # noqa: E402
from orbital_mcp.errors import error_response  # noqa: E402
from orbital_mcp.events import POLICY_VIOLATION  # noqa: E402
from orbital_mcp.liveness import analyze_run_liveness  # noqa: E402
from orbital_mcp.models import (  # noqa: E402
    HarnessConfig,
    HarnessProfile,
    HarnessRunMetadata,
    PermissionOption,
    PermissionRequest,
    RunCounts,
    SessionMetadata,
    TaskInput,
    TaskRun,
    FinalReport,
    FileAttributionRecord,
    normalize_run_status,
)
from orbital_mcp.permissions import choose_option, normalize_permission  # noqa: E402
from orbital_mcp.policy import CommandPolicyConfig, evaluate_command_policy  # noqa: E402
from orbital_mcp.profiles import HarnessRegistry  # noqa: E402
from orbital_mcp.service import TaskRunService  # noqa: E402
from orbital_mcp.snapshots import compare_snapshots, snapshot_workdir  # noqa: E402
from orbital_mcp.store import RunStore  # noqa: E402
from orbital_mcp.task_prompt import render_startup_prompt  # noqa: E402


class OrbitalCoreTests(unittest.TestCase):
    def test_config_loads_classification_and_support_metadata(self) -> None:
        config = load_config(Path("/tmp/orbital-config-does-not-exist"))
        profile = next(item for item in config.profiles if item.id == "opencode_acp_local")

        self.assertIn("fast_smoke", profile.classification.task_tags)
        self.assertEqual(profile.classification.locality, "subscription")
        self.assertEqual(profile.support.tier, "experimental_acp")
        self.assertEqual(config.storage_root, ".orbital")

    def test_default_profiles_separate_claude_cli_from_api_backed_agent_acp(self) -> None:
        config = load_config(Path("/tmp/orbital-config-does-not-exist"))
        profile_ids = {item.id for item in config.profiles}

        self.assertNotIn("claude_code_acp_local", profile_ids)

        cli = next(item for item in config.profiles if item.id == "claude_code_cli_local")
        self.assertEqual(cli.adapter, "cli")
        self.assertEqual(cli.runtime_family, "claude_code")
        self.assertEqual(cli.command, ["claude"])
        self.assertEqual(cli.auth_mode, "local_subscription")
        self.assertEqual(cli.cost_posture, "subscription_preferred")
        self.assertEqual(cli.support.tier, "cli_fallback")

        acp = next(item for item in config.profiles if item.id == "claude_agent_acp_api")
        self.assertEqual(acp.adapter, "acp")
        self.assertEqual(acp.runtime_family, "claude_agent")
        self.assertEqual(acp.command, ["claude-agent-acp"])
        self.assertEqual(acp.auth_mode, "api_key")
        self.assertEqual(acp.cost_posture, "metered_api")
        self.assertFalse(acp.enabled)
        self.assertTrue(acp.metered_api)
        self.assertEqual(acp.support.tier, "profile_template")

    def test_claude_agent_acp_readiness_requires_explicit_setup(self) -> None:
        config = load_config(Path("/tmp/orbital-config-does-not-exist"))
        registry = HarnessRegistry(config)
        profile = next(item for item in config.profiles if item.id == "claude_agent_acp_api")

        with patch.dict("os.environ", {}, clear=True):
            readiness = registry.readiness(profile, ROOT)

        self.assertFalse(readiness.ready)
        self.assertIn("profile disabled", readiness.missing_prerequisites)
        self.assertIn("ANTHROPIC_API_KEY is not set", readiness.missing_prerequisites)

    def test_claude_agent_acp_is_never_recommended_without_explicit_opt_in(self) -> None:
        registry = HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist")))

        result = registry.recommend(
            task_tags=["implementation"],
            required_capabilities=["dialogue"],
            locality="metered_api",
            cost_preference="metered_api",
            include_not_ready=True,
        )

        claude_agent = next(item for item in result["recommendations"] if item["profile_id"] == "claude_agent_acp_api")
        self.assertFalse(claude_agent["eligible"])
        self.assertIn("profile disabled", claude_agent["caveats"])
        self.assertIn("metered API profile requires explicit opt-in", claude_agent["caveats"])

    def test_custom_config_parses_profile_metadata(self) -> None:
        tmp = ROOT / ".tmp-test-config"
        tmp.mkdir(exist_ok=True)
        try:
            (tmp / "orbital.config.json").write_text(
                json.dumps(
                    {
                        "profiles": [
                            {
                                "id": "fake",
                                "display_name": "Fake",
                                "adapter": "acp",
                                "runtime_family": "generic",
                                "command": [sys.executable],
                                "auth_mode": "local_subscription",
                                "cost_posture": "subscription_preferred",
                                "classification": {
                                    "task_tags": ["docs"],
                                    "strengths": ["documentation edits"],
                                    "locality": "subscription",
                                },
                                "support": {"tier": "known_good_acp", "notes": ["fixture covered"]},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(tmp)
        finally:
            (tmp / "orbital.config.json").unlink(missing_ok=True)
            tmp.rmdir()

        self.assertEqual(config.profiles[0].classification.task_tags, ["docs"])
        self.assertEqual(config.profiles[0].support.tier, "known_good_acp")

    def test_recommend_harness_profiles_is_deterministic_and_explicit_about_caveats(self) -> None:
        registry = HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist")))

        result = registry.recommend(
            task_tags=["fast_smoke"],
            required_capabilities=["dialogue", "permissions"],
            disallowed_support_tiers=["profile_template"],
            locality="subscription",
        )

        recommendations = result["recommendations"]
        self.assertEqual(recommendations, registry.recommend(
            task_tags=["fast_smoke"],
            required_capabilities=["dialogue", "permissions"],
            disallowed_support_tiers=["profile_template"],
            locality="subscription",
        )["recommendations"])
        self.assertEqual(recommendations[0]["profile_id"], "opencode_acp_local")
        self.assertIn("fast_smoke", recommendations[0]["matched_task_tags"])
        metered = next(item for item in recommendations if item["profile_id"] == "opencode_acp_glm52")
        self.assertFalse(metered["eligible"])
        self.assertIn("metered API profile requires explicit opt-in", metered["caveats"])

    def test_registry_treats_explicit_metered_profile_id_as_opt_in(self) -> None:
        config = load_config(Path("/tmp/orbital-config-does-not-exist"))
        registry = HarnessRegistry(config)

        profile, _ = registry.select(ROOT, profile_id="opencode_acp_glm52", task=TaskInput("t", "o"))
        self.assertEqual(profile.id, "opencode_acp_glm52")

    def test_stable_error_response_maps_permission_restart_error(self) -> None:
        payload = error_response(ValueError("permission_not_resolvable_after_restart"))

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "permission_not_resolvable_after_restart")
        self.assertFalse(payload["error"]["retryable"])
        self.assertIn("Start a new run", payload["error"]["user_action"])

    def test_run_status_normalizer_maps_legacy_and_unknown_values(self) -> None:
        self.assertEqual(normalize_run_status("starting"), "launching")
        self.assertEqual(normalize_run_status("passed"), "completed")
        self.assertEqual(normalize_run_status("stopped"), "cancelled")
        self.assertEqual(normalize_run_status("nonsense"), "unknown")

    def test_store_recovers_non_terminal_runs_and_skips_malformed_jsonl(self) -> None:
        tmp = ROOT / ".tmp-test-store"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-test", tmp)
        try:
            store.create_run(run)
            (store.run_dir(run.run_id) / "dialogue.jsonl").write_text(
                '{"event_id":"evt-1","kind":"tool_call_started"}\n{bad json\n',
                encoding="utf-8",
            )

            recovered = store.recover_interrupted_runs()
            events = store.read_dialogue(run.run_id)["events"]

            self.assertEqual(recovered[0]["status"], "interrupted")
            self.assertEqual([event["kind"] for event in events], ["tool_call_started", "storage_recovery"])
            self.assertEqual(store.load_run(run.run_id)["status"], "interrupted")
        finally:
            _remove_tree(tmp)

    def test_store_rejects_path_traversal_ids(self) -> None:
        store = RunStore(ROOT / ".tmp-test-traversal" / ".orbital")
        try:
            with self.assertRaisesRegex(ValueError, "invalid run_id"):
                store.run_dir("../outside")
            with self.assertRaisesRegex(ValueError, "invalid session_id"):
                store.session_dir("../outside")
        finally:
            _remove_tree(ROOT / ".tmp-test-traversal")

    def test_bounded_log_tail_and_storage_diagnostics(self) -> None:
        tmp = ROOT / ".tmp-test-diagnostics"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-diagnostics", tmp)
        try:
            store.create_run(run)
            store.append_stderr(run.run_id, "alpha")
            store.append_stderr(run.run_id, "beta")
            (store.run_dir(run.run_id) / "dialogue.jsonl").write_text(
                '{"event_id":"evt-1","kind":"tool_call_started"}\n{bad json\n',
                encoding="utf-8",
            )
            (store.run_dir(run.run_id) / "run.json.tmp").write_text("{partial", encoding="utf-8")

            tail = store.read_log_tail(run.run_id, "stderr.log", max_bytes=6)
            diagnostics = store.storage_diagnostics(run.run_id)

            self.assertEqual(tail["text"], "\nbeta\n")
            self.assertTrue(tail["truncated"])
            codes = [issue["code"] for issue in diagnostics["issues"]]
            self.assertIn("malformed_jsonl", codes)
            self.assertIn("partial_write_tmp", codes)
        finally:
            _remove_tree(tmp)

    def test_snapshot_attribution_classifies_created_modified_and_deleted_files(self) -> None:
        tmp = ROOT / ".tmp-test-attribution"
        try:
            tmp.mkdir(exist_ok=True)
            (tmp / "modified.txt").write_text("before", encoding="utf-8")
            (tmp / "deleted.txt").write_text("before", encoding="utf-8")
            start = snapshot_workdir(tmp)

            (tmp / "modified.txt").write_text("after", encoding="utf-8")
            (tmp / "deleted.txt").unlink()
            (tmp / "created.txt").write_text("new", encoding="utf-8")
            result = compare_snapshots(start, snapshot_workdir(tmp))

            records = {item.path: item for item in result.files}
            self.assertEqual(records["created.txt"].change_type, "created")
            self.assertEqual(records["created.txt"].confidence, "high")
            self.assertEqual(records["modified.txt"].change_type, "modified")
            self.assertEqual(records["modified.txt"].confidence, "high")
            self.assertEqual(records["deleted.txt"].change_type, "deleted")
            self.assertEqual(records["deleted.txt"].confidence, "high")
        finally:
            _remove_tree(tmp)

    def test_run_summary_includes_file_attribution_records(self) -> None:
        tmp = ROOT / ".tmp-test-run-attribution"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-attribution", tmp, status="completed")
        try:
            tmp.mkdir(exist_ok=True)
            run.changed_files = ["created.txt"]
            run.changed_since_run_start = ["created.txt"]
            run.file_attribution = [
                FileAttributionRecord(
                    path="created.txt",
                    change_type="created",
                    attribution="changed_during_run",
                    confidence="high",
                )
            ]
            store.create_run(run)
            store.save_final_report(
                FinalReport(
                    schema_version=1,
                    run_id=run.run_id,
                    status="completed",
                    changed_files=run.changed_files,
                    pre_existing_changed_files=[],
                    changed_since_run_start=run.changed_since_run_start,
                    file_attribution=run.file_attribution,
                    final_response=None,
                    last_error=None,
                    harness=run.harness,
                )
            )
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            summary = service.get_run_summary(run.run_id)

            self.assertEqual(summary["file_attribution"][0]["path"], "created.txt")
            self.assertEqual(summary["file_attribution"][0]["confidence"], "high")
        finally:
            _remove_tree(tmp)

    def test_delegation_report_aggregates_file_attribution_confidence(self) -> None:
        tmp = ROOT / ".tmp-test-report-attribution"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-report-attribution", tmp, status="completed")
        try:
            tmp.mkdir(exist_ok=True)
            run.changed_files = ["created.txt"]
            run.changed_since_run_start = ["created.txt"]
            run.file_attribution = [
                FileAttributionRecord(
                    path="created.txt",
                    change_type="created",
                    attribution="changed_during_run",
                    confidence="high",
                )
            ]
            store.create_run(run)
            store.save_final_report(
                FinalReport(
                    schema_version=1,
                    run_id=run.run_id,
                    status="completed",
                    changed_files=run.changed_files,
                    pre_existing_changed_files=[],
                    changed_since_run_start=run.changed_since_run_start,
                    file_attribution=run.file_attribution,
                    final_response=None,
                    last_error=None,
                    harness=run.harness,
                )
            )
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            report = service.get_delegation_report(run_ids=[run.run_id])

            self.assertEqual(report["attribution"]["confidence_counts"]["high"], 1)
            self.assertEqual(report["attribution"]["file_records"][0]["path"], "created.txt")
        finally:
            _remove_tree(tmp)

    def test_pending_permission_after_restart_is_visible_but_not_resolvable(self) -> None:
        tmp = ROOT / ".tmp-test-permission"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-permission", tmp)
        try:
            store.create_run(run)
            store.append_permission(
                PermissionRequest(
                    permission_id="perm-task-run-permission-77",
                    run_id=run.run_id,
                    adapter_request_id="77",
                    summary="Edit file",
                )
            )
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            summary = service.get_run_summary(run.run_id)
            self.assertEqual(summary["pending_permission_requests"][0]["permission_id"], "perm-task-run-permission-77")
            with self.assertRaisesRegex(ValueError, "permission_not_resolvable_after_restart"):
                _run_async(service.resolve_permission(run.run_id, "perm-task-run-permission-77", "approve"))
        finally:
            _remove_tree(tmp)

    def test_permission_option_selection_prefers_explicit_ids_and_rejects_ambiguity(self) -> None:
        request = PermissionRequest(
            permission_id="perm-1",
            run_id="task-run-perm",
            adapter_request_id="1",
            options=[
                PermissionOption(option_id="allow-read", label="Allow read", kind="allow"),
                PermissionOption(option_id="allow-write", label="Allow write", kind="allow"),
                PermissionOption(option_id="deny", label="Deny", kind="deny"),
            ],
        )

        self.assertEqual(choose_option(request, "approve", explicit_option_id="allow-write"), "allow-write")
        with self.assertRaisesRegex(ValueError, "ambiguous approve options"):
            choose_option(request, "approve")

    def test_permission_normalization_extracts_paths_and_raw_reference(self) -> None:
        request = normalize_permission(
            "task-run-normalize",
            "42",
            {
                "params": {
                    "summary": "Edit files",
                    "risk": "write",
                    "paths": ["docs/TODO.md"],
                    "toolCall": {
                        "locations": [{"path": "src/orbital_mcp/server.py"}],
                        "rawInput": {"cwd": str(ROOT), "changes": {"pyproject.toml": "..."}},
                    },
                    "options": [{"id": "yes", "label": "Yes", "kind": "allow"}],
                }
            },
        )

        self.assertEqual(request.permission_id, "perm-task-run-normalize-42")
        self.assertEqual(request.risk, "write")
        self.assertEqual(request.options[0].option_id, "yes")
        self.assertEqual(
            request.paths,
            sorted(["docs/TODO.md", "src/orbital_mcp/server.py", str(ROOT), "pyproject.toml"]),
        )

    def test_startup_prompt_does_not_include_primary_only_guidance(self) -> None:
        prompt = render_startup_prompt(
            TaskInput(
                title="Implement feature",
                objective="Change the implementation.",
                allowed_paths=["src/orbital_mcp"],
                checks=["python3 -m unittest"],
            ),
            ROOT,
        )

        self.assertIn("Objective: Change the implementation.", prompt)
        self.assertIn("Allowed paths:\n- src/orbital_mcp", prompt)
        self.assertNotIn("profile-selection", prompt.lower())
        self.assertNotIn("scoring rubric", prompt.lower())
        self.assertNotIn("handoff report", prompt.lower())

    def test_command_policy_is_reviewable_by_default_and_blockable_by_config(self) -> None:
        review = evaluate_command_policy("python3 -m pip install pytest")
        blocked = evaluate_command_policy(
            "curl https://example.test",
            CommandPolicyConfig(network="block"),
        )
        allowed = evaluate_command_policy(
            "npm install",
            CommandPolicyConfig(package_manager="allow"),
        )

        self.assertIsNotNone(review)
        self.assertEqual(review.category, "package_manager")
        self.assertEqual(review.enforcement, "requires_primary_review")
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked.enforcement, "block")
        self.assertIsNone(allowed)

    def test_policy_violation_requires_primary_review_not_automatic_reject(self) -> None:
        tmp = ROOT / ".tmp-test-policy"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-policy", tmp, status="completed")
        try:
            store.create_run(run)
            store.append_dialogue(
                new_event(
                    run.run_id,
                    POLICY_VIOLATION,
                    "server",
                    "package manager command requires primary review: python3 -m pip install pytest",
                )
            )
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            verdict = service.get_run_policy_verdict(run.run_id)
            self.assertEqual(verdict["policy_verdict"], "requires_primary_review")
            self.assertEqual(verdict["recommended_action"], "review_policy_risk_and_decide")
            self.assertIn("policy_violation", verdict["reason_codes"])
        finally:
            _remove_tree(tmp)

    def test_legacy_run_statuses_normalize_on_primary_safe_outputs(self) -> None:
        tmp = ROOT / ".tmp-test-status"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-legacy-status", tmp, status="passed")
        try:
            store.create_run(run)
            service = TaskRunService(HarnessRegistry(load_config(Path("/tmp/orbital-config-does-not-exist"))), store)

            summary = service.get_run_summary(run.run_id)
            digest = service.get_run_status_digest(run.run_id)
            liveness = analyze_run_liveness(store.root, run.run_id, inspect_process=False)

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(digest["status"], "completed")
            self.assertEqual(liveness["signals"]["run_status"], "completed")
            self.assertEqual(liveness["verdict"], "terminal")
        finally:
            _remove_tree(tmp)

    def test_liveness_uses_orbital_signal_names(self) -> None:
        tmp = ROOT / ".tmp-test-liveness"
        store = RunStore(tmp / ".orbital")
        run = _run("task-run-liveness", tmp)
        try:
            store.create_run(run)
            store.append_dialogue(new_event(run.run_id, "tool_call_started", "worker", "editing [in_progress]"))

            payload = analyze_run_liveness(store.root, run.run_id, inspect_process=False)
            self.assertEqual(payload["verdict"], "active_orbital")
            self.assertIn("orbital", payload["signals"])
            self.assertNotIn("prole", payload["signals"])
            self.assertIn("orbital_quiet_seconds", payload["thresholds"])
        finally:
            _remove_tree(tmp)

    def test_fake_acp_run_captures_tools_checks_usage_model_and_stderr(self) -> None:
        tmp = ROOT / ".tmp-test-fake-acp-run"
        try:
            tmp.mkdir(exist_ok=True)
            service = _fake_acp_service(tmp)

            summary = _run_async(
                service.run_task_and_wait(
                    tmp,
                    TaskInput(
                        title="Fake ACP",
                        objective="Implement fake task. RUN_CHECK USAGE",
                        allowed_paths=["fake_output.txt"],
                        checks=["python3 -m pytest -q"],
                    ),
                    profile_id="fake_acp",
                    timeout_seconds=5,
                )
            )

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["evidence"]["checks"][0]["status"], "passed")
            self.assertGreaterEqual(summary["evidence"]["tool_calls"]["completed"], 2)
            self.assertEqual(summary["tokens"]["total"], 135)
            self.assertIn("fake-acp-model", summary["model"]["models"])
            self.assertEqual(summary["file_attribution"][0]["path"], "fake_output.txt")
            stderr_tail = service.get_run_log_tail(summary["run_id"], "stderr.log", max_bytes=4096)
            self.assertIn("AuthRequired", stderr_tail["text"])
            dialogue = service.get_dialogue(summary["run_id"], include_raw=False, include_agent_chunks=False)
            self.assertFalse(any(event.get("kind") == "agent_message_chunk" for event in dialogue["events"]))
            self.assertTrue(all("raw" not in event for event in dialogue["events"]))
        finally:
            _remove_tree(tmp)

    def test_fake_acp_permission_round_trip_completes_after_approval(self) -> None:
        tmp = ROOT / ".tmp-test-fake-acp-permission"
        try:
            tmp.mkdir(exist_ok=True)
            service = _fake_acp_service(tmp)

            resolution, summary = _run_async(_fake_permission_flow(service, tmp))

            self.assertEqual(resolution["permission"]["resolved_option_id"], "allow")
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["permission_counts"]["permission_count"], 1)
            self.assertEqual(summary["permission_counts"]["approved_permission_count"], 1)
        finally:
            _remove_tree(tmp)

    def test_fake_acp_malformed_stdout_is_captured_as_agent_text(self) -> None:
        tmp = ROOT / ".tmp-test-fake-acp-malformed"
        try:
            tmp.mkdir(exist_ok=True)
            service = _fake_acp_service(tmp)

            summary = _run_async(
                service.run_task_and_wait(
                    tmp,
                    TaskInput(
                        title="Malformed",
                        objective="Implement fake task. MALFORMED_STDOUT",
                        allowed_paths=["fake_output.txt"],
                    ),
                    profile_id="fake_acp",
                    timeout_seconds=5,
                )
            )
            dialogue = service.get_dialogue(summary["run_id"], include_agent_chunks=True)

            self.assertEqual(summary["status"], "completed")
            self.assertTrue(any(event.get("text") == "not-json-from-fake-harness" for event in dialogue["events"]))
        finally:
            _remove_tree(tmp)

    def test_delegation_session_workflow_creates_repair_and_finish_report(self) -> None:
        tmp = ROOT / ".tmp-test-session-workflow"
        try:
            tmp.mkdir(exist_ok=True)
            service = _fake_acp_service(tmp)

            result = _run_async(_delegation_repair_flow(service, tmp))

            repair_ticket = result["repair_session"]["session"]["tickets"][1]
            reviewed_attempt = result["reviewed_session"]["session"]["attempts"][0]
            finish_session = result["finished"]["session"]
            report = result["finished"]["report"]

            self.assertEqual(result["next_action"]["recommended_action"]["action"], "create_repair_ticket_from_run")
            self.assertTrue(repair_ticket["ticket_id"].startswith("task-1-repair-"))
            self.assertEqual(reviewed_attempt["decision"], "needs_repair")
            self.assertEqual(finish_session["status"], "finished")
            self.assertEqual(finish_session["final_status"], "success")
            self.assertEqual(report["workflow"]["known"], True)
            self.assertEqual(report["workflow"]["unsatisfied_requirement_ids"], [])
            self.assertEqual(report["workflow"]["pending_attempt_run_ids"], [])
        finally:
            _remove_tree(tmp)

    def test_delegation_session_warns_for_missing_review_evidence_and_blocks_success_finish(self) -> None:
        tmp = ROOT / ".tmp-test-session-warnings"
        try:
            tmp.mkdir(exist_ok=True)
            service = _fake_acp_service(tmp)

            result = _run_async(_delegation_warning_flow(service, tmp))
            warning_codes = [item["code"] for item in result["reviewed"]["session"]["session_warnings"]]

            self.assertIn("accepted_missing_review_evidence", warning_codes)
            self.assertIn("cannot finish success with unsatisfied requirements", result["finish_error"])
        finally:
            _remove_tree(tmp)


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


def _fake_acp_service(tmp: Path) -> TaskRunService:
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
    config = HarnessConfig(default_profile="fake_acp", storage_root=".orbital", profiles=[profile])
    return TaskRunService(HarnessRegistry(config), RunStore(tmp / ".orbital"))


async def _wait_for_permission(service: TaskRunService, run_id: str) -> str:
    import asyncio

    for _ in range(80):
        summary = service.get_run_summary(run_id)
        pending = summary.get("pending_permission_requests") or []
        if pending:
            return pending[0]["permission_id"]
        await asyncio.sleep(0.05)
    raise AssertionError("permission request did not arrive")


async def _fake_permission_flow(service: TaskRunService, tmp: Path) -> tuple[dict, dict]:
    response = await service.start_task_run(
        tmp,
        TaskInput(
            title="Permission",
            objective="Implement fake task with permission.",
            allowed_paths=["fake_output.txt"],
        ),
        profile_id="fake_acp",
    )
    run_id = response["run_id"]
    permission_id = await _wait_for_permission(service, run_id)
    resolution = await service.resolve_permission(run_id, permission_id, "approve")
    summary = await _wait_for_terminal_summary(service, run_id)
    return resolution, summary


async def _delegation_repair_flow(service: TaskRunService, tmp: Path) -> dict:
    session_payload = service.start_delegation_session(
        tmp,
        "Repair workflow",
        preferred_profile_id="fake_acp",
        primary_harness="unit-test",
    )
    session_id = session_payload["session"]["session_id"]
    service.create_requirement(session_id, "REQ-1", "Fake file exists", "fake_output.txt is created")
    service.create_delegation_ticket(
        session_id,
        "task-1",
        "No-op first attempt",
        "NOOP_PASS",
        requirement_ids=["REQ-1"],
        allowed_paths=["fake_output.txt"],
    )
    run_payload = await service.start_ticket_run(session_id, "task-1")
    run_id = run_payload["run_id"]
    await _wait_for_terminal_summary(service, run_id)
    next_action = service.get_next_recommended_action(session_id)
    repair_session = service.create_repair_ticket_from_run(session_id, "task-1", run_id)
    reviewed_session = service.record_attempt_review(
        session_id,
        "task-1",
        run_id,
        "needs_repair",
        "No changes were made.",
        inspected_files=["fake_output.txt"],
        verification_commands=["python3 -m pytest -q"],
    )
    service.update_requirement_status(session_id, "REQ-1", "satisfied", evidence=["repair ticket created"])
    finished = service.finish_delegation_session(
        session_id,
        "success",
        final_summary="Primary accepted after creating repair path.",
        final_verification="Primary inspected session state.",
    )
    return {
        "next_action": next_action,
        "repair_session": repair_session,
        "reviewed_session": reviewed_session,
        "finished": finished,
    }


async def _delegation_warning_flow(service: TaskRunService, tmp: Path) -> dict:
    session_payload = service.start_delegation_session(tmp, "Warning workflow", preferred_profile_id="fake_acp")
    session_id = session_payload["session"]["session_id"]
    service.create_requirement(session_id, "REQ-1", "Fake file exists", "fake_output.txt is created")
    service.create_delegation_ticket(
        session_id,
        "task-1",
        "Implement fake file",
        "Implement fake task.",
        requirement_ids=["REQ-1"],
        allowed_paths=["fake_output.txt"],
    )
    run_payload = await service.start_ticket_run(session_id, "task-1")
    run_id = run_payload["run_id"]
    await _wait_for_terminal_summary(service, run_id)
    reviewed = service.record_attempt_review(
        session_id,
        "task-1",
        run_id,
        "accepted",
        "Accepted without complete evidence for warning coverage.",
    )
    try:
        service.finish_delegation_session(session_id, "success")
    except ValueError as exc:
        finish_error = str(exc)
    else:
        finish_error = ""
    return {"reviewed": reviewed, "finish_error": finish_error}


async def _wait_for_terminal_summary(service: TaskRunService, run_id: str) -> dict:
    import asyncio

    for _ in range(100):
        summary = service.get_run_summary(run_id)
        if summary["status"] in {"completed", "failed", "blocked", "cancelled", "interrupted", "unknown"}:
            return summary
        await asyncio.sleep(0.05)
    raise AssertionError("run did not reach terminal status")


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        else:
            child.rmdir()
    path.rmdir()


if __name__ == "__main__":
    unittest.main()
