"""GRIT Sentinel — the workspace immune system (Phase Zero: scanner).

Deterministic, local, fail-closed static analysis over files, diffs, skills,
and prompt packages. Verdicts: ALLOW / LIMIT / HOLD / BLOCK. Every scan
emits sha256-identified evidence and appends to an append-only ledger.

Phase Zero is scan+verdict+ledger only. The capability broker (no action
without a matching unexpired authority token) is the named next phase —
nothing here pretends to enforce yet.
"""
from .scan import scan_paths, Verdict, SentinelReport

__all__ = ["scan_paths", "Verdict", "SentinelReport"]
