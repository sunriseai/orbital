# Orbital

<p>
  <img src="assets/orbital_logo.svg" alt="Orbital logo" width="120">
</p>

Orbital is an MCP delegation layer for running, supervising, and reviewing secondary coding agents.

It runs locally and gives the primary harness a stable control surface for profile selection, ACP/CLI adapter launch, permission mediation, evidence capture, liveness checks, file attribution, and structured handoff sessions.

The current implementation is intentionally CI-safe to validate: the default tests use local fake harnesses and do not require clicks, credentials, network access, real model calls, or installed real harnesses.

## Get Started

Prerequisites:

- Python 3.11 or newer.
- A shell in the repository root.
- Optional: a real ACP-capable harness such as Codex or OpenCode for manual local ACP smoke tests. Claude Code CLI is represented as a CLI fallback; Claude Agent SDK ACP is represented as a disabled, API-backed profile that requires explicit setup. The default test suite does not need a real harness.

Install for local development:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
```

Run the unattended validation suite:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Run the syntax check used during development:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m py_compile $(find src tests -name '*.py' -print)
```

Run optional smoke gates when you want broader runtime validation:

```bash
ORBITAL_RUN_PACKAGING_SMOKE=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
ORBITAL_RUN_REAL_HARNESS_SMOKE=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_validation_optional_smoke.py -v
```

The default suite includes a real MCP stdio transport smoke against the local fake harness. `ORBITAL_RUN_PACKAGING_SMOKE=1` additionally creates a temporary virtualenv, installs Orbital from a copied source tree, and verifies the installed console scripts. `ORBITAL_RUN_REAL_HARNESS_SMOKE=1` defaults to trying `codex_acp_local` and `opencode_acp_local`, skipping profiles that `orbital doctor` reports as not ready. Set `ORBITAL_REAL_HARNESS_PROFILES=<profile[,profile]>` to narrow or override that list; use `ORBITAL_REAL_HARNESS_PROFILES=codex_acp_official` to explicitly test the official `@agentclientprotocol/codex-acp` profile. Claude ACP should be tested through explicit API-backed `claude_agent_acp_api` setup, not through a local-subscription Claude Code ACP profile.

Run manual smoke wrappers when you want a timestamped log under `tests/manual/logs/`:

```bash
./tests/manual/run_manual_faux_harness_smoke.sh
./tests/manual/run_manual_local_codex_acp_smoke.sh
./tests/manual/run_manual_official_codex_acp_smoke.sh
./tests/manual/run_manual_local_opencode_acp_smoke.sh
./tests/manual/run_manual_local_codex_acp_permission_smoke.sh
./tests/manual/run_manual_official_codex_acp_permission_smoke.sh
./tests/manual/run_manual_local_opencode_acp_permission_smoke.sh
```

`run_manual_faux_harness_smoke.sh` stays CI-safe and uses fake harnesses. The `run_manual_local_*_acp_smoke.sh` scripts each target one installed/authenticated local ACP harness and may launch a real Codex or OpenCode worker. They also run `tests/manual/run_token_probe.py`, which fails unless `get_run_summary().tokens` reports canonical `external_agent_logs` telemetry for one uniquely correlated real local run. The OpenCode script also records `opencode --version`, `opencode acp --help`, and an ACP initialize handshake before the smoke task. The official Codex wrappers target `codex_acp_official`, which runs `npx -y @agentclientprotocol/codex-acp` with `INITIAL_AGENT_MODE=read-only`; the first run may download the package. Claude Agent SDK ACP smoke should be added here only after `claude_agent_acp_api` has a verified API-key setup path. Each script prints its scope and prerequisites before running.

The local permission smoke wrappers separately probe whether a real Codex/OpenCode ACP runtime emits a permission request that Orbital can expose and resolve. A `pass` result means the full primary-mediated approval path was exercised. A `permission_capability_gap` result means the secondary harness completed the task without emitting an ACP permission request, so Orbital had no real permission event to mediate; this is a runtime capability/configuration gap, not evidence that Orbital dropped a request.

### Token Telemetry

Orbital treats token telemetry as exact-only. Canonical run totals come from local agent logs that can be correlated to the run by isolated workspace path and run time window:

