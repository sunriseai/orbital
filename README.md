# Orbital

Orbital is a local MCP server for coordinating secondary coding harnesses from a primary harness. It gives the primary harness a stable control surface for profile selection, ACP/CLI adapter launch, permission mediation, evidence capture, liveness checks, file attribution, and structured handoff sessions.

The current implementation is intentionally CI-safe to validate: the default tests use local fake harnesses and do not require clicks, credentials, network access, real model calls, or installed real harnesses.

## Get Started

Prerequisites:

- Python 3.11 or newer.
- A shell in the repository root.
- Optional: a real ACP-capable harness such as Codex or OpenCode for manual local ACP smoke tests. Claude Code CLI is currently represented as a CLI fallback; Claude ACP should use the Claude Agent SDK adapter and API-key auth when that profile is added. The default test suite does not need a real harness.

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

The default suite includes a real MCP stdio transport smoke against the local fake harness. `ORBITAL_RUN_PACKAGING_SMOKE=1` additionally creates a temporary virtualenv, installs Orbital from a copied source tree, and verifies the installed console scripts. `ORBITAL_RUN_REAL_HARNESS_SMOKE=1` defaults to trying `codex_acp_local` and `opencode_acp_local`, skipping profiles that `orbital doctor` reports as not ready. Set `ORBITAL_REAL_HARNESS_PROFILES=<profile[,profile]>` to narrow or override that list. Claude ACP should be tested through an explicit API-backed `claude_agent_acp_api` profile once implemented, not through a local-subscription Claude Code ACP profile.

Run manual smoke wrappers when you want a timestamped log under `tests/manual/logs/`:

```bash
./tests/manual/run_manual_faux_harness_smoke.sh
./tests/manual/run_manual_local_codex_acp_smoke.sh
./tests/manual/run_manual_local_opencode_acp_smoke.sh
```

`run_manual_faux_harness_smoke.sh` stays CI-safe and uses fake harnesses. The `run_manual_local_*_acp_smoke.sh` scripts each target one installed/authenticated local ACP harness and may launch a real Codex or OpenCode worker. The OpenCode script also records `opencode --version`, `opencode acp --help`, and an ACP initialize handshake before the smoke task. Claude Agent SDK ACP smoke should be added here only after the API-backed `claude_agent_acp_api` profile exists and has a verified setup path. Each script prints its scope and prerequisites before running.

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

## Positioning

Orbital is not an SDLC platform yet. It is the local routing and control layer for multi-harness coding delegation.

The product center is:

1. Easy install of a local MCP server.
2. Simple setup and diagnostics for multiple harness profiles.
3. ACP-first adapters for Codex, OpenCode, Pi, and API-backed Claude Agent SDK; Claude Code remains a CLI fallback unless a local-subscription ACP path is verified.
4. Harness classification so a primary harness can choose the right secondary worker for a task.
5. Structured handoff, evidence, and review data between primary and secondary harnesses.

Future SDLC workflows can build on Orbital, but they should not shape the first product surface.
