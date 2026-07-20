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


def test_desktop_v2_layer_present():
    """V2 cinematic layer: swarm chat, instruments, editor, neural field."""
    for marker in ("core-war-room", "Message the swarm", "modelsel", "tokmeter",
                   "bgfx", "delegated_authority.yaml", "never_may", "typing",
                   "fgraph", "Policy Editor"):
        assert marker in HTML, marker


def test_desktop_v2_still_never_acts():
    """The chat/editor layer simulates; the model preference cannot under-floor."""
    assert "SIMULATED" in HTML
    assert "never under-floor" in HTML or "can never under-floor" in HTML
    assert "self_expand_authority" in HTML


def test_desktop_v3_aide_and_flows():
    """V3: GRIT Aide oracle, workflow canvas, tabbed editor, boot sequence."""
    for marker in ("aide-orb", "GRIT Aide", "Logos four-mind", "where do I start",
                   "Workflow — the governed path", "Run simulation", "fl-node",
                   "drone-contract.md", "logos-synthesis.md", "ed-tab",
                   "governed autonomous work"):
        assert marker in HTML, marker


def test_desktop_v3_aide_holds_no_authority():
    """The oracle points; it never pushes. Consequential asks route to approvals."""
    assert "not an actuator" in HTML
    assert "I hold no authority" in HTML
    assert "interrupt for nothing below HIGH" in HTML


def test_desktop_v4_orb_draggable_and_local_doctrine():
    assert "grit-aide-pos" in HTML          # persisted orb position
    assert "stopImmediatePropagation" in HTML  # drag does not trigger toggle
    assert "own LLM subscriptions" in HTML  # subscription, not API


def test_desktop_v5_guided_mode_default():
    """Calm Guided Mode: default landing, plain language, one primary action."""
    # guided is the default when no stored preference exists
    assert 'localStorage.getItem(MODE_KEY) || "guided"' in HTML
    for marker in ("Everything is protected", "needs your attention",
                   "Nothing has been sent", "Ask AgentGRIT", "Check my projects",
                   "Start something new", "Advanced view", "Simple view",
                   "Why am I seeing this?", "Recent activity"):
        assert marker in HTML, marker


def test_desktop_v5_plain_guide_identity_and_refusal():
    """Guide leads with plain identity; mythology demoted to About details."""
    assert "I keep track of what needs attention" in HTML
    assert "I cannot approve, publish, spend, or deploy anything for you" in HTML
    assert "About this assistant (technical details)" in HTML  # Logos lives here now
    assert "a person always does that part" in HTML  # ask-to-publish refusal


def test_desktop_v5_comfort_and_accessibility_contract():
    assert "Comfortable reading" in HTML
    assert "min-height:48px" in HTML          # primary touch targets
    assert "font-size:18px" in HTML           # guided base text size
    assert ":focus-visible{outline:3px" in HTML  # visible keyboard focus
    assert "body.comfort *{animation:none" in HTML  # comfort kills motion


def test_desktop_v5_no_new_action_surface():
    """Guided mode adds zero fetches and zero acting buttons."""
    import re
    for m in re.finditer(r"fetch\((`|\"|')([^`\"']+)", HTML):
        assert "/console/data" in m.group(2), m.group(2)
    assert "Reviewing here never triggers anything" in HTML
