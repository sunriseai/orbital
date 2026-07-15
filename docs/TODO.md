# Orbital Implementation TODO

This checklist turns the product, technical, and roadmap specs into executable work. Each item should be small enough to become an issue, PR, or delegated agent task.

## Current Baseline

Implemented and currently validated:

- Root `README.md` contains the first-run get-started path, profile setup model, manual smoke script pointers, Claude Code CLI versus Claude Agent SDK ACP distinction, and the documented workflow for adding another ACP harness such as Pi.
- Runtime profile templates separate `claude_code_cli_local` as the local/subscription Claude CLI fallback from `claude_agent_acp_api` as the explicit API-key-backed Claude Agent SDK ACP path.
- Codex now has two explicit local ACP profiles: `codex_acp_local` for the legacy Zed `codex-acp` command and `codex_acp_official` for the maintained `@agentclientprotocol/codex-acp` app-server adapter via `npx`.
- `claude_agent_acp_api` is disabled by default, uses `claude-agent-acp`, requires `ANTHROPIC_API_KEY`, and has readiness diagnostics for the command, API key, and Node >= 22.
- Default deterministic tests and fake ACP integration tests run unattended with no clicks, private credentials, network dependency, installed real harnesses, or real model calls.
- The fake ACP harness covers successful runs, streamed text, tool events, stderr capture, exact usage, exact model metadata, permission approval and denial, malformed stdout, JSON-RPC errors, non-zero exits, failed checks, path policy evidence, follow-up messages, stop behavior, smoke CLI validation, and handoff/session repair workflows.
- MCP stdio transport validation exercises tool listing, profile checks, fake task execution, primary-safe dialogue, and debug dialogue against the fake profile.
- Optional packaging validation is gated by `ORBITAL_RUN_PACKAGING_SMOKE=1`.
- Optional real-harness validation is gated by `ORBITAL_RUN_REAL_HARNESS_SMOKE=1`.
- Manual local ACP smoke currently covers Codex and OpenCode as separate scripts under `tests/manual`; OpenCode smoke evidence recorded OpenCode `1.17.13` and ACP `protocolVersion=1`.
- Canonical token telemetry is implemented for the practical V1 targets: Codex rollout JSONL under `~/.codex/sessions/**/rollout-*.jsonl` and OpenCode SQLite under `~/.local/share/opencode/opencode.db`. Manual Codex and OpenCode token probes use isolated token workspaces and require exactly one correlated external agent-log record.
- Initial evidence-gap controls are implemented in primary-safe run outputs: `evidence_status`, `evidence_score`, grouped `evidence_groups`, stable requested-check warning names, and `worker_claim_without_evidence` for prose-only completions.
- Initial ACP conformance foundations are implemented: transcript parsing, expectation-based conformance reports, fixture replay, fake ACP conformance checks, fake failure fixtures for malformed/unknown/stderr/stop/partial-result behavior, scrubbed Codex/OpenCode transcript excerpts, OpenCode ask-config multi-permission round-trip coverage, OpenCode permission failure-mode fixtures, capability matrix assertions, and deterministic missing-feature reporting.
- ACP conformance reports now expose both backward-compatible boolean `capabilities` and a `feature_states` matrix with `observed`, `missing`, `not_applicable`, and `capability_gap` values. Bounded `raw_refs` preserve malformed payload, unknown payload, stderr, and capability-gap locations for debug inspection.
- The Phase 3 conformance matrix now includes synthetic/scrubbed coverage for OpenCode ambiguous permission options, mixed allow/deny multi-request permissions, stop/cancel, stderr failure, partial terminal result behavior, and official Codex stop/cancel, stderr/guardian failure, malformed/unknown payload handling, permission capability gaps, model metadata, usage payloads, and terminal result shape.
- Initial diagnostic evidence fields are implemented on run summaries and status digests: `diagnostic_timeline`, `diagnostic_explainability`, compact diagnostic counts, top next step, and primary-safe artifact references derived from existing `.orbital/` artifacts.
- Codex ACP permission routing is documented as local-runtime-config-dependent: `Ask for Approval` can emit ACP permission requests for Orbital to mediate, while `Approve for me` can let the secondary Codex runtime approve internally and complete with `permission_capability_gap`.
- OpenCode ACP permission routing has a deterministic config lever: `opencode_acp_local_ask` injects `OPENCODE_CONFIG_CONTENT` with `permission.bash=ask` and `permission.edit=ask` so bash/edit permission mediation is not prompt-dependent. Explicit OpenCode Zen ask profiles now combine that permission behavior with pinned models, including `opencode_acp_big_pickle_ask` for `opencode/big-pickle` free-model smoke validation and `opencode_acp_glm52_ask` for stronger metered validation. Its scrubbed conformance fixture proves a real multi-request `session/request_permission` round trip with `once` approvals, and synthetic failure fixtures lock down denial, missing option IDs, and JSON-RPC resolution-error detection.
- Codex-as-primary controlling Codex-as-secondary is useful validation coverage, but it is not the targeted product workflow. The practical product goal remains a high-capability primary harness delegating bounded work to smaller, cheaper, local, or specialized secondary harnesses.
- The Prism / Orbital / `ngitd-core` boundary is now explicit: Prism coordinates the broader workflow, Orbital owns agent-run diagnostics and attachable run artifacts, and `ngitd-core` owns repo snapshots, captured changes, durable evidence artifacts, annotations, terminal dispositions, and lineage.
- No real local Claude ACP subscription path has been verified. Claude ACP planning remains API-backed through the Claude Agent SDK until proven otherwise.
- Smoke-verified real profiles remain `experimental_acp`; no real profile should be promoted to `known_good_acp` until adapter conformance fixtures and smoke evidence both pass.

Current engineering focus:

