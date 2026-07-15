# The GRIT Spec-Driven Workflow

*In-house spec-driven development, re-engineered from the pattern (not the codebase) that tools like Spec Kit popularized — but governed. The **soul** is a review doctrine every stage inherits; the **skeleton** is a staged, artifact-based sequence with a GRIT gate at each step. This is GRIT's own thesis — refuse, escalate, prove, leave a trail — applied to how work itself gets built.*

---

## The Soul (inherited by every stage — this is the ethos, verbatim)

> Review, grade, and improve at maximum output in every facet. Account for every issue you will face and surface it before proceeding. Re-prompt yourself for the strongest outcome with full context. Scrutinize like a chess grandmaster seeing every branch. Make no silent assumptions. **Be brutally honest — an uncomfortable truth beats an agreeable error.** Give the human clear next steps, only when needed.

Every stage below runs *through* that lens before it emits its artifact. The workflow is the skeleton; the soul is what keeps the skeleton from executing mechanically. A stage that produces a clean-looking artifact while hiding a contradiction has failed the soul, not passed the stage.

---

## The Skeleton (seven stages, each with an artifact and a GRIT gate)

| # | Stage | What it produces | The GRIT gate it must pass |
|---|---|---|---|
| 1 | **Constitution** | the non-negotiables in force for this work | the bylaws + Zeroth Law + project hard rules (already enforced in `bylaws.py`) |
| 2 | **Specify** | `SPEC` — what we're building, the outcomes, the edge cases, what's explicitly *out* of scope | soul: is this what was actually asked, or what's convenient to build? |
| 3 | **Clarify** | answered open questions — the assumptions made explicit | **maps to GRIT escalation**: the model must ask the human the open questions *before* planning, not silently assume |
| 4 | **Plan** | `PLAN` — architecture, stack, integration boundaries | soul: cheapest capable approach? reversible where possible? |
| 5 | **Tasks** | `TASKS` — ordered, small, individually reviewable units | each task is a unit small enough to verify (bylaw: verify-before-done) |
| 6 | **Analyze** | `RISK` — failure modes, edge cases, reversibility, what could go wrong | **maps to the Pillar Inspector + research-quality/trust gates**; HIGH/CRITICAL risk escalates to a human here, before any code |
| 7 | **Implement** | the change + its evidence | gated by the **trust ladder**; nothing is "done" without a tool result to point to |

**The rule that makes it work:** you do not advance a stage until its artifact exists and its gate passes. Spec before plan. Plan before tasks. Risk analysis before implementation. Clarification before assumption. This is the opposite of "toss a vague prompt at an agent and pray" — it is intent and constraints first, implementation last, with a brutally honest review at every checkpoint.

---

## Why in-house, not a fork

We steal the *shape* (Constitution → Specify → Clarify → Plan → Tasks → Analyze → Implement), not the tooling, for three reasons:

1. **It stays governed.** Each stage inherits GRIT's gates — escalation on ambiguity, the Pillar Inspector on risk, the trust ladder on implementation, evidence-before-done throughout. A generic spec tool has none of that.
2. **It stays provider-agnostic.** No CLI lock-in. The workflow is a doctrine any model can run under, routed cost-first like everything else.
3. **It tailors per stack.** The Constitution stage means something different for a trading module (kill-switches, paper-first) than for legal work (privilege, no unauthorized practice) than for a generic app. Same skeleton, different non-negotiables.

The soul is the constant; the Constitution stage is the variable.

---

## How to invoke it

For any non-trivial task, the operator (human or agent) says: **"Run this spec-driven."** That triggers the seven stages in order, each producing its artifact and passing its gate, with the soul applied throughout. For trivial, reversible work, the full ceremony is overkill — the workflow is for when mistakes are expensive, which is exactly when GRIT earns its keep.

---

*This doctrine is the soul; the seven stages are the skeleton. Together they make disciplined, auditable, brutally-honest development the default — not something that depends on the model remembering to be careful on a given run.*
