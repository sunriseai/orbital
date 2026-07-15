from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import HarnessConfig, HarnessProfile, ProfileClassification, ProfileSupport


CONFIG_FILE = "orbital.config.json"
OPENCODE_ASK_PERMISSION_CONFIG = json.dumps({"permission": {"bash": "ask", "edit": "ask"}})
OPENCODE_GLM52_MODEL = "opencode/glm-5.2"
OPENCODE_BIG_PICKLE_MODEL = "opencode/big-pickle"


def default_profiles() -> list[HarnessProfile]:
    return [
        HarnessProfile(
            id="codex_acp_local",
            display_name="Codex local subscription (Zed legacy)",
            adapter="acp",
            runtime_family="codex",
            command=["codex-acp"],
            auth_mode="local_subscription",
            cost_posture="subscription_preferred",
            capabilities=["dialogue", "permissions", "stop"],
            classification=ProfileClassification(
                task_tags=["implementation", "test_repair", "analysis", "long_context"],
                strengths=["general coding tasks", "broad codebase analysis"],
                limits=["requires local Codex ACP command"],
                max_recommended_scope="medium",
                cost_preference="subscription_preferred",
                locality="subscription",
            ),
            support=ProfileSupport(tier="experimental_acp", notes=["Requires local codex-acp command."]),
            block_mcp_servers="orbital,prism,codex-acp,github",
        ),
        HarnessProfile(
            id="codex_acp_official",
            display_name="Codex official ACP app-server adapter",
            adapter="acp",
            runtime_family="codex",
            command=["npx", "-y", "@agentclientprotocol/codex-acp"],
            auth_mode="local_subscription",
            cost_posture="subscription_preferred",
            capabilities=["dialogue", "permissions", "stop"],
            classification=ProfileClassification(
                task_tags=["implementation", "test_repair", "analysis", "long_context"],
                strengths=["official maintained Codex ACP adapter", "Codex App Server event coverage"],
                limits=["requires npx and package download/cache", "requires local Codex authentication"],
                max_recommended_scope="medium",
                cost_preference="subscription_preferred",
                locality="subscription",
            ),
            support=ProfileSupport(
                tier="experimental_acp",
                notes=[
                    "Official @agentclientprotocol/codex-acp app-server adapter.",
                    "Uses INITIAL_AGENT_MODE=read-only so edit and command probes should exercise approval mediation.",
                ],
            ),
            env={"INITIAL_AGENT_MODE": "read-only"},
            block_mcp_servers="orbital,prism,codex-acp,github",
        ),
        HarnessProfile(
            id="claude_agent_acp_api",
            display_name="Claude Agent SDK ACP API",
            adapter="acp",
            runtime_family="claude_agent",
            command=["claude-agent-acp"],
            auth_mode="api_key",
            cost_posture="metered_api",
            enabled=False,
            capabilities=["dialogue", "permissions", "stop"],
            classification=ProfileClassification(
                task_tags=["implementation", "analysis", "docs"],
                strengths=["API-backed Claude Agent SDK ACP tasks"],
                limits=["requires Node >= 22, claude-agent-acp, and ANTHROPIC_API_KEY", "metered API use requires explicit opt-in"],
                max_recommended_scope="medium",
                cost_preference="metered_api",
                locality="metered_api",
            ),
            support=ProfileSupport(
                tier="profile_template",
                notes=["API-backed Claude Agent SDK ACP profile. Disabled until explicitly configured."],
            ),
        ),
        HarnessProfile(
            id="claude_code_cli_local",
            display_name="Claude Code CLI local subscription",
            adapter="cli",
            runtime_family="claude_code",
            command=["claude"],
            auth_mode="local_subscription",
            cost_posture="subscription_preferred",
            capabilities=["dialogue", "tool_events", "stop"],
            permission_behavior="accept_edits",
            classification=ProfileClassification(
                task_tags=["implementation", "docs", "fast_smoke"],
                strengths=["CLI fallback when ACP is unavailable"],
                limits=["no interactive permission mediation"],
                max_recommended_scope="small",
                cost_preference="subscription_preferred",
                locality="subscription",
            ),
            support=ProfileSupport(tier="cli_fallback", notes=["CLI fallback has weaker permissions and telemetry."]),
        ),
        HarnessProfile(
            id="opencode_acp_local",
            display_name="OpenCode local",
            adapter="acp",
            runtime_family="opencode",
            command=["opencode", "acp", "--pure"],
            auth_mode="local_subscription",
            cost_posture="subscription_preferred",
            capabilities=["dialogue", "permissions", "stop"],
            classification=ProfileClassification(
                task_tags=["implementation", "test_repair", "fast_smoke", "local_only"],
                strengths=["local/subscription ACP tasks", "small implementation changes"],
                limits=["model and auth depend on OpenCode configuration"],
                max_recommended_scope="small",
                cost_preference="subscription_preferred",
                locality="subscription",
            ),
            support=ProfileSupport(tier="experimental_acp", notes=["Needs local smoke coverage before known-good support."]),
        ),
        HarnessProfile(
            id="opencode_acp_local_ask",
            display_name="OpenCode local (ask permissions)",
            adapter="acp",
            runtime_family="opencode",
            command=["opencode", "acp", "--pure"],
            auth_mode="local_subscription",
            cost_posture="subscription_preferred",
            capabilities=["dialogue", "permissions", "stop"],
            classification=ProfileClassification(
                task_tags=["implementation", "test_repair", "fast_smoke", "local_only", "permission_smoke"],
                strengths=["local/subscription ACP tasks", "deterministic bash/edit permission mediation"],
                limits=["model and auth depend on OpenCode configuration", "forces OpenCode bash/edit actions to ask"],
                max_recommended_scope="small",
                cost_preference="subscription_preferred",
                locality="subscription",
            ),
            support=ProfileSupport(
                tier="experimental_acp",
                notes=[
                    "Uses OPENCODE_CONFIG_CONTENT to force OpenCode bash/edit permissions to ask.",
                    "Use this profile when the primary must mediate secondary shell or edit permissions.",
                ],
            ),
            env={"OPENCODE_CONFIG_CONTENT": OPENCODE_ASK_PERMISSION_CONFIG},
        ),
        HarnessProfile(
            id="opencode_acp_glm52",
            display_name="OpenCode GLM-5.2",
            adapter="acp",
            runtime_family="opencode",
            command=["opencode", "acp", "--pure"],
            auth_mode="api_key",
            cost_posture="metered_api",
            capabilities=["dialogue", "permissions", "stop"],
            classification=ProfileClassification(
                task_tags=["implementation", "test_repair", "fast_smoke"],
                strengths=["explicit metered OpenCode ACP profile"],
                limits=["metered API use requires explicit primary opt-in"],
                max_recommended_scope="small",
                cost_preference="metered_api",
                locality="metered_api",
            ),
            support=ProfileSupport(tier="experimental_acp", notes=["Metered profile is never selected implicitly."]),
            env={"ORBITAL_ACP_MODEL": OPENCODE_GLM52_MODEL},
        ),
        HarnessProfile(
            id="opencode_acp_glm52_ask",
            display_name="OpenCode GLM-5.2 (ask permissions)",
            adapter="acp",
            runtime_family="opencode",
            command=["opencode", "acp", "--pure"],
            auth_mode="api_key",
            cost_posture="metered_api",
            capabilities=["dialogue", "permissions", "stop"],
            classification=ProfileClassification(
                task_tags=["implementation", "test_repair", "fast_smoke", "permission_smoke"],
                strengths=["explicit metered OpenCode ACP profile", "deterministic bash/edit permission mediation"],
                limits=["metered API use requires explicit primary opt-in", "forces OpenCode bash/edit actions to ask"],
                max_recommended_scope="small",
                cost_preference="metered_api",
                locality="metered_api",
            ),
            support=ProfileSupport(
                tier="experimental_acp",
                notes=[
                    "Pins OpenCode Zen model opencode/glm-5.2 through session/set_model.",
                    "Uses OPENCODE_CONFIG_CONTENT to force OpenCode bash/edit permissions to ask.",
                    "Metered profile is never selected implicitly.",
                ],
            ),
            env={
                "ORBITAL_ACP_MODEL": OPENCODE_GLM52_MODEL,
                "OPENCODE_CONFIG_CONTENT": OPENCODE_ASK_PERMISSION_CONFIG,
            },
        ),
        HarnessProfile(
            id="opencode_acp_big_pickle_ask",
            display_name="OpenCode Big Pickle (ask permissions)",
            adapter="acp",
            runtime_family="opencode",
            command=["opencode", "acp", "--pure"],
            auth_mode="api_key",
            cost_posture="metered_api",
            capabilities=["dialogue", "permissions", "stop"],
            classification=ProfileClassification(
                task_tags=["implementation", "test_repair", "fast_smoke", "permission_smoke", "cheap_smoke"],
                strengths=["free OpenCode Zen model during availability window", "deterministic bash/edit permission mediation"],
                limits=[
                    "metered/API-backed profile requires explicit primary opt-in",
                    "Big Pickle is free for a limited time according to OpenCode Zen pricing",
                    "free-period data may be used to improve the model",
                    "forces OpenCode bash/edit actions to ask",
                ],
                max_recommended_scope="small",
                cost_preference="free_or_low_cost",
                locality="metered_api",
            ),
            support=ProfileSupport(
                tier="experimental_acp",
                notes=[
                    "Pins OpenCode Zen model opencode/big-pickle through session/set_model.",
                    "Big Pickle is documented by OpenCode Zen as free for a limited time.",
                    "Uses OPENCODE_CONFIG_CONTENT to force OpenCode bash/edit permissions to ask.",
                    "Never selected implicitly.",
                ],
            ),
            env={
                "ORBITAL_ACP_MODEL": OPENCODE_BIG_PICKLE_MODEL,
                "OPENCODE_CONFIG_CONTENT": OPENCODE_ASK_PERMISSION_CONFIG,
            },
        ),
        HarnessProfile(
            id="codex_api",
            display_name="Codex API",
            adapter="api",
            runtime_family="codex",
            auth_mode="api_key",
            cost_posture="metered_api",
            enabled=False,
            capabilities=["dialogue"],
            classification=ProfileClassification(
                task_tags=["implementation", "analysis"],
                strengths=["API-backed fallback"],
                limits=["disabled by default", "no ACP normalization"],
                max_recommended_scope="small",
                cost_preference="metered_api",
                locality="metered_api",
            ),
            support=ProfileSupport(tier="profile_template", notes=["Deferred API adapter template."]),
        ),
    ]