- Treat diagnostic evidence as the next product control: Orbital cannot make primary or secondary harnesses deterministic, but it can make observations, raw artifacts, normalized timelines, warnings, capability gaps, and next-inspection pointers deterministic enough to diagnose what happened.
- Broaden the explicit adapter conformance fixture matrix for Codex and OpenCode before expanding it to Pi or Claude Agent SDK ACP.
- Apply the matrix first to smoke-verified local Codex ACP, official Codex ACP, and OpenCode ACP, because fuller real ACP conformance is the next support-tier gate.
- Prefer validation that exercises the intended mixed-harness delegation shape over scenarios that only prove a frontier harness can call another instance of itself. The near-term target matrix is Codex and, once verified, Claude as primary harnesses supervising OpenCode through `opencode_acp_local_ask` or an explicit pinned-model ask profile such as `opencode_acp_big_pickle_ask` as the secondary harness.
- Keep direct `../ngitd-core` integration, richer SDLC/git attribution, and containerized sandbox enforcement as later Prism or platform layers unless an adapter-conformance task exposes a narrow prerequisite.
- Keep the TODO below as the remaining implementation, hardening, and promotion backlog. Items that are already partially implemented should be treated as "finish, broaden, or lock down" work, not as absence of any code.

Risk-ranked hardening priorities:

1. Evidence gaps: impact 5, likelihood 4, easy now 5. Completed runs need deterministic warnings and repair seeds when edits, checks, tool evidence, or path-scope proof are missing.
2. Adapter drift: impact 5, likelihood 4, easy now 4. Real Codex and OpenCode must get replayable conformance fixtures before either profile can be considered known-good.
3. Permission ambiguity: impact 5, likelihood 3, easy now 4. Primary-mediated approvals need stable option mapping, conservative inference, post-restart behavior, and complete audit evidence.
4. Storage and restart uncertainty: impact 4, likelihood 3, easy now 4. Run records, event logs, final reports, and pending permissions need atomicity, schema versions, bounded reads, and recovery diagnostics before long-lived use.
5. Profile mismatch: impact 4, likelihood 3, easy now 4. Readiness, support tier, task classification, and capability gaps must remain visible in every selection path.
6. Telemetry misattribution: impact 3, likelihood 4, easy now 5. Codex/OpenCode canonical telemetry must stay exact-only, uniquely correlated, and separate from adapter diagnostics.
7. Quiet-run mistakes: impact 3, likelihood 3, easy now 3. Liveness must guide stop decisions and record whether stopping happened without a stop-safe recommendation.
8. Prompt over-trust: impact 5, likelihood 4, easy now 2. Prompt boundaries are necessary, but deterministic evidence and policy controls are the real mitigation.

Lower-priority for V1: perfect cross-provider cost accounting, full Claude ACP parity, hard sandbox enforcement, hosted service, SDLC workflows, and richer git attribution.

Current diagnostic decision:

- Orbital should be the system of record around nondeterministic harness behavior. It should preserve raw debug artifacts, normalize a concise diagnostic timeline, distinguish observation from inference, and point the operator to the exact artifact to inspect next when confidence is limited.
- Guardrail tests should stay narrow and product-critical: Codex primary now, Claude primary after setup verification, and OpenCode secondary through the ask-config ACP profile. Broader runtime coverage should follow only after this target path is diagnosable.
- Orbital's current integration posture with `ngitd-core` is `artifact_contract_only`: no `.ngit/` writes, no `ngit` subprocess calls, and no runtime dependency. Prism should later decide when Orbital artifacts become `ngitd-core` evidence or annotations.
- Matt Pocock's `/grill-with-docs` pattern is a Prism design issue, not an Orbital core feature. The durable version should be a Prism-owned context-grilling workflow that inspects repo code/docs, interviews the engineer one question at a time, and proposes `CONTEXT.md` glossary updates plus high-value ADRs before implementation. Orbital should later consume approved planning artifacts as bounded worker context, but it should not own the interview state machine, glossary, or ADR generation.

## Next Workplan: Phase 3 ACP Conformance Matrix

Goal:

- Broaden the replayable Codex/OpenCode ACP evidence matrix so adapter drift, permission ambiguity, and runtime-specific capability gaps are visible before any support-tier promotion.
- Keep the work inside Orbital's current product boundary: no direct `ngitd-core` integration, no sandbox claims, no SDLC workflow expansion, and no `known_good_acp` promotion.

Scope:

- Target runtimes: `opencode_acp_local`, `opencode_acp_local_ask`, `codex_acp_local`, and `codex_acp_official`.
- Target product path: a high-capability primary harness supervising OpenCode secondary through `opencode_acp_local_ask`.
- Non-target for this slice: Claude Agent ACP smoke, Pi adapter work, Prism artifact export, richer repo lineage, and sandbox enforcement.

Implemented baseline:

- ACP conformance reports list observed support for initialize, session creation, prompt submission, dialogue, tools, permissions, permission resolution, stop/cancel, stderr, model metadata, adapter usage payloads, canonical local-log telemetry applicability, malformed payload handling, and terminal result shape.
- Conformance reports explicitly distinguish `observed`, `missing`, `not_applicable`, and `capability_gap` feature states instead of collapsing all absent behavior into missing support.
- OpenCode fixtures cover stop/cancel behavior, stderr failure, partial terminal result, ambiguous permission options, and mixed allow/deny multi-request permission outcomes.
- Official Codex ACP fixtures cover stop/cancel behavior, stderr/guardian failure output, malformed/unknown payloads, permission capability gap behavior, model metadata, adapter usage payloads, and terminal result shape.
- Dropped, downgraded, unknown, malformed, stderr, and capability-gap cases preserve bounded raw transcript references for debug inspection.

Remaining implementation tasks:

- [ ] Add or broaden legacy Codex ACP fixtures only where they clarify compatibility behavior that differs from the official app-server adapter.
- [ ] Keep profile support tiers unchanged unless the fixture and smoke promotion gate is intentionally revisited in a separate decision.

Documentation tasks:

- [ ] Update `README.md` manual smoke/conformance notes only if operator-facing review steps or script outputs change.

Implemented automated tests:

- `tests/test_validation_acp_conformance.py` covers feature-state reporting, new fixture families, raw-ref preservation, support-tier no-promotion behavior, and runtime-specific capability-gap classification.

Remaining automated tests:

- [ ] Extend `tests/test_validation_fake_acp.py` only when a real-runtime fixture exposes a generic ACP shape that fake ACP should model.
- [ ] Extend `tests/test_orbital_core.py` if profile metadata, support-tier caveats, or primary-safe summary fields change.
- [ ] Continue extending `tests/test_docs_todo.py` when new docs language is added, so docs preserve the conformance matrix terms and reject accidental `known_good_acp` promotion.

