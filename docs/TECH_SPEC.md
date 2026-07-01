# Orbital Technical Spec

## Summary

Orbital should be a local MCP server with ACP-first harness adapters. It provides a stable tool surface for primary harnesses and a profile registry for secondary harnesses. The current repository already sketches many useful primitives; Orbital should keep the strongest ones while simplifying the product contract around multi-harness ACP delegation.

## Architecture

```text
Primary Harness
    |
    | MCP tools
    v
Orbital MCP Server
    |
    | Profile registry, task router, run service, evidence store
    v
Harness Adapter
    |
    | ACP JSON-RPC where available
    v
Secondary Harness
```

Core components:

- MCP server: exposes stable tools to primary harnesses.
- Profile registry: loads configuration, checks readiness, exposes classification metadata and capabilities.
- Task router: selects a profile by explicit ID or classification query.
- Adapter layer: normalizes ACP or compatibility protocol events.
- Run service: manages lifecycle, permissions, snapshots, and status.
- Evidence store: persists runs, dialogue, transcripts, permissions, summaries, and sessions.
- Policy layer: mediates, blocks, or flags risky command patterns and forbidden scope changes according to the active enforcement level.
- Reporting layer: produces primary-safe run summaries and multi-run reports.

The Prole Harness MCP first draft validates this component split, but Orbital should make the contracts sharper before rebuilding. In particular, profile recommendation, storage recovery, adapter support tiers, permission restart behavior, and primary-safe redaction should be explicit product contracts rather than incidental implementation behavior.

## Lessons From Prole Harness MCP

Orbital should carry forward these first-draft implementation patterns:

- Dataclass or schema-backed records for task inputs, profiles, runs, permissions, summaries, policy verdicts, repair seeds, sessions, attempts, reviews, reports, telemetry, and liveness.
- A server-owned run store with `run.json`, `dialogue.jsonl`, `transcript.log`, `stderr.log`, `permissions.jsonl`, and `final_report.json`.
- Primary-safe responses that omit raw dialogue by default and expose raw inspection only through bounded debug tools.
- Normalized event vocabulary for agent text, tool starts, tool updates, tool completions, tool failures, permission requests, permission results, stderr, policy violations, run errors, and run stops.
- Deterministic failure classifications such as `policy_violation`, `missing_requested_check`, `failed_requested_check`, `unknown_requested_check`, `no_op_pass`, `no_completed_tool_calls`, `acceptance_check_failed`, `changed_outside_allowed_paths`, `changed_forbidden_paths`, `permission_denied_or_cancelled`, `worker_error`, `stopped`, and `interrupted`.
- Policy verdicts that convert observable evidence into `accept_candidate`, `needs_repair`, `reject`, `blocked`, or `requires_primary_review`.
- Repair seeds that preserve original scope, checks, and acceptance hints while narrowing the next attempt to server-observed gaps.
- Liveness analysis that fuses run status, latest event time, pending permission state, pending tool state, process state, and optional external model-log activity.
- Exact-only telemetry that keeps primary usage, secondary adapter usage, and external model-log usage separate unless exact correlation exists.
- Session warnings that identify workflow drift without making Orbital the final acceptance authority.

Orbital should deliberately rework these first-draft limitations:

- Profile routing should not be default-first or local-first. It should be explicit profile ID selection or classification-based recommendation with reasons.
- Profile metadata needs classification, support tier, known limits, and capability gaps.
- File storage needs atomic writes, locking, recovery, retention, and schema migration rules.
- Pending permissions must have a defined behavior after server restart.
- Command policy should not be hard-coded as blanket denial. It should be policy-configurable and reported according to the active enforcement level.
- Debug dialogue, transcript reads, and summary generation must be bounded to avoid primary-context flooding.
- Compatibility adapters should be represented as lower capability tiers rather than hidden behind the same promise as known-good ACP adapters.

## Profile Model

Orbital profiles should be explicit and portable.

Suggested schema:

```json
{
  "id": "opencode_acp_local",
  "display_name": "OpenCode local",
  "runtime_family": "opencode",
  "adapter": "acp",
  "command": ["opencode", "acp", "--pure"],
  "auth_mode": "local_subscription",
  "cost_posture": "subscription_preferred",
  "enabled": true,
  "capabilities": ["dialogue", "permissions", "tool_events", "stop"],
  "permission_behavior": "manual",
  "classification": {
    "task_tags": ["implementation", "test_repair", "fast_smoke"],
    "strengths": ["small implementation changes", "test repair"],
    "limits": ["avoid broad architecture rewrites"],
    "max_recommended_scope": "small",
    "cost_preference": "subscription_preferred",
    "locality": "subscription"
  },
  "support": {
    "tier": "known_good_acp",
    "notes": []
  },
  "env": {},
  "policy": {
    "scrub_api_key_env": true,
    "approval_mode": "primary_mediated",
    "default_command_policy": "ask_primary",
    "block_mcp_servers": []
  }
}
```

