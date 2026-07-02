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
            "exact primary, secondary, combined, and external model-log telemetry",
            "fake ACP harness",
            "CI-Safe Validation",
            "no clicks",
            "ORBITAL_RUN_PACKAGING_SMOKE=1",
            "ORBITAL_RUN_REAL_HARNESS_SMOKE=1",
            "../ngitd-core",
            "claude_agent_acp_api",
            "claude_code_cli_local",
            "claude-agent-acp",
            "ANTHROPIC_API_KEY",
            "OpenCode `1.17.11`",
            "ACP `protocolVersion=1`",
            "experimental_acp",
        ]
        for phrase in required_phrases:
            self.assertIn(phrase, self.todo)

    def test_specs_and_todo_agree_on_non_sdlc_boundary(self) -> None:
        self.assertIn("Orbital is not a full SDLC agent", self.product)
        self.assertIn("SDLC-specific issue, branch, PR, CI, release, sprint, epic, owner, or team policy layers", self.todo)
        self.assertIn("Later: SDLC Layer", self.roadmap)

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
        self.assertNotIn("claude_code_acp_local", self.readme)
        self.assertNotIn("claude_code_acp_local", self.product)
        self.assertNotIn("claude_code_acp_local", self.roadmap)

    def test_opencode_smoke_evidence_does_not_imply_known_good(self) -> None:
        self.assertIn("OpenCode `1.17.11`", self.tech)
        self.assertIn("ACP `protocolVersion=1`", self.tech)
        self.assertIn("Manual local ACP smoke currently covers Codex and OpenCode", self.roadmap)
        self.assertIn("Keep smoke-verified profiles at `experimental_acp`", self.todo)
        self.assertIn("Do not promote to known_good_acp until adapter conformance fixtures pass.", self.tech)


if __name__ == "__main__":
    unittest.main()