def load_config(base_dir: Path | str = ".") -> HarnessConfig:
    base = Path(base_dir)
    config_path = base / CONFIG_FILE
    if not config_path.exists():
        return HarnessConfig(default_profile="opencode_acp_local", profiles=default_profiles())

    data = json.loads(config_path.read_text(encoding="utf-8"))
    profiles = [_profile_from_dict(item) for item in data.get("profiles", [])]
    if not profiles:
        profiles = default_profiles()
    return HarnessConfig(
        schema_version=int(data.get("schema_version", 1)),
        default_profile=data.get("default_profile", "opencode_acp_local"),
        allow_api_fallback=bool(data.get("allow_api_fallback", False)),
        storage_root=data.get("storage_root", ".orbital"),
        profiles=profiles,
    )


def _profile_from_dict(data: dict[str, Any]) -> HarnessProfile:
    return HarnessProfile(
        id=data["id"],
        display_name=data.get("display_name", data["id"]),
        adapter=data.get("adapter", "acp"),
        runtime_family=data.get("runtime_family", "generic"),
        command=list(data.get("command", [])),
        auth_mode=data.get("auth_mode", "unknown"),
        cost_posture=data.get("cost_posture", "unknown"),
        enabled=bool(data.get("enabled", True)),
        capabilities=list(data.get("capabilities", [])),
        permission_behavior=data.get("permission_behavior", "manual"),
        classification=_classification_from_dict(data.get("classification", {})),
        support=_support_from_dict(data.get("support", {})),
        env={str(k): str(v) for k, v in data.get("env", {}).items()},
        block_mcp_servers=data.get("block_mcp_servers"),
    )


def _classification_from_dict(data: Any) -> ProfileClassification:
    value = data if isinstance(data, dict) else {}
    return ProfileClassification(
        task_tags=[str(item) for item in value.get("task_tags", [])],
        strengths=[str(item) for item in value.get("strengths", [])],
        limits=[str(item) for item in value.get("limits", [])],
        max_recommended_scope=value.get("max_recommended_scope"),
        cost_preference=value.get("cost_preference"),
        locality=str(value.get("locality", "unknown")),
    )


def _support_from_dict(data: Any) -> ProfileSupport:
    value = data if isinstance(data, dict) else {}
    tier = str(value.get("tier", "profile_template"))
    if tier not in {"known_good_acp", "experimental_acp", "profile_template", "cli_fallback"}:
        tier = "profile_template"
    return ProfileSupport(
        tier=tier,  # type: ignore[arg-type]
        notes=[str(item) for item in value.get("notes", [])],
    )
