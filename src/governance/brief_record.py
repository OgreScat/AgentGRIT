"""
Brief record — opt-in persistence of a governed brief for the domain UI.

Mirrors decision_record: append-only JSONL, fail-safe, redacted.
Agents MAY call record_brief(envelope); the /brief UI only READs.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def record_brief(
    envelope: dict[str, Any] | None,
    *,
    kind: str | None = None,
    log_dir: Path | None = None,
    profile_id: str = "generic",
) -> dict[str, Any]:
    """Normalize an agent envelope to GovernedBrief and append logs/briefs.jsonl.

    Never raises. Returns the entry written (or the best-effort dict if write fails).
    """
    try:
        from src.api.brief_data import adapt_envelope, brief_to_entry
        from src.security.redact import redact
        from src.utils.logging import write_jsonl

        brief = adapt_envelope(envelope or {}, kind=kind)
        entry = brief_to_entry(brief, profile_id=profile_id)
        # Redact any secret-shaped strings in free text fields
        for key in ("question", "framing", "contested_reason"):
            if entry.get(key):
                entry[key] = redact(str(entry[key]))
        for item in entry.get("needs_judgment") or []:
            if isinstance(item, str):
                pass  # list rewritten below
        entry["needs_judgment"] = [
            redact(str(x)) for x in (entry.get("needs_judgment") or [])
        ]
        for a in entry.get("authorities") or []:
            if isinstance(a, dict) and a.get("title"):
                a["title"] = redact(str(a["title"]))
            if isinstance(a, dict) and a.get("citation"):
                a["citation"] = redact(str(a["citation"]))
        entry["ts"] = entry.get("ts") or datetime.now().isoformat()
        write_jsonl("briefs.jsonl", entry, log_dir=log_dir)
        return entry
    except Exception:
        return {
            "ts": datetime.now().isoformat(),
            "kind": kind or "unknown",
            "disposition": "unknown",
            "error": "brief_record failed safe",
        }
