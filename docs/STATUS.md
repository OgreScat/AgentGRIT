# Component maturity

Honest scope, so you know what is production-grade versus reference. AgentGRIT's
value is the governance core; the operator surfaces (API, bot) are reference
integrations you are expected to wire to your own orchestrator.

| Component | Status | Notes |
|---|---|---|
| Bylaw engine (`src/governance/bylaws.py`) | **Solid** | Deterministic, tested. Blocks destructive patterns, escalates risk. |
| Pillar Inspector (`src/governance/pillars.py`) | **Solid** | Deterministic 5-pillar scorecard, tested. |
| Research quality (`src/governance/research_quality.py`) | **Solid** | Deterministic evidence gating + conflict detection (CONTESTED verdict), tested. |
| Decision records (`src/governance/decision_record.py`) | **Solid** | Deterministic; composes router + bylaw + evidence into one auditable record; renders to plain text; append-only + fail-safe; tested. Wired into `router.execute`, `research.culminate`, and cost_governor BLOCK/ESCALATE. |
| Autonomy matrix (`src/governance/autonomy.py`) | **Solid (advisory)** | Deterministic Risk×Trust×bylaw×evidence gate (ALLOW / REQUIRE_BRIEFING / ESCALATE / DENY); fail-safe default; tested. `router.execute` **records** the gate in its decision but does not yet enforce it (bylaws remain the hard stop); call `may_auto_act()` from your own agents to enforce. Threading real per-action risk into the router is roadmap. |
| Budget governor (`src/governance/budget_governor.py`) | **Solid (library)** | Read facade over `GovernorConfig` thresholds + research paid-call cap; does not invent costs; tested. `govern_plan()` delegates to `cost_governor`; `check_estimated_usd()` is a convenience you call from your agents — not yet on a live call path. |
| Daily debrief (`src/agents/daily_debrief_agent.py`) | **Solid** | Deterministic rollup from decisions/research_budget/router logs; no LLM; tested. |
| Research layer (`src/execution/research.py`, `research_providers.py`) | **Solid** | Free-first, provider-agnostic, budget-governed. DuckDuckGo works keyless; add your own provider keys. |
| Deliberation (`src/governance/deliberation.py`) | **Working** | JR→Manager local-model review; requires a local model (Ollama). Fails safe to escalate. |
| Trust ladder (`src/governance/trust.py`) | **Working** | State machine present; promotion/demotion policy is conservative by default. |
| Cost-first router (`src/execution/router*.py`) | **Solid** | Capability-based routing, tested. |
| Notifications (`src/utils/notify.py`) | **Working** | Pluggable channels (Telegram/webhook/command); opt-in. |
| FastAPI server (`src/api/server.py`) | **Working** | Endpoints are scaffolding for your orchestrator, but guarded by an `X-API-Key` dependency that fails closed — it refuses to serve on a non-loopback host unless `API_SECRET_KEY` is set. See SECURITY.md. |
| Telegram bot (`src/bot/telegram.py`) | **Reference** | Command surface scaffolding — wire spawn/status handlers to your orchestrator. |
| Reply capture | **Not included** | Reading human replies is platform-specific (e.g. macOS Messages). The notify/ask direction is pluggable; implement capture for your channel. |

"Solid" = deterministic and unit-tested. "Working" = functional, may need your
config (local model, keys). "Reference" = a starting point you complete for your
stack. Do not expose the API without reading `SECURITY.md`.

How the pieces move together — task lifecycle, trust ladder, and per-project
doctrine flow, with each node mapped to its module: [DIAGRAMS.md](DIAGRAMS.md).
