from pathlib import Path
from typing import Any

from . import __version__
from .config import load_config
from .errors import error_response, ok_response
from .guidance import primary_guidance, worker_safe_constraints
from .models import TaskInput, to_jsonable
from .profiles import HarnessRegistry
from .service import TaskRunService
from .store import RunStore


def build_service(base_dir: Path | str = ".") -> TaskRunService:
    base = Path(base_dir).resolve()
    config = load_config(base)
    registry = HarnessRegistry(config)
    store = RunStore(base / config.storage_root)
    store.recover_interrupted_runs()
    return TaskRunService(registry, store)


def create_mcp_server(base_dir: Path | str = ".") -> Any:
    from mcp.server.fastmcp import FastMCP

    service = build_service(base_dir)
    config = service.registry.config
    mcp = FastMCP("Orbital MCP")

    @mcp.tool()
    def get_server_info() -> dict[str, Any]:
        profiles = service.registry.list_profiles()
        return {
            "name": "orbital-mcp",
            "version": __version__,
            "adapter_protocol": {
                "acp_session_new": "cwd+mcpServers",
                "acp_prompt": "text-content-sequence",
                "acp_permission_result": "outcome.outcome=selected+optionId",
                "acp_updates": "nested-session-update-content-text",
                "acp_tool_updates": "tool_call+tool_call_update-dialogue-events",
                "acp_execute_policy": "records package-manager, network, and destructive shell commands for primary review; configurable policies can block",
                "claude_cli": "print-stream-json-dialogue-events",
            },
            "reporting_policy": {
                "passed_runs_require_expected_files": True,
                "expected_files_from": ["file-like allowed_paths with explicit create/exists task intent"],
                "delegation_sessions": "explicit session tools persist primary assessments and final verification",
                "delegation_report": "from session_id or inferred from stored runs by workdir, run_ids, and optional time bounds",
                "primary_safe_default": "run responses and digests omit raw dialogue by default; use get_debug_dialogue for explicit raw inspection",
                "failure_classification": "derived from server evidence and normalized across secondary harnesses",
                "token_reporting": "canonical local agent-log telemetry from Codex, Claude, and OpenCode when correlated by workspace and run window; adapter usage is diagnostic only",
                "model_reporting": "exact adapter model metadata when available; unknown otherwise",
                "stop_safety": "get_run_liveness recommendation should be checked before stop_task_run for suspected inactivity",
            },
            "auth_policy": {
                "local_subscription_profiles_scrub_api_key_env": [
                    "OPENAI_API_KEY",
                    "CODEX_API_KEY",
                    "ANTHROPIC_API_KEY",
                ],
                "api_profiles_require_explicit_enablement": True,
            },
            "enabled_adapters": sorted({profile.adapter for profile in profiles if profile.enabled}),
            "runtime_paths": {profile.id: profile.command for profile in profiles},
            "configured_storage_root": str(service.store.root),
            "detected_harness_availability": [
                {
                    **to_jsonable(service.registry.readiness(profile)),
                    "capabilities": to_jsonable(
                        service.registry.capabilities(profile, service.registry.readiness(profile))
                    ),
                }
                for profile in profiles
            ],
        }

    @mcp.tool()
    def list_harness_profiles(workdir: str | None = None) -> dict[str, Any]:
        root = Path(workdir).resolve() if workdir else None
        return {
            "profiles": [
                {
                    **to_jsonable(profile),
                    "readiness": to_jsonable(readiness := service.registry.readiness(profile, root)),
                    "normalized_capabilities": to_jsonable(service.registry.capabilities(profile, readiness)),
                }
                for profile in service.registry.list_profiles()
            ]
        }

    @mcp.tool()
    def get_harness_profile(profile_id: str, workdir: str | None = None) -> dict[str, Any]:
        try:
            root = Path(workdir).resolve() if workdir else None
            profile = service.registry.get(profile_id)
            readiness = service.registry.readiness(profile, root)
            return ok_response(
                {
                    "profile": to_jsonable(profile),
                    "readiness": to_jsonable(readiness),
                    "normalized_capabilities": to_jsonable(service.registry.capabilities(profile, readiness)),
                }
            )
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def check_harness_profile(profile_id: str, workdir: str | None = None) -> dict[str, Any]:
        try:
            root = Path(workdir).resolve() if workdir else None
            profile = service.registry.get(profile_id)
            readiness = service.registry.readiness(profile, root)
            capabilities = service.registry.capabilities(profile, readiness)
            return ok_response(
                {
                    "passed": readiness.ready,
                    "profile_id": profile.id,
                    "support": to_jsonable(profile.support),
                    "readiness": to_jsonable(readiness),
                    "normalized_capabilities": to_jsonable(capabilities),
                    "auth_mode": profile.auth_mode,
                    "cost_posture": profile.cost_posture,
                    "metered_api": profile.metered_api,
                }
            )
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def recommend_harness_profiles(
        workdir: str | None = None,
        task_tags: list[str] | None = None,
        required_capabilities: list[str] | None = None,
        disallowed_support_tiers: list[str] | None = None,
        locality: str | None = None,
        cost_preference: str | None = None,
        include_not_ready: bool = False,
    ) -> dict[str, Any]:
        root = Path(workdir).resolve() if workdir else None
        return service.registry.recommend(
            workdir=root,
            task_tags=task_tags,
            required_capabilities=required_capabilities,
            disallowed_support_tiers=disallowed_support_tiers,
            locality=locality,
            cost_preference=cost_preference,
            include_not_ready=include_not_ready,
        )

    @mcp.tool()
    def preflight_task_run(
        workdir: str,
        profile_id: str | None = None,
        task_constraints: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            task = TaskInput(title="preflight", objective="preflight", constraints=task_constraints or [])
            return ok_response(service.preflight(Path(workdir).resolve(), task=task, profile_id=profile_id))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    async def start_task_run(
        workdir: str,
        task_title: str,
        task_objective: str,
        harness_profile_id: str | None = None,
        allowed_paths: list[str] | None = None,
        forbidden_paths: list[str] | None = None,
        constraints: list[str] | None = None,
        acceptance_hints: list[str] | None = None,
        checks: list[str] | None = None,
        rules: list[str] | None = None,
        runtime_mode: str | None = None,
        allow_metered_api: bool = False,
    ) -> dict[str, Any]:
        task = TaskInput(
            title=task_title,
            objective=task_objective,
            allowed_paths=allowed_paths or [],
            forbidden_paths=forbidden_paths or [],
            constraints=constraints or [],
            acceptance_hints=acceptance_hints or [],
            checks=checks or [],
            rules=rules or [],
            runtime_mode=runtime_mode,
            allow_metered_api=allow_metered_api,
        )
        try:
            return ok_response(await service.start_task_run(Path(workdir).resolve(), task, profile_id=harness_profile_id))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    async def send_task_message(run_id: str, message: str) -> dict[str, Any]:
        try:
            return ok_response(await service.send_task_message(run_id, message))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def get_task_run(run_id: str) -> dict[str, Any]:
        try:
            return ok_response(service.get_task_run(run_id))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def list_task_runs() -> dict[str, Any]:
        try:
            return ok_response(service.list_task_runs())
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def get_dialogue(run_id: str, since_event_id: str | None = None, max_events: int = 100) -> dict[str, Any]:
        try:
            return ok_response(service.get_dialogue(run_id, since_event_id, max_events))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def get_debug_dialogue(
        run_id: str,
        since_event_id: str | None = None,
        max_events: int = 100,
        include_raw: bool = False,
        include_agent_chunks: bool = False,
        event_kinds: list[str] | None = None,
        max_chars: int = 20_000,
    ) -> dict[str, Any]:
        try:
            return ok_response(
                service.get_dialogue(
                    run_id,
                    since_event_id,
                    max_events,
                    include_raw=include_raw,
                    include_agent_chunks=include_agent_chunks,
                    event_kinds=event_kinds,
                    max_chars=max_chars,
                )
            )
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def get_run_summary(run_id: str, max_events: int = 100) -> dict[str, Any]:
        try:
            return ok_response(service.get_run_summary(run_id, max_events))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def get_run_log_tail(run_id: str, name: str, max_bytes: int = 65536) -> dict[str, Any]:
        try:
            return ok_response(service.get_run_log_tail(run_id, name, max_bytes=max_bytes))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def get_storage_diagnostics(run_id: str) -> dict[str, Any]:
        try:
            return ok_response(service.get_storage_diagnostics(run_id))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def get_run_status_digest(run_id: str) -> dict[str, Any]:
        try:
            return ok_response(service.get_run_status_digest(run_id))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def get_run_policy_verdict(run_id: str) -> dict[str, Any]:
        try:
            return ok_response(service.get_run_policy_verdict(run_id))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def get_run_liveness(run_id: str, model_log_path: str | None = None) -> dict[str, Any]:
        try:
            return ok_response(service.get_run_liveness(run_id, model_log_path=model_log_path))
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    def get_primary_guidance(host_harness: str | None = None) -> dict[str, Any]:
        return primary_guidance(host_harness)

    @mcp.tool()
    def get_worker_safe_constraints() -> dict[str, Any]:
        return worker_safe_constraints()

    @mcp.tool()
    def get_delegation_report(
        session_id: str | None = None,
        workdir: str | None = None,
        run_ids: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        objective: str | None = None,
        accepted_run_ids: list[str] | None = None,
        rejected_run_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        resolved_workdir = str(Path(workdir).resolve()) if workdir else None
        return service.get_delegation_report(
            session_id=session_id,
            workdir=resolved_workdir,
            run_ids=run_ids,
            since=since,
            until=until,
            objective=objective,
            accepted_run_ids=accepted_run_ids,
            rejected_run_ids=rejected_run_ids,
        )

    @mcp.tool()
    def start_delegation_session(
        workdir: str,
        objective: str,
        preferred_profile_id: str | None = None,
        primary_harness: str | None = None,
        max_runs: int | None = None,
    ) -> dict[str, Any]:
        return service.start_delegation_session(
            Path(workdir).resolve(),
            objective,
            preferred_profile_id=preferred_profile_id,
            primary_harness=primary_harness,
            max_runs=max_runs,
        )

    @mcp.tool()
    def create_requirement(
        session_id: str,
        requirement_id: str,
        statement: str,
        proof_needed: str,
    ) -> dict[str, Any]:
        return service.create_requirement(session_id, requirement_id, statement, proof_needed)

    @mcp.tool()
    def update_requirement_status(
        session_id: str,
        requirement_id: str,
        status: str,
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        return service.update_requirement_status(session_id, requirement_id, status, evidence=evidence)

    @mcp.tool()
    def create_delegation_ticket(
        session_id: str,
        ticket_id: str,
        title: str,
        objective: str,
        requirement_ids: list[str] | None = None,
        allowed_paths: list[str] | None = None,
        forbidden_paths: list[str] | None = None,
        checks: list[str] | None = None,
        acceptance_hints: list[str] | None = None,
        rules: list[str] | None = None,
    ) -> dict[str, Any]:
        return service.create_delegation_ticket(
            session_id,
            ticket_id,
            title,
            objective,
            requirement_ids=requirement_ids,
            allowed_paths=allowed_paths,
            forbidden_paths=forbidden_paths,
            checks=checks,
            acceptance_hints=acceptance_hints,
            rules=rules,
        )

    @mcp.tool()
    async def start_ticket_run(
        session_id: str,
        ticket_id: str,
        harness_profile_id: str | None = None,
    ) -> dict[str, Any]:
        return await service.start_ticket_run(session_id, ticket_id, harness_profile_id=harness_profile_id)

    @mcp.tool()
    def record_delegation_run_assessment(
        session_id: str,
        run_id: str,
        decision: str,
        rationale: str,
        inspected_files: list[str] | None = None,
        verification_commands: list[str] | None = None,
        repair_prompt: str | None = None,
    ) -> dict[str, Any]:
        return service.record_delegation_run_assessment(
            session_id,
            run_id,
            decision,
            rationale,
            inspected_files=inspected_files,
            verification_commands=verification_commands,
            repair_prompt=repair_prompt,
        )

    @mcp.tool()
    def record_attempt_review(
        session_id: str,
        ticket_id: str,
        run_id: str,
        decision: str,
        rationale: str,
        inspected_files: list[str] | None = None,
        verification_commands: list[str] | None = None,
        repair_prompt: str | None = None,
    ) -> dict[str, Any]:
        return service.record_attempt_review(
            session_id,
            ticket_id,
            run_id,
            decision,
            rationale,
            inspected_files=inspected_files,
            verification_commands=verification_commands,
            repair_prompt=repair_prompt,
        )

    @mcp.tool()
    def create_repair_ticket_from_run(
        session_id: str,
        ticket_id: str,
        run_id: str,
        repair_ticket_id: str | None = None,
    ) -> dict[str, Any]:
        return service.create_repair_ticket_from_run(session_id, ticket_id, run_id, repair_ticket_id)

    @mcp.tool()
    def get_delegation_session(session_id: str) -> dict[str, Any]:
        return service.get_delegation_session(session_id)

    @mcp.tool()
    def get_next_recommended_action(session_id: str) -> dict[str, Any]:
        return service.get_next_recommended_action(session_id)

    @mcp.tool()
    def finish_delegation_session(
        session_id: str,
        final_status: str,
        final_summary: str | None = None,
        final_verification: str | None = None,
        override_reason: str | None = None,
    ) -> dict[str, Any]:
        return service.finish_delegation_session(
            session_id,
            final_status,
            final_summary=final_summary,
            final_verification=final_verification,
            override_reason=override_reason,
        )

    @mcp.tool()
    async def run_task_and_wait(
        workdir: str,
        task_title: str,
        task_objective: str,
        harness_profile_id: str | None = None,
        allowed_paths: list[str] | None = None,
        forbidden_paths: list[str] | None = None,
        constraints: list[str] | None = None,
        acceptance_hints: list[str] | None = None,
        checks: list[str] | None = None,
        rules: list[str] | None = None,
        runtime_mode: str | None = None,
        allow_metered_api: bool = False,
        timeout_seconds: float = 120,
        poll_interval_ms: int = 250,
        max_events: int = 100,
    ) -> dict[str, Any]:
        task = TaskInput(
            title=task_title,
            objective=task_objective,
            allowed_paths=allowed_paths or [],
            forbidden_paths=forbidden_paths or [],
            constraints=constraints or [],
            acceptance_hints=acceptance_hints or [],
            checks=checks or [],
            rules=rules or [],
            runtime_mode=runtime_mode,
            allow_metered_api=allow_metered_api,
        )
        return await service.run_task_and_wait(
            Path(workdir).resolve(),
            task,
            profile_id=harness_profile_id,
            timeout_seconds=timeout_seconds,
            poll_interval_ms=poll_interval_ms,
            max_events=max_events,
        )

    @mcp.tool()
    async def resolve_permission(
        run_id: str,
        permission_id: str,
        decision: str,
        option_id: str | None = None,
        rationale: str | None = None,
        adapter_request_id: str | None = None,
        deciding_primary: str | None = None,
    ) -> dict[str, Any]:
        try:
            return ok_response(
                await service.resolve_permission(
                    run_id,
                    permission_id,
                    decision,
                    option_id,
                    rationale,
                    adapter_request_id,
                    deciding_primary,
                )
            )
        except Exception as exc:
            return error_response(exc)

    @mcp.tool()
    async def stop_task_run(run_id: str) -> dict[str, Any]:
        try:
            return ok_response(await service.stop_task_run(run_id))
        except Exception as exc:
            return error_response(exc)

    return mcp


def run_stdio(base_dir: Path | str = ".") -> None:
    create_mcp_server(base_dir).run()
