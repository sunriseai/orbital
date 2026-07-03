# Orbital Product Spec

## Summary

Orbital is an MCP delegation layer for running, supervising, and reviewing secondary coding agents.

The user installs Orbital locally, configures one or more harness profiles, classifies those profiles by the kinds of tasks they are good at, and lets the primary harness delegate bounded work to the right secondary worker through a normalized MCP interface. Orbital owns process launch, protocol adaptation, permissions, run evidence, file attribution, and structured handoff data. The primary harness owns planning, task judgment, profile choice, and final acceptance.

The existing Prole Harness MCP codebase proves that this loop is useful, but it is broader and more benchmark-oriented than Orbital should be. Orbital should rebuild the idea around a crisp MCP-to-ACP product: install, configure harnesses, classify them, run tasks, capture evidence, and return primary-safe state.

## First-Draft Learnings

Orbital should treat Prole Harness MCP as a validated first draft, not as a throwaway prototype. The first draft showed that a local MCP can make primary/secondary coding workflows materially more useful when the server owns observable run state instead of asking the worker to self-report.

Carry forward these validated product ideas:

- Server-derived evidence is the core product. Run IDs, profile metadata, normalized dialogue, tool events, permission records, file attribution, check evidence, warnings, liveness, and reports should come from Orbital, not from worker final prose.
- Primary-safe summaries are necessary for ordinary control flow. The primary harness should be able to poll concise status and review bounded summaries without reading raw transcripts by default.
- Handoff/session state is valuable in V1. Durable objectives, handoff items, bounded tasks, attempts, primary reviews, repair seeds, and reports let the primary harness manage real multi-run work rather than reconstructing state from prompts.
- Liveness is a safety feature, not a UI extra. The first draft showed that quiet server output does not always mean the worker is stalled; primary harnesses need stop guidance before cancelling long or quiet runs.
- Exact-only telemetry is the right trust boundary. Adapter-observed secondary usage, primary-reported usage, and external model-log telemetry should remain separate unless exact correlation exists.
- Compatibility adapters are useful, but capability gaps must be explicit. CLI fallbacks can provide value, but they usually have weaker permissions, telemetry, follow-up dialogue, and tool-event semantics than ACP adapters.

Rework these first-draft weaknesses:

- Replace default/local-first profile selection with explicit profile choice or classification-based recommendations. Orbital should recommend; the primary harness should choose.
- Add support tiers so profile templates, experimental ACP adapters, known-good ACP adapters, and CLI fallbacks are not presented as equivalent.
- Define restart and recovery behavior for active runs, interrupted processes, partial logs, and pending permissions before users depend on them.
- Move from binary command blocking toward capability-based safety: prompt-only, adapter-mediated, process-observed, and sandbox-enforced.
- Keep public docs focused on MCP-to-ACP delegation. Benchmark, playbook, and SDLC language can exist as examples or later layers, but should not define the core product surface.
- Treat real ACP harness conformance as the central near-term product hardening work. Richer Git/SDLC integration and stronger sandbox execution can build on the delegation layer later, but they should not displace adapter trust as the V1 wedge.

## Product Goals

- Make multi-harness coding delegation easy to install and run locally.
- Hide ACP and harness-specific protocol details behind one MCP tool surface.
- Support multiple configured secondary harnesses, including OpenCode, Pi, Codex, Claude Code CLI fallback, and API-backed Claude Agent SDK ACP.
- Let users classify harnesses by task suitability, cost posture, auth mode, capabilities, and operating constraints.
- Give primary harnesses enough structured evidence to judge delegated work without trusting worker final prose.
- Preserve a clean boundary between primary-only orchestration guidance and worker-safe task instructions.
- Preserve durable handoff/session state for multi-run delegation loops.
- Stay useful as a standalone open source MCP before any SDLC-specific product layer exists.

## Non-Goals

- Orbital is not a project management system.
- Orbital is not a full SDLC agent, ticketing system, CI manager, or benchmark harness in the first product version.
- Orbital should not decide whether product requirements are satisfied. It should supply evidence and routing signals; the primary harness remains the reviewer.
- Orbital should not require every secondary harness to expose identical capabilities. It should normalize what it can and report capability gaps explicitly.
- Orbital should not estimate token usage or model identity when adapters do not expose exact data.
- Orbital should not describe permission or command policy as hard sandboxing unless it is actually running workers inside an enforced sandbox or container.

## Primary Users

- Developers who use a high-capability primary harness and want local or cheaper secondary workers for implementation tasks.
- Tool builders who want a stable MCP surface for running multiple ACP-capable harnesses.
- Open source contributors who want to add harness adapters or improve evidence capture without adopting a larger SDLC product.

## Product Boundary

### Primary Harness

The primary harness:

- receives the user's high-level objective
- decomposes it into bounded task requests
- reviews Orbital's profile recommendations when useful
- selects or confirms a secondary harness profile
- resolves permissions conservatively
- inspects changed files, checks, warnings, and evidence
- decides whether a run is accepted, rejected, or needs repair
- reports outcome and remaining risk to the user

### Orbital MCP

Orbital:

- stores harness profile configuration
- detects harness readiness
- recommends matching profiles from classification and capability metadata
- launches secondary harnesses
- speaks ACP where available
- exposes non-ACP compatibility adapters only when needed
- normalizes dialogue, tool activity, permissions, checks, liveness, telemetry, and file changes
- stores run and session artifacts locally
- returns primary-safe summaries and deterministic routing hints

### Secondary Harness

The secondary harness:

- receives a bounded task prompt
- edits, tests, and reports within the selected runtime
- emits ACP events, permission requests, tool updates, usage payloads, or CLI output that Orbital normalizes

