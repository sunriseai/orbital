# Orbital Roadmap

## Phase 0: Spec And Rename Decision

Goal: turn the current repository from a broad sketch into a focused Orbital rebuild plan.

Deliverables:

- Product, technical, and roadmap specs under `docs/`.
- Naming decision for package, executable, config file, storage directory, and MCP server display name.
- Compatibility decision for existing Prole Harness commands and data.
- Initial open source positioning and license decision.
- Inventory of Prole Harness MCP behaviors to carry forward, rework, or drop.
- Decision on whether existing `.prole-harness/` data receives migration support or is treated as legacy read-only reference material.

Exit criteria:

- The product goal is clearly MCP-to-ACP multi-harness delegation.
- SDLC-specific work is explicitly deferred.
- Public contract changes are identified before implementation starts.
- First-draft learnings are represented in the product and technical specs rather than living only in review notes.

## Phase 1: Orbital Core Shape

Goal: establish the minimal open source MCP product surface.

Deliverables:

- Rename user-facing server identity to Orbital.
- Define `orbital.config.json` schema.
- Define `.orbital/` storage layout.
- Define storage versioning, atomic write behavior, lock strategy, log retention, and interrupted-run recovery.
- Keep or shim existing Prole storage only if migration is intentionally supported.
- Stabilize the core MCP tools for discovery, profile listing, run lifecycle, permissions, summaries, liveness, and debug dialogue.
- Define request/response schemas, stable error codes, status enums, pagination behavior, and schema versioning for the core MCP tools.
- Update setup/doctor commands around Orbital naming.
- Port the proven first-draft schema concepts for task input, run metadata, permission records, run summaries, status digests, policy verdicts, repair seeds, and liveness.
- Define restart behavior for non-terminal runs and pending permissions before exposing run recovery as reliable.

Exit criteria:

- A new user can install, configure, start, and connect Orbital as an MCP server.
- Existing core behavior still works for at least one ACP harness.
- Primary-safe run summaries and status digests are available without raw dialogue.
- Interrupted or recovered runs have deterministic statuses and diagnostics.

## Phase 2: Harness Profiles And Classification

Goal: make multiple harnesses configurable and classifiable.

Deliverables:

- Add profile `classification` metadata.
- Add profile notes for strengths, limits, and recommended task scope.
- Align profiles on the canonical `classification.task_tags`, `strengths`, `limits`, `max_recommended_scope`, `cost_preference`, and `locality` schema.
- Add `recommend_harness_profiles` MCP tool.
- Add support-tier labels for `known_good_acp`, `experimental_acp`, `profile_template`, and `cli_fallback`.
- Add first-class default profile templates for OpenCode, Pi, Codex, Claude Code CLI, and Claude Agent SDK ACP, with honest support tiers, auth modes, cost posture, and capability gaps.
- Keep API-backed profiles disabled or explicit by default.
- Add diagnostics that explain missing executables, auth gaps, and unavailable capabilities.
- Replace default-first profile selection with explicit profile selection or classification-based recommendation.
- Return deterministic recommendation reasons, caveats, matched tags, missing tags, matched capabilities, and missing capabilities.

Exit criteria:

- The primary harness can ask which ready profiles match a task class.
- Profile recommendation output includes reasons and caveats.
- The product supports multiple secondary harnesses without hidden profile switching.
- Public docs do not imply equal support quality across all harness families.
- Ready-to-launch profiles are distinguished from known-good supported profiles.

## Phase 3: ACP Adapter Hardening

Goal: make ACP conformance the main trust gate for supported secondary coding agents.

Primary risks addressed: adapter drift, permission ambiguity, profile mismatch, and evidence gaps caused by runtime-specific protocol behavior.

Deliverables:

- Normalize ACP event shapes across OpenCode, Pi, Codex, and API-backed Claude Agent SDK where available.
- Capture text updates, tool events, permission requests, stop behavior, model selection, and usage payloads.
- Preserve complete permission approval round trips: request context, adapter option IDs, primary decision, adapter response, and post-decision run evidence.
- Keep raw protocol payloads in debug logs, not primary-safe summaries.
- Add adapter conformance fixtures for each supported runtime family.
- Keep CLI compatibility only where ACP is not available or not reliable.
- Treat Claude Code CLI as the local/subscription Claude path unless a local-subscription ACP command is verified.
- Treat Claude ACP as `claude-agent-acp` through the Claude Agent SDK with API-key auth, not as a `claude-code-acp` local-subscription command.
- Port or recreate the fake ACP harness strategy from Prole Harness MCP.
- Add fixture coverage for malformed events, unknown event shapes, permission option matching, exact telemetry, stderr, and stop behavior.
- Add fixture coverage for primary-mediated approval and denial so Orbital can prove the primary harness receives enough context to decide without constant manual user approval.
- Mark each profile's support tier from fixture and smoke-run evidence.
- Use fake ACP conformance as the local baseline, then add real-harness conformance fixtures for Codex and OpenCode before considering either profile known-good.
- Keep real-runtime permission smoke outcomes explicit: `pass` means a permission request was observed and resolved, while `permission_capability_gap` means the harness completed without emitting an ACP permission request.
- Keep richer Git/SDLC attribution and stronger sandbox execution out of this phase unless a conformance fixture requires a narrow supporting change.

