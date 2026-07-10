# GRIT -- Verification Runbook (do these in order)

Follow top to bottom. Each step says exactly what to type and what you should
see. Nothing here needs API keys or the internet except where noted. Total
time: ~15 minutes to fully verified.

---

## STEP 0 -- Get the repo (1 min)

```bash
git clone <this-repo-url>
cd AgentGRIT
```

You should see folders: `src/`, `tests/`, `skills/`, `evals/`, and files
`grit.py`, `docs/ARCHITECTURE.md`, `RUNBOOK.md` (this file).

---

## STEP 1 -- Confirm the core works with ZERO setup (2 min)

The cost-governance engine is pure Python (stdlib only). Prove it runs before
installing anything:

```bash
python3 grit.py govern "Research DeFi protocols and review the findings"
```

**Expected:** a printed plan ending in a `VERDICT:` line and a `ROUTING SPEC`
JSON block. If you see that, the brain works. ✅

Try the expensive path:

```bash
python3 grit.py govern "Port our 500-file service from Flask to FastAPI and keep tests passing"
```

**Expected:** `VERDICT: ESCALATE` (because trust starts UNTRUSTED and it's a
token furnace). That's correct behavior -- it's refusing to auto-spend.

---

## STEP 2 -- Run the eval suite + watch trust get EARNED (2 min)

```bash
python3 grit.py eval
```

**Expected:** `12/12 passed`, `ALL PASSED ✅`, then a `TRUST LADDER UPDATE`
block. A report is saved to `evals/last_report.json`.

Now run it 5 times to earn TRUSTED, then check the ladder:

```bash
for i in 1 2 3 4 5; do python3 grit.py eval > /dev/null; done
python3 grit.py trust
```

**Expected:** every pattern shows `trusted (✓5 ✗0, streak 5)`. This is the
autonomy ladder working -- trust is earned by passing evals, not asserted.

> To reset trust at any time: `rm data/trust_state.json`

---

## STEP 3 -- Install Python deps for the FULL system (3 min)

Only needed if you want the API server, Telegram bot, or live LLM routing
(not needed for govern/eval, which you just proved work).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Then run the full test suite:

```bash
python3 -m pytest tests/ -q
```

**Expected:** all tests pass. If something unrelated fails on a missing dep,
note it and move on -- the governance core is already proven in Steps 1-2.

---

## STEP 4 -- Set up Ollama (the free local model) (5 min)

This is what makes routing actually save money -- free local inference for
the soft stages.

```bash
brew install ollama          # if not already installed
ollama serve &               # start the daemon in background
ollama pull qwen3-coder:30b  # or any coding model your hardware handles
```

Verify it answers:

```bash
ollama run qwen3-coder:30b "print hello world in python"
```

**Expected:** it prints a Python snippet. Ctrl+D to exit.

---

## STEP 5 -- Wire your keys (only if running live routing) (2 min)

```bash
cp .env.example .env 2>/dev/null || touch .env
```

Edit `.env` and add what you have (all optional -- Ollama alone works):

```
OLLAMA_ENABLED=true
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3-coder:30b

# optional, only if you have them:
ANTHROPIC_API_KEY=
PPLX_API_KEY=
TELEGRAM_BOT_TOKEN=
ADMIN_IDS=
```

---

## STEP 6 -- The real test: govern a workflow in your own agentic tool (5 min)

This is the payoff, and it's specific to whatever orchestrator you're
pairing GRIT with (a workflow runtime, a folder of subagent prompts, or
your own script).

1. Pick a real task. Get its governed plan:
   ```bash
   python3 grit.py govern "audit every API endpoint under src/ for missing auth checks"
   ```
2. Copy the `ROUTING SPEC` JSON it prints.
3. Hand that spec to your orchestrator when you kick off the task, so stages
   route per the plan instead of defaulting everything to one model.
4. While it runs, note the actual token count each stage used.

---

## STEP 7 -- Calibrate (the one thing that makes cost numbers real) (3 min)

The governor's dollar estimates use placeholder constants. After Step 6 you
have real numbers. Open `src/workflow/planner.py` and update:

- `TOKENS_PER_AGENT` (currently `6000`) -> your observed average tokens/agent
- `DEFAULT_FANOUT` dict -> adjust counts toward what actually got spawned

Re-run `python3 grit.py eval` to confirm still green. Now the cost numbers
match reality and you can quote real work against them.

---

## QUICK REFERENCE

| Command | What it does |
|---------|--------------|
| `python3 grit.py govern "task"` | Plan + price a task, get routing spec |
| `python3 grit.py govern "task" --trust AUTONOMOUS` | Govern as if fully trusted |
| `python3 grit.py eval` | Run eval suite, update trust ladder |
| `python3 grit.py eval --no-trust` | Run evals without touching trust |
| `python3 grit.py trust` | Show current trust ladder state |
| `rm data/trust_state.json` | Reset trust to UNTRUSTED |
| `python3 -m pytest tests/ -q` | Full test suite |

## IF SOMETHING IS BROKEN

- `govern`/`eval` fail with import error -> you're not in the `AgentGRIT/` dir.
- Trust never climbs -> check `data/` is writable; `rm data/trust_state.json` and retry.
- Full system import errors -> missing dep from Step 3; the governance core
  (Steps 1-2) does not need them and is the proven foundation.
