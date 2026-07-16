"""Logos Vault schemas — manifest, artifacts, admission states, failures."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class AdmissionState(str, Enum):
    QUARANTINE = "quarantine"   # raw/unreviewed — never retrievable
    REVIEWED = "reviewed"       # human-inspected, not yet approved
    APPROVED = "approved"       # retrievable by role selection
    DEPRECATED = "deprecated"   # superseded — never retrievable
    REVOKED = "revoked"         # pulled for cause — never retrievable


# Artifact types the role profiles understand.
ARTIFACT_TYPES = (
    "playbook",
    "routing_rubric",
    "standing_instructions",
    "operator_manual",
    "trap_tests",
    "eval",
    "doctrine",
    "model_profile",
    "adapter_code",
    "raw_handoff",
)


@dataclass
class LogosArtifact:
    artifact_id: str
    path: str                    # relative to vault root
    artifact_type: str
    sha256: str
    admission_state: str = AdmissionState.QUARANTINE.value
    sensitivity: str = "internal"          # public | internal | private
    roles: list[str] = field(default_factory=list)  # optional role hints
    source_class: str = "distilled"        # distilled | authored | raw_import
    notes: str = ""

    def retrievable(self) -> bool:
        return self.admission_state == AdmissionState.APPROVED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "path": self.path,
            "artifact_type": self.artifact_type,
            "sha256": self.sha256,
            "admission_state": self.admission_state,
            "sensitivity": self.sensitivity,
            "roles": list(self.roles),
            "source_class": self.source_class,
            "notes": self.notes,
        }


@dataclass
class LogosManifest:
    vault_name: str
    version: str
    pin: str
    generated_at: str
    artifacts: list[LogosArtifact] = field(default_factory=list)

    def approved(self) -> list[LogosArtifact]:
        return [a for a in self.artifacts if a.retrievable()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "vault_name": self.vault_name,
            "version": self.version,
            "pin": self.pin,
            "generated_at": self.generated_at,
            "artifacts": [a.to_dict() for a in self.artifacts],
        }


class ValidationFailure(str, Enum):
    DISABLED = "disabled"
    PATH_MISSING = "path_missing"
    PIN_FILE_MISSING = "pin_file_missing"
    PIN_MISMATCH = "pin_mismatch"
    MANIFEST_MISSING = "manifest_missing"
    MANIFEST_MALFORMED = "manifest_malformed"
    ARTIFACT_MISSING = "artifact_missing"
    HASH_MISMATCH = "hash_mismatch"


@dataclass
class ValidationReport:
    valid: bool
    failures: list[dict[str, str]] = field(default_factory=list)
    manifest: LogosManifest | None = None
    approved_count: int = 0
    quarantined_count: int = 0
    total_count: int = 0

    def add_failure(self, code: ValidationFailure, detail: str = "") -> None:
        self.valid = False
        self.failures.append({"code": code.value, "detail": detail})

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "failures": list(self.failures),
            "approved_count": self.approved_count,
            "quarantined_count": self.quarantined_count,
            "total_count": self.total_count,
            "vault_version": self.manifest.version if self.manifest else None,
        }


def manifest_from_dict(data: dict[str, Any]) -> LogosManifest:
    arts = []
    for a in data.get("artifacts") or []:
        if not isinstance(a, dict):
            continue
        arts.append(LogosArtifact(
            artifact_id=str(a.get("artifact_id") or ""),
            path=str(a.get("path") or ""),
            artifact_type=str(a.get("artifact_type") or "playbook"),
            sha256=str(a.get("sha256") or ""),
            admission_state=str(a.get("admission_state") or AdmissionState.QUARANTINE.value),
            sensitivity=str(a.get("sensitivity") or "internal"),
            roles=list(a.get("roles") or []),
            source_class=str(a.get("source_class") or "distilled"),
            notes=str(a.get("notes") or ""),
        ))
    return LogosManifest(
        vault_name=str(data.get("vault_name") or ""),
        version=str(data.get("version") or ""),
        pin=str(data.get("pin") or ""),
        generated_at=str(data.get("generated_at") or ""),
        artifacts=arts,
    )


def load_manifest(vault_path: Path) -> LogosManifest:
    """Load vault-manifest.json. Raises on missing/malformed (validator catches)."""
    raw = (Path(vault_path) / "vault-manifest.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or not data.get("artifacts"):
        raise ValueError("manifest missing artifacts")
    return manifest_from_dict(data)
