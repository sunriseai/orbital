from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from typing import Any

from orbital_test_helpers import (
    ROOT,
    fake_acp_service,
    remove_tree,
    run_async,
    task,
    wait_for_permission,
    wait_for_terminal_summary,
)

from orbital_mcp.acp_conformance import (  # noqa: E402
    AcpConformanceExpectation,
    evaluate_acp_conformance,
    evaluate_acp_conformance_fixture,
    load_acp_conformance_fixture,
)
from orbital_mcp.config import load_config  # noqa: E402


FIXTURE_DIR = ROOT / "tests" / "fixtures" / "acp_conformance"
REAL_PROFILE_FIXTURES = [
    path.name
    for path in sorted(FIXTURE_DIR.glob("*.json"))
    if not path.name.startswith("fake_")
]

FEATURE_STATE_KEYS = {
    "initialize",
    "session_creation",
    "prompt_submission",
    "dialogue",
    "tools",
    "permissions",
    "permission_resolution",
    "stop_cancel",
    "stderr",
    "model_metadata",
    "adapter_usage_payload",
    "canonical_local_log_telemetry",
    "malformed_payload_handling",
    "terminal_result_shape",
}


class AcpAdapterConformanceFixtureTests(unittest.TestCase):
    def test_fixture_loader_rejects_incomplete_fixture(self) -> None:
        tmp = ROOT / ".tmp-test-acp-bad-fixture.json"
        try:
            tmp.write_text(json.dumps({"fixture_id": "bad"}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing required fields"):
                load_acp_conformance_fixture(tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def test_fixture_replay_covers_fake_and_real_runtime_profiles(self) -> None:
        expected_capabilities = {
            "fake_acp_core": {
                "dialogue": True,
                "tools": True,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": True,
                "model_metadata": True,
            },
            "fake_acp_permission_round_trip": {
                "dialogue": True,
                "tools": False,
                "permissions": True,
                "permission_round_trip": True,
                "adapter_usage_payload": False,
                "model_metadata": False,
            },
            "fake_acp_malformed_unknown": {
                "dialogue": False,
                "tools": False,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": False,
                "model_metadata": False,
                "unknown_payloads": True,
                "malformed_payloads": True,
            },
            "fake_acp_partial_result": {
                "dialogue": False,
                "tools": False,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": False,
                "model_metadata": False,
                "terminal_result": False,
            },
            "fake_acp_stderr_failure": {
                "dialogue": False,
                "tools": False,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": False,
                "model_metadata": False,
                "stderr": True,
                "terminal_result": True,
            },
            "fake_acp_stop_cancel": {
                "dialogue": False,
                "tools": False,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": False,
                "model_metadata": False,
                "stop_or_cancel": True,
                "terminal_result": True,
            },
            "codex_legacy_smoke": {
                "dialogue": True,
                "tools": True,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": True,
                "model_metadata": False,
            },
            "codex_official_permission_gap": {
                "dialogue": True,
                "tools": True,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": True,
                "model_metadata": True,
            },
            "codex_official_malformed_unknown": {
                "dialogue": False,
                "tools": False,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": True,
                "model_metadata": True,
                "unknown_payloads": True,
                "malformed_payloads": True,
            },
            "codex_official_stderr_guardian_failure": {
                "dialogue": False,
                "tools": True,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": True,
                "model_metadata": True,
                "stderr": True,
                "terminal_result": True,
            },
            "codex_official_stop_cancel": {
                "dialogue": False,
                "tools": False,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": False,
                "model_metadata": False,
                "stop_or_cancel": True,
                "terminal_result": True,
            },
            "opencode_smoke": {
                "dialogue": True,
                "tools": True,
                "permissions": False,
                "permission_round_trip": False,
                "multi_permission_round_trip": False,
                "adapter_usage_payload": True,
                "model_metadata": False,
            },
            "opencode_ask_permission_round_trip": {
                "dialogue": True,
                "tools": True,
                "permissions": True,
                "permission_round_trip": True,
                "multi_permission_round_trip": True,
                "adapter_usage_payload": True,
                "model_metadata": False,
            },
            "opencode_partial_result": {
                "dialogue": False,
                "tools": False,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": False,
                "model_metadata": False,
                "terminal_result": False,
            },
            "opencode_permission_ambiguous_options": {
                "dialogue": False,
                "tools": True,
                "permissions": True,
                "permission_round_trip": False,
                "multi_permission_round_trip": False,
                "adapter_usage_payload": True,
                "model_metadata": False,
            },
            "opencode_permission_denied": {
                "dialogue": True,
                "tools": True,
                "permissions": True,
                "permission_round_trip": True,
                "multi_permission_round_trip": False,
                "adapter_usage_payload": True,
                "model_metadata": False,
                "jsonrpc_errors": False,
            },
            "opencode_permission_mixed_allow_deny": {
                "dialogue": True,
                "tools": True,
                "permissions": True,
                "permission_round_trip": True,
                "multi_permission_round_trip": True,
                "adapter_usage_payload": True,
                "model_metadata": False,
            },
            "opencode_permission_jsonrpc_error": {
                "dialogue": False,
                "tools": True,
                "permissions": True,
                "permission_round_trip": False,
                "multi_permission_round_trip": False,
                "adapter_usage_payload": True,
                "model_metadata": False,
                "jsonrpc_errors": True,
            },
            "opencode_permission_missing_option_ids": {
                "dialogue": False,
                "tools": True,
                "permissions": True,
                "permission_round_trip": False,
                "multi_permission_round_trip": False,
                "adapter_usage_payload": True,
                "model_metadata": False,
                "jsonrpc_errors": False,
            },
            "opencode_stderr_failure": {
                "dialogue": False,
                "tools": False,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": False,
                "model_metadata": False,
                "stderr": True,
                "terminal_result": True,
            },
            "opencode_stop_cancel": {
                "dialogue": False,
                "tools": False,
                "permissions": False,
                "permission_round_trip": False,
                "adapter_usage_payload": False,
                "model_metadata": False,
                "stop_or_cancel": True,
                "terminal_result": True,
            },
        }

        for path in sorted(FIXTURE_DIR.glob("*.json")):
            with self.subTest(fixture=path.name):
                report = evaluate_acp_conformance_fixture(path)
                self.assertTrue(report["ok"], report)
                expected = expected_capabilities[report["fixture_id"]]
                for capability, value in expected.items():
                    self.assertEqual(report["capabilities"][capability], value, report)
                self.assertEqual(set(report["feature_states"]), FEATURE_STATE_KEYS)
                self.assertTrue(
                    set(report["feature_states"].values()) <= {"observed", "missing", "not_applicable", "capability_gap"}
                )

    def test_real_profiles_remain_experimental_until_fixture_promotion_gate_changes(self) -> None:
        profiles = {profile.id: profile for profile in load_config(ROOT).profiles}
        fixture_profiles = {
            evaluate_acp_conformance_fixture(FIXTURE_DIR / fixture)["profile_id"]
            for fixture in REAL_PROFILE_FIXTURES
        }

        self.assertEqual(
            fixture_profiles,
            {"codex_acp_local", "codex_acp_official", "opencode_acp_local", "opencode_acp_local_ask"},
        )
        for profile_id in fixture_profiles:
            self.assertEqual(profiles[profile_id].support.tier, "experimental_acp")

        known_good_real_profiles = [
            profile.id
            for profile in profiles.values()
            if profile.support.tier == "known_good_acp" and profile.id in fixture_profiles
        ]
        self.assertEqual(known_good_real_profiles, [])

    def test_opencode_ask_permission_fixture_proves_multi_request_round_trip(self) -> None:
        report = evaluate_acp_conformance_fixture(FIXTURE_DIR / "opencode_ask_permission_round_trip.json")

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["profile_id"], "opencode_acp_local_ask")
        self.assertEqual(report["observed"]["permission_request_count"], 2)
        self.assertEqual(report["observed"]["permission_resolution_count"], 2)
        self.assertEqual(report["observed"]["permission_option_ids"], ["once"])
        self.assertTrue(report["capabilities"]["multi_permission_round_trip"])

    def test_opencode_permission_denial_fixture_preserves_reject_context(self) -> None:
        report = evaluate_acp_conformance_fixture(FIXTURE_DIR / "opencode_permission_denied.json")

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["profile_id"], "opencode_acp_local_ask")
        self.assertEqual(report["observed"]["permission_request_count"], 1)
        self.assertEqual(report["observed"]["permission_resolution_count"], 1)
        self.assertEqual(report["observed"]["permission_request_option_ids"], ["once", "always", "reject"])
        self.assertEqual(report["observed"]["permission_option_ids"], ["reject"])
        self.assertTrue(report["capabilities"]["permission_round_trip"])

    def test_opencode_missing_option_ids_fixture_reports_gap(self) -> None:
        report = evaluate_acp_conformance_fixture(FIXTURE_DIR / "opencode_permission_missing_option_ids.json")

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["observed"]["permission_request_count"], 1)
        self.assertEqual(report["observed"]["permission_request_missing_option_id_count"], 2)
        self.assertEqual(report["observed"]["permission_request_option_ids"], [])
        self.assertFalse(report["capabilities"]["permission_round_trip"])

    def test_opencode_permission_jsonrpc_error_fixture_reports_protocol_error(self) -> None:
        report = evaluate_acp_conformance_fixture(FIXTURE_DIR / "opencode_permission_jsonrpc_error.json")

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["observed"]["permission_request_count"], 1)
        self.assertEqual(report["observed"]["permission_resolution_count"], 0)
        self.assertEqual(report["observed"]["jsonrpc_error_count"], 1)
        self.assertIn("jsonrpc_error", report["observed"]["normalized_features"])
        self.assertTrue(report["capabilities"]["jsonrpc_errors"])

    def test_feature_state_matrix_classifies_observed_missing_not_applicable_and_gaps(self) -> None:
        report = evaluate_acp_conformance_fixture(FIXTURE_DIR / "opencode_permission_ambiguous_options.json")

        self.assertTrue(report["ok"], report)
        self.assertEqual(report["feature_states"]["initialize"], "observed")
        self.assertEqual(report["feature_states"]["permissions"], "observed")
        self.assertEqual(report["feature_states"]["permission_resolution"], "capability_gap")
        self.assertEqual(report["feature_states"]["canonical_local_log_telemetry"], "not_applicable")
        self.assertEqual(report["feature_states"]["stderr"], "missing")
        self.assertEqual(
            report["raw_refs"]["capability_gaps"],
            [{"feature": "permission_resolution", "ref": "feature_states.permission_resolution"}],
        )

    def test_raw_refs_preserve_unknown_malformed_and_stderr_locations(self) -> None:
        codex_report = evaluate_acp_conformance_fixture(FIXTURE_DIR / "codex_official_malformed_unknown.json")
        stderr_report = evaluate_acp_conformance_fixture(FIXTURE_DIR / "codex_official_stderr_guardian_failure.json")

        self.assertTrue(codex_report["ok"], codex_report)
        self.assertEqual(codex_report["feature_states"]["malformed_payload_handling"], "observed")
        self.assertEqual([item["line"] for item in codex_report["raw_refs"]["malformed_payloads"]], [5])
        self.assertEqual(
            {(item.get("method"), item.get("session_update")) for item in codex_report["raw_refs"]["unknown_payloads"]},
            {("codex/guardian", None), ("session/update", "guardian_status_update")},
        )
        self.assertEqual(codex_report["feature_states"]["permissions"], "capability_gap")
        self.assertTrue(codex_report["raw_refs"]["capability_gaps"])

        self.assertTrue(stderr_report["ok"], stderr_report)
        self.assertEqual(stderr_report["feature_states"]["stderr"], "observed")
        self.assertEqual(stderr_report["raw_refs"]["stderr"], [{"line": 8, "direction": "!", "kind": "stderr"}])

    def test_new_opencode_and_codex_fixture_families_are_covered(self) -> None:
        required = {
            "opencode_permission_ambiguous_options",
            "opencode_permission_mixed_allow_deny",
            "opencode_stop_cancel",
            "opencode_stderr_failure",
            "opencode_partial_result",
            "codex_official_malformed_unknown",
            "codex_official_stop_cancel",
            "codex_official_stderr_guardian_failure",
        }
        observed = {
            evaluate_acp_conformance_fixture(path)["fixture_id"]
            for path in sorted(FIXTURE_DIR.glob("*.json"))
        }

        self.assertTrue(required <= observed)

        mixed = evaluate_acp_conformance_fixture(FIXTURE_DIR / "opencode_permission_mixed_allow_deny.json")
        self.assertEqual(mixed["observed"]["permission_option_ids"], ["once", "reject"])
        self.assertTrue(mixed["capabilities"]["multi_permission_round_trip"])
        self.assertEqual(mixed["feature_states"]["permission_resolution"], "observed")

        partial = evaluate_acp_conformance_fixture(FIXTURE_DIR / "opencode_partial_result.json")
        self.assertEqual(partial["feature_states"]["terminal_result_shape"], "capability_gap")

    def test_conformance_report_lists_missing_expected_features(self) -> None:
        transcript = '> {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'

        report = evaluate_acp_conformance(
            transcript,
            AcpConformanceExpectation(
                client_methods=["initialize", "session/new"],
                server_methods=["session/update"],
                session_updates=["agent_message_chunk"],
                normalized_features=["dialogue"],
                require_usage_payload=True,
            ),
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["missing"]["client_methods"], ["session/new"])
        self.assertEqual(report["missing"]["server_methods"], ["session/update"])
        self.assertEqual(report["missing"]["session_updates"], ["agent_message_chunk"])
        self.assertEqual(report["missing"]["normalized_features"], ["dialogue"])
        self.assertEqual(report["missing"]["usage_payload"], ["usage_payload"])

    def test_fake_acp_fixture_covers_core_protocol_and_primary_safe_filtering(self) -> None:
        tmp = ROOT / ".tmp-test-acp-conformance-core"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            summary = run_async(
                service.run_task_and_wait(
                    tmp,
                    task(
                        "Implement fake task. RUN_CHECK USAGE",
                        allowed_paths=["fake_output.txt"],
                        checks=["python3 -m pytest -q"],
                    ),
                    profile_id="fake_acp",
                    timeout_seconds=30,
                )
            )
            run_id = summary["run_id"]

            transcript = service.get_run_log_tail(run_id, "transcript.log", max_bytes=50_000)["text"]
            conformance = evaluate_acp_conformance(
                transcript,
                AcpConformanceExpectation(
                    client_methods=["initialize", "session/new", "session/prompt"],
                    server_methods=["session/update"],
                    session_updates=["agent_message_chunk", "tool_call", "tool_call_update"],
                    result_statuses=["passed"],
                    require_usage_payload=True,
                    require_model_metadata=True,
                ),
            )
            protocol = _protocol_messages(transcript)
            sent_methods = [item["message"].get("method") for item in protocol if item["direction"] == ">"]
            received_methods = [item["message"].get("method") for item in protocol if item["direction"] == "<"]
            received_updates = [
                item["message"].get("params", {}).get("update", {}).get("sessionUpdate")
                for item in protocol
                if item["direction"] == "<"
            ]

            self.assertEqual(summary["status"], "completed")
            self.assertTrue(conformance["ok"], conformance)
            self.assertIn("fake-acp-model", conformance["observed"]["models"])
            self.assertEqual(conformance["observed"]["usage_payload_count"], 1)
            self.assertIn("# launch_env auth_mode=local_subscription", transcript)
            self.assertIn("initialize", sent_methods)
            self.assertIn("session/new", sent_methods)
            self.assertIn("session/prompt", sent_methods)
            self.assertIn("session/update", received_methods)
            self.assertIn("agent_message_chunk", received_updates)
            self.assertIn("tool_call", received_updates)
            self.assertIn("tool_call_update", received_updates)
            self.assertTrue(any(item["message"].get("result", {}).get("status") == "passed" for item in protocol))
            self.assertEqual(summary["evidence"]["checks"][0]["status"], "passed")
            self.assertGreaterEqual(summary["evidence"]["tool_calls"]["completed"], 2)
            self.assertFalse(summary["tokens"]["known"])
            self.assertEqual(summary["token_sources"]["adapter_payloads"]["total"], 135)
            self.assertFalse(summary["token_sources"]["external_agent_logs"]["known"])
            self.assertIn("fake-acp-model", summary["model"]["models"])

            raw_dialogue = service.get_dialogue(run_id, include_raw=True, include_agent_chunks=True)
            usage_events = [
                event
                for event in raw_dialogue["events"]
                if _raw_update(event).get("usage")
            ]
            self.assertEqual(len(usage_events), 1)
            self.assertEqual(
                _raw_update(usage_events[0])["usage"]["input_tokens"],
                100,
            )
            self.assertEqual(_raw_update(usage_events[0])["model"], "fake-acp-model")

            primary_safe_dialogue = service.get_dialogue(run_id, include_raw=False, include_agent_chunks=False)
            self.assertTrue(primary_safe_dialogue["raw_events_omitted"])
            self.assertTrue(primary_safe_dialogue["agent_chunks_omitted"])
            self.assertFalse(any("raw" in event for event in primary_safe_dialogue["events"]))
            self.assertFalse(any(event.get("kind") == "agent_message_chunk" for event in primary_safe_dialogue["events"]))

            stderr_tail = service.get_run_log_tail(run_id, "stderr.log", max_bytes=4096)
            self.assertIn("AuthRequired", stderr_tail["text"])
        finally:
            remove_tree(tmp)

    def test_fake_acp_permission_fixture_preserves_adapter_ids_options_and_resolution(self) -> None:
        tmp = ROOT / ".tmp-test-acp-conformance-permission"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            resolution, summary = run_async(_permission_approval_flow(service, tmp))
            run_id = summary["run_id"]

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(resolution["permission"]["adapter_request_id"], "77")
            self.assertEqual(resolution["permission"]["command_or_action"], "edit")
            self.assertEqual(resolution["permission"]["paths"], ["fake_output.txt"])
            self.assertEqual(resolution["permission"]["resources"], ["file:fake_output.txt"])
            self.assertEqual(resolution["permission"]["resolved_option_id"], "allow")
            self.assertEqual(resolution["permission"]["decision_rationale"], "fake test approval")
            self.assertEqual(
                resolution["permission"]["adapter_result"],
                {"outcome": {"outcome": "selected", "optionId": "allow"}},
            )
            self.assertEqual(
                [option["option_id"] for option in resolution["permission"]["options"]],
                ["allow", "deny"],
            )
            self.assertEqual(resolution["permission"]["raw"]["method"], "session/request_permission")
            self.assertEqual(summary["permission_counts"]["permission_count"], 1)
            self.assertEqual(summary["permission_counts"]["approved_permission_count"], 1)

            permissions = _jsonl(tmp / ".orbital" / "runs" / run_id / "permissions.jsonl")
            self.assertEqual([item["status"] for item in permissions], ["pending", "approved"])
            self.assertTrue(all(item["adapter_request_id"] == "77" for item in permissions))
            self.assertEqual(permissions[0]["command_or_action"], "edit")
            self.assertIsNone(permissions[0]["resolved_option_id"])
            self.assertEqual(permissions[1]["resolved_option_id"], "allow")
            self.assertEqual(permissions[1]["decision_rationale"], "fake test approval")
            self.assertEqual(permissions[1]["adapter_result"]["outcome"]["optionId"], "allow")

            transcript = service.get_run_log_tail(run_id, "transcript.log", max_bytes=50_000)["text"]
            conformance = evaluate_acp_conformance(
                transcript,
                AcpConformanceExpectation(permission_option_ids=["allow"]),
            )
            self.assertTrue(conformance["ok"], conformance)
            permission_replies = [
                item["message"]
                for item in _protocol_messages(transcript)
                if item["direction"] == ">"
                and item["message"].get("id") == 77
                and item["message"].get("result", {}).get("outcome")
            ]
            self.assertEqual(permission_replies[0]["result"]["outcome"]["optionId"], "allow")
        finally:
            remove_tree(tmp)

    def test_fake_acp_codex_camel_permission_method_is_normalized(self) -> None:
        tmp = ROOT / ".tmp-test-acp-conformance-codex-permission"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            resolution, summary = run_async(_permission_approval_flow(service, tmp, codex_camel=True))
            run_id = summary["run_id"]

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["permission_counts"]["permission_count"], 1)
            self.assertEqual(summary["permission_counts"]["approved_permission_count"], 1)
            self.assertEqual(resolution["permission"]["raw"]["method"], "requestPermission")
            self.assertEqual(resolution["permission"]["adapter_request_id"], "77")
            self.assertEqual(resolution["permission"]["resolved_option_id"], "allow")

            permissions = _jsonl(tmp / ".orbital" / "runs" / run_id / "permissions.jsonl")
            self.assertEqual([item["status"] for item in permissions], ["pending", "approved"])
            self.assertEqual(permissions[0]["raw"]["method"], "requestPermission")

            transcript = service.get_run_log_tail(run_id, "transcript.log", max_bytes=50_000)["text"]
            permission_replies = [
                item["message"]
                for item in _protocol_messages(transcript)
                if item["direction"] == ">"
                and item["message"].get("id") == 77
                and item["message"].get("result", {}).get("outcome")
            ]
            self.assertEqual(permission_replies[0]["result"]["outcome"]["optionId"], "allow")
        finally:
            remove_tree(tmp)

    def test_fake_acp_zero_permission_id_is_preserved_and_resolved(self) -> None:
        tmp = ROOT / ".tmp-test-acp-conformance-zero-permission-id"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            resolution, summary = run_async(_permission_approval_flow(service, tmp, zero_id=True))
            run_id = summary["run_id"]

            self.assertEqual(summary["status"], "completed")
            self.assertEqual(resolution["permission"]["adapter_request_id"], "0")
            self.assertEqual(resolution["permission"]["permission_id"], f"perm-{run_id}-0")
            self.assertEqual(resolution["permission"]["resolved_option_id"], "allow")

            permissions = _jsonl(tmp / ".orbital" / "runs" / run_id / "permissions.jsonl")
            self.assertEqual([item["adapter_request_id"] for item in permissions], ["0", "0"])
            self.assertEqual([item["status"] for item in permissions], ["pending", "approved"])

            transcript = service.get_run_log_tail(run_id, "transcript.log", max_bytes=50_000)["text"]
            permission_replies = [
                item["message"]
                for item in _protocol_messages(transcript)
                if item["direction"] == ">"
                and item["message"].get("id") == 0
                and item["message"].get("result", {}).get("outcome")
            ]
            self.assertEqual(permission_replies[0]["result"]["outcome"]["optionId"], "allow")
        finally:
            remove_tree(tmp)

    def test_fake_acp_permission_denial_preserves_complete_round_trip(self) -> None:
        tmp = ROOT / ".tmp-test-acp-conformance-permission-denial"
        try:
            tmp.mkdir(exist_ok=True)
            service = fake_acp_service(tmp)

            resolution, summary = run_async(_permission_denial_flow(service, tmp))
            run_id = summary["run_id"]

            self.assertEqual(summary["status"], "failed")
            self.assertEqual(resolution["permission"]["status"], "denied")
            self.assertEqual(resolution["permission"]["resolved_option_id"], "deny")
            self.assertEqual(resolution["permission"]["decision_rationale"], "fake test denial")
            self.assertEqual(resolution["permission"]["adapter_result"]["outcome"]["optionId"], "deny")
            self.assertEqual(summary["permission_counts"]["denied_permission_count"], 1)

            permissions = _jsonl(tmp / ".orbital" / "runs" / run_id / "permissions.jsonl")
            self.assertEqual([item["status"] for item in permissions], ["pending", "denied"])
            self.assertEqual(permissions[1]["adapter_result"]["outcome"]["optionId"], "deny")

            transcript = service.get_run_log_tail(run_id, "transcript.log", max_bytes=50_000)["text"]
            conformance = evaluate_acp_conformance(
                transcript,
                AcpConformanceExpectation(permission_option_ids=["deny"], result_statuses=["failed"]),
            )
            self.assertTrue(conformance["ok"], conformance)
            permission_replies = [
                item["message"]
                for item in _protocol_messages(transcript)
                if item["direction"] == ">"
                and item["message"].get("id") == 77
                and item["message"].get("result", {}).get("outcome")
            ]
            self.assertEqual(permission_replies[0]["result"]["outcome"]["optionId"], "deny")
        finally:
            remove_tree(tmp)


