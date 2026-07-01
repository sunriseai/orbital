from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..models import PermissionRequest


@dataclass
class AcpSessionInfo:
    session_id: str | None
    process_id: int | None


@dataclass
class PromptResult:
    status: str
    text: str | None = None
    raw: dict[str, Any] | None = None


class AdapterSink(Protocol):
    async def agent_text(self, text: str, raw: dict[str, Any] | None = None) -> None: ...
    async def tool_update(self, kind: str, text: str, raw: dict[str, Any] | None = None) -> None: ...
    async def policy_violation(self, reason: str, raw: dict[str, Any] | None = None) -> None: ...
    async def permission_requested(self, permission: PermissionRequest) -> None: ...
    async def stderr(self, text: str) -> None: ...
    async def transcript(self, text: str) -> None: ...
