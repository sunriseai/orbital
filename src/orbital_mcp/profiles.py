from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import HarnessConfig, HarnessProfile, ProfileCapabilities, ReadinessResult, TaskInput
from .models import to_jsonable


class ProfileSelectionError(ValueError):
    pass


class HarnessRegistry:
    def __init__(self, config: HarnessConfig):
        self.config = config
        self._profiles = {profile.id: profile for profile in config.profiles}

    def list_profiles(self) -> list[HarnessProfile]:
        return list(self.config.profiles)

    def get(self, profile_id: str) -> HarnessProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise ProfileSelectionError(f"unknown harness profile: {profile_id}") from exc

    def readiness(self, profile: HarnessProfile, workdir: Path | None = None) -> ReadinessResult:
        missing: list[str] = []
        if not profile.enabled:
            missing.append("profile disabled")
        if workdir is not None and not workdir.exists():
            missing.append(f"workdir does not exist: {workdir}")
        if profile.adapter in {"acp", "cli"}:
            if not profile.command:
                missing.append("missing command")
            elif shutil.which(profile.command[0]) is None and not Path(profile.command[0]).exists():
                missing.append(f"executable not found: {profile.command[0]}")
            elif (
                profile.adapter == "cli"
                and profile.runtime_family == "claude_code"
                and profile.auth_mode == "local_subscription"
            ):
                auth_missing = _claude_subscription_auth_missing(profile.command)
                if auth_missing:
                    missing.append(auth_missing)
        elif profile.adapter == "api":
            if not profile.enabled:
                missing.append("API profile must be explicitly enabled")
            if not os.environ.get("OPENAI_API_KEY") and profile.runtime_family == "codex":
                missing.append("OPENAI_API_KEY is not set")
        else:
            missing.append(f"unsupported adapter: {profile.adapter}")

        return ReadinessResult(
            profile_id=profile.id,
            ready=not missing,
            status="ready" if not missing else "not_ready",
            missing_prerequisites=missing,
        )

    def capabilities(
        self,
        profile: HarnessProfile,
        readiness: ReadinessResult | None = None,
    ) -> ProfileCapabilities:
        capability_names = set(profile.capabilities)
        return ProfileCapabilities(
            supports_dialogue="dialogue" in capability_names or profile.adapter in {"acp", "cli"},
            supports_permissions=("permissions" in capability_names or profile.adapter == "acp")
            and profile.permission_behavior != "none",
            supports_tool_events="tool_events" in capability_names or profile.adapter in {"acp", "cli"},
            supports_stop="stop" in capability_names or profile.adapter in {"acp", "cli"},
            supports_followup_messages=profile.adapter == "acp",
            subscription_auth_verified=(
                profile.auth_mode == "local_subscription"
                and (readiness.ready if readiness is not None else False)
            ),
        )

    def recommend(
        self,
        *,
        workdir: Path | None = None,
        task_tags: list[str] | None = None,
        required_capabilities: list[str] | None = None,
        disallowed_support_tiers: list[str] | None = None,
        locality: str | None = None,
        cost_preference: str | None = None,
        include_not_ready: bool = False,
    ) -> dict[str, Any]:
        requested_tags = {tag for tag in (task_tags or []) if tag}
        required = {cap for cap in (required_capabilities or []) if cap}
        disallowed_tiers = set(disallowed_support_tiers or [])
        recommendations: list[dict[str, Any]] = []
        for profile in self.list_profiles():
            readiness = self.readiness(profile, workdir)
            capabilities = self.capabilities(profile, readiness)
            capability_map = _capability_map(capabilities)
            profile_tags = set(profile.classification.task_tags)
            matched_tags = sorted(requested_tags & profile_tags)
            missing_tags = sorted(requested_tags - profile_tags)
            matched_capabilities = sorted(cap for cap in required if capability_map.get(cap) is True)
            missing_capabilities = sorted(cap for cap in required if capability_map.get(cap) is not True)
            caveats: list[str] = []
            if not readiness.ready:
                caveats.extend(readiness.missing_prerequisites)
            if profile.support.tier in disallowed_tiers:
                caveats.append(f"support tier disallowed: {profile.support.tier}")
            if profile.metered_api and not self.config.allow_api_fallback:
                caveats.append("metered API profile requires explicit opt-in")
            if missing_capabilities:
                caveats.append("missing required capabilities: " + ", ".join(missing_capabilities))
            if missing_tags:
                caveats.append("missing requested task tags: " + ", ".join(missing_tags))
            if locality and profile.classification.locality != locality:
                caveats.append(f"locality mismatch: {profile.classification.locality}")
            if cost_preference and profile.classification.cost_preference != cost_preference:
                caveats.append(f"cost preference mismatch: {profile.classification.cost_preference}")

            eligible = (
                profile.enabled
                and (readiness.ready or include_not_ready)
                and profile.support.tier not in disallowed_tiers
                and not missing_capabilities
            )
            if profile.metered_api and not self.config.allow_api_fallback:
                eligible = False
            if not include_not_ready and not readiness.ready:
                eligible = False

            score = _support_score(profile.support.tier)
            score += len(matched_tags) * 10
            score += len(matched_capabilities) * 8
            if locality and profile.classification.locality == locality:
                score += 5
            if cost_preference and profile.classification.cost_preference == cost_preference:
                score += 5
            if profile.metered_api:
                score -= 20
            if not readiness.ready:
                score -= 100
            if missing_tags:
                score -= len(missing_tags) * 3

            recommendations.append(
                {
                    "profile_id": profile.id,
                    "ready": readiness.ready,
                    "support": to_jsonable(profile.support),
                    "matched_task_tags": matched_tags,
                    "missing_task_tags": missing_tags,
                    "matched_capabilities": matched_capabilities,
                    "missing_capabilities": missing_capabilities,
                    "cost_posture": profile.cost_posture,
                    "locality": profile.classification.locality,
                    "score": score,
                    "eligible": eligible,
                    "reasons": _recommendation_reasons(profile, matched_tags, matched_capabilities),
                    "caveats": caveats,
                    "profile": to_jsonable(profile),
                    "readiness": to_jsonable(readiness),
                    "normalized_capabilities": to_jsonable(capabilities),
                }
            )
        recommendations.sort(key=lambda item: (-int(item["eligible"]), -int(item["score"]), str(item["profile_id"])))
        for idx, item in enumerate(recommendations, start=1):
            item["rank"] = idx
        return {"recommendations": recommendations}

    def select(
        self,
        workdir: Path,
        task: TaskInput | None = None,
        profile_id: str | None = None,
        runtime_family: str | None = None,
    ) -> tuple[HarnessProfile, ReadinessResult]:
        if profile_id:
            profile = self.get(profile_id)
            self._enforce_api_policy(profile, task, explicit=True)
            return profile, self.readiness(profile, workdir)

        candidates = self.list_profiles()
        if runtime_family:
            candidates = [profile for profile in candidates if profile.runtime_family == runtime_family]

        default = self._profiles.get(self.config.default_profile or "")
        ordered: list[HarnessProfile] = []
        if default and default in candidates:
            ordered.append(default)
        ordered.extend(profile for profile in candidates if profile not in ordered)

        local_ready: list[tuple[HarnessProfile, ReadinessResult]] = []
        api_ready: list[tuple[HarnessProfile, ReadinessResult]] = []
        first_not_ready: tuple[HarnessProfile, ReadinessResult] | None = None

        for profile in ordered:
            readiness = self.readiness(profile, workdir)
            if first_not_ready is None:
                first_not_ready = (profile, readiness)
            if not readiness.ready:
                continue
            if profile.metered_api:
                api_ready.append((profile, readiness))
            elif profile.auth_mode == "local_subscription":
                local_ready.append((profile, readiness))

        if local_ready:
            return local_ready[0]
        for profile, readiness in api_ready:
            self._enforce_api_policy(profile, task, explicit=False)
            return profile, readiness

        if first_not_ready:
            return first_not_ready
        raise ProfileSelectionError("no harness profiles configured")

    def _enforce_api_policy(self, profile: HarnessProfile, task: TaskInput | None, explicit: bool) -> None:
        if not profile.metered_api:
            return
        allowed = explicit or self.config.allow_api_fallback or bool(task and task.allow_metered_api)
        if not allowed:
            raise ProfileSelectionError(f"metered API profile is not allowed by policy: {profile.id}")


