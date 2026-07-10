"""Autonomy Matrix -- Risk × Trust × bylaw × evidence, fail-safe defaults."""

from src.governance.autonomy import AutonomyGate, decide, may_auto_act
from src.governance.escalations import RiskLevel
from src.governance.trust import TrustLevel
from src.governance.bylaws import BylawAction


def test_autonomous_low_allows():
    d = decide(risk=RiskLevel.LOW, trust=TrustLevel.AUTONOMOUS)
    assert d.gate is AutonomyGate.ALLOW
    assert may_auto_act(d)


def test_high_risk_escalates_even_when_autonomous():
    d = decide(risk=RiskLevel.HIGH, trust=TrustLevel.AUTONOMOUS)
    assert d.gate is AutonomyGate.ESCALATE
    assert not may_auto_act(d)


def test_critical_escalates():
    d = decide(risk="critical", trust="trusted")
    assert d.gate is AutonomyGate.ESCALATE


def test_untrusted_low_requires_briefing():
    d = decide(risk="low", trust="untrusted")
    assert d.gate is AutonomyGate.REQUIRE_BRIEFING


def test_untrusted_medium_escalates():
    d = decide(risk=RiskLevel.MEDIUM, trust=TrustLevel.UNTRUSTED)
    assert d.gate is AutonomyGate.ESCALATE


def test_block_is_deny():
    d = decide(risk="low", trust="autonomous", bylaw_action=BylawAction.BLOCK)
    assert d.gate is AutonomyGate.DENY


def test_contested_escalates():
    d = decide(risk="low", trust="autonomous", evidence_verdict="contested")
    assert d.gate is AutonomyGate.ESCALATE


def test_require_human_escalates():
    d = decide(risk="low", trust="trusted", evidence_require_human=True)
    assert d.gate is AutonomyGate.ESCALATE


def test_insufficient_escalates():
    d = decide(risk="low", trust="trusted", evidence_verdict="insufficient")
    assert d.gate is AutonomyGate.ESCALATE


def test_unknown_risk_fails_toward_escalate():
    # missing/unknown risk must not silently ALLOW
    d = decide(risk=None, trust="autonomous")
    assert d.gate is AutonomyGate.ESCALATE


def test_trusted_medium_allows():
    d = decide(risk=20, trust="trusted")
    assert d.gate is AutonomyGate.ALLOW
