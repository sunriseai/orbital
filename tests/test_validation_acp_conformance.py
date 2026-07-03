from __future__ import annotations

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


class AcpAdapterConformanceFixtureTests(unittest.TestCase):
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
                    timeout_seconds=5,
                )
            )
            run_id = summary["run_id"]

            transcript = service.get_run_log_tail(run_id, "transcript.log", max_bytes=50_000)["text"]
            protocol = _protocol_messages(transcript)
            sent_methods = [item["message"].get("method") for item in protocol if item["direction"] == ">"]
            received_methods = [item["message"].get("method") for item in protocol if item["direction"] == "<"]
            received_updates = [
                item["message"].get("params", {}).get("update", {}).get("sessionUpdate")
                for item in protocol
                if item["direction"] == "<"
            ]

            self.assertEqual(summary["status"], "completed")
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
            self.assertEqual(summary["tokens"]["total"], 135)
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
            self.assertEqual(resolution["permission"]["resolved_option_id"], "allow")
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


async def _permission_approval_flow(service, tmp: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    response = await service.start_task_run(
        tmp,
        task("Implement fake task with permission.", allowed_paths=["fake_output.txt"]),
        profile_id="fake_acp",
    )
    run_id = response["run_id"]
    permission_id = await wait_for_permission(service, run_id)
    resolution = await service.resolve_permission(run_id, permission_id, "approve")
    summary = await wait_for_terminal_summary(service, run_id)
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