- Codex: `~/.codex/sessions/**/rollout-*.jsonl`, using `total_token_usage` records from the Codex rollout log.
- OpenCode: `~/.local/share/opencode/opencode.db`, using `step-finish` token snapshots from the OpenCode SQLite `part` table. These rows are cumulative snapshots for a session, so Orbital keeps the highest reported `tokens.total` instead of summing rows.

Adapter-reported usage payloads remain visible under diagnostic token sources, but they are not canonical totals. If Orbital cannot uniquely correlate a local agent-log record, `tokens.known` stays false rather than estimating.

### Claude Support

Claude support is split intentionally:

- `claude_code_cli_local` is the local Claude Code CLI fallback. It uses the `claude` command and local Claude Code authentication, but it is not an ACP profile.
- `claude_agent_acp_api` is the planned ACP path. It uses the Claude Agent SDK ACP adapter through `claude-agent-acp`, requires `ANTHROPIC_API_KEY`, and is treated as metered API usage.

The [Claude Agent SDK docs](https://code.claude.com/docs/en/agent-sdk/overview) describe API-key setup with `ANTHROPIC_API_KEY` and state that SDK-built third-party agents should use API-key authentication rather than claude.ai login/rate limits. The ACP agents list includes the Claude Agent adapter as [`claude-agent-acp`](https://agentclientprotocol.com/get-started/agents). Orbital should not imply a local-subscription Claude ACP path unless a supported local ACP adapter is verified.

Inspect the local setup:

```bash
orbital doctor
orbital profiles
orbital mcp-config
```

Create an `orbital.config.json` only when you need to override the built-in profile templates. A minimal local fake-harness config for smoke testing looks like this:

```json
{
  "default_profile": "fake_acp",
  "storage_root": ".orbital",
  "profiles": [
    {
      "id": "fake_acp",
      "display_name": "Fake ACP",
      "adapter": "acp",
      "runtime_family": "fake",
      "command": ["python3", "tests/fixtures/fake_acp_harness.py"],
      "auth_mode": "local_subscription",
      "cost_posture": "subscription_preferred",
      "capabilities": ["dialogue", "permissions", "tool_events", "stop"],
      "support": {"tier": "known_good_acp"}
    }
  ]
}
```

Then run a local smoke test:

```bash
orbital-mcp-smoke --profile fake_acp --workdir /tmp/orbital-smoke
```

For real harnesses, start with `orbital profiles` and `orbital doctor`, then configure your primary harness with the MCP config emitted by `orbital mcp-config`. API-backed or metered profiles are intentionally explicit opt-in; the default posture favors local/subscription profiles.

Runtime data is written under `.orbital/` by default. That directory is local state and should not be committed.

## Project Docs

Core documents:

- [Product Spec](docs/PRODUCT_SPEC.md): user problem, product boundary, expected workflows, and non-goals.
- [Technical Spec](docs/TECH_SPEC.md): architecture, data model, MCP tools, adapter contracts, and storage/security expectations.
- [Roadmap](docs/ROADMAP.md): phased rebuild plan from the current sketch to an open source Orbital MCP.
- [Implementation TODO](docs/TODO.md): execution checklist for turning the specs into buildable tasks.

To add another ACP harness such as Pi, start with the [Technical Spec](docs/TECH_SPEC.md) section on adding a new ACP harness. New harnesses should begin as conservative profile templates, then earn `experimental_acp` or `known_good_acp` through readiness diagnostics, manual smoke evidence, deterministic tests, and adapter conformance fixtures.

## Positioning

Orbital is not an SDLC platform yet. It is an MCP delegation layer for running, supervising, and reviewing secondary coding agents.

The product center is:

1. Easy install of a local MCP server.
2. Simple setup and diagnostics for multiple harness profiles.
3. ACP-first adapters for Codex, OpenCode, Pi, and API-backed Claude Agent SDK; Claude Code remains a CLI fallback unless a local-subscription ACP path is verified.
4. Harness classification so a primary harness can choose the right secondary worker for a task.
5. A complete primary-mediated approval channel so the primary harness can make smart, safe decisions for secondary-agent permission requests when policy allows.
6. Structured handoff, evidence, and review data between primary and secondary harnesses.

Future SDLC workflows can build on Orbital, but they should not shape the first product surface.
