from __future__ import annotations

from datetime import UTC, datetime
from itertools import count
from typing import Any

from .models import DialogueEvent

_event_counter = count(1)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_event(
    run_id: str,
    kind: str,
    speaker: str,
    text: str | None = None,
    raw: dict[str, Any] | str | None = None,
    raw_ref: str | None = None,
) -> DialogueEvent:
    return DialogueEvent(
        event_id=f"evt-{next(_event_counter):012d}",
        run_id=run_id,
        timestamp=utc_now(),
        kind=kind,
        speaker=speaker,
        text=redact_display_text(text),
        raw=raw,
        raw_ref=raw_ref,
    )


def redact_display_text(text: str | None) -> str | None:
    if text is None:
        return None
    redacted = text
    secret_markers = ["api_key=", "API_KEY=", "token=", "TOKEN=", "password=", "PASSWORD="]
    for marker in secret_markers:
        idx = redacted.find(marker)
        if idx >= 0:
            end = redacted.find(" ", idx)
            if end < 0:
                end = len(redacted)
            redacted = redacted[: idx + len(marker)] + "[REDACTED]" + redacted[end:]
    return redacted
