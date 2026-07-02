# Orbital Implementation TODO

This checklist turns the product, technical, and roadmap specs into executable work. Each item should be small enough to become an issue, PR, or delegated agent task.

## 1. Project Identity And Rename

- [ ] Choose final package, executable, config file, storage directory, and MCP server display names.
- [ ] Decide whether existing `.prole-harness/` data is unsupported, read-only reference material, or migrated intentionally.
- [ ] Rename user-facing server identity to Orbital.
- [ ] Remove benchmark/playbook-first positioning from public docs and keep MCP-to-ACP delegation as the product center.
- [ ] Update setup, doctor, smoke, and MCP config command names around Orbital naming.

Acceptance criteria:

- New users see only Orbital naming in first-run docs and MCP server identity.
- Any Prole compatibility behavior is explicitly documented.
- Public positioning does not imply Orbital is an SDLC platform.

Tests:

- Regression test for docs naming and links.
- CLI/help snapshot or equivalent test once commands exist.

## 2. Config, Schema, And Storage Foundation

- [ ] Define `orbital.config.json` schema with profile classification, support tier, capabilities, auth mode, cost posture, env, and policy fields.
- [ ] Define `.orbital/` storage layout with runs and sessions.
- [ ] Add schema versions to config, run records, session records, summaries, status digests, policy verdicts, and reports.
- [ ] Implement atomic writes for `run.json`, `session.json`, and final reports.
- [ ] Keep event streams append-only for dialogue, permissions, telemetry, stderr, and transcripts.
- [ ] Add lock strategy for concurrent writes to the same run or session.
- [ ] Add bounded reads for debug dialogue, transcripts, stderr tails, and report generation.
- [ ] Add storage diagnostics for malformed JSON, malformed JSONL lines, partial writes, unsupported schema versions, and missing artifacts.
- [ ] Define startup recovery for non-terminal runs, interrupted processes, and partial logs.

Acceptance criteria:

- Interrupted or recovered runs receive deterministic `interrupted` or `unknown` status with diagnostics.
- Storage recovery never deletes raw logs or overwrites final reports without recording a recovery event.
- Pending permissions from a previous server process remain visible as evidence.

Tests:

- Unit tests for schema loading and defaults.
- Unit tests for atomic JSON writes and append-only JSONL.
- Regression tests for malformed JSONL, partial final reports, path-traversal IDs, and bounded log reads.
- Recovery tests for active runs, interrupted runs, and pending permissions after restart.

## 3. Core MCP Tool Contracts

- [ ] Define stable request/response schemas for `get_server_info`, `list_harness_profiles`, `get_harness_profile`, `check_harness_profile`, and `recommend_harness_profiles`.
- [ ] Define stable request/response schemas for `preflight_task_run`, `start_task_run`, `send_task_message`, `get_run_status_digest`, `get_run_summary`, `get_debug_dialogue`, `resolve_permission`, `get_run_liveness`, `stop_task_run`, and `list_task_runs`.
- [ ] Add stable error objects with `code`, `message`, optional `details`, retryability, and user-action indicators.
- [ ] Normalize run statuses to `created`, `launching`, `running`, `waiting_for_permission`, `stopping`, `completed`, `failed`, `blocked`, `cancelled`, `interrupted`, and `unknown`.
- [ ] Preserve adapter-native statuses only in debug metadata.
- [ ] Keep raw events omitted from primary-safe tools by default.
- [ ] Add explicit raw/debug access through bounded `get_debug_dialogue`.

Acceptance criteria:

- Primary harnesses can operate from status digests and summaries without raw transcript reads.
- Breaking response changes require schema versioning or feature flags.
- Run creation returns a durable run ID immediately after launch attempt recording.

Tests:

- Contract tests for every MCP request/response shape.
- Regression tests that primary-safe tools omit raw events and agent chunks by default.
- Regression tests for debug dialogue filtering, event limits, and character limits.

## 4. Profiles, Classification, And Recommendation

