from __future__ import annotations

from pathlib import Path

from .models import TaskInput


def render_startup_prompt(task: TaskInput, workdir: Path) -> str:
    sections = [
        "You are executing one bounded coding task for Orbital MCP.",
        f"Task title: {task.title}",
        f"Objective: {task.objective}",
        f"Workdir: {workdir}",
        _list_section("Allowed paths", task.allowed_paths),
        _list_section("Forbidden paths", task.forbidden_paths),
        _list_section("Constraints", task.constraints),
        _list_section("Acceptance hints", task.acceptance_hints),
        _list_section("Requested checks", task.checks),
        _list_section("Rules", task.rules),
        (
            "Stay within allowed paths when provided. Avoid forbidden paths. "
            "Explain important decisions in normal working dialogue. Run requested checks when feasible. "
            "Report final changed files and unresolved issues. Request permission instead of making unsafe "
            "changes when the harness supports permissions."
        ),
    ]
    return "\n\n".join(section for section in sections if section)


def _list_section(title: str, values: list[str]) -> str:
    if not values:
        return f"{title}: none specified"
    return title + ":\n" + "\n".join(f"- {value}" for value in values)