Required profile fields:

- `id`
- `display_name`
- `runtime_family`
- `adapter`
- `command`
- `auth_mode`
- `cost_posture`
- `enabled`
- `capabilities`
- `classification.task_tags`

Optional but recommended profile fields:

- `classification.strengths`
- `classification.limits`
- `classification.max_recommended_scope`
- `classification.cost_preference`
- `classification.locality`
- `support.tier`
- `support.notes`

Supported runtime families for the first product pass:

- `opencode`
- `pi`
- `codex`
- `claude_code`

Supported adapters:

- `acp`: primary target
- `cli`: compatibility fallback for harnesses without usable ACP
- `api`: deferred or disabled by default

Support tiers:

- `known_good_acp`: adapter has conformance fixtures and smoke-run coverage.
- `experimental_acp`: profile exists and ACP appears usable, but fixtures or smoke coverage are incomplete.
- `profile_template`: configuration guidance exists, but Orbital should not imply launch-time support.
- `cli_fallback`: Orbital can launch and observe CLI behavior, but normalized ACP capabilities are unavailable or partial.

Orbital should report support tier and capability gaps separately. A profile can be ready to launch while still lacking permissions, usage telemetry, stop support, or complete tool-event normalization.

Readiness and support tier are different:

- Readiness answers whether Orbital can attempt to launch a profile in the current environment.
- Support tier answers how much trust the adapter/profile has earned through fixtures, smoke runs, and known capability coverage.
- Capability gaps answer which normalized features the primary harness should not assume for a particular profile.

For example, a CLI profile can be ready and useful while still reporting `cli_fallback`, `supports_permissions=false`, `supports_followup_messages=false`, and `usage_telemetry=unknown`.

## Classification Model

Classifications should be profile metadata, not hard-coded product truth. The primary harness may ask Orbital for matching profiles, but the primary chooses the final assignment.

Profile classification fields:

- `task_tags`: broad task suitability labels
- `strengths`: free-form user-visible notes
- `limits`: known weaknesses or constraints
- `max_recommended_scope`: optional label such as `tiny`, `small`, `medium`, or `large`
- `cost_preference`: optional ranking hint
- `locality`: `local`, `subscription`, `metered_api`, or `unknown`

Orbital should expose both raw profile metadata and normalized selection hints.

Profile recommendation algorithm:

- Filter disabled profiles unless explicitly requested.
- Filter out not-ready profiles unless the caller asks for diagnostics.
- Match requested `task_tags` against `classification.task_tags`.
- Prefer profiles with required capabilities when specified.
- Penalize support tiers with lower confidence, but do not hide them unless the caller disallows them.
- Apply locality and cost preferences deterministically.
- Return all meaningful caveats rather than collapsing them into a single score.

Recommendation output should be deterministic for the same inputs and config. Each recommendation should include:

- `profile_id`
- `rank`
- `ready`
- `support.tier`
- `matched_task_tags`
- `missing_task_tags`
- `matched_capabilities`
- `missing_capabilities`
- `cost_posture`
- `locality`
- `reasons`
- `caveats`

Orbital should not start a run from `recommend_harness_profiles`; the primary harness should pass the chosen profile ID to `start_task_run` or intentionally use a classification query in `start_task_run`.

## MCP Tool Surface

Orbital should keep the tool surface small and stable.

### Discovery And Setup

- `get_server_info`
- `list_harness_profiles`
- `get_harness_profile`
- `check_harness_profile`
- `recommend_harness_profiles`

`recommend_harness_profiles` takes task tags and selection preferences, then returns ranked ready profiles with reasons. It does not start a run.

Minimum request and response contracts:

