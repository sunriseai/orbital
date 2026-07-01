from __future__ import annotations

from typing import Any


PRIMARY_GUIDANCE_VERSION = "1"


PRIMARY_WORKFLOW_STEPS = [
    "Start a delegation session for multi-run work.",
    "Create a concise requirements ledger before delegating implementation.",
    "Create bounded tickets that name the requirement IDs they advance.",
    "Use a fixed secondary profile for the session unless the user starts a new session.",
    "Delegate one ticket at a time and poll get_run_status_digest rather than raw dialogue by default.",
    "Use get_run_policy_verdict and get_next_recommended_action before inventing retry prompts.",
    "Call get_run_liveness before stopping or declaring a quiet run stalled.",
    "Record an attempt review after every terminal run.",
    "Use create_repair_ticket_from_run for routine server-classified gaps; do not lower the product contract.",
    "Finish the session only after final verification or a concrete blocker.",
]


WORKER_SAFE_CONSTRAINTS = [
    "Stay inside declared allowed_paths.",
    "Avoid declared forbidden_paths.",
    "Do not read or write secrets, auth files, environment files, SSH keys, private tokens, or credentials.",
    "Do not install packages, update dependencies, or run package managers unless explicitly requested.",
    "Do not use network access, external CDNs, downloads, uploads, or remote APIs unless explicitly requested.",
    "Do not run destructive shell commands.",
    "Do not perform broad unrelated refactors.",
    "Run requested checks when feasible and report unresolved issues.",
]


def primary_guidance(host_harness: str | None = None) -> dict[str, Any]:
    host = (host_harness or "generic").strip().lower() or "generic"
    return {
        "schema_version": 1,
        "guidance_version": PRIMARY_GUIDANCE_VERSION,
        "host_harness": host,
        "summary": (
            "Use Orbital MCP as a local delegation control plane: the primary harness plans, "
            "delegates, reviews evidence, manages permissions, requests repairs, and reports outcomes."
        ),
        "role_boundaries": {
            "primary_harness": [
                "Create requirements and tickets.",
                "Resolve permissions conservatively.",
                "Inspect changed files and verification output.",
                "Record reviews and decide whether a run counts.",
            ],
            "orbital_mcp": [
                "Launch configured workers.",
                "Persist runs, sessions, transcripts, permissions, snapshots, warnings, liveness, and reports.",
                "Normalize adapter-specific events into a stable MCP surface.",
            ],
            "secondary_harness": [
                "Execute bounded coding tickets in the selected runtime.",
                "Emit dialogue, tool, and permission events for Orbital to capture.",
            ],
        },
        "workflow_steps": PRIMARY_WORKFLOW_STEPS,
        "review_rules": [
            "Worker prose is context, not proof.",
            "Raw dialogue and transcripts are debug/audit material; prefer digests, verdicts, warnings, and log refs.",
            "Passing checks are necessary but not sufficient.",
            "Accepted runs must satisfy the targeted requirements with implementation and test evidence.",
            "User-facing artifacts must be verified through their public interface when feasible.",
            "Treat policy violations, missing checks, no-op passes, and out-of-scope changes as repair or rejection signals.",
        ],
        "recommended_tools": [
            "start_delegation_session",
            "create_requirement",
            "create_delegation_ticket",
            "start_ticket_run",
            "get_run_status_digest",
            "get_run_policy_verdict",
            "get_run_summary",
            "get_run_liveness",
            "create_repair_ticket_from_run",
            "record_attempt_review",
            "get_next_recommended_action",
            "finish_delegation_session",
            "get_delegation_report",
        ],
    }


def worker_safe_constraints() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "guidance_version": PRIMARY_GUIDANCE_VERSION,
        "constraints": WORKER_SAFE_CONSTRAINTS,
    }


def prompt_pack(host_harness: str | None = None) -> str:
    guidance = primary_guidance(host_harness)
    constraints = worker_safe_constraints()["constraints"]
    lines = [
        "# Orbital Primary Guidance",
        "",
        guidance["summary"],
        "",
        "Workflow:",
        *[f"- {step}" for step in guidance["workflow_steps"]],
        "",
        "Review rules:",
        *[f"- {rule}" for rule in guidance["review_rules"]],
        "",
        "Worker-safe constraints to pass only when relevant:",
        *[f"- {constraint}" for constraint in constraints],
        "",
        "Do not pass primary-only workflow, retry, scoring, or session-reporting guidance into secondary task prompts.",
    ]
    return "\n".join(lines) + "\n"
