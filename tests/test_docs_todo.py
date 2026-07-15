from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TODO = DOCS / "TODO.md"
README = ROOT / "README.md"


class DocsTodoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.todo = TODO.read_text(encoding="utf-8")
        cls.readme = README.read_text(encoding="utf-8")
        cls.product = (DOCS / "PRODUCT_SPEC.md").read_text(encoding="utf-8")
        cls.tech = (DOCS / "TECH_SPEC.md").read_text(encoding="utf-8")
        cls.roadmap = (DOCS / "ROADMAP.md").read_text(encoding="utf-8")

    def test_readme_links_execution_checklist(self) -> None:
        self.assertIn("[Implementation TODO](docs/TODO.md)", self.readme)

    def test_todo_has_expected_execution_sections(self) -> None:
        headings = re.findall(r"^## \d+\. (.+)$", self.todo, flags=re.MULTILINE)
        self.assertEqual(
            headings,
            [
                "Project Identity And Rename",
                "Config, Schema, And Storage Foundation",
                "Core MCP Tool Contracts",
                "Profiles, Classification, And Recommendation",
                "ACP Adapters And Compatibility",
                "Run Lifecycle, Evidence, And File Attribution",
                "Permissions And Capability-Based Policy",
                "Handoff Sessions",
                "Liveness, Telemetry, And Reports",
                "Open Source Readiness",
                "CI-Safe Validation Suites",
            ],
        )

    def test_every_todo_section_has_acceptance_criteria_and_tests(self) -> None:
        sections = re.split(r"^## \d+\. .+$", self.todo, flags=re.MULTILINE)[1:]
        self.assertEqual(len(sections), 11)
        for section in sections:
            self.assertIn("Acceptance criteria:", section)
            self.assertIn("Tests:", section)
            self.assertRegex(section, r"(?m)^- \[ \] ")

    def test_todo_preserves_key_planning_decisions(self) -> None:
        required_phrases = [
            "Keep handoff/session tools in V1",
            "Replace default-first profile routing",
            "support tiers: `known_good_acp`, `experimental_acp`, `profile_template`, and `cli_fallback`",
            "atomic writes",
            "permission_not_resolvable_after_restart",
            "policy level: `prompt_only`, `adapter_mediated`, `process_observed`, or `sandbox_enforced`",
            "canonical local agent-log telemetry",
            "fake ACP harness",
            "CI-Safe Validation",
            "no clicks",
            "ORBITAL_RUN_PACKAGING_SMOKE=1",
            "ORBITAL_RUN_REAL_HARNESS_SMOKE=1",
            "../ngitd-core",
            "claude_agent_acp_api",
            "claude_code_cli_local",
            "claude-agent-acp",
            "codex_acp_official",
            "@agentclientprotocol/codex-acp",
            "ANTHROPIC_API_KEY",
            "OpenCode `1.17.13`",
            "ACP `protocolVersion=1`",
            "experimental_acp",
            "adding a new ACP harness",
            "primary-mediated approval",
            "without constant manual user approval",
            "complete permission round trip",
        ]
        for phrase in required_phrases:
            self.assertIn(phrase, self.todo)

    def test_specs_and_todo_agree_on_non_sdlc_boundary(self) -> None:
        self.assertIn("Orbital is not a full SDLC agent", self.product)
        self.assertIn("SDLC-specific issue, branch, PR, CI, release, sprint, epic, owner, or team policy layers", self.todo)
        self.assertIn("Later: SDLC Layer", self.roadmap)

    def test_specs_and_todo_preserve_prism_ngitd_boundary(self) -> None:
        for phrase in [
            "Prism / Orbital / ngitd Boundary",
            "artifact contract",
            "run-control assessment",
            "ngitd-core",
            "repo snapshots",
            "terminal dispositions",
            "lineage",
            "no `.ngit/` writes",
        ]:
            self.assertIn(phrase, self.product + self.tech + self.roadmap + self.todo + self.readme)
        self.assertIn("artifact_contract_only", self.todo)
        self.assertIn("not direct `ngitd-core` integration", self.roadmap)

    def test_specs_and_todo_preserve_diagnostic_evidence_contract(self) -> None:
        for phrase in [
            "diagnostic_timeline",
            "diagnostic_explainability",
            "observed",
            "inferred",
            "unknown",
            "diagnostic_next_steps",
            "top next step",
        ]:
            self.assertIn(phrase, self.readme + self.product + self.tech + self.roadmap + self.todo)

    def test_specs_and_todo_preserve_acp_conformance_matrix_contract(self) -> None:
        for phrase in [
            "feature_states",
            "`observed`, `missing`, `not_applicable`, or `capability_gap`",
            "bounded `raw_refs`",
            "Canonical local-log telemetry is `not_applicable`",
            "ambiguous permission options",
            "mixed allow/deny multi-request outcomes",
            "No profile is promoted to `known_good_acp`",
        ]:
            self.assertIn(phrase, self.tech + self.roadmap + self.todo)

    def test_docs_preserve_explicit_opencode_zen_ask_profiles(self) -> None:
        docs = self.readme + self.tech + self.roadmap + self.todo
        for phrase in [
            "opencode_acp_big_pickle_ask",
            "opencode/big-pickle",
            "free for a limited time",
            "free-period data-use caveat",
            "opencode_acp_glm52_ask",
        ]:
            self.assertIn(phrase, docs)

    def test_readme_explains_orbital_observation_model(self) -> None:
        for phrase in [
            "## Observation Model",
            "only records what it can see through its own control path",
            "not a general observer",
            "MCP calls made to Orbital",
            "ACP or CLI events from secondary harness processes that Orbital launches",
            "does not see arbitrary model activity outside that loop",
            "should not fabricate or directly write diagnostic facts",
        ]:
            self.assertIn(phrase, self.readme)

    def test_specs_and_todo_agree_on_profile_classification_schema(self) -> None:
        for phrase in [
            "classification.task_tags",
            "strengths",
            "limits",
            "max_recommended_scope",
            "cost_preference",
            "locality",
        ]:
            self.assertIn(phrase, self.tech)
            self.assertIn(phrase, self.todo)

    def test_todo_is_checklist_oriented(self) -> None:
        unchecked_items = re.findall(r"(?m)^- \[ \] ", self.todo)
        self.assertGreaterEqual(len(unchecked_items), 70)
        self.assertNotIn("- [x]", self.todo.lower())

    def test_validation_suites_are_unattended_and_ci_safe(self) -> None:
        self.assertIn("## 11. CI-Safe Validation Suites", self.todo)
        for phrase in [
            "no clicks",
            "private credentials",
            "real model calls",
            "installed real harnesses",
            "Fake ACP integration tests",
            "MCP stdio transport",
            "installed-package validation",
            "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v",
        ]:
            self.assertIn(phrase, self.todo)

    def test_claude_acp_is_documented_as_api_backed_not_local_subscription(self) -> None:
        for doc in [self.readme, self.product, self.tech, self.roadmap, self.todo]:
            self.assertIn("Claude Agent", doc)
        self.assertIn("claude_agent_acp_api", self.tech)
        self.assertIn("claude_agent_acp_api", self.todo)
        self.assertIn("claude_code_cli_local", self.tech)
        self.assertIn("claude_code_cli_local", self.todo)
        self.assertIn("ANTHROPIC_API_KEY", self.product)
        self.assertIn("ANTHROPIC_API_KEY", self.todo)
        self.assertIn("Claude Code CLI", self.readme)
        self.assertIn("https://code.claude.com/docs/en/agent-sdk/overview", self.readme)
        self.assertIn("https://agentclientprotocol.com/get-started/agents", self.readme)
        self.assertIn("SDK-built third-party agents should use API-key authentication", self.readme)
        self.assertNotIn("claude_code_acp_local", self.readme)
        self.assertNotIn("claude_code_acp_local", self.product)
        self.assertNotIn("claude_code_acp_local", self.roadmap)

    def test_opencode_smoke_evidence_does_not_imply_known_good(self) -> None:
        self.assertIn("OpenCode `1.17.13`", self.tech)
        self.assertIn("ACP `protocolVersion=1`", self.tech)
        self.assertIn("Manual local ACP smoke currently covers legacy Codex ACP and OpenCode", self.roadmap)
        self.assertIn("codex_acp_official", self.roadmap)
        self.assertIn("Keep smoke-verified profiles at `experimental_acp`", self.todo)
        self.assertIn("Do not promote to known_good_acp until adapter conformance fixtures pass.", self.tech)

    def test_new_acp_harness_workflow_is_documented(self) -> None:
        self.assertIn("## Adding A New ACP Harness", self.tech)
        for phrase in [
            "profile-and-evidence workflow",
            "Add readiness diagnostics",
            "Capture smoke evidence",
            "Add adapter conformance fixtures",
            "For Pi specifically",
        ]:
            self.assertIn(phrase, self.tech)
        self.assertIn("adding a new ACP harness", self.todo)
        self.assertIn("following the documented profile, readiness, smoke, fixture, and support-tier workflow", self.roadmap)
        self.assertIn("To add another ACP harness such as Pi", self.readme)


if __name__ == "__main__":
    unittest.main()