- `get_server_info` returns server name, version, storage root, supported adapter families, supported MCP tool versions, and feature flags.
- `list_harness_profiles` accepts optional filters for enabled state, readiness, runtime family, support tier, adapter, task tags, locality, cost preference, and capability flags. It returns stable profile IDs, display names, readiness summaries, support tiers, capabilities, and classification metadata.
- `get_harness_profile` accepts a profile ID and returns full non-secret profile configuration, readiness state, support tier, capability gaps, and diagnostics.
- `check_harness_profile` accepts a profile ID and optional workdir. It returns executable availability, auth readiness, adapter handshake result when safe, support tier, capability observations, and actionable diagnostics.
- `recommend_harness_profiles` accepts task tags, optional required capabilities, optional disallowed support tiers, optional locality or cost preferences, and optional workdir. It returns ranked profiles with deterministic reasons, caveats, readiness state, and unsupported requirement details.

Errors should use stable codes such as `profile_not_found`, `profile_disabled`, `profile_not_ready`, `unsupported_adapter`, `invalid_filter`, and `diagnostic_failed`.

Tool errors should include:

- stable `code`
- human-readable `message`
- optional `details`
- whether the error is retryable
- whether user action is required

### Runs

- `preflight_task_run`
- `start_task_run`
- `send_task_message`
- `get_run_status_digest`
- `get_run_summary`
- `get_debug_dialogue`
- `resolve_permission`
- `get_run_liveness`
- `stop_task_run`
- `list_task_runs`

Primary-safe tools should omit raw events by default. `get_debug_dialogue` should be the explicit raw-inspection path.

Minimum run contracts:

- `preflight_task_run` validates the task input, profile selection or classification query, workdir, path scope, requested checks, and policy settings. It returns selected or candidate profiles, warnings, blocking errors, and permission expectations without starting a worker.
- `start_task_run` accepts either an explicit profile ID or a classification query, plus the task input model. It returns a run ID immediately after durable run creation and launch attempt recording.
- `send_task_message` appends a bounded worker-safe message to an active run when the adapter supports continued dialogue. It must reject primary-only orchestration guidance.
- `get_run_status_digest` returns primary-safe status, liveness headline, latest safe worker update, pending permissions, changed-file counts, check status, warning count, and next recommended poll interval.
- `get_run_summary` returns the full primary-safe evidence model after completion or on request for active runs. It should include unknown fields explicitly rather than omitting them.
- `get_debug_dialogue` requires an explicit run ID and should support bounded ranges or byte limits so raw transcript access cannot accidentally flood the primary context.
- `resolve_permission` accepts a permission request ID, decision, optional edited command or scope, and rationale. It records the primary decision and returns whether the adapter accepted it.
- `get_run_liveness` returns the liveness model described below and should be callable for any active or recently interrupted run.
- `stop_task_run` requests cooperative cancellation first when the adapter supports it, then records whether process termination was attempted or required.
- `list_task_runs` supports filtering by session ID, profile ID, status, workdir, and time range, with pagination.

Run statuses should include at least `created`, `launching`, `running`, `waiting_for_permission`, `stopping`, `completed`, `failed`, `blocked`, `cancelled`, and `unknown`.

Tool responses should include stable `schema_version` fields. Breaking response changes should be gated behind a new schema version or feature flag.

Run status semantics:

- `created`: run record exists durably, but launch has not started.
- `launching`: worker process launch or adapter initialization is in progress.
- `running`: worker has accepted the task or is emitting events.
- `waiting_for_permission`: run has at least one pending permission request and the adapter can pause for a decision.
- `stopping`: cooperative stop or process termination has been requested.
- `completed`: worker reached a successful terminal status; this is still only an acceptance candidate.
- `failed`: worker, adapter, check, policy, or acceptance-output validation failed.
- `blocked`: run cannot continue without an external decision or missing prerequisite.
- `cancelled`: primary or user intentionally stopped the run.
- `interrupted`: Orbital lost process/control continuity or recovered an active run after restart without a clean terminal state.
- `unknown`: stored state is incomplete, corrupt, or too old to classify safely.

Orbital should map adapter-native terminal statuses into these normalized statuses and preserve adapter-native status in debug metadata.

### Multi-Run Handoff

Keep a generic session model, but do not make it SDLC-specific.

- `start_handoff_session`
- `create_handoff_item`
- `create_task_ticket`
- `start_ticket_run`
- `record_run_review`
- `get_next_recommended_action`
- `create_repair_ticket_from_run`
- `finish_handoff_session`
- `get_handoff_report`

Names can change during the rebuild, but the concept should remain: a primary harness needs durable state for objective, requirements or handoff items, tickets, attempts, reviews, and final report.

Handoff/session tools are in V1 scope. They should remain generic delegation primitives and avoid SDLC-specific assumptions. If the word `ticket` remains in API names, public docs should define it as a bounded local task record, not an issue tracker object.

