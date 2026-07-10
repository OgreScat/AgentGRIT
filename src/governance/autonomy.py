"""
Autonomy Matrix -- deterministic gate for "may the GM act alone?"

Composes EXISTING surfaces only:
  * RiskLevel          (src/governance/escalations.py)
  * TrustLevel         (src/governance/trust.py)
  * BylawAction        (src/governance/bylaws.py) -- optional
  * research_quality.Verdict / require_human -- optional

It DECIDES the autonomy posture; it does not execute, notify, or invent
risk. Every input is duck-typed so callers can pass real enums or their
string values. When inputs are missing or contradictory, the default is
REQUIRE_BRIEFING or ESCALATE -- never silent ALLOW.

Gate meanings:
  ALLOW             -- GM may act; log and continue (LOW/MEDIUM under trust)
  REQUIRE_BRIEFING  -- act only after the human has been informed (async OK);
                       used for UNTRUSTED low-risk and soft cost/plan notes
  ESCALATE          -- stop; human must decide before any side effect
  DENY              -- hard refuse (bylaw block / provenance fence); complete
                       logged outcome, no human needed to say no

This module is pure and import-light. Wire it at call sites that currently
branch on trust or risk ad-hoc (router, cost_governor consumers, culminate).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class AutonomyGate(str, Enum):
    ALLOW = "allow"
    REQUIRE_BRIEFING = "require_briefing"
    ESCALATE = "escalate"
    DENY = "deny"


def _val(x: Any) -> Any:
    return x.value if isinstance(x, Enum) else x


def _risk_int(risk: Any) -> int:
    """Normalize RiskLevel (IntEnum), name, or int to comparable int.
    Unknown -> HIGH (30) so we fail toward human review, not ALLOW."""
    if risk is None:
        return 30  # HIGH
    if isinstance(risk, int) and not isinstance(risk, bool):
        return int(risk)
    v = _val(risk)
    if isinstance(v, int) and not isinstance(v, bool):
        return int(v)
    names = {"low": 10, "medium": 20, "high": 30, "critical": 40}
    if isinstance(v, str) and v.lower() in names:
        return names[v.lower()]
    return 30


def _trust_str(trust: Any) -> str:
    if trust is None:
        return "untrusted"
    v = _val(trust)
    return str(v).lower() if v is not None else "untrusted"


@dataclass(frozen=True)
class AutonomyDecision:
    gate: AutonomyGate
    reason: str
    risk: int
    trust: str

    def to_entry(self) -> dict:
        return {
            "gate": self.gate.value,
            "reason": self.reason,
            "risk": self.risk,
            "trust": self.trust,
        }


def decide(
    risk: Any = None,
    trust: Any = None,
    *,
    bylaw_action: Any = None,
    evidence_verdict: Any = None,
    evidence_require_human: bool = False,
) -> AutonomyDecision:
    """Return the autonomy gate for this (risk, trust, bylaw, evidence) tuple.

    Order is intentional and fail-safe:
      1. Bylaw BLOCK -> DENY (refusal is a complete decision)
      2. Contested evidence -> ESCALATE (never average a contradiction)
      3. Bylaw ESCALATE or evidence.require_human -> ESCALATE
      4. HIGH / CRITICAL risk -> ESCALATE (human decides the severe)
      5. UNTRUSTED trust -> REQUIRE_BRIEFING (LOW) or ESCALATE (MEDIUM+)
      6. TRUSTED / AUTONOMOUS + LOW/MEDIUM -> ALLOW
      7. Anything else -> REQUIRE_BRIEFING
    """
    r = _risk_int(risk)
    t = _trust_str(trust)
    ba = _val(bylaw_action)
    ev = _val(evidence_verdict)

    if ba == "block":
        return AutonomyDecision(
            AutonomyGate.DENY, "bylaw hard block", r, t,
        )

    if ev == "contested":
        return AutonomyDecision(
            AutonomyGate.ESCALATE,
            "trusted sources disagree (CONTESTED) -- resolve before acting",
            r, t,
        )

    if ba == "escalate" or evidence_require_human:
        why = (
            "bylaw requires human decision" if ba == "escalate"
            else "evidence requires human review"
        )
        return AutonomyDecision(AutonomyGate.ESCALATE, why, r, t)

    if ev == "insufficient":
        return AutonomyDecision(
            AutonomyGate.ESCALATE,
            "evidence insufficient for action",
            r, t,
        )

    # HIGH=30, CRITICAL=40 -- matches escalations.RiskLevel
    if r >= 30:
        return AutonomyDecision(
            AutonomyGate.ESCALATE,
            f"risk {r} is HIGH/CRITICAL -- human decides the severe",
            r, t,
        )

    if t == "untrusted":
        if r >= 20:  # MEDIUM+
            return AutonomyDecision(
                AutonomyGate.ESCALATE,
                "UNTRUSTED trust + MEDIUM risk -- escalate until track record earned",
                r, t,
            )
        return AutonomyDecision(
            AutonomyGate.REQUIRE_BRIEFING,
            "UNTRUSTED trust -- inform human before/as acting on LOW risk",
            r, t,
        )

    if t in ("trusted", "autonomous") and r <= 20:
        return AutonomyDecision(
            AutonomyGate.ALLOW,
            f"{t.upper()} trust may auto-decide LOW/MEDIUM risk",
            r, t,
        )

    return AutonomyDecision(
        AutonomyGate.REQUIRE_BRIEFING,
        "default fail-safe: brief human when posture is unclear",
        r, t,
    )


def may_auto_act(decision: AutonomyDecision) -> bool:
    """True only for ALLOW. REQUIRE_BRIEFING is not silent autonomy."""
    return decision.gate is AutonomyGate.ALLOW


def must_stop(decision: AutonomyDecision) -> bool:
    """True when the gate forbids side effects: DENY or ESCALATE.

    REQUIRE_BRIEFING proceeds (caller must have recorded the brief) — it is
    not a hard stop. Unknown/missing decisions fail toward stop.
    """
    if decision is None:
        return True
    return decision.gate in (AutonomyGate.DENY, AutonomyGate.ESCALATE)


# ── Per-action risk classifier (deterministic, pattern-based) ─────────────────
# Maps action text (+ optional bylaw result) to RiskLevel ints matching
# escalations.RiskLevel: LOW=10, MEDIUM=20, HIGH=30, CRITICAL=40.
# Never invents monetary cost; only classifies severity of the *kind* of act.

# CRITICAL: irreversible money movement, destructive system-wide ops
_CRITICAL_PATTERNS = (
    r"\b(wire|send|execute)\s+(a\s+)?(payment|transfer|trade)\b",
    r"\b(transfer|move)\s+(funds|money|usd|btc|eth)\b",
    r"\b(place|execute)\s+(an?\s+)?(order|trade)\b",
    r"\bdrop\s+table\b",
    r"\brm\s+-rf\s+/\b",
    r"\bgit\s+push\s+--force\b.*\b(main|master)\b",
    r"\bforce.?push\b.*\b(main|master)\b",
)

# HIGH: production deploy, secret rotation, publish, destructive scoped ops,
# and attorney-side irreversible legal acts (file/serve/advise-client).
_HIGH_PATTERNS = (
    r"\b(deploy\s+to\s+prod|production\s+deploy|deploy\s+production)\b",
    r"\b(rotate|revoke|exfiltrate)\s+(api[_ -]?keys?|secrets?|credentials?|tokens?)\b",
    r"\b(publish\s+(the\s+)?(repo|package|release)|make\s+\w+\s+public)\b",
    r"\bgh\s+repo\s+(create|edit)\b",
    r"\b(delete|destroy|wipe)\s+(the\s+)?(production|prod|database|db|secrets?)\b",
    r"\brm\s+-rf\b",
    r"\bgit\s+push\s+--force\b",
    r"\b(payment|payout|wire\s+transfer)\b",
    r"\b(chmod\s+777|disable\s+auth|skip\s+verification)\b",
    # Legal domain: filing / serving / client advice are never auto-run
    r"\b(file|filing)\s+(a\s+)?(motion|complaint|brief|pleading|lawsuit|petition)\b",
    r"\b(serve|service\s+of)\s+(process|a\s+subpoena|the\s+complaint)\b",
    r"\badvise\s+(a\s+|the\s+)?client\b",
    r"\bsend\s+(a\s+)?(demand\s+letter|cease.?and.?desist|filing)\b",
)

# MEDIUM: multi-file writes, migrations, schema, auth-adjacent
_MEDIUM_PATTERNS = (
    r"\b(migrat|refactor|rewrite)\b",
    r"\b(schema\s+change|alter\s+table)\b",
    r"\b(auth|permission|acl|rbac)\b",
    r"\b(across\s+(the\s+)?(codebase|project)|multiple\s+files)\b",
)


def classify_action_risk(
    action: str,
    *,
    bylaw_result: Any = None,
    reversible: bool | None = None,
) -> int:
    """Deterministic risk int for an action string.

    Precedence:
      1. CRITICAL patterns → 40
      2. HIGH patterns → 30
      3. Bylaw BLOCK already refused (caller still gets HIGH for audit) → 30
      4. Bylaw ESCALATE (severity implied) → 30
      5. MEDIUM patterns → 20
      6. Explicit irreversible + non-trivial action → 20
      7. Default → 10 (LOW)

    Fail-safe: empty/None action → HIGH (30), not silent LOW.
    """
    if not action or not str(action).strip():
        return 30
    text = str(action).lower()

    for pat in _CRITICAL_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return 40
    for pat in _HIGH_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return 30

    ba = _val(getattr(bylaw_result, "action", None)) if bylaw_result is not None else None
    if ba in ("block", "escalate"):
        # Bylaw already flagged severity; do not under-rank.
        return 30

    for pat in _MEDIUM_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return 20

    if reversible is False and len(text) > 20:
        return 20

    return 10


if __name__ == "__main__":
    demos = [
        decide(risk="low", trust="autonomous"),
        decide(risk="high", trust="autonomous"),
        decide(risk="low", trust="untrusted"),
        decide(risk="medium", trust="untrusted"),
        decide(risk="low", trust="trusted", bylaw_action="block"),
        decide(risk="low", trust="trusted", evidence_verdict="contested"),
        decide(risk="low", trust="trusted", evidence_require_human=True),
    ]
    for d in demos:
        print(f"{d.gate.value:18}  risk={d.risk} trust={d.trust}  -- {d.reason}")
    print("--- classify ---")
    for s in (
        "format this file",
        "deploy to production and rotate secrets",
        "execute a wire transfer of funds",
        "refactor across the codebase",
    ):
        print(f"  {classify_action_risk(s):2d}  {s}")
