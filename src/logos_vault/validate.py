"""Logos Vault fail-closed validation.

Checks, in order (any failure -> invalid, never default-allow):
1. enabled + configured (disabled is the default and reports as such);
2. vault path exists;
3. pin file consistency — the vault's .grit-vault-pin first line AND the
   manifest pin must both equal the configured pin. NOTE: this is
   CONFIGURATION CONSISTENCY VALIDATION only, not cryptographic identity
   verification of a repository or release.
4. manifest present and well-formed;
5. every manifest artifact exists on disk and matches its sha256
   (real content integrity — a tampered or drifted file fails closed).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import MANIFEST_FILENAME, PIN_FILENAME, LogosVaultConfig, load_config
from .schema import (
    AdmissionState,
    ValidationFailure,
    ValidationReport,
    load_manifest,
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def validate_vault(config: LogosVaultConfig | None = None) -> ValidationReport:
    """Validate the configured vault. Fail-closed; never raises."""
    report = ValidationReport(valid=True)
    cfg = config if config is not None else load_config()

    if not cfg.enabled:
        report.add_failure(ValidationFailure.DISABLED, "vault disabled (default)")
        return report
    if cfg.path is None or not cfg.pin:
        report.add_failure(ValidationFailure.DISABLED, "vault not fully configured")
        return report
    if not cfg.path.is_dir():
        report.add_failure(ValidationFailure.PATH_MISSING, str(cfg.path))
        return report

    pin_file = cfg.path / PIN_FILENAME
    if not pin_file.is_file():
        report.add_failure(ValidationFailure.PIN_FILE_MISSING, PIN_FILENAME)
        return report
    try:
        disk_pin = pin_file.read_text(encoding="utf-8").splitlines()[0].strip()
    except Exception:
        disk_pin = ""
    if disk_pin != cfg.pin:
        report.add_failure(
            ValidationFailure.PIN_MISMATCH,
            "configured pin does not match vault pin file",
        )
        return report

    manifest_path = cfg.path / MANIFEST_FILENAME
    if not manifest_path.is_file():
        report.add_failure(ValidationFailure.MANIFEST_MISSING, MANIFEST_FILENAME)
        return report
    try:
        manifest = load_manifest(cfg.path)
    except Exception as exc:  # noqa: BLE001 — fail closed on any parse issue
        report.add_failure(ValidationFailure.MANIFEST_MALFORMED, str(exc)[:200])
        return report

    if manifest.pin != cfg.pin:
        report.add_failure(
            ValidationFailure.PIN_MISMATCH,
            "manifest pin does not match configured pin",
        )
        return report

    for art in manifest.artifacts:
        apath = cfg.path / art.path
        if not apath.is_file():
            report.add_failure(ValidationFailure.ARTIFACT_MISSING, art.path)
            continue
        try:
            actual = _sha256_file(apath)
        except Exception:
            actual = ""
        if actual != art.sha256:
            report.add_failure(ValidationFailure.HASH_MISMATCH, art.path)

    report.manifest = manifest
    report.total_count = len(manifest.artifacts)
    report.approved_count = sum(1 for a in manifest.artifacts if a.retrievable())
    report.quarantined_count = sum(
        1 for a in manifest.artifacts
        if a.admission_state == AdmissionState.QUARANTINE.value
    )
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI smoke: python -m src.logos_vault.validate (uses env config)."""
    report = validate_vault()
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