- [ ] Replace default-first profile routing with explicit profile selection or classification-based recommendation.
- [ ] Add canonical `classification.task_tags`, `strengths`, `limits`, `max_recommended_scope`, `cost_preference`, and `locality` fields.
- [ ] Add support tiers: `known_good_acp`, `experimental_acp`, `profile_template`, and `cli_fallback`.
- [ ] Distinguish readiness, support tier, and capability gaps in all profile outputs.
- [ ] Implement `recommend_harness_profiles` with deterministic ranking, reasons, caveats, matched tags, missing tags, matched capabilities, and missing capabilities.
- [ ] Add first-class profile templates for OpenCode, Pi, Codex, Claude Code CLI, and Claude Agent SDK ACP with honest support tiers.
- [ ] Replace any unverified local-subscription `claude_code_acp_local` profile with `claude_code_cli_local` plus disabled or explicit API-backed `claude_agent_acp_api`.
- [ ] Document Claude ACP as `claude-agent-acp` through the Claude Agent SDK with `ANTHROPIC_API_KEY`, not as a Claude Code CLI subscription path.
- [ ] Record current smoke evidence in profile metadata or docs: Codex local ACP manual smoke passed, OpenCode local ACP manual smoke passed with OpenCode `1.17.11` and ACP `protocolVersion=1`.
- [ ] Keep smoke-verified profiles at `experimental_acp` until adapter conformance fixtures justify `known_good_acp`.
- [ ] Keep API-backed profiles disabled or explicit by default.
- [ ] Prevent hidden profile switching inside a handoff session.

Acceptance criteria:

- A ready profile is not automatically presented as known-good support.
- The primary harness chooses the final profile assignment.
- Recommendation output is deterministic for identical config and inputs.
- Claude Code CLI and Claude Agent SDK ACP appear as separate profiles with different auth modes, cost postures, and support tiers.
- OpenCode smoke evidence records the command, OpenCode version, ACP protocol version, selected profile, changed files, warnings, and telemetry availability.

Tests:

- Unit tests for classification schema parsing.
- Unit tests for recommendation ranking and tie-breaking.
- Regression tests for support-tier caveats and missing capability reporting.
- Regression tests that metered/API profiles are never selected implicitly.
- Regression tests that `claude_agent_acp_api` is explicit opt-in and `claude_code_cli_local` remains the local/subscription Claude fallback.

## 5. ACP Adapters And Compatibility

- [ ] Port or recreate the fake ACP harness strategy from Prole Harness MCP.
- [ ] Define adapter conformance fixtures for initialization, session creation, prompt submission, streamed text, tool events, permissions, stderr, stop/cancel, exact usage, exact model metadata, and malformed events.
- [ ] Normalize ACP event shapes across supported harnesses into one event vocabulary.
- [ ] Keep raw protocol payloads in debug logs, not primary-safe summaries.
- [ ] Label no profile `known_good_acp` without conformance fixture coverage and a smoke run.
- [ ] Keep CLI compatibility only where ACP is unavailable or unreliable.
- [ ] Treat Claude Code CLI as the local/subscription Claude path until a local-subscription ACP command is verified.
- [ ] Treat Claude Agent SDK ACP as API-key/metered via `claude-agent-acp`.
- [ ] Report CLI fallback capability gaps explicitly, especially permissions, follow-up messages, stop behavior, tool events, and telemetry.

Acceptance criteria:

- Primary harnesses do not need runtime-specific ACP knowledge.
- Adapter capability gaps are visible before a run starts.
- Known-good support claims are backed by fixtures and smoke evidence.

Tests:

- Fake ACP integration tests.
- Fixture tests for each supported runtime family.
- Regression tests for permission option matching and malformed ACP payloads.
- Smoke tests for each profile that can be exercised locally.
- Smoke tests should cover local Codex ACP and OpenCode ACP separately from API-backed Claude Agent ACP.

## 6. Run Lifecycle, Evidence, And File Attribution