Manual tests:

- [ ] Run `tests/manual/run_manual_local_opencode_acp_permission_smoke.sh` with `opencode_acp_local_ask` and confirm the result is `pass`, not `permission_capability_gap`, when OpenCode ask-config is active.
- [ ] Run `tests/manual/run_manual_official_codex_acp_smoke.sh` when the official adapter is available; classify any missing permission request as `permission_capability_gap`, not Orbital mediation success.
- [ ] Run `tests/manual/run_manual_official_codex_acp_permission_smoke.sh` only when local Codex is intentionally set to `Ask for Approval`; record whether the runtime emits ACP permission requests.
- [ ] Review each manual log for diagnostic anchors: selected profile, ACP initialize details, permission mode/config, request option IDs, selected decisions, terminal status, token correlation result, warnings, and capability gaps.

Validation commands:

- [ ] `python3 -m pytest -q tests/test_validation_acp_conformance.py`
- [ ] `python3 -m pytest -q tests/test_validation_fake_acp.py`
- [ ] `python3 -m pytest -q tests/test_orbital_core.py`
- [ ] `python3 -m pytest -q tests/test_docs_todo.py`
- [ ] `python3 -m pytest -q`
- [ ] `git diff --check`

Exit criteria:

- The conformance report gives a primary harness a clear, runtime-specific view of what ACP behavior was observed, what is missing, what is not applicable, and what is a known capability gap.
- OpenCode ask-config permission behavior has replay coverage for happy path, denial, malformed/missing options, JSON-RPC resolution failure, ambiguous options, and mixed multi-request outcomes.
- Official Codex ACP remains experimental but has clearer fixture-backed evidence for its current app-server behavior and gaps.
- No profile is promoted to `known_good_acp`.
- Docs and tests agree that this slice hardens the support-tier gate; it does not widen Orbital into Prism, `ngitd-core`, SDLC, or sandbox responsibilities.

## Risk Workplans

These workplans intentionally overlap with the numbered implementation sections. They organize the same work by failure mode so planning can start from "what could go wrong?" before choosing a feature area.

### Evidence Gaps

Problem:

- A secondary harness can finish with convincing prose but missing edits, missing checks, missing tool evidence, or changes outside the requested scope.
- The primary harness may accept a bad run if Orbital does not make missing proof obvious.

Workplan:

- [ ] Define a stable warning taxonomy for evidence gaps: `no_changed_files`, `no_completed_tool_calls`, `missing_requested_check`, `failed_requested_check`, `unknown_requested_check`, `changed_outside_allowed_paths`, `changed_forbidden_paths`, `acceptance_check_failed`, and `worker_claim_without_evidence`.
- [ ] Add a deterministic evidence completeness score to run summaries, based on changed files, requested checks, tool timeline, final status, warnings, and path-scope evidence.
- [ ] Make `get_run_summary` group warnings by severity and explicitly distinguish blocking evidence gaps from review-only caveats.
- [ ] Ensure every completed run with requested checks records check status as `passed`, `failed`, `missing`, or `unknown`; never infer success from final prose.
- [ ] Expand repair seed generation so each evidence gap maps to a concrete repair objective, preserved allowed paths, and the original acceptance hints.
- [ ] Add summary fields that separate worker final response from server-observed proof.
- [ ] Add regression tests for successful prose with no edits, edits with no checks, checks missing from transcript, failed checks, forbidden path changes, outside-allowed-path changes, and completed runs with no tool evidence.
- [ ] Add manual smoke review guidance that tells the operator which evidence fields must be inspected before trusting a real harness smoke.

Decision rule:

- A run can be an `accept_candidate` only when required evidence is present or explicitly marked not requested; otherwise it should be `needs_repair`, `requires_primary_review`, or `blocked`.

### Diagnostic Evidence Layer

Problem:

- Primary and secondary harness behavior will remain partly model- and harness-dependent, even with strong prompts and adapter configuration.
- Without a complete diagnostic trail, a failed or surprising run can look like a model problem, adapter problem, policy problem, permission gap, or Orbital bug with no reliable way to separate them.

Current Baseline:

- Orbital already stores raw transcripts, stderr, dialogue, permissions, summaries, conformance fixtures, token-source diagnostics, warning groups, and capability-gap classifications.
- Manual Codex/OpenCode smokes already produce review logs that identify pass/fail outcomes, permission capability gaps, and token telemetry correlation.
- Run summaries now expose a derived `diagnostic_timeline` and `diagnostic_explainability`; status digests expose compact diagnostic counts and top next step without raw events.

Workplan:

Implemented baseline:

- Derived run summaries now include a canonical diagnostic timeline for launch, prompt, dialogue, tool, permission, check, telemetry, warning, terminal, and fallback event phases.
- Summary explainability now separates `observed`, `inferred`, `unknown`, and `diagnostic_next_steps` so primary harnesses do not confuse evidence with interpretation.
- Warning, capability-gap, permission, transcript, final-report, and token-source diagnostics now point to primary-safe artifact references where Orbital has such an artifact.
- Status digests now expose compact diagnostic counts and top next step without raw events or raw adapter payloads.

Remaining work:

- [ ] Broaden diagnostic timeline phases to include ACP initialize and session creation when adapters expose those as normalized events.
- [ ] Add Prism-facing artifact export packaging once Prism defines the attachment contract for `ngitd-core` evidence and annotations.
- [ ] Extend manual smoke review logs to assert the presence of diagnostic anchors: selected profile/config, ACP initialize details, permission mode/config, request option IDs, selected decisions, terminal status, token correlation result, warnings, and capability gaps.
- [ ] Add regression tests for diagnostic timelines on successful runs, permission-denied runs, permission capability gaps, failed checks, missing evidence, JSON-RPC errors, and telemetry ambiguity.
- [ ] Prioritize target-path smokes and fixtures for Codex primary supervising OpenCode secondary through `opencode_acp_local_ask`; add Claude primary once its setup path is verified.

Decision rule:

- When Orbital cannot fully control or verify harness behavior, it should preserve enough evidence to explain the uncertainty and recommend the next specific artifact or summary field to inspect.

