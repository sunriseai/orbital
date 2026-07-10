from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from ..events import TOOL_CALL_COMPLETED, TOOL_CALL_FAILED, TOOL_CALL_STARTED, TOOL_CALL_UPDATED
from ..models import HarnessProfile
from ..permissions import normalize_permission
from ..policy import command_policy_violation, normalize_command
from .base import AcpSessionInfo, AdapterSink, PromptResult


API_KEY_ENV_VARS = ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY")
PROFILE_MODEL_ENV = "ORBITAL_ACP_MODEL"
PERMISSION_REQUEST_METHODS = {
    "requestPermission",
    "session/requestPermission",
    "session.requestPermission",
    "session/request_permission",
    "permission/request",
}


class AcpProtocolError(RuntimeError):
    pass


class AcpWorkerController:
    def __init__(self, run_id: str, sink: AdapterSink):
        self.run_id = run_id
        self.sink = sink
        self.profile: HarnessProfile | None = None
        self.process: asyncio.subprocess.Process | None = None
        self.cwd: Path | None = None
        self.session_id: str | None = None
        self._next_id = 1
        self._pending_calls: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_permission_request_ids: set[str] = set()
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self.last_stop_method: str | None = None

    async def launch(self, profile: HarnessProfile, cwd: Path) -> None:
        self.profile = profile
        self.cwd = cwd
        env = os.environ.copy()
        scrubbed_api_keys: list[str] = []
        if profile.auth_mode == "local_subscription":
            for key in API_KEY_ENV_VARS:
                if key in env and key not in profile.env:
                    env.pop(key, None)
                    scrubbed_api_keys.append(key)
        env.update(profile.env)
        if profile.block_mcp_servers:
            env.setdefault("CODEX_ACP_BLOCK_MCP_SERVERS", profile.block_mcp_servers)
            env.setdefault("ORBITAL_BLOCK_MCP_SERVERS", profile.block_mcp_servers)
        await self.sink.transcript(
            "# launch_env "
            f"auth_mode={profile.auth_mode} "
            f"cost_posture={profile.cost_posture} "
            f"scrubbed_api_key_env={','.join(scrubbed_api_keys) if scrubbed_api_keys else 'none'}"
        )
        self.process = await asyncio.create_subprocess_exec(
            *profile.command,
            cwd=str(cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

    async def initialize(self) -> AcpSessionInfo:
        await self._request("initialize", {"protocolVersion": 1})
        result = await self._request("session/new", {"cwd": str(self.cwd), "mcpServers": []})
        self.session_id = str(result.get("sessionId") or result.get("session_id") or result.get("id") or "")
        model_id = _profile_model_id(self.profile)
        if self.session_id and model_id:
            await self._request("session/set_model", {"sessionId": self.session_id, "modelId": model_id})
            await self.sink.transcript(f"# acp_model model_id={model_id}")
        return AcpSessionInfo(
            session_id=self.session_id or None,
            process_id=self.process.pid if self.process else None,
        )

    async def send_prompt(self, text: str) -> PromptResult:
        result = await self._request(
            "session/prompt",
            {"sessionId": self.session_id, "prompt": [{"type": "text", "text": text}]},
        )
        return PromptResult(status=str(result.get("status", "passed")), text=result.get("text"), raw=result)

    async def resolve_permission(self, request_id: str, option_id: str) -> dict[str, Any]:
        if request_id not in self._pending_permission_request_ids:
            raise AcpProtocolError(f"unknown pending adapter request id: {request_id}")
        self._pending_permission_request_ids.remove(request_id)
        result = {"outcome": {"outcome": "selected", "optionId": option_id}}
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": _decode_jsonrpc_id(request_id),
                "result": result,
            }
        )
        return result

    async def cancel_permission(self, request_id: str) -> None:
        if request_id not in self._pending_permission_request_ids:
            return
        self._pending_permission_request_ids.remove(request_id)
        await self._send(
            {
                "jsonrpc": "2.0",
                "id": _decode_jsonrpc_id(request_id),
                "result": {"outcome": {"outcome": "cancelled"}},
            }
        )

    async def cancel(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()

    async def stop(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
                self.last_stop_method = "terminate"
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
                self.last_stop_method = "kill"
        for task in [self._reader_task, self._stderr_task]:
            if task:
                task.cancel()
        pending_tasks = [task for task in [self._reader_task, self._stderr_task] if task]
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

    async def wait(self) -> int | None:
        if not self.process:
            return None
        return await self.process.wait()

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        call_id = str(self._next_id)
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_calls[call_id] = future
        await self._send({"jsonrpc": "2.0", "id": int(call_id), "method": method, "params": params})
        return await future

    async def _send(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise AcpProtocolError("ACP process is not running")
        line = json.dumps(message, separators=(",", ":"))
        await self.sink.transcript(f"> {line}")
        self.process.stdin.write((line + "\n").encode("utf-8"))
        await self.process.stdin.drain()

    async def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                await self.sink.transcript(f"< {text}")
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    await self.sink.agent_text(text, {"raw_stdout": text})
                    continue
                await self._handle_message(message)
        finally:
            if self._pending_calls:
                return_code = self.process.returncode
                if return_code is None:
                    return_code = await self.process.wait()
                self._fail_pending_calls(AcpProtocolError(f"ACP process exited before response: {return_code}"))

    async def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            await self.sink.stderr(text)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        if "id" in message and ("result" in message or "error" in message):
            call_id = str(message["id"])
            future = self._pending_calls.pop(call_id, None)
            if future and not future.done():
                if "error" in message:
                    future.set_exception(AcpProtocolError(str(message["error"])))
                else:
                    result = message.get("result")
                    future.set_result(result if isinstance(result, dict) else {"value": result})
            return

        method = str(message.get("method", ""))
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method in {"session/update", "session/message", "agent/message"}:
            text = _extract_text_update(params)
            if text:
                await self.sink.agent_text(text, message)
            tool_update = _extract_tool_update(params)
            if tool_update:
                kind, summary = tool_update
                await self.sink.tool_update(kind, summary, message)
                violation = _tool_policy_violation(params)
                if violation:
                    await self.sink.policy_violation(
                        (
                            f"{violation.reason}: {violation.command} "
                            f"(category={violation.category}; level={violation.policy_level}; "
                            f"enforcement={violation.enforcement})"
                        ),
                        message,
                    )
                    if violation.enforcement == "block":
                        await self._abort(AcpProtocolError(f"{violation.reason}: {violation.command}"))
            return
        if method in PERMISSION_REQUEST_METHODS:
            adapter_id = str(message.get("id") or params.get("request_id") or params.get("id"))
            self._pending_permission_request_ids.add(adapter_id)
            await self.sink.permission_requested(normalize_permission(self.run_id, adapter_id, message))
            return

    async def _abort(self, exc: BaseException) -> None:
        self._fail_pending_calls(exc)
        if self.process and self.process.returncode is None:
            self.process.terminate()

    def _fail_pending_calls(self, exc: BaseException) -> None:
        for future in list(self._pending_calls.values()):
            if not future.done():
                future.set_exception(exc)
        self._pending_calls.clear()


def _decode_jsonrpc_id(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def _profile_model_id(profile: HarnessProfile | None) -> str | None:
    if not profile:
        return None
    model_id = profile.env.get(PROFILE_MODEL_ENV, "").strip()
    return model_id or None


def _extract_text_update(params: dict[str, Any]) -> str | None:
    update = params.get("update")
    if isinstance(update, dict):
        content = update.get("content")
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            return content["text"]
        if isinstance(update.get("text"), str):
            return update["text"]
        if isinstance(update.get("delta"), str):
            return update["delta"]

    content = params.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    if isinstance(content, str):
        return content
    if isinstance(params.get("text"), str):
        return params["text"]
    if isinstance(params.get("delta"), str):
        return params["delta"]
    return None


def _extract_tool_update(params: dict[str, Any]) -> tuple[str, str] | None:
    update = params.get("update")
    if not isinstance(update, dict):
        return None
    session_update = update.get("sessionUpdate")
    if session_update not in {"tool_call", "tool_call_update"}:
        return None

    status = str(update.get("status") or "unknown")
    event_kind = _tool_event_kind(str(session_update), status)
    title = str(update.get("title") or update.get("kind") or "tool")
    tool_kind = str(update.get("kind") or "tool")
    parts = [f"{title} [{tool_kind}; {status}]"]

    locations = _extract_tool_locations(update)
    if locations:
        parts.append("paths: " + ", ".join(locations))

    output = _extract_tool_output(update)
    if output:
        parts.append(output)

    return event_kind, " | ".join(parts)


def _tool_policy_violation(params: dict[str, Any]):
    update = params.get("update")
    if not isinstance(update, dict):
        return None
    tool_kind = str(update.get("kind") or "").lower()
    title = str(update.get("title") or "").lower()
    if tool_kind != "execute" and "bash" not in title and "shell" not in title:
        return None
    raw_input = update.get("rawInput")
    command = normalize_command(raw_input)
    if not command:
        return None
    return command_policy_violation(command)


def _tool_event_kind(session_update: str, status: str) -> str:
    if session_update == "tool_call":
        return TOOL_CALL_STARTED
    if status == "completed":
        return TOOL_CALL_COMPLETED
    if status in {"failed", "error"}:
        return TOOL_CALL_FAILED
    return TOOL_CALL_UPDATED


def _extract_tool_locations(update: dict[str, Any]) -> list[str]:
    locations: list[str] = []
    for location in update.get("locations", []):
        if isinstance(location, dict) and isinstance(location.get("path"), str):
            locations.append(location["path"])

    raw_input = update.get("rawInput")
    if isinstance(raw_input, dict):
        file_path = raw_input.get("filePath") or raw_input.get("filepath")
        if isinstance(file_path, str):
            locations.append(file_path)
        cwd = raw_input.get("cwd")
        command = raw_input.get("command")
        if isinstance(cwd, str) and isinstance(command, list):
            command_text = " ".join(str(part) for part in command)
            locations.append(f"{cwd}: {command_text}")

    return sorted(set(locations))


def _extract_tool_output(update: dict[str, Any]) -> str | None:
    raw_output = update.get("rawOutput")
    if isinstance(raw_output, dict):
        if "exit_code" in raw_output:
            return f"exit_code: {raw_output['exit_code']}"
        output = raw_output.get("output") or raw_output.get("aggregated_output")
        if isinstance(output, str) and output.strip():
            return _truncate_summary(output.strip())

    content = update.get("content")
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            nested = item.get("content")
            if isinstance(nested, dict) and isinstance(nested.get("text"), str):
                text_parts.append(nested["text"])
            elif isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        if text_parts:
            return _truncate_summary(" ".join(text_parts).strip())

    return None


def _truncate_summary(text: str, limit: int = 240) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."