- [ ] Implement worker-safe startup prompt construction from task fields only.
- [ ] Ensure primary-only guidance, retry strategy, scoring rubrics, profile-selection reasoning, and session report expectations never enter worker prompts.
- [ ] Capture normalized dialogue, tool timeline, permissions, stderr, transcript references, check evidence, warning details, and failure classifications.
- [ ] Implement deterministic policy verdicts: `accept_candidate`, `needs_repair`, `reject`, `blocked`, and `requires_primary_review`.
- [ ] Generate repair seeds from server-observed gaps while preserving task scope, checks, and acceptance hints.
- [ ] Add fallback file attribution until `../ngitd-core` integration exists.
- [ ] Distinguish pre-existing dirty files, files changed during run, possibly concurrent changes, untracked files, deletes, renames, generated artifacts, and unknown attribution.
- [ ] Add attribution confidence values: `high`, `medium`, `low`, and `unknown`.

Acceptance criteria:

- Worker prose is context, never proof.
- Passed runs with no changes, no completed tools, missing checks, failed checks, or forbidden path changes produce warnings and failure classifications.
- File attribution is explicit about uncertainty.

Tests:

- Unit tests for startup prompt visibility boundaries.
- Regression tests for no-op passes, missing checks, failed checks, policy violations, forbidden path changes, and acceptance-output failures.
- File attribution tests for tracked changes, untracked files, generated artifacts, deleted files, and non-Git workdirs.

## 7. Permissions And Capability-Based Policy

- [ ] Normalize permission requests into stable records with run ID, adapter request ID, risk, paths, options, raw reference, decision, and rationale.
- [ ] Prefer explicit adapter option IDs for approval/denial.
- [ ] Infer approve/deny options only when exactly one option matches.
- [ ] Return stable errors for ambiguous options, unknown permissions, resolved permissions, and post-restart non-resolvable permissions.
- [ ] Replace blanket command denial with configurable policy behavior.
- [ ] Report active policy level: `prompt_only`, `adapter_mediated`, `process_observed`, or `sandbox_enforced`.
- [ ] Allow primary-mediated approval for risky actions when the adapter can pause.
- [ ] Record whether a violation was prevented, mediated, or only observed after the fact.

Acceptance criteria:

- Orbital does not imply sandboxing unless sandbox enforcement exists.
- The primary harness can approve reasonable risky actions with rationale when the adapter supports mediation.
- Pending permissions after restart remain visible but return `permission_not_resolvable_after_restart` unless reattachment is supported.

Tests:

- Unit tests for permission normalization and option selection.
- Regression tests for post-restart pending permissions.
- Policy tests for package install, network command, destructive command, scope expansion, explicit approval, and observed-only violations.

## 8. Handoff Sessions

- [ ] Keep handoff/session tools in V1.
- [ ] Use generic delegation entities: session, handoff item, task, attempt, review, repair, and report.
- [ ] If API names keep `ticket`, document it as a bounded local task record, not an issue tracker object.
- [ ] Implement session start, item creation, task creation, task attempt start, primary review recording, next-action recommendation, repair task creation, session finish, and handoff report retrieval.
- [ ] Preserve session warnings for profile mismatch, path-scope drift, missing review evidence, unsatisfied handoff items, unreviewed attempts, pending permissions on finish, unattributed files, and stopping without liveness.
- [ ] Keep final acceptance owned by the primary harness.
- [ ] Preserve exact primary, secondary, combined, and external model-log telemetry distinctions in session reports.

Acceptance criteria:

- A primary harness can manage a multi-run loop without reconstructing state from prompts.
- Repair tasks can be generated from server evidence without raw transcript reads.
- Session warnings inform primary review without automatically deciding acceptance.

Tests:

- Structured workflow tests for session, item, task, attempt, review, repair, finish, and report.
- Regression tests for profile drift, path-scope warnings, missing review evidence, unreviewed attempts, and unsatisfied handoff items.
- Tests for primary token usage validation and report aggregation.

## 9. Liveness, Telemetry, And Reports

- [ ] Implement liveness from run status, latest event time, pending permission, pending tool, process state, and optional model-log activity.
- [ ] Require primary harnesses to check liveness before stopping quiet runs.
- [ ] Record whether a stop had a recent stop-allowed liveness recommendation.
- [ ] Attempt cooperative adapter cancellation before process termination.
- [ ] Keep secondary adapter telemetry, primary-reported telemetry, and external model-log telemetry separate.
- [ ] Combine token totals only when primary and secondary totals are both exact.
- [ ] Keep external model-log telemetry unattributed unless run-correlation metadata exists.
- [ ] Generate handoff reports with timing, profile mix, runs, evidence, attribution, warnings, and token accounting.