### Prism / ngitd Boundary

Problem:

- Orbital can accidentally grow into a second repo-memory system if run evidence, accepted/rejected attempts, file attribution, and session reports are described as durable change history.
- Direct `ngitd-core` integration inside Orbital would blur product ownership before Prism exists to coordinate the broader workflow.
- A repo-grounded planning/interview workflow such as Matt Pocock's `/grill-with-docs` could blur Orbital's scope if treated as part of delegation. It belongs in Prism because it is pre-delegation context formation, not secondary-agent run supervision.

Current Baseline:

- Orbital owns agent-run diagnostics and fallback file attribution under `.orbital/`.
- `ngitd-core` owns repo-local `.ngit/` memory: repo snapshots, captured changes, durable evidence artifacts, annotations, terminal dispositions, and lineage.
- Prism is the planned coordinating app that can connect Orbital run artifacts to `ngitd-core` evidence or annotations later.
- Prism should also own any durable context-grilling workflow: repo inspection, question planning, user-confirmed answers, glossary term state, ADR candidate state, artifact review, and approved writes to `CONTEXT.md` or `docs/adr/`.

Workplan:

Implemented baseline:

- `get_server_info.system_boundaries.integration_posture` is set to `artifact_contract_only`.
- Orbital `accept_candidate`, `needs_repair`, and `reject` are documented as run-control assessment values, not repo-change dispositions.
- Handoff session reviews are scoped to delegated attempts and primary operational review state.
- File attribution is documented as fallback-level until Prism coordinates richer repo-change memory through `ngitd-core`.
- Orbital has no `.ngit/` writes, no `ngit` subprocess calls, no `ngitd-core` config discovery, and no ngit-specific runtime dependency.

Remaining work:

- [ ] Define future artifact exports so Prism can attach Orbital run summaries, permission logs, check evidence, telemetry diagnostics, and warning/capability-gap reports to `ngitd-core` records.
- [ ] Capture the Prism context-grilling design in Prism's own docs: a downloadable/installable app workflow with durable session state, harness switching, repo-grounded questions, user confirmation, `CONTEXT.md` glossary updates, selective ADR generation, and later `ngitd-core` capture.
- [ ] Define the narrow Orbital integration point for approved planning artifacts: Orbital may accept references or bounded excerpts from Prism-generated `CONTEXT.md` and ADRs as worker-safe task context, without owning their creation or review.
- [ ] Broaden regression tests as new tools are added so server metadata, primary guidance, and docs preserve this boundary.

Decision rule:

- Orbital may observe, summarize, and recommend for agent runs. Prism coordinates cross-system workflow and pre-build context formation. `ngitd-core` records durable repo-change evidence, disposition, and lineage.

### Adapter Drift

Problem:

- Codex, OpenCode, and future ACP harnesses may differ in event names, payload nesting, permission formats, stop behavior, stderr handling, model metadata, and usage reporting.
- A local smoke pass proves launchability, not complete adapter correctness.

Workplan:

- [ ] Define a reusable ACP conformance fixture schema that captures initialize, session creation, prompt submission, streamed text, tool calls, permission requests, permission resolution, stderr, stop/cancel, final result, model metadata, and usage payloads.
- [ ] Broaden the current fixture-driven fake ACP conformance tests to cover the remaining permission result variants beyond the existing approval round trip, stop/cancel, stderr-only failure, malformed payload, unknown event, and partial-result fixtures.
- [ ] Broaden the current legacy Codex ACP fixture beyond the scrubbed smoke excerpt to include stop/cancel and failure-mode transcript coverage.
- [ ] Broaden the current official Codex ACP fixture beyond the scrubbed permission-capability-gap excerpt to include stop/cancel and failure-mode transcript coverage.
- [ ] Broaden the current OpenCode ACP fixture beyond the scrubbed smoke excerpt to include stop/cancel and failure-mode transcript coverage.
- [ ] Add fixture cases for malformed JSON-RPC, unknown event shapes, missing IDs, unknown stop reasons, partial result payloads, and stderr-only failures.
- [ ] Extend the current conformance report so it lists normalized features observed for each runtime family: dialogue, tools, permissions, stop, stderr, model metadata, adapter usage payloads, and local-log token telemetry.
- [ ] Gate `known_good_acp` promotion on fixture pass, manual smoke pass, documented capability gaps, and deterministic regression coverage.
- [ ] Keep raw transcript references available in debug artifacts whenever a normalizer drops, downgrades, or ignores an unknown payload.

Decision rule:

- A profile can be ready to launch from doctor checks and smoke evidence, but it cannot be `known_good_acp` until replayable conformance fixtures cover its claimed capabilities.

### Permission Ambiguity

Problem:

- A permission request can expose ambiguous approve/deny options, stale adapter request IDs, incomplete risk context, or an action Orbital cannot actually mediate.
- Bad permission handling can approve unintended actions or imply control that does not exist.

Current Baseline:

- Permission records now carry schema version, adapter request ID, risk/action/command context, paths/resources, options, raw reference, decision, deciding primary, timestamps, selected option ID, adapter resolution status, and adapter result when available.
- Permission option resolution fails closed: explicit adapter option IDs are preferred, approve/deny inference is allowed only when exactly one option matches, stale restart-visible permissions return `permission_not_resolvable_after_restart`, mismatched adapter request IDs return `unknown_adapter_request`, and adapter resolution failures are appended as audit evidence before returning `adapter_permission_resolution_failed`.
- Fake ACP and service-level regression tests cover explicit approval, explicit denial, ambiguous options, adapter request mismatch, restart-visible pending permissions, resolved permissions, and adapter resolution failure evidence.
- Manual Codex/OpenCode permission smoke wrappers classify no-request real-runtime completions as `permission_capability_gap` rather than treating them as verified approval mediation.
- OpenCode-specific permission behavior is now part of the planning baseline: `opencode_acp_local_ask` can force ACP permission requests by configuration, OpenCode may emit multiple permission requests during one task, and its `once`/`always`/`reject` options should be normalized without making Orbital core OpenCode-specific.
- OpenCode ask-config conformance now includes fixture coverage for a rejected permission, malformed/missing request option IDs, and a JSON-RPC permission resolution error; these fixtures prove detection and auditability, not support-tier promotion.