Session warnings:

Orbital should maintain structured warnings that help the primary detect workflow drift:

- `profile_mismatch`: a run used a different profile than the session preferred profile.
- `changed_outside_allowed_paths`: a run changed files outside task scope.
- `changed_forbidden_paths`: a run changed forbidden paths.
- `accepted_missing_review_evidence`: the primary marked a run accepted without inspected files or verification commands.
- `unsatisfied_handoff_items`: a finished session still has unsatisfied handoff items.
- `unreviewed_attempts`: one or more attempts have no primary review.
- `stop_without_liveness_check`: a run was stopped without a recent stop-allowed liveness recommendation.
- `pending_permissions_on_finish`: a session was finished while one or more runs still had pending permissions.
- `unattributed_final_files`: final dirty files cannot be attributed to selected runs.

Session warnings are evidence for the primary harness. They should not automatically change final acceptance unless the primary chooses to treat them as blocking.

## ACP Adapter Contract

The ACP adapter should normalize:

- initialization
- session creation
- prompt submission
- text updates
- tool call starts, updates, completions, and failures
- permission requests
- permission results
- stop or cancel behavior
- model selection when supported
- exact token/model usage when exposed

Adapter output must preserve:

- raw transcript references
- normalized event kind
- speaker
- text summary
- raw payload in debug logs
- event timestamp
- run ID

ACP compatibility differences should be hidden from primary harnesses. If OpenCode, Pi, Codex, or Claude Code use slightly different ACP event shapes, adapters should map them to the same event vocabulary.

Adapter conformance fixtures:

Each supported runtime family should have fixture transcripts or fake harnesses that cover:

- initialize and session creation
- prompt submission
- streamed text updates
- tool start/update/completion/failure
- permission request and resolution
- stderr capture
- stop/cancel behavior
- exact token usage when exposed
- exact model metadata when exposed
- malformed or unknown event shapes

A profile should not be labeled `known_good_acp` until its adapter passes conformance fixtures and at least one smoke run.

Compatibility adapters:

CLI adapters can remain valuable, but they must explicitly report weaker capabilities. For example, a CLI fallback may provide dialogue and tool-ish stream parsing while lacking interactive permission mediation, continued dialogue, or exact usage telemetry.

## Task Input Model

Task input should stay bounded and worker-safe.

Fields:

- `title`
- `objective`
- `workdir`
- `allowed_paths`
- `forbidden_paths`
- `constraints`
- `acceptance_hints`
- `checks`
- `rules`
- `task_tags`
- `runtime_mode`
- `allow_metered_api`

Do not inject primary-only orchestration strategy into worker prompts. The worker prompt should contain only the task slice, scope, checks, and safe constraints.

Path fields should be resolved relative to `workdir` unless absolute paths are explicitly allowed by policy. Orbital should reject path scopes that escape `workdir` unless the primary explicitly grants that scope.

Worker prompt construction:

Orbital should generate worker startup prompts only from worker-safe task fields:

- title
- objective
- workdir
- allowed paths
- forbidden paths
- constraints
- acceptance hints
- requested checks
- rules

Orbital should not inject primary-only guidance, retry strategy, scoring rubrics, session report expectations, profile-selection reasoning, or hidden orchestration instructions into worker prompts. This first-draft boundary was important enough to keep as a regression test.

## Run Evidence Model

Run summaries should preserve the current sketch's most useful ideas:

- status
- status reason
- selected profile
- workdir
- changed files
- pre-existing dirty files
- changed files since run start
- final response
- latest agent response
- pending permission requests
- permission counts
- tool timeline
- evidence
- exact token telemetry when known
- exact model telemetry when known
- warning details
- failure classifications
- log references

Evidence should include:

- tool call counts by normalized kind
- completed write/edit count
- completed execute count
- requested check status
- permission counts
- policy violations

File attribution should eventually integrate with `../ngitd-core` for extended Git state capture and richer dirty-workdir management. Until that integration exists, Orbital should define and test a simpler fallback:

- require a readable workdir
- detect whether the workdir is a Git repository
- capture baseline tracked modifications, staged changes, untracked files, and ignored-file visibility when available
- record pre-existing dirty files before launch
- record changed files since run start after completion or polling
- mark attribution as `unknown` when files change concurrently or when the workdir is not Git-backed

The summary should distinguish `pre_existing_dirty`, `changed_during_run`, `possibly_concurrent_change`, `untracked`, `deleted`, `renamed`, and `unknown_attribution` when the underlying data supports it.

