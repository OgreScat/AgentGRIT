"""compiler.py — deterministic Markdown-vault compiler (generic, no LLM/network).

Turns a folder of Markdown notes into a governed manifest. Domain-neutral: the caller
supplies project roots and sensitivity policy; nothing is hardcoded.

Four knowledge states — policy | evidence | proposal | archive:
- policy: approved, versioned governing docs. Only these may bind routing/gates.
- evidence: tool output / records; support claims with provenance.
- proposal: drafts / model output; read-only context, never authority.
- archive: superseded; excluded from retrieval by default.

Guarantees: default-deny on malformed frontmatter; path-fence; secret-scan quarantine;
sha256 + git provenance; privacy sensitivities block cloud downstream.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MANIFEST_SCHEMA = "agentgrit-knowledge/manifest.v1"

VALID_KINDS = {"policy", "evidence", "proposal", "archive"}
VALID_STATUS = {"approved", "draft", "superseded", "expired", "unverified"}
VALID_SENSITIVITY = {"public", "internal", "private", "confidential"}
VALID_AUTHORITY = {"approved", "proposed", "none"}
REQUIRED_FIELDS = (
    "kind", "status", "project", "created", "updated",
    "sensitivity", "authority", "source_refs", "expires_at",
)
# Sensitivities a caller's cloud adapter may see. Others fail closed.
CLOUD_ALLOWED_SENSITIVITY = {"public", "internal"}

_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"][^'\"]{8,}"),
]


@dataclass
class KnowledgeNote:
    path: str
    sha256: str
    git_rev: str
    kind: str
    status: str
    project: str
    sensitivity: str
    authority: str
    created: str
    updated: str
    expires_at: str
    source_refs: list[str] = field(default_factory=list)
    cloud_allowed: bool = False
    indexed: bool = True
    quarantine_reason: str | None = None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_rev(path: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(path.parent), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else "no-git"
    except Exception:
        return "no-git"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str | None]:
    """Dependency-free flat-YAML frontmatter parser. Returns (fields, error)."""
    if not text.startswith("---"):
        return {}, "no frontmatter block"
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return {}, "frontmatter must open with a lone '---'"
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, "unterminated frontmatter block"
    fields: dict[str, Any] = {}
    i = 1
    while i < end:
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if ":" not in raw:
            return {}, f"malformed frontmatter line: {raw!r}"
        key, _, val = raw.partition(":")
        key, val = key.strip(), val.strip()
        if val == "":
            items = []
            j = i + 1
            while j < end and lines[j].lstrip().startswith("- "):
                items.append(lines[j].lstrip()[2:].strip())
                j += 1
            fields[key] = items
            i = j
            continue
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            fields[key] = [x.strip() for x in inner.split(",") if x.strip()] if inner else []
        else:
            fields[key] = val.strip().strip('"').strip("'")
        i += 1
    return fields, None


def _validate(fields: dict[str, Any]) -> str | None:
    for req in REQUIRED_FIELDS:
        if req not in fields:
            return f"missing required field: {req}"
    if fields["kind"] not in VALID_KINDS:
        return f"invalid kind: {fields['kind']}"
    if fields["status"] not in VALID_STATUS:
        return f"invalid status: {fields['status']}"
    if fields["sensitivity"] not in VALID_SENSITIVITY:
        return f"invalid sensitivity: {fields['sensitivity']}"
    if fields["authority"] not in VALID_AUTHORITY:
        return f"invalid authority: {fields['authority']}"
    if fields["kind"] == "policy" and fields["authority"] == "approved" and fields["status"] != "approved":
        return "policy claims authority=approved but status!=approved"
    return None


def _is_expired(expires_at: Any) -> bool:
    if not expires_at or expires_at in ("never", "none"):
        return False
    try:
        return date.fromisoformat(str(expires_at)) < datetime.now(tz=timezone.utc).date()
    except ValueError:
        return False


def _secret_hit(text: str) -> str | None:
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            return pat.pattern[:40]
    return None


def _project_from_path(rel_path: str, roots: dict[str, str]) -> str | None:
    for proj, root in roots.items():
        if rel_path.startswith(root.rstrip("/")):
            return proj
    return None


def compile_note(file_path: Path, vault_root: Path,
                 project_roots: dict[str, str] | None = None) -> KnowledgeNote:
    rel = str(file_path.relative_to(vault_root))
    text = file_path.read_text(encoding="utf-8", errors="replace")
    sha, rev = _sha256_text(text), _git_rev(file_path)

    def quarantine(reason: str, f: dict[str, Any] | None = None) -> KnowledgeNote:
        f = f or {}
        return KnowledgeNote(
            path=rel, sha256=sha, git_rev=rev,
            kind=str(f.get("kind", "unknown")), status=str(f.get("status", "unknown")),
            project=str(f.get("project", "unknown")),
            sensitivity=str(f.get("sensitivity", "private")),
            authority=str(f.get("authority", "none")),
            created=str(f.get("created", "")), updated=str(f.get("updated", "")),
            expires_at=str(f.get("expires_at", "")),
            source_refs=list(f.get("source_refs", []) or []),
            cloud_allowed=False, indexed=False, quarantine_reason=reason,
        )

    secret = _secret_hit(text)
    if secret:
        return quarantine(f"secret pattern detected ({secret})")
    fields, err = parse_frontmatter(text)
    if err:
        return quarantine(f"frontmatter: {err}")
    verr = _validate(fields)
    if verr:
        return quarantine(f"validation: {verr}", fields)
    if project_roots:
        path_proj = _project_from_path(rel, project_roots)
        if path_proj is not None and path_proj != str(fields["project"]):
            return quarantine(
                f"path fence: declares project={fields['project']} but lives under {path_proj}", fields
            )
    if _is_expired(fields["expires_at"]):
        n = quarantine("expired", fields)
        n.quarantine_reason = "expired"
        return n

    sensitivity = str(fields["sensitivity"])
    return KnowledgeNote(
        path=rel, sha256=sha, git_rev=rev,
        kind=str(fields["kind"]), status=str(fields["status"]),
        project=str(fields["project"]), sensitivity=sensitivity,
        authority=str(fields["authority"]),
        created=str(fields["created"]), updated=str(fields["updated"]),
        expires_at=str(fields["expires_at"]),
        source_refs=list(fields.get("source_refs", []) or []),
        cloud_allowed=sensitivity in CLOUD_ALLOWED_SENSITIVITY,
        indexed=fields["kind"] != "archive",
        quarantine_reason=None if fields["kind"] != "archive" else "archive (excluded by default)",
    )


def compile_vault(vault_root: str | Path, project_roots: dict[str, str] | None = None,
                  exclude_dirs: Iterable[str] = (".obsidian", ".git")) -> dict[str, Any]:
    root = Path(vault_root).resolve()
    excl = set(exclude_dirs)
    notes = [
        compile_note(md, root, project_roots)
        for md in sorted(root.rglob("*.md"))
        if not any(part in excl for part in md.relative_to(root).parts[:-1])
    ]
    indexed = [n for n in notes if n.indexed]
    return {
        "schema": MANIFEST_SCHEMA,
        "vault_root": str(root),
        "compiled_at": datetime.now(tz=timezone.utc).isoformat(),
        "counts": {
            "total": len(notes),
            "indexed": len(indexed),
            "quarantined": len(notes) - len(indexed),
            "by_kind": {k: sum(1 for n in indexed if n.kind == k) for k in VALID_KINDS},
        },
        "notes": [asdict(n) for n in notes],
    }