Workplan:

- [ ] Define the canonical permission record fields: `permission_id`, `run_id`, `adapter_request_id`, `status`, `risk`, `action`, `command`, `paths`, `resources`, `options`, `selected_option_id`, `decision`, `rationale`, `deciding_primary`, timestamps, and raw debug reference.
- [ ] Require explicit adapter option IDs whenever available; infer approve/deny only when exactly one option is semantically matched.
- [ ] Return stable errors for ambiguous option inference, unknown permission ID, unknown adapter request ID, already-resolved permission, and post-restart non-resolvable permission.
- [ ] Record adapter response after permission resolution and surface whether the adapter accepted, rejected, ignored, or failed the decision.
- [ ] Distinguish permission policy levels: `prompt_only`, `adapter_mediated`, `process_observed`, and `sandbox_enforced`.
- [ ] Add policy evidence that says whether a risky action was prevented, mediated, or only observed.
- [ ] Add post-restart behavior: stored pending permissions remain visible as evidence, but `resolve_permission` returns `permission_not_resolvable_after_restart` unless adapter reattachment is implemented.
- [ ] Add regression tests for explicit approval, explicit denial, ambiguous options, missing options, stale request IDs, resolved permissions, restart-visible pending permissions, and adapter resolution failure.
- [ ] Broaden OpenCode ask-config permission conformance beyond the current happy path plus denial, missing option ID, and JSON-RPC error fixtures to cover ambiguous options and mixed allow/deny multi-request outcomes.
- [ ] Add policy tests that exercise primary decisions over multiple OpenCode permission requests with mixed allow/deny outcomes.
- [ ] Keep refining OpenCode request-context display in primary-safe summaries so command/action/path/risk evidence is easy to inspect without raw transcript reads.

Decision rule:

- Permission resolution must fail closed unless Orbital can identify exactly one intended adapter option and can send it to a live actionable request.

### Storage And Restart Uncertainty

Problem:

- Run records, permission logs, transcripts, and final reports can be partially written or stale after interruption.
- After restart, Orbital may not know whether a worker is still alive or whether a pending permission is actionable.

Current Baseline:

- Run/session/final-report writes use temp-file plus replace semantics behind per-run or per-session file locks, while dialogue, permission, transcript, and stderr streams are append-only.
- Storage diagnostics report malformed JSON, malformed JSONL, missing artifacts, unsupported schema versions, partial temp files, and stale pending permissions on recovered interrupted runs.
- Startup recovery marks non-terminal run records as `interrupted`, appends a recovery event, leaves pending permissions visible as evidence, and keeps those permissions non-resolvable unless adapter reattachment is later implemented.

Workplan:

- [ ] Add schema versions to config, run records, session records, status digests, summaries, permission records, and final reports.
- [ ] Implement atomic writes for `run.json`, `session.json`, and final reports using temp-file plus replace semantics.
- [ ] Keep event-style files append-only: `dialogue.jsonl`, `permissions.jsonl`, telemetry logs, stderr tails, and transcript references.
- [ ] Add file locks or a single-writer strategy for concurrent writes to the same run or session.
- [ ] Add bounded readers for JSONL, transcript, stderr, and debug dialogue with explicit truncation metadata.
- [ ] Add storage diagnostics for malformed JSON, malformed JSONL lines, missing artifacts, unsupported schema versions, and partial final reports.
- [ ] Define startup recovery for non-terminal runs: active records without a live process become `interrupted` or `unknown` with a recovery diagnostic.
- [ ] Preserve raw logs during recovery; never delete or rewrite evidence without recording a recovery event.
- [ ] Make recovered pending permissions visible but non-resolvable unless adapter reattachment is supported.
- [ ] Add tests for partial `run.json`, malformed permission JSONL, corrupted final report, interrupted active run, stale pending permission, path traversal run IDs, and bounded log reads.

Decision rule:

- Recovery should preserve evidence and mark uncertainty. It should not try to make an interrupted run look cleanly completed or failed unless the stored evidence proves it.

### Profile Mismatch

Problem:

- A profile can be executable and authenticated but still not suitable for a task or not trustworthy enough for a support claim.
- Hidden default selection or unsupported capability assumptions can send work to the wrong harness.

Current Baseline:

- Recommendation responses keep readiness separate from support tier and include structured `recommendation_factors`: matched/missing tags, matched/missing capabilities, locality and cost preference match, support tier caveats, readiness blockers, and capability gaps.
- Preflight responses expose selected profile metadata, readiness, support tier, classification, normalized capabilities, and deterministic capability gaps before a run starts.
- Metered API profiles remain explicit opt-in for selection, and support tier caveats stay visible even when a profile is executable.

Workplan:

- [ ] Ensure every profile exposes readiness, support tier, runtime family, adapter, auth mode, cost posture, capabilities, classification tags, known limits, and capability gaps.
- [ ] Keep readiness separate from support tier in `list_harness_profiles`, `get_harness_profile`, `check_harness_profile`, and recommendation responses.
- [ ] Implement deterministic recommendation reasons: matched tags, missing tags, matched capabilities, missing capabilities, locality/cost match, support-tier caveats, and readiness blockers.
- [ ] Reject hidden profile switching inside handoff sessions unless the primary explicitly starts a new run with a different profile.
- [ ] Add warnings for session profile drift and run profile mismatch.
- [ ] Keep API-backed or metered profiles explicit opt-in and never selected implicitly by local/subscription preference.
- [ ] Add tests for recommendation determinism, disabled profiles, not-ready profiles, support-tier caveats, missing capabilities, metered opt-in, and profile drift warnings.
- [ ] Add profile metadata notes that identify current Codex/OpenCode status as smoke-verified experimental until real conformance fixtures pass.

Decision rule:

- Profile selection can recommend, but the primary owns final assignment. Orbital must never present launch readiness as known-good support.

### Telemetry Misattribution

Problem:

- Token totals can be unavailable, double-counted, invented by prompts, or correlated to the wrong local agent session.
- Bad telemetry can mislead cost, model, or report decisions even when task output is correct.

Current Baseline:

- Run summaries use canonical token totals only when exactly one correlated local agent-log record matches the run workspace and time window; multiple matches keep `tokens.known=false` and include ambiguity caveats.
- Adapter usage payloads remain under diagnostic `token_sources.adapter_payloads` and do not contaminate canonical totals.
- Codex rollout JSONL and OpenCode SQLite scanners preserve the practical V1 accounting rules: grouped Codex sessions with cache-aware net input, and OpenCode cumulative `step-finish` snapshots using the highest reported `tokens.total`.

Workplan:

- [ ] Keep canonical token totals sourced only from correlated local agent logs, currently Codex rollout JSONL and OpenCode SQLite for the practical V1 gate.
- [ ] Keep adapter-observed usage payloads under diagnostic sources and out of canonical totals.
- [ ] Keep external model-log telemetry diagnostic unless a run-correlation identifier exists.
- [ ] Require local agent-log correlation by workspace path and run time window; manual token probes should isolate a token workspace and require exactly one matched external record.
- [ ] Preserve OpenCode handling as cumulative `step-finish` snapshots using the highest reported `tokens.total`, not summed rows.
- [ ] Preserve Codex handling as grouped rollout files by session ID with net input, cached input, output, total, model, timestamp, session ID, and source path.
- [ ] Add caveats to summaries when canonical telemetry is known but correlation depends on workspace/time rather than adapter-provided run ID.
- [ ] Add tests for no matching records, multiple matching records, OpenCode cumulative snapshots, Codex cache accounting, adapter payload diagnostic separation, and session report aggregation.
- [ ] Decide whether Claude local-log parsing remains supported without a verified Claude ACP profile, and document its support tier.

Decision rule:

- If token telemetry is not uniquely correlated, `tokens.known` stays false. Orbital should never ask the worker to self-report token usage.

### Quiet-Run Mistakes

Problem:

- A worker can be alive but quiet, waiting on permission, or dead without a clean terminal event.
- Stopping too early can interrupt useful work; waiting too long can block the primary.

Current Baseline:

- `get_run_liveness` combines run status, latest Orbital event age, pending permission state, pending tool state, process state, and optional model-log activity into verdicts with stop safety, recommendations, reasons, thresholds, and evidence.
- `stop_task_run` records `stop_without_liveness_check` session warnings unless there is a recent stop-allowed liveness recommendation, and warning messages include the last verdict, last action, and check age when available.
- Stopping a run attempts adapter stop/cancel behavior, records cancellation in final reports, and marks pending permissions cancelled in append-only permission evidence.

Workplan:

- [ ] Keep liveness as a first-class MCP tool that can be called for active and recently interrupted runs.
- [ ] Combine run status, latest Orbital event time, pending permission state, pending tool state, process state, and optional model-log activity.
- [ ] Return liveness verdicts with stop safety, severity, recommended action, reason codes, summary, and next poll interval.
- [ ] Require `stop_task_run` to record whether a recent liveness check existed and whether it recommended stopping.
- [ ] Add a `stop_without_liveness_check` warning when the primary stops a run without a recent stop-safe liveness recommendation.
- [ ] Attempt cooperative adapter cancellation before process termination when the adapter supports it; record forced termination separately.
- [ ] Mark pending permissions cancelled or unknown when a run is stopped, according to adapter capability.
- [ ] Add tests for active recent event, pending permission, pending tool, quiet short run, suspect stalled run, stop-safe run, terminal run, unknown run, cooperative cancel, forced termination, and stop-without-liveness warning.

Decision rule:

- Orbital should recommend stop only when recent evidence indicates stalled or inactive behavior. If evidence is insufficient, it should recommend inspection or continued polling.

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
- [ ] Preserve the Claude split: `claude_code_cli_local` is the local/subscription fallback, and `claude_agent_acp_api` is disabled or explicit API-backed ACP.
- [ ] Document Claude ACP as `claude-agent-acp` through the Claude Agent SDK with `ANTHROPIC_API_KEY`, not as a Claude Code CLI subscription path.
- [ ] Broaden recorded smoke evidence in profile metadata or docs as additional Codex/OpenCode permission, failure-mode, and stop/cancel fixtures are added.
- [ ] Keep smoke-verified profiles at `experimental_acp` until adapter conformance fixtures justify `known_good_acp`.
- [ ] Keep API-backed profiles disabled or explicit by default.
- [ ] Prevent hidden profile switching inside a handoff session.

Acceptance criteria:

- A ready profile is not automatically presented as known-good support.
- The primary harness chooses the final profile assignment.
- Recommendation output is deterministic for identical config and inputs.
- Claude Code CLI and Claude Agent SDK ACP appear as separate profiles with different auth modes, cost postures, and support tiers.
- OpenCode smoke evidence records the command, OpenCode version, ACP protocol version, selected profile, changed files, warnings, and telemetry availability.
- Codex and OpenCode manual token probes fail unless canonical `external_agent_logs` telemetry is known and uniquely correlated to the isolated token workspace.

Tests:

- Unit tests for classification schema parsing.
- Unit tests for recommendation ranking and tie-breaking.
- Regression tests for support-tier caveats and missing capability reporting.
- Regression tests that metered/API profiles are never selected implicitly.
- Regression tests that `claude_agent_acp_api` is explicit opt-in and `claude_code_cli_local` remains the local/subscription Claude fallback.

## 5. ACP Adapters And Compatibility

