#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def recv() -> dict | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def main() -> None:
    while True:
        message = recv()
        if message is None:
            return
        method = message.get("method")
        msg_id = message.get("id")
        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "ok": True,
                        "apiKeysPresent": {
                            "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
                            "CODEX_API_KEY": bool(os.environ.get("CODEX_API_KEY")),
                        },
                    },
                }
            )
        elif method == "session/new":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {"sessionId": "fake-session"}})
        elif method == "session/set_model":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        elif method == "session/prompt":
            raw_prompt = message.get("params", {}).get("prompt", "")
            if isinstance(raw_prompt, list):
                prompt = "\n".join(str(item.get("text", item)) for item in raw_prompt)
            else:
                prompt = str(raw_prompt)
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "Fake harness started."},
                        }
                    },
                }
            )
            if "EXIT_NONZERO" in prompt:
                sys.stderr.write("fake harness exiting non-zero\n")
                sys.stderr.flush()
                sys.exit(7)
            if "JSONRPC_ERROR" in prompt:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32000, "message": "Fake JSON-RPC failure"},
                    }
                )
                continue
            if "WAIT_FOR_FOLLOWUP" in prompt:
                followup = recv()
                followup_id = followup.get("id")
                raw_followup_prompt = followup.get("params", {}).get("prompt", "") if isinstance(followup, dict) else ""
                if isinstance(raw_followup_prompt, list):
                    followup_prompt = "\n".join(str(item.get("text", item)) for item in raw_followup_prompt)
                else:
                    followup_prompt = str(raw_followup_prompt)
                if "FOLLOWUP_WRITE" in followup_prompt:
                    send_write("fake-followup-write", Path("followup_output.txt"), "changed by followup\n")
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": followup_id,
                        "result": {"status": "passed", "text": "Follow-up completed."},
                    }
                )
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"status": "passed", "text": "Initial prompt completed after follow-up."},
                    }
                )
                continue
            if "STUBBORN_SLEEP" in prompt:
                import signal

                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                time.sleep(30)
            elif "SLEEP" in prompt:
                time.sleep(30)
            if "MALFORMED_STDOUT" in prompt:
                sys.stdout.write("not-json-from-fake-harness\n")
                sys.stdout.flush()
            if "NOOP_PASS" in prompt:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"status": "passed", "text": "No changes needed."},
                    }
                )
                continue
            if "FAIL_RESULT" in prompt:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"status": "failed", "text": "Fake harness failed as requested."},
                    }
                )
                continue
            if "FORBIDDEN_COMMAND" in prompt:
                send(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "update": {
                                "sessionUpdate": "tool_call",
                                "toolCallId": "fake-pip-1",
                                "title": "bash",
                                "kind": "execute",
                                "status": "pending",
                                "locations": [{"path": str(Path.cwd())}],
                                "rawInput": {"cwd": str(Path.cwd())},
                            }
                        },
                    }
                )
                send(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "update": {
                                "sessionUpdate": "tool_call_update",
                                "toolCallId": "fake-pip-1",
                                "title": "pip install -e .",
                                "kind": "execute",
                                "status": "in_progress",
                                "locations": [{"path": str(Path.cwd())}],
                                "rawInput": {
                                    "cwd": str(Path.cwd()),
                                    "command": "pip install -e .",
                                    "description": "Install package in development mode",
                                },
                            }
                        },
                    }
                )
                time.sleep(30)
            if "FAILED_CHECK" in prompt:
                send_check("fake-check-failed", "python3 -m pytest -q", 1, "1 failed in 0.01s\n")
            if "with permission" in prompt.lower():
                ambiguous = "AMBIGUOUS_PERMISSION" in prompt
                codex_camel = "CODEX_CAMEL_PERMISSION" in prompt
                zero_id = "ZERO_PERMISSION_ID" in prompt
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": 0 if zero_id else 77,
                        "method": "requestPermission" if codex_camel else "session/request_permission",
                        "params": {
                            "summary": "Edit fake_output.txt",
                            "risk": "file_edit",
                            "action": "edit",
                            "resources": ["file:fake_output.txt"],
                            "paths": ["fake_output.txt"],
                            "toolCall": {
                                "title": "write fake_output.txt",
                                "kind": "edit",
                                "rawInput": {"command": "write fake_output.txt", "filePath": "fake_output.txt"},
                            },
                            "options": (
                                [
                                    {"id": "allow-read", "label": "Allow read", "kind": "allow"},
                                    {"id": "allow-write", "label": "Allow write", "kind": "allow"},
                                    {"id": "deny", "label": "Deny", "kind": "deny"},
                                ]
                                if ambiguous
                                else [
                                    {"id": "allow", "label": "Allow", "kind": "allow"},
                                    {"id": "deny", "label": "Deny", "kind": "deny"},
                                ]
                            ),
                        },
                    }
                )
                permission_response = recv()
                outcome = permission_response.get("result", {}).get("outcome", {})
                option = outcome.get("optionId") if outcome.get("outcome") == "selected" else None
                if option != "allow":
                    send(
                        {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {"status": "failed", "text": "Permission denied."},
                        }
                    )
                    continue
            if "FORBIDDEN_PATH" in prompt:
                send_write("fake-forbidden-write", Path("secret.txt"), "changed forbidden path\n")
            if "OUTSIDE_ALLOWED" in prompt:
                send_write("fake-outside-write", Path("outside.txt"), "changed outside allowed path\n")
            if "RUN_CHECK" in prompt:
                send_check("fake-check-1", "python3 -m pytest -q", 0, "1 passed in 0.01s\n")
            target = Path("followup_output.txt") if "FOLLOWUP_WRITE" in prompt else Path("ORBITAL_SMOKE.md") if "ORBITAL_SMOKE.md" in prompt else Path("fake_output.txt")
            send_write("fake-write-1", target, "changed by fake harness\n")
            if "USAGE" in prompt:
                send(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": " Usage event recorded."},
                                "model": "fake-acp-model",
                                "usage": {
                                    "input_tokens": 100,
                                    "output_tokens": 25,
                                    "cache_read_input_tokens": 10,
                                    "total_tokens": 135,
                                },
                            }
                        },
                    }
                )
            sys.stderr.write(
                'ERROR AuthRequired(AuthRequiredError { www_authenticate_header: "Bearer error=\\"invalid_request\\", error_description=\\"No access token was provided in this request\\", resource_metadata=\\"https://api.githubcopilot.com/.well-known/oauth-protected-resource/mcp/\\"" })\n'
            )
            sys.stderr.flush()
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": " Fake harness wrote fake_output.txt."},
                        }
                    },
                }
            )
            send(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"status": "passed", "text": "Implemented fake task."},
                }
            )
        else:
            send({"jsonrpc": "2.0", "id": msg_id, "error": {"message": f"unknown method {method}"}})


