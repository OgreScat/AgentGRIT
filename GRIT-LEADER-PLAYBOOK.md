# GRIT Leader Playbook — the leader/worker setup with AgentGRIT as the soul

The viral "run one model as the leader, cheaper models as labor" workflow, rebuilt on real
governance. **Key insight: this architecture is what AgentGRIT's bylaws/trust-ladder system was
built for** — cost-first routing (expensive brain plans/reviews, cheap labor executes), a trust
ladder, evidence bundles, no self-graded homework. This playbook captures the pattern and wires
it to your own projects.

## The team (an example shape — build yours under `.claude/agents/` or your tool's equivalent)

| Agent | Model | GRIT role | Job |
|---|---|---|---|
| `grit-builder` | high-capability | DEVELOPER | exactly one task from the plan; TDD; evidence or it didn't happen |
| `grit-verifier` | high-capability | fresh eyes | re-runs proof itself (e.g. `verify.sh`); hallucination + scope-creep checks; PASS/FAIL only |
| `grit-scribe` | cheaper tier | cost tier | docs/doctrine appends; never touches code (cost-first routing in action) |

Fan out research and architecture work to whatever research/planning agents your tooling
provides. **Don't create speculative workers** — one worker one lane, add lanes when a real job
demands them. If you run a local model as a bottom rung, have it earn lanes via
`grit.py eval` and the trust ladder (UNTRUSTED → TRUSTED → AUTONOMOUS, any failure demotes),
never on faith — `src/governance/model_provenance.py` is the lineage gate that backs this.

## Leader protocol (per job)

1. **Plan first** (plan mode / a planning agent). Brief format — outcome + constraints + reason:
   *"I'm preparing X for [who]; they need [what]. Constraints: [red-lines]. Plan first, then
   delegate, verify every stage."*
2. **Delegate parallel lanes** — only when lanes don't touch the same files.
3. **Verify every stage cold** — `grit-verifier` re-runs the proof; FAIL goes back with notes.
   A stage never advances on the builder's word.
4. **Evidence-bundle the result** — commit message records what was verified and how (the same
   convention this project's own CLAUDE.md should codify for you).
5. **Scribe records** — doctrine append with the run's real numbers.

## Finish lines that can't be faked

Demanding "pasted proof" isn't enough on its own. Go further: **the proof is an executable
gate**, not prose.

- Example: *"done when `bash scripts/verify.sh` exits 0 — paste its full output — or stop after
  N turns."* The gate itself checks tests/typecheck/build/licensing; a worker cannot satisfy it
  with words.
- Always include the **brake** ("or stop after N turns") and the **honesty line** ("every
  progress claim must point to a real result from this run") — the honesty line IS the GRIT
  evidence bundle.
- Loops (scheduled agents, unattended runs) get the same finish-line discipline. Never start an
  unattended loop without a brake in writing.

## The five workflows, mapped to your own projects

Fill these in with your own project names — the shapes are what matter:

1. **Giant codebase job** → a large multi-stage expansion or migration: stage per unit of work,
   verifier gates each stage.
2. **Deep research sprint** → a legal/compliance/competitive-landscape packet: one research
   agent, one doc, verified against primary sources.
3. **The orchestrator** → this playbook, standing. The architecture outlives any one model — the
   leader seat is a role, not a model (GRIT principle: whatever ships next slots into the same
   seat).
4. **Reference-driven frontend** → any UI/screen work: folder of reference screenshots in-repo,
   builder builds against them, verifier compares output to reference.
5. **Knowledge base** → a `PRODUCT_DOCTRINE.md`-style living doc for each real project you run
   through GRIT, grown session by session.

## Corrections to the "leader/worker" hype post genre (verified against this very harness)

- ❌ **"Asking it to show reasoning trips a safety filter and silently reroutes you to a lesser
  model" — false.** No such mechanism. Asking for reasoning is fine (verbose, sometimes wasteful —
  that's the real cost).
- ⚠️ **Urgency hooks ("this model leaves the subscription on X date")** — treat as unverified;
  a course-seller's urgency hook. Check the vendor's official channels, not a sales post.
- ⚠️ **Marketing anecdotes** (huge line-count migrations, large runaway spend numbers) —
  unverifiable; the *brake* advice they motivate is still correct.
- ⚠️ **Third-party skill collections** — unvetted third-party skill install (supply-chain rule
  applies); prefer skills you've reviewed yourself. Skip what you haven't vetted.
- ✅ Right, and worth keeping: light CLAUDE.md; worker/verifier separation; parallel lanes;
  evidence-over-claims; plan mode; goals/loops with brakes.
- 🔧 **"Delete half your CLAUDE.md" needs one edit for most projects:** cut process
  *scaffolding*, never *red-lines*. For anything safety- or compliance-sensitive, the
  non-negotiable rules are not scaffolding — they're the constitution. A project's own CLAUDE.md
  should be the light shape: rules + pointers.

## Cockpit mapping (hype-post controls → what this maps to in a real governed setup)

Model pinning ✅ · plan mode ✅ · context compaction/clearing ✅ · MCP tool access ✅ ·
project-context file (e.g. `CLAUDE.md`) ✅ · headless/scripted runs ✅ · effort/thinking-budget
controls ✅ (medium default is usually right; raise it for cascade-grade work) · "goal loops" →
here it's scheduled agents + the same finish-line/judge pattern, whatever your tooling calls it ·
workers → your own `.claude/agents/*` (this playbook's team shape).

## One standing rule

The leader plans, reviews, and decides; workers type; the verifier re-proves. **The brain never
types, and nobody grades their own homework.** That's the whole thesis.
