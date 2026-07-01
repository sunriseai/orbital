from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from ..events import TOOL_CALL_COMPLETED, TOOL_CALL_FAILED, TOOL_CALL_STARTED
from ..models import HarnessProfile
from .base import AcpSessionInfo, AdapterSink, PromptResult


CLAUDE_API_KEY_ENV_VARS = ("ANTHROPIC_API_KEY",)


class ClaudeCliController:
    def __init__(self, run_id: str, sink: AdapterSink):
        self.run_id = run_id
        self.sink = sink
        self.profile: HarnessProfile | None = None
        self.cwd: Path | None = None
        self.process: asyncio.subprocess.Process | None = None

    async def launch(self, profile: HarnessProfile, cwd: Path) -> None:
        self.profile = profile
        self.cwd = cwd
        scrubbed = CLAUDE_API_KEY_ENV_VARS if profile.auth_mode == "local_subscription" else ()
        await self.sink.transcript(
            "# launch_env "
            f"auth_mode={profile.auth_mode} "
            f"cost_posture={profile.cost_posture} "
            f"scrubbed_api_key_env={','.join(scrubbed) if scrubbed else 'none'}"
        )

    async def initialize(self) -> AcpSessionInfo:
        return AcpSessionInfo(session_id=None, process_id=None)

    async def send_prompt(self, text: str) -> PromptResult:
        if not self.profile or not self.cwd:
            raise RuntimeError("Claude CLI controller is not launched")

        env = os.environ.copy()
        if self.profile.auth_mode == "local_subscription":
            for key in CLAUDE_API_KEY_ENV_VARS:
                if key not in self.profile.env:
                    env.pop(key, None)
        env.update(self.profile.env)

        command = [
            *self.profile.command,
            "-p",
            "--verbose",
            "--output-format",
            "stream-json",
            "--permission-mode",
            "acceptEdits",
            "--safe-mode",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
        ]
        await self.sink.transcript("> " + json.dumps({"command": command, "stdin": "<prompt>"}))
        self.process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(self.cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        assert self.process.stdin and self.process.stdout and self.process.stderr
        self.process.stdin.write(text.encode("utf-8"))
        await self.process.stdin.drain()
        self.process.stdin.close()
        stderr_task = asyncio.create_task(self._read_stderr())
        final_text_parts: list[str] = []
        failed = False
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                raw_line = line.decode("utf-8", errors="replace").strip()
                if not raw_line:
                    continue
                await self.sink.transcript(f"< {raw_line}")
                try:
                    message = json.loads(raw_line)
                except json.JSONDecodeError:
                    await self.sink.agent_text(raw_line, {"raw_stdout": raw_line})
                    final_text_parts.append(raw_line)
                    continue
                text_update = _extract_claude_text(message)
                if text_update:
                    final_text_parts.append(text_update)
                    await self.sink.agent_text(text_update, message)
                for kind, summary in _extract_claude_tool_updates(message):
                    await self.sink.tool_update(kind, summary, message)
                if message.get("type") == "result":
                    failed = bool(message.get("is_error"))
                    result = message.get("result")
                    if isinstance(result, str) and result and not final_text_parts:
                        final_text_parts.append(result)
        finally:
            returncode = await self.process.wait()
            await stderr_task

        return PromptResult(
            status="failed" if failed or returncode else "passed",
            text="".join(final_text_parts) or None,
            raw={"returncode": returncode},
        )

    async def resolve_permission(self, request_id: str, option_id: str) -> None:
        raise RuntimeError("Claude CLI adapter does not support interactive permission resolution")

    async def cancel_permission(self, request_id: str) -> None:
        return None

    async def cancel(self) -> None:
        await self.stop()

    async def stop(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

    async def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            await self.sink.stderr(line.decode("utf-8", errors="replace").rstrip("\n"))


def _extract_claude_text(message: dict[str, Any]) -> str | None:
    if isinstance(message.get("text"), str):
        return message["text"]
    nested = message.get("message")
    if isinstance(nested, dict):
        content = nested.get("content")
        if isinstance(content, list):
            return "".join(
                item["text"]
                for item in content
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
            ) or None
    return None


def _extract_claude_tool_updates(message: dict[str, Any]) -> list[tuple[str, str]]:
    updates: list[tuple[str, str]] = []
    nested = message.get("message")
    if not isinstance(nested, dict):
        return updates
    content = nested.get("content")
    if not isinstance(content, list):
        return updates

    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "tool_use":
            name = str(item.get("name") or "tool")
            tool_id = str(item.get("id") or "")
            summary = f"{name} [tool_use; started]"
            if tool_id:
                summary += f" | id: {tool_id}"
            updates.append((TOOL_CALL_STARTED, summary))
        elif item.get("type") == "tool_result":
            tool_id = str(item.get("tool_use_id") or "")
            status = "failed" if item.get("is_error") else "completed"
            text = _truncate_summary(_stringify_tool_result(item.get("content")))
            summary = f"tool_result [{status}]"
            if tool_id:
                summary += f" | id: {tool_id}"
            if text:
                summary += f" | {text}"
            updates.append((TOOL_CALL_FAILED if item.get("is_error") else TOOL_CALL_COMPLETED, summary))
    return updates


def _stringify_tool_result(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    return ""


def _truncate_summary(text: str, limit: int = 240) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."