def send_check(tool_call_id: str, command: str, exit_code: int, output: str) -> None:
    send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": tool_call_id,
                    "title": command,
                    "kind": "execute",
                    "status": "pending",
                    "locations": [{"path": str(Path.cwd())}],
                    "rawInput": {
                        "cwd": str(Path.cwd()),
                        "command": command,
                        "description": "Run requested checks",
                    },
                }
            },
        }
    )
    send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": tool_call_id,
                    "title": command,
                    "kind": "execute",
                    "status": "completed",
                    "locations": [{"path": str(Path.cwd())}],
                    "rawInput": {
                        "cwd": str(Path.cwd()),
                        "command": command,
                        "description": "Run requested checks",
                    },
                    "rawOutput": {
                        "metadata": {
                            "exit": exit_code,
                            "output": output,
                            "truncated": False,
                        },
                        "output": output,
                    },
                }
            },
        }
    )


def send_write(tool_call_id: str, path: Path, text: str) -> None:
    absolute = Path.cwd() / path
    send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": tool_call_id,
                    "title": f"write {path}",
                    "kind": "edit",
                    "status": "pending",
                    "locations": [{"path": str(absolute)}],
                    "rawInput": {"filePath": str(absolute)},
                }
            },
        }
    )
    path.write_text(text, encoding="utf-8")
    send(
        {
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call_update",
                    "toolCallId": tool_call_id,
                    "title": str(path),
                    "kind": "edit",
                    "status": "completed",
                    "locations": [{"path": str(absolute)}],
                    "content": [
                        {
                            "type": "content",
                            "content": {"type": "text", "text": f"Wrote {path} successfully."},
                        }
                    ],
                }
            },
        }
    )


if __name__ == "__main__":
    main()
