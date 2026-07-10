# Contributing to AgentGRIT

Thanks for your interest. AgentGRIT is a governance-first agent runtime — the
bar for changes is a little different from most agent frameworks: governance
behavior must stay legible, deterministic, and tested.

## Ground rules

1. **Governance stays deterministic.** The bylaw engine, Pillar Inspector, and
   research-quality assessment must not depend on an LLM to reach a verdict. If a
   change makes a governance decision opaque, it will be rejected.
2. **New governance behavior needs a test.** Anything that can block, escalate,
   or gate an action must have a unit test proving it (see `tests/test_pillars.py`
   and `tests/test_research_quality.py` for the pattern).
3. **No hardcoded providers or personal data.** Providers, models, endpoints, and
   notification channels are configured via env/bylaws, never hardcoded. There
   are no personal identifiers anywhere in the tree.
4. **Evidence over assertion.** Don't claim a behavior works — add a test or a
   reproducible command that shows it.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q            # all tests should pass
ruff check .
```

## Making a change

- Keep pull requests focused. One behavior per PR.
- Run `pytest -q` and `ruff check .` before opening a PR.
- If you touch the bylaws, pillars, trust ladder, or research-quality thresholds,
  say so explicitly in the PR description — those are the safety-critical parts.
- Update the relevant doc (`docs/`, `README.md`) if you change a public behavior.

## What we especially want

- More deterministic governance checks and their tests.
- Additional research providers (conform to `ResearchProvider` in
  `src/execution/research_providers.py`).
- Notification channels (conform to the pluggable `notify` contract).
- Calibration data / baselines for the quality thresholds.

## What we will not merge

- LLM-in-the-loop governance verdicts (breaks determinism/auditability).
- Provider-lock-in or hardcoded credentials.
- Features that bypass the human escalation path for high-stakes actions.

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities via a private advisory,
never a public issue with a working exploit.