First-draft attribution caveats to address:

- Hashing the whole tree is simple but can be expensive on large repositories.
- Git `status --porcelain` output needs careful treatment for untracked directories, ignored files, renames, deletes, and nested repositories.
- Concurrent user edits can make run attribution uncertain.
- Generated artifacts such as caches should be identified separately from source changes.
- A final dirty file may be changed by a rejected run and still present after an accepted repair; reports should surface that explicitly.

Orbital should mark attribution confidence per file or per summary. Suggested values: `high`, `medium`, `low`, and `unknown`.

## Handoff Data Model

Orbital should model primary-to-secondary handoff generically enough for future SDLC layers, without becoming one.

Entities:

- Session: objective, workdir, preferred profile, primary harness, run IDs, reviews, final status.
- Handoff item: requirement-like statement, proof needed, status, evidence.
- Ticket: bounded task objective, item IDs, allowed paths, checks, acceptance hints, rules.
- Attempt: ticket ID, run ID, attempt number, review decision.
- Review: primary judgment, rationale, inspected files, verification commands, repair prompt.
- Report: timing, profile mix, run counts, evidence summary, attribution, token accounting, warnings.

The handoff model should avoid SDLC nouns such as sprint, epic, story, branch policy, release gate, and owner assignment in v1.

## Storage

Default storage should be file-backed and local.

Suggested layout after rename:

```text
.orbital/
  config.json
  runs/
    <run-id>/
      run.json
      dialogue.jsonl
      transcript.log
      stderr.log
      permissions.jsonl
      final_report.json
  sessions/
    <session-id>/
      session.json
      primary_tokens.jsonl
```

File storage keeps the open source product easy to inspect, test, and debug. A database can be considered later if concurrent or hosted use cases require it.

Storage invariants:

- Run IDs and session IDs must be globally unique enough for local concurrent use and safe as path names.
- `run.json` and `session.json` writes should be atomic, using write-then-rename behavior.
- Event-style files such as `dialogue.jsonl`, `permissions.jsonl`, and telemetry logs should be append-only.
- The store should tolerate interrupted runs and partial logs; recovery should mark uncertain active runs as `unknown` or `interrupted` with a diagnostic.
- Concurrent writes to the same run or session should use a lock file or equivalent process-local synchronization.
- Large logs should have configurable retention or truncation settings. Primary-safe summaries should reference truncated logs explicitly.
- Debug transcripts should not be loaded into memory unboundedly for summary generation.
- The storage schema should include a version so future migrations can be explicit.
- Orbital should provide a diagnostic command or tool result that identifies storage corruption, partial writes, and unsupported schema versions.

Recovery requirements:

- On startup, Orbital should scan non-terminal runs in storage.
- If a run has no active controller in this server process, Orbital should mark it `interrupted` or `unknown` unless it can safely reattach to the adapter.
- Pending permissions from a previous process should remain visible in summaries, but `resolve_permission` should return a stable `permission_not_resolvable_after_restart` error unless adapter reattachment is supported.
- Interrupted runs should preserve all existing artifacts and be eligible for report inclusion.
- Recovery should never delete raw logs or overwrite final reports without recording a recovery event.
- If JSONL files contain malformed lines, Orbital should skip malformed entries for bounded reads, report corruption diagnostics, and avoid failing the entire summary when possible.

Retention requirements:

- Transcript and stderr tails should support bounded reads.
- Debug dialogue should support `since_event_id`, event-kind filters, maximum event count, and maximum character/byte limits.
- Summary generation should read only the bounded data it needs, except for explicit offline report generation.

## Security And Permissions

Default stance:

- local-first
- no hidden API fallback
- scrub API key environment variables for local subscription profiles unless explicitly overridden
- route risky worker actions through primary-mediated permission approval when the adapter exposes permission requests
- allow policy to require approval for package installs, network-capable commands, destructive commands, scope expansion, and external MCP server use
- record all permission requests and decisions
- keep secret values out of summaries and prompts
- treat policy violations as server evidence

Orbital should not claim OS-level sandboxing unless it actually enforces it.

Policy enforcement levels:

- `prompt_only`: Orbital can include rules in the worker prompt but cannot enforce them.
- `adapter_mediated`: Orbital can approve, deny, or modify adapter-emitted permission requests.
- `process_observed`: Orbital can observe process state, output, and some command evidence but cannot guarantee prevention.
- `sandbox_enforced`: Orbital runs the worker in an actual sandbox or container and can enforce filesystem, network, or process limits.