## Core Workflows

### 1. Install And Connect

The user should be able to install Orbital, run a doctor command, and generate MCP host configuration without reading adapter internals.

Expected flow:

1. Install Orbital.
2. Run diagnostics.
3. Generate MCP config for the user's primary harness.
4. Start the MCP server.
5. Confirm the primary harness can call `get_server_info`.

### 2. Add Harness Profiles

The user should be able to add multiple local harnesses with explicit profile metadata.

Each profile should include:

- stable profile ID
- display name
- runtime family, such as `opencode`, `pi`, `codex`, or `claude_code`
- adapter protocol, usually `acp`
- command and arguments
- auth mode
- cost posture
- capability flags
- permission behavior
- optional environment variables
- optional policy restrictions
- task classification tags

### 3. Classify Harnesses

Orbital should expose harness classification so the primary harness can choose a secondary worker based on the task.

Example classification dimensions:

- `implementation`: general code edits
- `test_repair`: test creation and repair
- `refactor`: narrow refactors
- `frontend`: UI implementation
- `backend`: services, APIs, data modeling
- `analysis`: code exploration and diagnosis
- `docs`: documentation edits
- `fast_smoke`: small low-risk tasks
- `long_context`: broad file-reading tasks
- `local_only`: no metered API
- `needs_manual_permissions`: requires primary permission decisions

Classifications are advisory. The primary harness chooses and remains accountable for the assignment.

Recommendation output should include enough context for the primary harness to make a conservative choice:

- readiness
- support tier
- capability matches and gaps
- classification matches
- locality and cost posture
- known limits
- reasoned ranking

Orbital should not silently switch profiles during a session unless the primary explicitly starts a new run with a different profile.

### 4. Delegate A Task

The primary harness should be able to start a bounded run with:

- workdir
- task title
- objective
- target profile or classification query
- allowed paths
- forbidden paths
- constraints
- acceptance hints
- requested checks
- worker-safe rules

Orbital should return a run ID immediately and let the primary poll primary-safe status.

### 5. Review Evidence

The primary harness should receive:

- terminal status
- selected profile metadata
- changed files
- changed files since run start
- pre-existing dirty files
- pending and resolved permission requests
- requested check evidence
- normalized tool evidence
- warnings and failure classifications
- final worker response
- bounded dialogue when explicitly requested
- log references for audit
- exact model and token telemetry when available

Worker prose is context, not proof.

### 6. Repair Loop

Orbital should help the primary harness turn a failed or partial run into a smaller repair task.

The product should support:

- deterministic verdicts such as `accept_candidate`, `needs_repair`, `reject`, and `blocked`
- repair seeds derived from server-observed gaps
- run assessments recorded by the primary harness
- session-level reporting for multiple attempts
- session warnings for workflow drift, such as profile mismatch, path-scope violations, unreviewed attempts, accepted runs without review evidence, and stopping without a stop-safe liveness recommendation

This remains a generic delegation loop, not an SDLC workflow.

### 7. Handoff Sessions

Handoff/session tools are part of the first product version. They preserve durable state across a primary harness and one or more secondary runs without making Orbital an SDLC system.

The session model should use generic delegation language:

- objective
- handoff item
- task
- attempt
- review
- repair
- report

The model should avoid workflow-specific assumptions such as sprint ownership, issue tracker state, branch policy, PR review gates, release approvals, or CI ownership. Future SDLC products can map their own nouns onto Orbital's generic handoff model.

The session model should preserve the first draft's useful operating loop:

1. Start a session with a high-level objective, workdir, primary harness, and optional preferred profile.
2. Record handoff items that describe what must be true and what proof is needed.
3. Create bounded tasks linked to one or more handoff items.
4. Start attempts from those tasks.
5. Poll status digests and liveness while attempts run.
6. Record primary reviews after inspecting evidence and files.
7. Create repair tasks from deterministic server-observed gaps.
8. Finish the session with final status, summary, and verification.

## Product Principles

- ACP first. Prefer ACP adapters for all supported harnesses.
- Honest Claude paths. Treat Claude Code CLI as the local/subscription fallback path, and Claude Agent SDK ACP as an API-key, metered profile unless a local-subscription Claude ACP command is verified.
- Primary-safe by default. Raw transcripts are opt-in debug material.
- Honest unknowns. Unknown tokens, model names, checks, capabilities, and classifications should stay unknown.
- Local and open. The default product should work as a local open source MCP.
- Configurable but explicit. Avoid hidden profile switching, hidden API fallback, or implicit credential use.
- Capability-based safety. Orbital should distinguish what it can enforce, what it can mediate through ACP permissions, and what it can only observe or report.
- Evidence over vibes. Orbital should record observable facts, not infer success from natural language.
- Worker prompts stay bounded. Primary-only guidance must not leak into secondary task prompts.

## Open Questions

- What exact ACP command should Pi expose, and which capability flags are reliably available?
- What exact profile defaults should Orbital ship for `claude_agent_acp_api`, including required Node version, `claude-agent-acp` installation, and `ANTHROPIC_API_KEY` diagnostics?
- Which harnesses should be labeled known-good ACP support, experimental ACP support, profile-template-only support, or CLI fallback support at launch?
- Should profile classification be purely user-authored, or should Orbital support optional measured performance notes later?
- Should profile selection by classification be a dedicated MCP tool, or folded into `start_task_run`?
- What is the minimum handoff/session tool contract needed for v1 without importing SDLC-specific workflow semantics?
- What should the package, executable, and storage names be after the Orbital rename?
- What container or sandbox mode should Orbital support later if stronger command policy enforcement becomes part of a higher-assurance deployment mode?