Exit criteria:

- Each supported ACP harness can pass a smoke run.
- Manual local ACP smoke currently covers legacy Codex ACP and OpenCode; OpenCode smoke records OpenCode `1.17.13` and ACP `protocolVersion=1`.
- Official Codex ACP app-server validation is represented by the side-by-side `codex_acp_official` profile, manual wrappers, and a scrubbed conformance fixture, but it remains experimental until the fixture matrix covers all claimed capabilities.
- Manual local ACP permission smoke reports either a full approval round trip or a clearly labeled runtime permission capability gap.
- Claude Agent SDK ACP exists as disabled API-backed profile metadata, but remains unverified until it passes explicit API-key smoke.
- Capability gaps are reported clearly instead of hidden.
- Primary harnesses do not need runtime-specific ACP knowledge.
- No runtime family is labeled `known_good_acp` without conformance fixture coverage.

## Phase 4: Handoff Sessions

Goal: preserve what worked in the current delegation model without turning Orbital into an SDLC system.

Deliverables:

- Rename delegation session concepts to generic handoff concepts.
- Keep objective, handoff items, tickets, attempts, reviews, and reports.
- Add repair-ticket creation from server-observed gaps.
- Keep primary-only guidance separate from worker-safe constraints.
- Produce reports with timing, profile mix, evidence, attribution, and exact token accounting when known.
- Document `ticket` as a bounded local task record if the term remains in API names.
- Preserve first-draft session warnings for profile mismatch, path-scope drift, missing review evidence, unreviewed attempts, unsatisfied handoff items, unattributed files, and stopping without liveness.
- Preserve deterministic next-action recommendations for ordinary session control flow.
- Preserve canonical local agent-log token telemetry for session reports.

Exit criteria:

- A primary harness can manage a multi-run task loop with durable state.
- The handoff model remains generic and does not assume sprint, issue, PR, release, or CI workflow semantics.
- Repair tasks can be generated from server-observed gaps without reading raw transcripts.
- Session reports expose canonical local agent-log telemetry and keep adapter payload and model-log telemetry diagnostic.

## Phase 5: Open Source Readiness

Goal: make Orbital understandable and approachable to contributors.

Deliverables:

- Public README focused on install, MCP connection, profile configuration, and first smoke run.
- Contributor guide for adding adapters and profile templates.
- Example configs for OpenCode, Pi, Codex, and Claude Code.
- Example configs must distinguish Claude Code CLI fallback from API-backed Claude Agent SDK ACP.
- Security model documentation.
- Test suite organized around adapter fixtures, profile selection, policy, storage, summaries, and liveness.
- Release checklist.
- Host contract documentation that distinguishes prompt-driven worker behavior from server-driven evidence.
- Documentation for support tiers, capability gaps, and adapter fallback expectations.
- Documentation for adding a new ACP harness, including profile template, readiness diagnostics, smoke evidence, conformance fixtures, and support-tier promotion criteria.
- Documentation for recovery behavior after process restart or partial storage corruption.
- Documentation for primary-safe versus debug/raw data surfaces.

Exit criteria:

- A contributor can add a new ACP harness profile or adapter fixture by following the documented profile, readiness, smoke, fixture, and support-tier workflow.
- A user can diagnose setup failures without asking for internal support.

## Phase 6: Quality And Reliability

Goal: improve trust in run state and primary decisions.

Primary risks addressed: storage and restart uncertainty, quiet-run mistakes, file attribution gaps, and policy/evidence ambiguity.

Deliverables:

- Stronger policy verdict coverage.
- Better check evidence extraction.
- More robust file attribution for dirty workdirs.
- Improved liveness with optional model log adapters.
- Better permission option matching and audit output.
- Stronger primary-mediated approval summaries for smart, safe secondary-agent supervision.
- Golden test fixtures for realistic ACP transcripts.
- Configurable command policy that can ask the primary for approval where adapter mediation exists, instead of blanket deny behavior.
- Explicit attribution confidence for file changes and final dirty files.
- Better generated-artifact detection and rejected-file-still-present reporting.
- Restart/recovery test coverage for active runs, interrupted runs, pending permissions, malformed JSONL, and partial final reports.

Exit criteria:

- Primary-safe summaries are reliable enough for ordinary control flow.
- Raw transcript inspection is only needed for ambiguous or debug cases.
- Recovery diagnostics are clear enough that primary harnesses can choose repair, retry, or manual inspection.

## Later: Richer Git And Execution Controls

These are valuable, but they should build on a trusted delegation layer rather than define the initial product wedge.

Possible later work:

- Integration planning for `../ngitd-core` as the long-term extended Git data source.
- Rich dirty-workdir history, branch/commit metadata, and cross-run file attribution.
- Containerized or sandboxed execution modes for stronger filesystem, network, and process enforcement.
- Higher-level management or prompt-policy overlays for teams that want stricter approval workflows.

## Later: SDLC Layer

SDLC workflows should come after Orbital is solid as an MCP-to-ACP routing layer.

Possible later work:

- issue or task tracker integration
- branch and PR orchestration
- benchmark scenarios
- release gates
- CI integration
- team policy packs
- hosted or multi-user service

These should build on Orbital's handoff and evidence model rather than expanding the v1 product scope.