Acceptance criteria:

- Quiet active runs are not classified as safe to stop solely because Orbital has no recent event.
- Model-log telemetry never contaminates primary/secondary totals without correlation.
- Reports can be useful even with unknown telemetry.

Tests:

- Liveness tests for active server event, active model log, waiting permission, quiet short, suspect stalled, stop safe, terminal, and unknown states.
- Stop tests for cooperative cancellation, process termination, and stop-without-liveness warnings.
- Telemetry tests for exact secondary, exact primary, combined known, combined unknown, and model-log unattributed cases.

## 10. Open Source Readiness

- [ ] Write public README focused on install, MCP connection, profile configuration, first smoke run, and troubleshooting.
- [ ] Write host contract documentation that separates prompt-driven worker behavior from server-driven evidence.
- [ ] Write contributor guide for adding adapters and profile templates.
- [ ] Add example configs for OpenCode, Pi, Codex, and Claude Code.
- [ ] Split Claude examples into local Claude Code CLI fallback and API-backed Claude Agent SDK ACP.
- [ ] Document support tiers, capability gaps, policy levels, recovery behavior, and primary-safe versus debug surfaces.
- [ ] Add release checklist.
- [ ] Ensure the full test suite can run without private credentials by using fake harnesses and optional smoke tests.

Acceptance criteria:

- A contributor can add a profile template or adapter fixture without reading the whole codebase.
- A user can diagnose setup failures without internal support.
- Public docs are honest about experimental and fallback support.

Tests:

- Docs regression tests for required sections and public-contract claims.
- Example config validation tests.
- Release checklist smoke test once packaging exists.

## 11. CI-Safe Validation Suites

- [ ] Treat deterministic unit/regression tests and fake-harness integration tests as first-class CI gates.
- [ ] Ensure default validation runs unattended with no clicks, browser interaction, private credentials, network dependency, real model calls, or installed real harnesses.
- [ ] Keep optional real-harness smoke experiments outside the default suite and gated by explicit environment variables.
- [ ] Add deterministic tests for config/schema defaults, support tiers, profile classification, disabled profiles, and metered profile opt-in.
- [ ] Add deterministic tests for profile recommendation determinism, tie-breaking, caveats, missing capabilities, and explicit selection behavior.
- [ ] Add deterministic tests for storage invariants: atomic JSON writes, append-only JSONL, bounded reads, malformed logs, partial writes, path traversal rejection, and startup recovery.
- [ ] Add deterministic MCP/service contract tests for primary-safe responses, debug responses, stable errors, schema versions, and canonical statuses.
- [ ] Add deterministic tests for permission normalization, policy verdicts, restart visibility, and approval/denial option selection.
- [ ] Add deterministic tests for run evidence, startup prompt boundaries, no-op pass warnings, requested checks, path policy, attribution confidence, liveness, telemetry, reports, and handoff/session state transitions.
- [ ] Add fake ACP scenarios for happy-path runs, streamed text, tool events, stderr, exact usage, exact model metadata, permission approval, permission denial, malformed stdout, failed results, hung workers, failed checks, forbidden commands, forbidden path writes, outside-allowed-path writes, stop behavior, and session repair workflows.
- [ ] Add a test-only fake profile smoke path so `orbital_mcp.smoke` can be validated unattended from a local config fixture.
- [ ] Keep fake-harness tests limited to local fixture processes, temporary workdirs, and `.orbital` stores that are cleaned after each test.
- [ ] Add MCP contract tests for tool response envelopes, `ok_response` and `error_response` shape, primary-safe defaults, debug access flags, schema versions, and canonical status fields.
- [ ] Add fake ACP failure-mode tests for non-zero worker exit, JSON-RPC error responses, ambiguous permission options, follow-up messages through `send_task_message`, and cooperative cancel versus forced termination evidence.
- [ ] Add storage durability tests for malformed or partial final reports, append-only permission latest-state reads, and session warning persistence across service restart.
- [ ] Add package/CLI validation that distinguishes source-tree execution from installed-package execution and records any packaging gap explicitly.
- [ ] Add default MCP stdio transport validation for tool listing, profile checks, fake task execution, primary-safe dialogue, and debug dialogue.
- [ ] Add optional installed-package validation gated by `ORBITAL_RUN_PACKAGING_SMOKE=1`.
- [ ] Add optional real-harness validation gated by `ORBITAL_RUN_REAL_HARNESS_SMOKE=1` and selected profile IDs.
- [ ] Keep default optional real-harness validation focused on local/subscription ACP profiles that do not require API keys.
- [ ] Add a separate API-backed Claude Agent ACP smoke path gated by explicit profile selection and `ANTHROPIC_API_KEY`.

