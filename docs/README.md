# Orbital

Orbital is a local MCP server for coordinating secondary coding harnesses from a primary harness. It gives the primary harness a stable control surface for profile selection, ACP/CLI adapter launch, permission mediation, evidence capture, liveness checks, file attribution, and structured handoff sessions.

The current implementation is intentionally CI-safe to validate: the default tests use local fake harnesses and do not require clicks, credentials, network access, real model calls, or installed real harnesses.

## Get Started

Prerequisites:

- Python 3.11 or newer.
- A shell in the repository root.
- Optional: a real ACP-capable harness such as Codex, Claude Code, or OpenCode for manual smoke tests. The default test suite does not need one.

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

- [Product Spec](PRODUCT_SPEC.md): user problem, product boundary, expected workflows, and non-goals.
- [Technical Spec](TECH_SPEC.md): architecture, data model, MCP tools, adapter contracts, and storage/security expectations.
- [Roadmap](ROADMAP.md): phased rebuild plan from the current sketch to an open source Orbital MCP.
- [Implementation TODO](TODO.md): execution checklist for turning the specs into buildable tasks.

## Positioning

Orbital is not an SDLC platform yet. It is the local routing and control layer for multi-harness coding delegation.

The product center is:

1. Easy install of a local MCP server.
2. Simple setup and diagnostics for multiple harness profiles.
3. ACP-first adapters for Codex, Claude Code, OpenCode, and Pi.
4. Harness classification so a primary harness can choose the right secondary worker for a task.
5. Structured handoff, evidence, and review data between primary and secondary harnesses.

Future SDLC workflows can build on Orbital, but they should not shape the first product surface.
