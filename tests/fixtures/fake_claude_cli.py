#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def emit(message: dict) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    if sys.argv[1:3] == ["auth", "status"]:
        emit({"loggedIn": True, "authMethod": "oauth", "apiProvider": "firstParty"})
        return

    if "-p" not in sys.argv:
        print("expected -p", file=sys.stderr)
        raise SystemExit(2)

    prompt = sys.stdin.read()
    target = "CLAUDE_SMOKE.md" if "CLAUDE_SMOKE.md" in prompt else "fake_claude_output.txt"
    target_path = Path.cwd() / target
    emit(
        {
            "type": "assistant",
            "model": "fake-claude-model",
            "message": {
                "model": "fake-claude-model",
                "content": [
                    {"type": "text", "text": "Claude fake started."},
                    {"type": "tool_use", "id": "toolu_fake_write", "name": "Write", "input": {"file_path": str(target_path)}},
                ]
            },
        }
    )
    target_path.write_text("The Claude Code CLI worker executed this task through Orbital MCP.\n", encoding="utf-8")
    emit(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_fake_write",
                        "content": "Wrote file successfully.",
                    }
                ]
            },
        }
    )
    emit(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": " Claude fake wrote the requested file.",
                    }
                ]
            },
        }
    )
    emit(
        {
            "type": "result",
            "is_error": False,
            "model": "fake-claude-model",
            "usage": {
                "input_tokens": 33,
                "output_tokens": 7,
                "cache_read_input_tokens": 2,
                "total_tokens": 42,
            },
            "result": "done",
            "apiKeysPresent": {"ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY"))},
        }
    )


if __name__ == "__main__":
    main()
