"""AgentGRIT Desktop — read-only invariants and self-containment."""
from __future__ import annotations

import re
from pathlib import Path

HTML = (Path(__file__).resolve().parent.parent / "src/api/desktop.html").read_text(encoding="utf-8")


def test_desktop_route_is_get_only():
    from src.api import server
    routes = [(getattr(r, "path", ""), getattr(r, "methods", None) or set()) for r in server.app.routes]
    desk = [(p, m) for p, m in routes if p == "/desktop"]
    assert desk, "/desktop route missing"
    for _, methods in desk:
        assert "GET" in methods
        assert not {"POST", "PUT", "DELETE", "PATCH"} & methods


def test_desktop_html_self_contained():
    assert "cdn." not in HTML.lower()
    assert "https://" not in HTML
    # only http:// occurrences allowed are SVG namespace declarations in data URIs
    for m in re.finditer(r"http://[^'\"\s)]+", HTML):
        assert m.group(0).startswith("http://www.w3.org/"), m.group(0)
    assert "<script src" not in HTML.lower()
    assert "@import" not in HTML


def test_desktop_never_acts():
    assert "NEVER ACTS" in HTML
    assert 'method="post"' not in HTML.lower()
    # every fetch targets the read-only console rollup
    for m in re.finditer(r"fetch\((`|\"|')([^`\"']+)", HTML):
        assert "/console/data" in m.group(2), m.group(2)


def test_desktop_core_surfaces_present():
    for marker in ("Mission Control", "Agent Room", "Approval Center", "Evidence Inspector",
                   "Routing + Cost Ledger", "Historian", "Artifact Explorer", "Policy + Trust Center",
                   "trust ladder", "What needs you now", "POLICY BLOCKED"):
        assert marker.lower() in HTML.lower(), marker


def test_desktop_three_lens_and_labels():
    assert "FABLE" in HTML and "GROK" in HTML and "TERRA" in HTML
    for tok in ("CERTAIN", "LIKELY", "ASSUMPTION", "UNKNOWN"):
        assert tok.lower() in HTML.lower()
