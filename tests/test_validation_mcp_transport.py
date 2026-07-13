from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path

from orbital_test_helpers import ROOT, remove_tree, write_fake_acp_config

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402


class McpTransportValidationTests(unittest.TestCase):
    def test_stdio_mcp_transport_lists_tools_and_runs_fake_task(self) -> None:
        tmp = ROOT / ".tmp-test-mcp-transport"
        workdir = tmp / "work"
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            write_fake_acp_config(tmp)

            result = _run_async(_mcp_smoke(tmp, workdir))

            self.assertIn("get_server_info", result["tool_names"])
            self.assertIn("run_task_and_wait", result["tool_names"])
            self.assertEqual(result["server_info"]["name"], "orbital-mcp")
            boundaries = result["server_info"]["system_boundaries"]
            self.assertEqual(boundaries["integration_posture"], "artifact_contract_only")
            self.assertIn("Prism", boundaries["external_coordinator"])
            self.assertIn("ngitd-core", boundaries["repo_memory_owner"])
            self.assertIn("repo-change capture", boundaries["orbital_does_not_own"])
            self.assertTrue(result["profile_check"]["ok"])
            self.assertEqual(result["profile_check"]["profile_id"], "fake_acp")
            self.assertEqual(result["run_summary"]["status"], "completed")
            self.assertTrue(result["safe_dialogue"]["raw_events_omitted"])
            self.assertTrue(result["safe_dialogue"]["agent_chunks_omitted"])
            self.assertFalse(any("raw" in event for event in result["safe_dialogue"]["events"]))
            self.assertTrue(any("raw" in event for event in result["debug_dialogue"]["events"]))
            self.assertTrue((workdir / "fake_output.txt").exists())
        finally:
            remove_tree(tmp)


async def _mcp_smoke(base_dir: Path, workdir: Path) -> dict:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    params = StdioServerParameters(
        command=os.environ.get("PYTHON", "python3"),
        args=["-m", "orbital_mcp.cli", "--base-dir", str(base_dir)],
        cwd=str(ROOT),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            server_info = await _call_json(session, "get_server_info", {})
            profile_check = await _call_json(session, "check_harness_profile", {"profile_id": "fake_acp"})
            recommendation = await _call_json(
                session,
                "recommend_harness_profiles",
                {
                    "task_tags": ["fast_smoke"],
                    "required_capabilities": ["dialogue", "permissions"],
                    "include_not_ready": True,
                },
            )
            run_summary = await _call_json(
                session,
                "run_task_and_wait",
                {
                    "workdir": str(workdir),
                    "task_title": "MCP fake task",
                    "task_objective": "Create fake_output.txt through MCP transport.",
                    "harness_profile_id": "fake_acp",
                    "allowed_paths": ["fake_output.txt"],
                    "timeout_seconds": 5,
                },
            )
            run_id = run_summary["run_id"]
            safe_dialogue = await _call_json(session, "get_dialogue", {"run_id": run_id})
            debug_dialogue = await _call_json(
                session,
                "get_debug_dialogue",
                {"run_id": run_id, "include_raw": True, "include_agent_chunks": True},
            )
            return {
                "tool_names": [tool.name for tool in tools.tools],
                "server_info": server_info,
                "profile_check": profile_check,
                "recommendation": recommendation,
                "run_summary": run_summary,
                "safe_dialogue": safe_dialogue,
                "debug_dialogue": debug_dialogue,
            }


async def _call_json(session: ClientSession, name: str, arguments: dict) -> dict:
    result = await session.call_tool(name, arguments)
    if getattr(result, "isError", False):
        raise AssertionError(f"MCP tool {name} returned error: {result}")
    if not result.content:
        raise AssertionError(f"MCP tool {name} returned no content")
    text = getattr(result.content[0], "text", None)
    if not isinstance(text, str):
        raise AssertionError(f"MCP tool {name} returned non-text content: {result.content[0]}")
    return json.loads(text)


def _run_async(coro):
    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
