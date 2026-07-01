from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommandPolicyViolation:
    command: str
    reason: str
    category: str
    policy_level: str
    enforcement: str


@dataclass(frozen=True)
class CommandPolicyConfig:
    policy_level: str = "adapter_mediated"
    package_manager: str = "requires_primary_review"
    network: str = "requires_primary_review"
    destructive: str = "requires_primary_review"


_PACKAGE_MANAGER_PATTERN = re.compile(
    r"""
    (^|\b|[;&|]\s*)
    (?:
      (?:python(?:\d+(?:\.\d+)*)?|python3)\s+-m\s+pip
      |pip(?:3|\d+(?:\.\d+)*)?
      |uv\s+(?:pip\s+)?(?:add|remove|sync|pip\s+install)
      |poetry\s+(?:add|remove|install|update)
      |pdm\s+(?:add|remove|install|update|sync)
      |npm\s+(?:install|i|add|update)
      |pnpm\s+(?:install|add|update)
      |yarn\s+(?:install|add|upgrade)
      |bun\s+(?:install|add|update)
      |cargo\s+(?:install|add|update)
      |brew\s+(?:install|upgrade|update)
      |apt(?:-get)?\s+(?:install|update|upgrade)
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_NETWORK_PATTERN = re.compile(
    r"""
    (^|\b|[;&|]\s*)
    (?:
      curl|wget|httpie|http|scp|rsync|ssh
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


_DESTRUCTIVE_PATTERN = re.compile(
    r"""
    (^|\b|[;&|]\s*)
    (?:
      rm\s+(?:-[^\s]*[rf][^\s]*|-[^\s]*[fr][^\s]*)
      |git\s+(?:reset\s+--hard|clean\s+-[^\s]*f)
      |sudo\b
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def command_policy_violation(
    raw: dict[str, Any] | list[Any] | str | None,
    config: CommandPolicyConfig | None = None,
) -> CommandPolicyViolation | None:
    return evaluate_command_policy(raw, config)


def evaluate_command_policy(
    raw: dict[str, Any] | list[Any] | str | None,
    config: CommandPolicyConfig | None = None,
) -> CommandPolicyViolation | None:
    policy = config or CommandPolicyConfig()
    command = normalize_command(raw)
    if not command:
        return None
    if _DESTRUCTIVE_PATTERN.search(command):
        return _violation(command, "destructive", policy.destructive, policy.policy_level)
    if _PACKAGE_MANAGER_PATTERN.search(command):
        return _violation(command, "package_manager", policy.package_manager, policy.policy_level)
    if _NETWORK_PATTERN.search(command):
        return _violation(command, "network", policy.network, policy.policy_level)
    return None


def normalize_command(raw: dict[str, Any] | list[Any] | str | None) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw.strip() or None
    if isinstance(raw, list):
        return " ".join(shlex.quote(str(part)) for part in raw).strip() or None
    if isinstance(raw, dict):
        command = raw.get("command")
        if isinstance(command, str):
            return command.strip() or None
        if isinstance(command, list):
            return " ".join(shlex.quote(str(part)) for part in command).strip() or None
    return None


def _violation(command: str, category: str, enforcement: str, policy_level: str) -> CommandPolicyViolation | None:
    if enforcement in {"allow", "observe"}:
        return None
    action = "blocked" if enforcement == "block" else "requires primary review"
    return CommandPolicyViolation(
        command=command,
        reason=f"{category.replace('_', ' ')} command {action}",
        category=category,
        policy_level=policy_level,
        enforcement=enforcement,
    )