- Risk addressed: adapter drift, permission ambiguity, profile mismatch.
- [ ] Maintain the fake ACP harness as the canonical local conformance fixture and extend it only when a real ACP harness exposes a new protocol shape we need to normalize.
- [ ] Define reusable adapter conformance fixtures for initialization, session creation, prompt submission, streamed text, tool events, permissions, stderr, stop/cancel, exact usage, exact model metadata, and malformed events.
- [ ] Keep `tests/test_validation_acp_conformance.py` focused on observable adapter evidence: transcript send/receive lines, primary-safe filtering, raw debug payloads, permission option IDs, stderr capture, usage, and model metadata.
- [ ] Add a Codex ACP conformance fixture from captured local smoke transcripts or a deterministic replay harness.
- [ ] Add an OpenCode ACP conformance fixture from captured local smoke transcripts or a deterministic replay harness.
- [ ] Add primary-mediated approval conformance coverage for permission request context, adapter option IDs, primary decision payloads, adapter responses, and post-decision run evidence.
- [ ] Define the promotion checklist that moves a real profile from `experimental_acp` to `known_good_acp`: readiness diagnostics, manual smoke evidence, conformance fixture pass, documented capability gaps, and regression tests.
- [ ] Normalize ACP event shapes across supported harnesses into one event vocabulary.
- [ ] Keep raw protocol payloads in debug logs, not primary-safe summaries.
- [ ] Label no profile `known_good_acp` without conformance fixture coverage and a smoke run.
- [ ] Document the repeatable workflow for adding a new ACP harness: profile template, readiness diagnostics, manual smoke evidence, deterministic tests, adapter conformance fixtures, and support-tier promotion.
- [ ] Keep CLI compatibility only where ACP is unavailable or unreliable.
- [ ] Treat Claude Code CLI as the local/subscription Claude path until a local-subscription ACP command is verified.
- [ ] Treat Claude Agent SDK ACP as API-key/metered via `claude-agent-acp`.
- [ ] Report CLI fallback capability gaps explicitly, especially permissions, follow-up messages, stop behavior, tool events, and telemetry.

Acceptance criteria:

- Primary harnesses do not need runtime-specific ACP knowledge.
- Adapter capability gaps are visible before a run starts.
- The primary harness receives enough structured permission context to make smart, safe approval decisions without constant manual user approval when policy allows.
- Known-good support claims are backed by fixtures and smoke evidence.
- Codex and OpenCode remain `experimental_acp` until their real-harness conformance evidence exists.
- A new harness such as Pi can start as a conservative profile template and graduate only after readiness, smoke, and conformance evidence exists.

Tests:

- Fake ACP integration tests.
- Adapter conformance fixture tests for each supported runtime family before support-tier promotion.
- Regression tests for new-harness profile templates, readiness diagnostics, recommendation caveats, and support-tier promotion rules.
- Regression tests for permission option matching and malformed ACP payloads.
- Smoke tests for each profile that can be exercised locally.
- Smoke tests should cover local Codex ACP and OpenCode ACP separately from API-backed Claude Agent ACP.

## 6. Run Lifecycle, Evidence, And File Attribution

- Risk addressed: prompt over-trust, evidence gaps, scope drift.
- [ ] Implement worker-safe startup prompt construction from task fields only.
- [ ] Ensure primary-only guidance, retry strategy, scoring rubrics, profile-selection reasoning, and session report expectations never enter worker prompts.
- [ ] Capture normalized dialogue, tool timeline, permissions, stderr, transcript references, check evidence, warning details, and failure classifications.
- [ ] Implement deterministic policy verdicts: `accept_candidate`, `needs_repair`, `reject`, `blocked`, and `requires_primary_review`.
- [ ] Generate repair seeds from server-observed gaps while preserving task scope, checks, and acceptance hints.
- [ ] Keep fallback file attribution explicit until later `../ngitd-core` integration exists.
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

- Risk addressed: permission ambiguity, prompt over-trust, unsupported enforcement claims.
- [ ] Normalize permission requests into stable records with run ID, adapter request ID, risk, command/action, paths, resources, options, raw reference, decision, rationale, and adapter result.
- [ ] Prefer explicit adapter option IDs for approval/denial.
- [ ] Infer approve/deny options only when exactly one option matches.
- [ ] Return stable errors for ambiguous options, unknown permissions, resolved permissions, and post-restart non-resolvable permissions.
- [ ] Replace blanket command denial with configurable policy behavior.
- [ ] Report active policy level: `prompt_only`, `adapter_mediated`, `process_observed`, or `sandbox_enforced`.
- [ ] Allow primary-mediated approval for risky actions when the adapter can pause.
- [ ] Preserve the complete permission round trip: secondary request, primary-facing decision context, selected adapter option ID, adapter response, and run outcome after the decision.
- [ ] Record whether a violation was prevented, mediated, or only observed after the fact.
- [ ] Use OpenCode granular permission config as a profile-level enforcement lever, not as a core policy dependency: start with `bash=ask` and `edit=ask`, then consider narrower allow/deny patterns only after generic policy tests exist.
- [ ] Preserve and display OpenCode's structured permission context through the generic permission model so the primary can decide from command/action/path/risk evidence.
- [ ] Avoid automatic OpenCode `always` approvals unless the primary explicitly chooses a session-scoped policy change.

Acceptance criteria:

- Orbital does not imply sandboxing unless sandbox enforcement exists.
- The primary harness can approve reasonable risky actions with rationale when the adapter supports mediation.
- Primary-mediated approvals are complete enough for a primary harness to supervise secondary agents without asking the user to approve every action manually.
- Pending permissions after restart remain visible but return `permission_not_resolvable_after_restart` unless reattachment is supported.

Tests:

- Unit tests for permission normalization and option selection.
- Regression tests for post-restart pending permissions.
- Regression tests for complete approval and denial round trips through the adapter.
- Policy tests for package install, network command, destructive command, scope expansion, explicit approval, and observed-only violations.

## 8. Handoff Sessions

- [ ] Keep handoff/session tools in V1.
- [ ] Use generic delegation entities: session, handoff item, task, attempt, review, repair, and report.
- [ ] If API names keep `ticket`, document it as a bounded local task record, not an issue tracker object.
- [ ] Implement session start, item creation, task creation, task attempt start, primary review recording, next-action recommendation, repair task creation, session finish, and handoff report retrieval.
- [ ] Preserve session warnings for profile mismatch, path-scope drift, missing review evidence, unsatisfied handoff items, unreviewed attempts, pending permissions on finish, unattributed files, and stopping without liveness.
- [ ] Keep final acceptance owned by the primary harness.
- [ ] Preserve canonical local agent-log telemetry in session reports and keep adapter payload and model-log telemetry diagnostic.

Acceptance criteria:

- A primary harness can manage a multi-run loop without reconstructing state from prompts.
- Repair tasks can be generated from server evidence without raw transcript reads.
- Session warnings inform primary review without automatically deciding acceptance.

Tests:

