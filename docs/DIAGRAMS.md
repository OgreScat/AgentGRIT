# AgentGRIT — How it moves

Four diagrams, four questions: how a task moves through governance, what may
run without a human, how per-project doctrine shapes the agents, and what the
audit trail captures. Every node names the module that implements it — the
diagrams are checkable against the code, not marketing shapes. (System overview:
[`architecture.svg`](architecture.svg) in the README.)

## 1. Task lifecycle — classify, route, verify, prove

```mermaid
flowchart TD
    A["Task arrives"] --> B["Classify + route<br/>router_v2.py — emits a stated reason"]
    B --> C{"Bylaw gate<br/>bylaws.py — Law-0 blocks"}
    C -- "forbidden" --> X["REFUSED<br/>logged with reason, never executed"]
    C -- "allowed" --> D["Execute on cheapest capable model<br/>capability_map.py + quota_fallback.py"]
    D --> E{"Verify against reality<br/>verification.py + pillars.py"}
    E -- "evidence holds" --> F["DONE — with evidence to point to"]
    E -- "evidence weak" --> G{"Research-quality gate<br/>research_quality.py"}
    G -- "insufficient" --> H["ESCALATE to human<br/>deliberation.py verdict + notify"]
    F --> M["Lessons + audit trail<br/>memory.py + logs/"]
    X --> M
    H --> M
```

Nothing reaches DONE without evidence; a refusal or escalation is a *complete,
logged outcome*, not a failure state.

## 2. Trust ladder — what runs without you

```mermaid
flowchart LR
    subgraph EARNED["Trust is earned, never assumed — trust.py + data/trust_state.json"]
        U["UNTRUSTED<br/>every plan escalates"] -- "5 green eval runs" --> T["TRUSTED<br/>routine plans auto-approve"]
        T -- "20 green eval runs" --> AU["AUTONOMOUS<br/>governed loops may run unattended"]
        AU -- "any red eval / violation" --> U
    end
```

```mermaid
flowchart TD
    L["Recurring loop<br/>loops.py + loops.json"] --> R{"Risk vs the loop's<br/>declared trust ceiling"}
    R -- "LOW / MEDIUM<br/>at or under ceiling" --> AUTO["Runs unattended<br/>logged, gardener-checked nightly"]
    R -- "HIGH / CRITICAL<br/>over ceiling" --> HUM["Stops and escalates<br/>human decision via your channel"]
```

Demotion is one bad eval; promotion is many good ones. Loops carry their own
ceilings — a loop can never quietly exceed the autonomy it declared.

## 3. Per-project doctrine — specialists under one constitution

```mermaid
flowchart TD
    P["Project folder<br/>_START_HERE.md · MEMORY.md"] --> CL["context_loader.py<br/>doctrine folded into the task<br/>(unconfigured project: NO_PROJECT_CONTEXT_FOUND, escalate — never guess)"]
    CL --> PE["Persona layer — persona.py<br/>adds a specialist voice ON TOP of the constitution floor;<br/>no persona can reason its way out from under the bylaws"]
    PE --> JR["JR drafts<br/>local model"]
    JR --> MG["Manager reviews vs doctrine<br/>deliberation.py"]
    MG --> GM{"GM verdict"}
    GM -- "benign + proceed" --> ACT["Act — silent, logged"]
    GM -- "high-stakes or uncertain" --> ESC["Escalate to human<br/>fails safe when the local model is absent"]
    ACT --> MEM["memory.py — lessons, facts, corrections<br/>accumulated doctrine shapes future behavior"]
    ESC --> MEM
```

Personas and project configs ship empty by design — GRIT supplies the machinery
and the constitution; you supply the specialists and the projects.

## 4. Decision record — the auditable "why"

```mermaid
flowchart TD
    R["router.RoutingDecision<br/>provider · cost · cheaper options passed over"] --> C["decision_record.compose()<br/>derives disposition deterministically"]
    BY["bylaws.BylawResult<br/>proceed / escalate / block"] --> C
    EV["research_quality.Assessment<br/>verdict · score · conflict signal"] --> C
    C --> D{"Disposition"}
    D -- "bylaw block" --> REF["REFUSED"]
    D -- "sources disagree" --> CON["CONTESTED"]
    D -- "escalate / require_human" --> ESC2["ESCALATED"]
    D -- "cleared" --> PRO["PROCEED"]
    REF --> W["record() → logs/decisions.jsonl<br/>append-only, fail-safe · render() → plain text"]
    CON --> W
    ESC2 --> W
    PRO --> W
```

Every field traces to a real upstream result — nothing is invented or
estimated-as-fact. This is the artifact a compliance reviewer reads: what was
decided, the cheaper options passed over and why, the evidence behind it, and who
or which threshold authorized it. See `src/governance/decision_record.py`
(`python -m src.governance.decision_record` prints a sample of each disposition).
