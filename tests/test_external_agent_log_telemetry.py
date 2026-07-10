from __future__ import annotations

import json
import sqlite3
import unittest

from orbital_test_helpers import ROOT, remove_tree

from orbital_mcp.agent_log_telemetry import scan_external_agent_token_telemetry  # noqa: E402


class ExternalAgentLogTelemetryTests(unittest.TestCase):
    def test_scans_claude_project_jsonl_usage(self) -> None:
        tmp = ROOT / ".tmp-test-external-claude-logs"
        project = tmp / "project"
        log_dir = tmp / "home" / ".claude" / "projects" / "-tmp-project"
        try:
            project.mkdir(parents=True)
            log_dir.mkdir(parents=True)
            (log_dir / "claude-session.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"timestamp": "2026-07-03T10:00:00Z", "cwd": str(project), "type": "user"}),
                        json.dumps(
                            {
                                "timestamp": "2026-07-03T10:00:01Z",
                                "type": "assistant",
                                "message": {
                                    "model": "claude-test",
                                    "usage": {
                                        "input_tokens": 100,
                                        "output_tokens": 20,
                                        "cache_read_input_tokens": 40,
                                    },
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-07-03T10:00:02Z",
                                "type": "assistant",
                                "message": {
                                    "model": "claude-test",
                                    "usage": {
                                        "input_tokens": 10,
                                        "output_tokens": 5,
                                        "cache_read_input_tokens": 25,
                                    },
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            telemetry = scan_external_agent_token_telemetry(project=project, home=tmp / "home")

            self.assertTrue(telemetry.known)
            self.assertEqual(telemetry.input, 110)
            self.assertEqual(telemetry.output, 25)
            self.assertEqual(telemetry.cache, 40)
            self.assertEqual(telemetry.total, 175)
            self.assertEqual(telemetry.records[0].agent, "claude")
        finally:
            remove_tree(tmp)

    def test_scans_codex_rollout_total_token_usage(self) -> None:
        tmp = ROOT / ".tmp-test-external-codex-logs"
        project = tmp / "project"
        log_dir = tmp / "home" / ".codex" / "sessions" / "2026" / "07" / "03"
        try:
            project.mkdir(parents=True)
            log_dir.mkdir(parents=True)
            (log_dir / "rollout-2026-07-03T10-00-00-00000000-0000-0000-0000-000000000001.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-07-03T10:00:00Z",
                                "type": "session_meta",
                                "payload": {"cwd": str(project), "model": "gpt-test"},
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-07-03T10:00:01Z",
                                "type": "event_msg",
                                "payload": {
                                    "info": {
                                        "total_token_usage": {
                                            "input_tokens": 200,
                                            "cached_input_tokens": 50,
                                            "output_tokens": 30,
                                            "total_tokens": 230,
                                        }
                                    }
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            telemetry = scan_external_agent_token_telemetry(project=project, home=tmp / "home")

            self.assertTrue(telemetry.known)
            self.assertEqual(telemetry.input, 150)
            self.assertEqual(telemetry.output, 30)
            self.assertEqual(telemetry.cache, 50)
            self.assertEqual(telemetry.total, 230)
            self.assertEqual(telemetry.records[0].agent, "codex")
        finally:
            remove_tree(tmp)

    def test_scans_opencode_sqlite_step_finish_tokens(self) -> None:
        tmp = ROOT / ".tmp-test-external-opencode-logs"
        project = tmp / "project"
        db_path = tmp / "home" / ".local" / "share" / "opencode" / "opencode.db"
        try:
            project.mkdir(parents=True)
            db_path.parent.mkdir(parents=True)
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "CREATE TABLE session ("
                    "id TEXT PRIMARY KEY, directory TEXT, title TEXT, "
                    "time_created INTEGER, time_updated INTEGER, model TEXT)"
                )
                conn.execute("CREATE TABLE message (session_id TEXT, time_created INTEGER, data TEXT)")
                conn.execute("CREATE TABLE part (session_id TEXT, time_created INTEGER, data TEXT)")
                conn.execute(
                    "INSERT INTO session VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "opencode-session",
                        str(project),
                        "Task",
                        1783082400000,
                        1783082402000,
                        json.dumps({"id": "opencode-test", "providerID": "opencode"}),
                    ),
                )
                conn.execute(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    (
                        "opencode-session",
                        1783082401000,
                        json.dumps({"role": "assistant", "modelID": "opencode-message-test"}),
                    ),
                )
                conn.execute(
                    "INSERT INTO part VALUES (?, ?, ?)",
                    (
                        "opencode-session",
                        1783082401000,
                        json.dumps(
                            {
                                "type": "step-finish",
                                "tokens": {
                                    "total": 120,
                                    "input": 80,
                                    "output": 10,
                                    "cache": {"read": 30, "write": 15},
                                },
                            }
                        ),
                    ),
                )
                conn.execute(
                    "INSERT INTO part VALUES (?, ?, ?)",
                    (
                        "opencode-session",
                        1783082402000,
                        json.dumps(
                            {
                                "type": "step-finish",
                                "tokens": {
                                    "total": 135,
                                    "input": 100,
                                    "output": 15,
                                    "cache": {"read": 20},
                                },
                            }
                        ),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            telemetry = scan_external_agent_token_telemetry(project=project, home=tmp / "home")

            self.assertTrue(telemetry.known)
            self.assertEqual(telemetry.input, 100)
            self.assertEqual(telemetry.output, 15)
            self.assertEqual(telemetry.cache, 20)
            self.assertEqual(telemetry.total, 135)
            self.assertEqual(telemetry.records[0].agent, "opencode")
            self.assertEqual(telemetry.records[0].model, "opencode-test")
        finally:
            remove_tree(tmp)


if __name__ == "__main__":
    unittest.main()