- Structured workflow tests for session, item, task, attempt, review, repair, finish, and report.
- Regression tests for profile drift, path-scope warnings, missing review evidence, unreviewed attempts, and unsatisfied handoff items.
- Tests for canonical local agent-log telemetry and report aggregation.

## 9. Liveness, Telemetry, And Reports

- Risk addressed: quiet-run mistakes, telemetry misattribution, report over-trust.
- [ ] Implement liveness from run status, latest event time, pending permission, pending tool, process state, and optional model-log activity.
- [ ] Require primary harnesses to check liveness before stopping quiet runs.
- [ ] Record whether a stop had a recent stop-allowed liveness recommendation.
- [ ] Attempt cooperative adapter cancellation before process termination.
- [ ] Keep local Codex and OpenCode agent logs as canonical token telemetry when correlated by workspace and run window.
- [ ] Keep adapter payload telemetry and external model-log telemetry diagnostic, not canonical.
- [ ] Preserve OpenCode `step-finish` handling as cumulative snapshots that use the highest reported `tokens.total` instead of summing rows.
- [ ] Verify whether Claude local-log parsing should remain supported without a verified Claude ACP profile, and document its support tier accordingly.
- [ ] Keep external model-log telemetry unattributed unless run-correlation metadata exists.
- [ ] Generate handoff reports with timing, profile mix, runs, evidence, attribution, warnings, and token accounting.

Acceptance criteria:

- Quiet active runs are not classified as safe to stop solely because Orbital has no recent event.
- Model-log telemetry never contaminates canonical token totals without correlation.
- Reports can be useful even with unknown telemetry.

Tests:

- Liveness tests for active server event, active model log, waiting permission, quiet short, suspect stalled, stop safe, terminal, and unknown states.
- Stop tests for cooperative cancellation, process termination, and stop-without-liveness warnings.
- Telemetry tests for canonical local agent-log records, unknown canonical totals, adapter diagnostics, and model-log unattributed cases.

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

- [ ] Keep deterministic unit/regression tests and fake-harness integration tests as first-class CI gates.
- [ ] Keep default validation unattended with no clicks, browser interaction, private credentials, network dependency, real model calls, or installed real harnesses.
- [ ] Keep optional real-harness smoke experiments outside the default suite and gated by explicit environment variables.
- [ ] Add deterministic tests for config/schema defaults, support tiers, profile classification, disabled profiles, and metered profile opt-in.
- [ ] Add deterministic tests for profile recommendation determinism, tie-breaking, caveats, missing capabilities, and explicit selection behavior.
- [ ] Add deterministic tests for storage invariants: atomic JSON writes, append-only JSONL, bounded reads, malformed logs, partial writes, path traversal rejection, and startup recovery.
- [ ] Add deterministic MCP/service contract tests for primary-safe responses, debug responses, stable errors, schema versions, and canonical statuses.
- [ ] Add deterministic tests for permission normalization, policy verdicts, restart visibility, and approval/denial option selection.
- [ ] Add deterministic tests for run evidence, startup prompt boundaries, no-op pass warnings, requested checks, path policy, attribution confidence, liveness, telemetry, reports, and handoff/session state transitions.
- [ ] Keep fake ACP scenarios for happy-path runs, streamed text, tool events, stderr, exact usage, exact model metadata, permission approval, permission denial, complete primary-mediated permission round trips, malformed stdout, failed results, hung workers, failed checks, forbidden commands, forbidden path writes, outside-allowed-path writes, stop behavior, and session repair workflows.
- [ ] Keep the test-only fake profile smoke path so `orbital_mcp.smoke` can be validated unattended from a local config fixture.
- [ ] Keep fake-harness tests limited to local fixture processes, temporary workdirs, and `.orbital` stores that are cleaned after each test.
- [ ] Add MCP contract tests for tool response envelopes, `ok_response` and `error_response` shape, primary-safe defaults, debug access flags, schema versions, and canonical status fields.
- [ ] Add fake ACP failure-mode tests for non-zero worker exit, JSON-RPC error responses, ambiguous permission options, follow-up messages through `send_task_message`, and cooperative cancel versus forced termination evidence.
- [ ] Add storage durability tests for malformed or partial final reports, append-only permission latest-state reads, and session warning persistence across service restart.
- [ ] Keep package/CLI validation that distinguishes source-tree execution from installed-package execution and records any packaging gap explicitly.
- [ ] Keep default MCP stdio transport validation for tool listing, profile checks, fake task execution, primary-safe dialogue, and debug dialogue.
- [ ] Keep optional installed-package validation gated by `ORBITAL_RUN_PACKAGING_SMOKE=1`.
- [ ] Keep optional real-harness validation gated by `ORBITAL_RUN_REAL_HARNESS_SMOKE=1` and selected profile IDs.
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

Completed alignment:

1. Replaced the runtime profile template named `claude_code_acp_local` with `claude_agent_acp_api`.
2. Configured `claude_agent_acp_api` as `adapter=acp`, `runtime_family=claude_agent`, `command=["claude-agent-acp"]`, `auth_mode=api_key`, `cost_posture=metered_api`, and disabled by default.
3. Kept `claude_code_cli_local` as `adapter=cli`, `runtime_family=claude_code`, `command=["claude"]`, `auth_mode=local_subscription`, `cost_posture=subscription_preferred`, and `support.tier=cli_fallback`.
4. Added readiness diagnostics so `claude_agent_acp_api` checks for Node >= 22, `claude-agent-acp`, and `ANTHROPIC_API_KEY`.
5. Added regression tests for profile defaults, readiness diagnostics, metered opt-in, recommendation caveats, and docs alignment.

Remaining Claude Agent ACP work:

1. Verify the actual `claude-agent-acp` install path and API-key smoke behavior.
2. Add a Claude Agent ACP manual smoke script only after setup is verified; keep Codex/OpenCode as the only active local ACP manual scripts until then.
3. Add explicit Claude Agent ACP real-harness smoke only when API credentials are intentionally provided.

## Deferred

- Hosted or multi-user service.
- Hard sandboxing before an actual sandbox or container mode exists.
- `../ngitd-core` integration and richer SDLC/git attribution.
- Automatic product acceptance.
- Benchmark scoring as a first-class product feature.
- SDLC-specific issue, branch, PR, CI, release, sprint, epic, owner, or team policy layers.
