# AgentGRIT v0.1.0 — Release Notes

**AgentGRIT is the operating layer that makes AI agents safe to leave running** — by governing what they can do, routing work to the cheapest capable model, and requiring proof before marking anything done. It is a governance-first runtime, not a chatbot or a model replacement. See [README](README.md) and [docs/STATUS.md](docs/STATUS.md) for component maturity.

## What's in v0.1.0

- **Cost-first routing** — classify each task, send it to the cheapest capable model (local Ollama first), escalate to cloud only when the task needs it. Quota/429 on a frontier model descends the ladder instead of failing.
- **Bylaws, not approval gates** — agents enforce rules on themselves; a deterministic (non-LLM) engine blocks destructive commands (Law 0) and gates risk.
- **Evidence before "done"** — completion requires a tool result to point to, not an assertion. A native Pillar Inspector and a research-quality gate refuse action on weak/uncorroborated evidence.
- **Governed autonomy** — LOW/MEDIUM risk is handled autonomously; HIGH/CRITICAL escalates through a two-person-integrity flow to a human (reference notification surfaces: Telegram / webhook / command — wire your own).
- **Governed loops** — declare recurring jobs with a per-loop trust ceiling; a loop auto-runs only up to its declared risk.
- **Nightly gardener** — deterministic checkers keep the memory layer honest (secrets-in-docs, map drift, bloat). A rule without a checker does not exist.
- **Governed skill-discovery** — find capabilities (direct / adjacent / recombination), review on merits, auto-green-light the clearly-good, auto-reject the clearly-bad; a human sees only secret-access / unvetted-code / high-stakes cases.
- **Live HUD** (`make hud`) — GM status, escalations, models, system usage.

## Security hardening in this release

- **Fail-closed API auth** — every endpoint except `/health` + docs requires a matching `X-API-Key` (constant-time compare) when `API_SECRET_KEY` is set; with no key set the server serves loopback-only and *refuses* a non-loopback bind (HTTP 503).
- **Shell-exec gate** — command execution runs through Law-0 blocked-pattern checks before executing; a destructive command is refused (exit 126) and never runs.
- **Bounded exhaust** — JSONL logs rotate at a size cap, paired with the gardener's large-file checker.

## Reproducible verification (clean room)

Run yourself — this is exactly how it was verified:

```bash
git clone <this-repo> agentgrit && cd agentgrit
python3.11 -m venv venv && ./venv/bin/python -m pip install -e ".[dev]"
./venv/bin/python scripts/smoketest.py     # -> 9 passed, 0 failed
./venv/bin/python -m pytest -q               # -> exit 0
```

Verified 2026-07-08 from a fresh clone + fresh venv: install exit 0, smoketest **9 passed / 0 failed**, full suite **pytest exit 0**, and the documented entry points (`src.main`, `src.api.server`, `grit`) all import cleanly. Single squashed commit; `git fsck` clean; no personal identifiers in tree or history.

## Honest scope

Maturity is disclosed in [docs/STATUS.md](docs/STATUS.md): the governance core (bylaws, Pillar Inspector, research-quality, router, gardener) is **Solid** (deterministic + unit-tested); deliberation and trust ladder are **Working** (need a local model / config); the FastAPI server and Telegram bot are **Reference** surfaces you wire to your own orchestrator. Star-count skill vetting is a weak signal — populate `TRUSTED_SOURCES` for real trust.
