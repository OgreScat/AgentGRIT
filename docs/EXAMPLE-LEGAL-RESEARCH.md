# Example: Legal Research Advisor (governed, attorney-tool only)

**Research aid for a licensed attorney. Not legal advice. Verify before filing.**

This is the Repo Steward pattern applied to law: a governed *advisor* that
composes existing primitives. It never files, serves, or sends. Public-record
sources only (CourtListener / Free Law Project). No Westlaw, Lexis, or other
paid databases. No confidential case data belongs in this public repo.

| Primitive | Role |
|---|---|
| `observe.adapters.courtlistener` | Public-record opinion search (`parse_payload` / `search_opinions`) |
| `LLMRouter.route_with_evidence` | Local-first cost routing (evidence trail) |
| `research_quality.assess` | SUFFICIENT / WEAK / **CONTESTED** / INSUFFICIENT |
| `autonomy.classify_action_risk` + `decide` + `must_stop` | FILE/SEND/ADVISE-CLIENT → escalate; research brief may proceed |
| `decision_record.record(..., authorized_by="agent:legal_research")` | One auditable record per run |
| **Cite-or-refuse** | Holding without a verified `courtlistener.com/opinion/…` URL is **dropped** |
| **UPL firewall** | Consumer “advise me / should I sue” requests are refused |

## How to run

```bash
# One-shot (prefer attorney framing in the question)
make agent-legal Q="case law research for counsel: qualified immunity at summary judgment"

# Equivalent CLI
python -m src.agents.legal_research_agent \
  "case law research for counsel: qualified immunity at summary judgment"

# Network-free fixture
python -m src.agents.legal_research_agent \
  --fixture tests/fixtures/legal/courtlistener_search.json \
  "case law research for counsel: qualified immunity at summary judgment"

# Via orchestrator (demo loop; dry-run safe)
python -m src.main --agent legal_research --dry-run
```

Optional: set `COURTLISTENER_TOKEN` (or `COURTLISTENER_API_TOKEN`) for higher
API rate limits. The adapter works without a token when the API allows it and
fails safe to `[]` otherwise.

---

## Sample A — fixture run with real citation shape + dropped uncited claim + CONTESTED

Command equivalent (unit/integration path; network-free):

```text
LegalResearchAgent.run_once(
  "case law research for counsel: split on qualified immunity doctrine",
  attorney_confirmed=True,
  events=[affirming_opinion, denying_opinion],  # opposite polarity, shared topic
  extra_claims=[{"case_name": "Ghost Precedent v. Vacuum", "holding": "Always win.", "url": ""}],
  skip_free_research=True,
)
```

Output (abridged from a real local run on 2026-07-10):

```
LEGAL RESEARCH BRIEFING
  Research aid for a licensed attorney. Not legal advice. Verify before filing.
================================================================
  status:     escalate
  decision:   contested
  evidence:   contested (score 0.8)
  autonomy:   escalate
  routed:     perplexity

ISSUE
----------------------------------------------------------------
  case law research for counsel: split on qualified immunity doctrine

AUTHORITIES (cite-or-refuse: verified CourtListener URLs only)
----------------------------------------------------------------
  1. Affirming Case v. State
     citation: 555 U.S. 1
     holding:  qualified immunity summary judgment doctrine confirmed effective …
     source:   https://www.courtlistener.com/opinion/111111/affirming/

  2. Denying Case v. State
     citation: 555 U.S. 2
     holding:  qualified immunity summary judgment doctrine refuted ineffective …
     source:   https://www.courtlistener.com/opinion/222222/denying/

DROPPED (no verifiable citation — not stated as holdings)
----------------------------------------------------------------
  ✗ Ghost Precedent v. Vacuum  [no verified CourtListener opinion URL]

CONTESTED AUTHORITY
----------------------------------------------------------------
  ⚠ irreversible action but sources conflict -> resolve or escalate
    (courtlistener and courtlistener share the topic but assert opposite conclusions)
  Do not treat discordant authority as corroboration.

NEEDS ATTORNEY JUDGMENT
----------------------------------------------------------------
  • Resolve CONTESTED authority before any filing posture.
  • Confirm jurisdiction, procedural posture, and controlling authority.
  • Read the full opinion text at each CourtListener URL before relying.
  • This tool does not practice law and does not create an attorney-client
    relationship with any third party.
  • Any FILE / SEND / ADVISE-CLIENT action is escalated; human only.
  • Autonomy gate requires human decision before any filing or client-facing advice.

SOURCES
----------------------------------------------------------------
  Public-record sources only (CourtListener / Free Law Project).
  No Westlaw, Lexis, or other paid databases are queried.

This agent does NOT file, serve, send, or advise clients. Advisor-to-attorney only.
  Research aid for a licensed attorney. Not legal advice. Verify before filing.
================================================================
```

### What the governance stack did

| Gate | Result |
|---|---|
| Cite-or-refuse | Ghost claim **dropped** (no CourtListener URL) |
| `research_quality.assess` | **CONTESTED** (discordant high-trust sources) |
| Autonomy on research | `must_stop` → escalate (evidence requires human) |
| FILE / SEND / ADVISE-CLIENT proposals | Each classified risk≥30 → escalate |
| `decision_record` | One row, `authorized_by: "agent:legal_research"`, disposition `contested` |

### Decision record shape (same run)

```json
{
  "action": "legal_research: case law research for counsel: split on qualified immunity doctrine",
  "disposition": "contested",
  "authorized_by": "agent:legal_research",
  "evidence": {
    "verdict": "contested",
    "require_human": true
  }
}
```

---

## Sample B — UPL firewall (public advice refused)

```bash
python -m src.agents.legal_research_agent \
  "I am not a lawyer — should I sue my boss? advise me"
```

Status: `refused_upl`. No authorities are stated. Briefing still carries the
attorney-tool disclaimer. A decision record is written with disposition
`refused`.

---

## Explicit scope (read this)

1. **Advisor-to-attorney only.** Not legal advice to the public. Not a substitute
   for a licensed attorney’s professional judgment.
2. **Public record only.** CourtListener / Free Law Project. Paid databases are
   out of scope for this open-source agent.
3. **No confidential matter data in this repo.** Deploy confidential workflows
   in your private layer; this agent is the generic reference implementation.
4. **Never files.** Filing, serving, sending demand letters, and advising a
   client are always escalated side effects.

Verified network-free: `pytest tests/test_legal_research.py -q` (and full
`pytest -q` green at introduction).
