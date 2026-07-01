from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


SKIP_DIRS = {".git", ".orbital", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


@dataclass
class FileSnapshot:
    digests: dict[str, str] = field(default_factory=dict)
    dirty_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    renamed_files: list[str] = field(default_factory=list)


@dataclass
class FileAttribution:
    path: str
    change_type: str
    attribution: str
    confidence: str
    notes: list[str] = field(default_factory=list)


@dataclass
class ChangeAttribution:
    pre_existing_changed_files: list[str]
    changed_since_run_start: list[str]
    changed_files: list[str]
    files: list[FileAttribution] = field(default_factory=list)


def snapshot_workdir(workdir: Path) -> FileSnapshot:
    dirty, untracked, deleted, renamed = _git_status_files(workdir)
    return FileSnapshot(
        digests=_digest_tree(workdir),
        dirty_files=dirty,
        untracked_files=untracked,
        deleted_files=deleted,
        renamed_files=renamed,
    )


def compare_snapshots(start: FileSnapshot, end: FileSnapshot) -> ChangeAttribution:
    changed_since = sorted(
        path
        for path in set(start.digests) | set(end.digests)
        if start.digests.get(path) != end.digests.get(path)
    )
    changed_files = sorted(set(end.dirty_files) | set(changed_since))
    return ChangeAttribution(
        pre_existing_changed_files=sorted(start.dirty_files),
        changed_since_run_start=changed_since,
        changed_files=changed_files,
        files=_file_attributions(start, end, changed_since, changed_files),
    )


def _digest_tree(workdir: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    if not workdir.exists():
        return digests
    for path in sorted(workdir.rglob("*")):
        if not path.is_file() or _should_skip(path, workdir):
            continue
        rel = path.relative_to(workdir).as_posix()
        try:
            digests[rel] = _sha256(path)
        except OSError:
            continue
    return digests


def _should_skip(path: Path, workdir: Path) -> bool:
    rel_parts = path.relative_to(workdir).parts
    return any(part in SKIP_DIRS for part in rel_parts)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_attributions(
    start: FileSnapshot,
    end: FileSnapshot,
    changed_since: list[str],
    changed_files: list[str],
) -> list[FileAttribution]:
    records: list[FileAttribution] = []
    start_dirty = set(start.dirty_files)
    end_untracked = set(end.untracked_files)
    end_deleted = set(end.deleted_files)
    renamed = set(end.renamed_files)
    for path in changed_files:
        notes: list[str] = []
        if path in renamed:
            change_type = "renamed"
        elif path in end_deleted or path not in end.digests:
            change_type = "deleted"
        elif path not in start.digests:
            change_type = "created"
        elif path in changed_since:
            change_type = "modified"
        else:
            change_type = "pre_existing_dirty"

        if path in start_dirty and path in changed_since:
            attribution = "possibly_concurrent"
            confidence = "medium"
            notes.append("File was dirty before the run and also changed during the run.")
        elif path in changed_since:
            attribution = "changed_during_run"
            confidence = "high"
        elif path in start_dirty:
            attribution = "pre_existing"
            confidence = "low"
            notes.append("File was already dirty before the run; fallback attribution cannot assign it to the worker.")
        else:
            attribution = "unknown"
            confidence = "unknown"
            notes.append("Fallback attribution could not classify this path.")

        if path in end_untracked:
            notes.append("Path is currently untracked.")
        records.append(
            FileAttribution(
                path=path,
                change_type=change_type,
                attribution=attribution,
                confidence=confidence,
                notes=notes,
            )
        )
    return records


def _git_status_files(workdir: Path) -> tuple[list[str], list[str], list[str], list[str]]:
    if not (workdir / ".git").exists():
        return [], [], [], []
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v1", "-uall"],
            cwd=workdir,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return [], [], [], []
    if proc.returncode != 0:
        return [], [], [], []
    dirty: list[str] = []
    untracked: list[str] = []
    deleted: list[str] = []
    renamed: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) <= 3:
            continue
        status = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            _, path = path.split(" -> ", 1)
            renamed.append(path)
        dirty.append(path)
        if status == "??":
            untracked.append(path)
        if "D" in status:
            deleted.append(path)
    return sorted(dirty), sorted(untracked), sorted(deleted), sorted(renamed)