The default local open source mode should be honest about the active enforcement level. A future containerized mode can support stronger defaults for package installs, network use, destructive commands, and path isolation.

Permission decisions:

- The primary harness should be able to approve reasonable risky actions with an explicit rationale.
- Orbital should record the original request, normalized risk category, decision, deciding primary harness, timestamp, and resulting adapter action.
- When an adapter cannot pause for permission approval, Orbital should report the gap as a capability limitation instead of implying enforcement.
- If Orbital only detects a violation after the fact, it should classify it as observed evidence, not as a prevented action.

Permission normalization:

Orbital should normalize adapter permission shapes into:

- `permission_id`
- `run_id`
- `adapter_request_id`
- `status`
- `summary`
- `risk`
- `paths`
- `options`
- `raw_ref`
- `resolved_option_id`
- `decision_rationale`

Option matching should prefer explicit option IDs from the adapter. If the primary supplies only `approve` or `deny`, Orbital may infer the adapter option from labels/kinds only when exactly one option matches. Ambiguous or missing options should return a stable error and require explicit `option_id`.

Post-restart behavior must be clear: stored pending permissions are evidence, but not necessarily actionable.

Primary-safe redaction:

- Secret-looking environment values, tokens, API keys, credentials, and private key material must be redacted from summaries, prompts, and primary-safe status tools.
- Raw transcripts and stderr logs may contain sensitive material and should be exposed only through explicit debug tools with bounded reads.
- Worker final responses and latest updates should be scrubbed before appearing in primary-safe summaries.
- Log references should identify local paths or run-relative artifact names without embedding secret content.
- Redaction should be best-effort and documented as such unless paired with a stronger secret scanner.

## Liveness

Keep liveness as a first-class safety feature.

Inputs:

- run status
- latest event time
- pending permission state
- process state
- optional model log activity

Output:

- verdict
- stop safety
- recommended action
- severity
- summary
- next check interval

Primary harnesses should call liveness before stopping quiet runs.

Stop behavior:

- `stop_task_run` should record whether a recent liveness check existed and whether it allowed stopping.
- If no stop-allowed liveness recommendation exists, Orbital may still stop when the primary explicitly requests it, but should add a session warning.
- Stop should attempt cooperative adapter cancellation first when supported.
- Process termination should be recorded separately from cooperative cancellation.
- Pending permissions should be cancelled or marked `unknown` when a run is stopped, according to adapter capability.

## Telemetry

Telemetry should be exact-only.

- Secondary tokens come from adapter-observed usage payloads.
- Primary tokens are recorded only when the primary harness reports exact usage.
- External model-log telemetry stays separate unless it can be correlated to a specific run.
- Unknown model or token fields should remain explicit unknowns.

Telemetry aggregation:

- Secondary run telemetry should aggregate exact adapter-observed usage records from normalized events and raw transcript payloads.
- Primary telemetry should be appended by the primary harness with source, scope, optional run ID, optional model, exact counts, and notes.
- Session reports should expose primary, secondary, and combined token accounting separately.
- Combined totals should be known only when both primary and secondary totals are known exactly.
- External model-log telemetry should include provider, source, attribution, latest record, and caveats. It should not be folded into primary/secondary totals without run-correlation metadata.

## Migration From Current Sketch

Carry forward:

- profile registry and readiness checks
- ACP adapter normalization
- local subscription auth posture
- permission request normalization
- task input boundaries
- run store and file snapshots
- primary-safe status digest
- run summary evidence model
- policy verdicts and repair seeds
- liveness analysis
- session/report concepts
- fake ACP harness and adapter conformance fixture strategy
- exact-only primary/secondary/model-log telemetry separation
- deterministic repair seed generation
- session warnings for workflow drift

Rework:

- rename package, commands, config, and storage from Prole Harness to Orbital
- make classification part of profiles
- add Pi ACP profile support
- reduce benchmark/playbook language in public docs
- separate generic handoff sessions from later SDLC workflows
- simplify install and setup docs for open source adoption
- replace default-first profile routing with classification-based recommendations
- add restart/recovery semantics for active runs and pending permissions
- harden file storage with atomic writes, locks, bounded reads, retention, and migration rules
- turn command policy into configurable capability-based approval and evidence

Defer:

- hosted multi-user service
- hard sandboxing
- automatic product acceptance
- benchmark scoring as a first-class product feature
- SDLC-specific ticket, release, and CI policy layers
