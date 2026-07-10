# Component maturity

Honest scope, so you know what is production-grade versus reference. AgentGRIT's
value is the governance core; the operator surfaces (API, bot) are reference
integrations you are expected to wire to your own orchestrator.

| Component | Status | Notes |
|---|---|---|
| Bylaw engine (`src/governance/bylaws.py`) | **Solid** | Deterministic, tested. Blocks destructive patterns, escalates risk. |
| Pillar Inspector (`src/governance/pillars.py`) | **Solid** | Deterministic 5-pillar scorecard, tested. |
| Research quality (`src/governance/research_quality.py`) | **Solid** | Deterministic evidence gating + conflict detection (CONTESTED); env-global defaults; optional per-project overrides via `config/projects/<name>.yaml`. Live from `research.culminate`. |
| Decision records (`src/governance/decision_record.py`) | **Solid** | Deterministic; wired into `router.execute`, `research.culminate`, and cost_governor BLOCK/ESCALATE. |
| Autonomy matrix (`src/governance/autonomy.py`) | **Solid** | Risk×Trust×bylaw×evidence gate. **Live + binding** in `router.execute`: `classify_action_risk` + `must_stop` DENY/ESCALATE before any model call; REQUIRE_BRIEFING proceeds after record. |
| Budget governor (`src/governance/budget_governor.py`) | **Solid** | Priority-aware dollar facade; **live** from `cost_governor.govern()` via `check_estimated_usd`. Hard ceiling never rises for priority. |
| Priority manager (`src/governance/priority_manager.py`) | **Solid** | `config/priorities.yaml` weights; live via budget_governor + cost_governor. |
| Config loader (`src/governance/config_loader.py`) | **Solid** | `config/budget.yaml` + `priorities.yaml`; defaults identical to historical GovernorConfig/env when files absent. |
| Daily debrief (`src/agents/daily_debrief_agent.py`) | **Solid** | Deterministic rollup; **schedulable** via `make debrief` / `run_debrief_and_notify` (optional notify). Public repo has no GM cron — wire from your scheduler. |
| Idea→project (`src/planning/idea_to_project.py`) | **Solid** | Offline scaffold (`projects/<slug>/`); CLI + `make idea-project`. |
| Skill discovery (`src/execution/skill_discovery.py` + `skills/`) | **Solid** | Drop-in `skills/` catalog; `discover_local` + CLI; propose-only (no install). |
| Research layer (`src/execution/research.py`, `research_providers.py`) | **Solid** | Free-first, provider-agnostic, budget-governed. DuckDuckGo works keyless; add your own provider keys. |
| Deliberation (`src/governance/deliberation.py`) | **Working** | JR→Manager local-model review; requires a local model (Ollama). Fails safe to escalate. |
| Trust ladder (`src/governance/trust.py`) | **Working** | State machine present; promotion/demotion policy is conservative by default. |
| Cost-first router (`src/execution/router*.py`) | **Solid** | Capability-based routing + binding autonomy; tested. |
| Notifications (`src/utils/notify.py`) | **Working** | Pluggable channels (Telegram/webhook/command); opt-in. |
| FastAPI server (`src/api/server.py`) | **Working** | Endpoints are scaffolding for your orchestrator, but guarded by an `X-API-Key` dependency that fails closed — it refuses to serve on a non-loopback host unless `API_SECRET_KEY` is set. See SECURITY.md. |
| Telegram bot (`src/bot/telegram.py`) | **Reference** | Command surface scaffolding — wire spawn/status handlers to your orchestrator. Hardened bot remains the `main.py` control plane. |
| Reply capture | **Not included** | Reading human replies is platform-specific (e.g. macOS Messages). The notify/ask direction is pluggable; implement capture for your channel. |

"Solid" = deterministic and unit-tested. "Working" = functional, may need your
config (local model, keys). "Reference" = a starting point you complete for your
stack. Do not expose the API without reading `SECURITY.md`.

How the pieces move together — task lifecycle, trust ladder, and per-project
doctrine flow, with each node mapped to its module: [DIAGRAMS.md](DIAGRAMS.md).
