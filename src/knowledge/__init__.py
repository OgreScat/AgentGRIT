"""Knowledge — governed Markdown-vault knowledge source for AgentGRIT (Phase 1, reference).

Generic, domain-neutral capability: treat a folder of Markdown notes as a *governed*
knowledge source. Notes are classified (policy | evidence | proposal | archive),
provenance-tracked (sha256 + git rev), path-fenced, secret-scanned, and served to a
worker only as a bounded, untrusted-data-wrapped ContextBundle — never as raw vault
access, never as executable instructions.

This ships NO configured vault, NO project names, NO private data — only the machinery
and empty slots. A downloader points it at their own vault and defines their own
project roots and sensitivity policy.

Status: Phase 1 / reference. Deterministic only — no embeddings, no LLM, no network.
"""

from .compiler import (
    KnowledgeNote,
    compile_vault,
    parse_frontmatter,
    MANIFEST_SCHEMA,
)
from .bundle import ContextBundle, build_bundle, select_by, UNTRUSTED_HEADER

__all__ = [
    "KnowledgeNote",
    "compile_vault",
    "parse_frontmatter",
    "MANIFEST_SCHEMA",
    "ContextBundle",
    "build_bundle",
    "select_by",
    "UNTRUSTED_HEADER",
]
