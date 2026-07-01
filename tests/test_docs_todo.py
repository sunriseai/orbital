from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
TODO = DOCS / "TODO.md"


class DocsTodoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.todo = TODO.read_text(encoding="utf-8")
        cls.readme = (DOCS / "README.md").read_text(encoding="utf-8")
        cls.product = (DOCS / "PRODUCT_SPEC.md").read_text(encoding="utf-8")
        cls.tech = (DOCS / "TECH_SPEC.md").read_text(encoding="utf-8")
        cls.roadmap = (DOCS / "ROADMAP.md").read_text(encoding="utf-8")

    def test_readme_links_execution_checklist(self) -> None:
        self.assertIn("[Implementation TODO](TODO.md)", self.readme)

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
            "../ngitd-core",
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
            "PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v",
        ]:
            self.assertIn(phrase, self.todo)


if __name__ == "__main__":
    unittest.main()