Acceptance criteria:

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` exercises the default deterministic and fake-harness validation suites without human intervention.
- The default suite validates real MCP stdio transport using only the local fake harness.
- `ORBITAL_RUN_PACKAGING_SMOKE=1` validates console scripts and fake smoke behavior from an installed package in a temporary virtualenv.
- Fake-harness tests use only local fixture processes and temporary workdirs.
- Validation leaves no `.tmp-test-*`, `.orbital`, `__pycache__`, or `.pyc` artifacts behind in the repository tree.
- No default test requires browser clicks, network access, private credentials, installed real harnesses, or model/API access.
- Optional real-harness smoke coverage is explicitly separate from the default suite and skipped unless enabled by environment variables.
- API-backed real-harness smoke coverage is never implied by local/subscription smoke commands.

Tests:

- Docs regression tests for this CI-safe validation section and unattended-suite claims.
- Deterministic unit/regression tests for config, profiles, storage, contracts, permissions, policy, evidence, attribution, liveness, telemetry, reports, and sessions.
- Fake ACP integration tests for success, permissions, protocol robustness, failure modes, liveness/stop behavior, path policy, checks, smoke CLI, and session repair workflows.
- MCP contract tests for stable success and error envelopes.
- Storage durability regression tests for append-only latest-state semantics and malformed report handling.
- MCP transport smoke tests for actual stdio tool wiring.
- Optional packaging and real-harness smoke tests with explicit environment-variable gates.

## Claude Profile Alignment Workplan

1. Replace the runtime profile template named `claude_code_acp_local` with `claude_agent_acp_api`.
2. Configure `claude_agent_acp_api` as `adapter=acp`, `runtime_family=claude_agent`, `command=["claude-agent-acp"]`, `auth_mode=api_key`, `cost_posture=metered_api`, and disabled or explicit opt-in by default.
3. Keep `claude_code_cli_local` as `adapter=cli`, `runtime_family=claude_code`, `command=["claude"]`, `auth_mode=local_subscription`, `cost_posture=subscription_preferred`, and `support.tier=cli_fallback`.
4. Update readiness diagnostics so `claude_agent_acp_api` checks for Node >= 22, `claude-agent-acp`, and `ANTHROPIC_API_KEY`, while `claude_code_cli_local` checks for `claude`.
5. Update profile recommendation rules so the metered Claude Agent ACP profile is never selected implicitly.
6. Add a Claude Agent ACP manual smoke script only after `claude_agent_acp_api` exists and readiness diagnostics can distinguish missing Node, missing `claude-agent-acp`, and missing `ANTHROPIC_API_KEY`; keep Codex/OpenCode as the only active local ACP manual scripts until then.
7. Add or update regression tests for profile defaults, readiness diagnostics, metered opt-in, recommendation caveats, and manual smoke command naming.
8. Run deterministic suite, packaging smoke, and local Codex/OpenCode manual smoke now; add explicit Claude Agent ACP manual smoke later only when API credentials are intentionally provided and the profile is implemented.

## Deferred

- Hosted or multi-user service.
- Hard sandboxing before an actual sandbox or container mode exists.
- Automatic product acceptance.
- Benchmark scoring as a first-class product feature.
- SDLC-specific issue, branch, PR, CI, release, sprint, epic, owner, or team policy layers.