def _claude_subscription_auth_missing(command: list[str]) -> str | None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    try:
        result = subprocess.run(
            [*command, "auth", "status"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Claude Code auth check failed: {exc}"
    payload_text = (result.stdout or result.stderr).strip()
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return "Claude Code subscription auth check did not return JSON"
    if payload.get("loggedIn") and payload.get("authMethod") != "api_key":
        return None
    return "Claude Code local subscription auth is not available without ANTHROPIC_API_KEY"


def _capability_map(capabilities: ProfileCapabilities) -> dict[str, bool]:
    return {
        "dialogue": capabilities.supports_dialogue,
        "permissions": capabilities.supports_permissions,
        "tool_events": capabilities.supports_tool_events,
        "stop": capabilities.supports_stop,
        "followup_messages": capabilities.supports_followup_messages,
        "subscription_auth_verified": capabilities.subscription_auth_verified,
    }


def _support_score(tier: str) -> int:
    return {
        "known_good_acp": 40,
        "experimental_acp": 25,
        "cli_fallback": 10,
        "profile_template": 0,
    }.get(tier, 0)


def _recommendation_reasons(
    profile: HarnessProfile,
    matched_tags: list[str],
    matched_capabilities: list[str],
) -> list[str]:
    reasons = [f"support tier: {profile.support.tier}"]
    if matched_tags:
        reasons.append("matched task tags: " + ", ".join(matched_tags))
    if matched_capabilities:
        reasons.append("matched capabilities: " + ", ".join(matched_capabilities))
    if profile.classification.strengths:
        reasons.append("strengths: " + "; ".join(profile.classification.strengths[:2]))
    return reasons