async def _permission_approval_flow(
    service, tmp: Path, codex_camel: bool = False, zero_id: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    objective = "Implement fake task with permission."
    if codex_camel:
        objective += " CODEX_CAMEL_PERMISSION"
    if zero_id:
        objective += " ZERO_PERMISSION_ID"
    response = await service.start_task_run(
        tmp,
        task(objective, allowed_paths=["fake_output.txt"]),
        profile_id="fake_acp",
    )
    run_id = response["run_id"]
    permission_id = await wait_for_permission(service, run_id)
    resolution = await service.resolve_permission(
        run_id,
        permission_id,
        "approve",
        option_id="allow",
        rationale="fake test approval",
    )
    summary = await wait_for_terminal_summary(service, run_id)
    return resolution, summary


async def _permission_denial_flow(service, tmp: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    response = await service.start_task_run(
        tmp,
        task("Implement fake task with permission.", allowed_paths=["fake_output.txt"]),
        profile_id="fake_acp",
    )
    run_id = response["run_id"]
    permission_id = await wait_for_permission(service, run_id)
    resolution = await service.resolve_permission(
        run_id,
        permission_id,
        "deny",
        option_id="deny",
        rationale="fake test denial",
    )
    for _ in range(120):
        summary = service.get_run_summary(run_id)
        if summary["status"] == "failed":
            return resolution, summary
        await asyncio.sleep(0.05)
    summary = service.get_run_summary(run_id)
    if run_id in service._controllers:
        await service.stop_task_run(run_id)
    return resolution, summary


def _protocol_messages(transcript: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for line in transcript.splitlines():
        if not line.startswith(("> ", "< ")):
            continue
        messages.append({"direction": line[0], "message": json.loads(line[2:])})
    return messages


def _raw_update(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("raw")
    if not isinstance(raw, dict):
        return {}
    params = raw.get("params")
    if not isinstance(params, dict):
        return {}
    update = params.get("update")
    return update if isinstance(update, dict) else {}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
