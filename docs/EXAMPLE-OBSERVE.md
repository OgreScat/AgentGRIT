# Example: GRIT Observe v0

**Observe ≠ act.** Adapters pull keyless public feeds; fuse scores freshness and
cross-source corroboration; `research_quality.assess` grades the batch; a single
`decision_record` is written per run. Stale, lone-source, or contested signals
are marked **NOT ACTIONABLE** and cannot authorize side effects.

| Piece | Module |
|---|---|
| Registry | `src/observe/registry.py` |
| Adapters | `usgs_earthquakes`, `gdelt`, `polymarket` under `src/observe/adapters/` |
| Fuse | `src/observe/fuse.py` |
| Gate | `src/observe/gate.py` → `research_quality.assess` + `decision_record.record` |
| CLI | `python -m src.observe.run` / `make observe` |
| API | `GET /observe/view` on existing FastAPI server |

## How to run

```bash
# Live keyless feeds (network)
make observe
make observe FEED=usgs_earthquakes

# Offline fixtures (same path as tests — no network)
make observe-fixture
# or:
python -m src.observe.run --fixture-dir tests/fixtures/observe
```

## Real sample (fixtures — reproducible)

Command: `python -m src.observe.run --fixture-dir tests/fixtures/observe --no-record`

```
GRIT OBSERVE REPORT  ·  scored evidence only (no action)
==========================================================
  verdict:     sufficient  (score=0.42)
  reason:      adequate for a reversible high-stakes action
  actionable:  0  / non-actionable: 6
  decision:    n/a  auth=observe:all
  require_human: False

EVENTS
----------------------------------------------------------
  1. [✗ NOT ACTIONABLE] Major earthquake strikes coastal region, officials respond
     source=gdelt  type=news  cat=world_event
     freshness=fresh  evidence=0.54  salience=0.55
     corroboration=gdelt
     refused because: lone-source, weak-evidence

  2. [✗ NOT ACTIONABLE] Kraken IPO by ___ ?
     source=polymarket  type=prediction_market  cat=market
     freshness=stale  evidence=0.35  salience=1.00
     corroboration=polymarket
     url=https://polymarket.com/event/kraken-ipo-in-2025
     refused because: stale, lone-source, weak-evidence

  3. [✗ NOT ACTIONABLE] UK election called by...?
     source=polymarket  ...
     refused because: stale, lone-source, weak-evidence

  4–6. [✗ NOT ACTIONABLE] USGS quakes (fixture snapshots)
     freshness=stale  evidence=0.35
     refused because: stale, lone-source, weak-evidence

NOTES
----------------------------------------------------------
  • stale events present — refused actionability individually
  • lone-source events capped — cannot alone authorize action
Observation does not act. Contested/stale/lone-source signals cannot authorize side effects.
==========================================================
```

### Where actionability was refused (the 10x)

| Event | Why not actionable |
|---|---|
| GDELT earthquake article (fresh) | **Lone source** + evidence_grade &lt; 0.55 — one news hit cannot alone authorize action |
| Polymarket markets | **Stale** event timestamps (markets opened long ago) + lone source |
| USGS significant-month fixtures | **Stale** relative to now + single seismic source |

Corroboration rule (fuse): if USGS **and** GDELT both describe the same quake
topic/geo, `corroborating_sources` length ≥ 2 and `evidence_grade` rises.
Lone sources stay capped. That is the difference from a raw world-state dump.

### Decision record (when recording is on)

`decision_record.record(..., authorized_by="observe:all")` appends to
`logs/decisions.jsonl`. With zero actionable events the bylaw surface is
**ESCALATE** (“no actionable observations”). Observation still does not act.

## API

```bash
# Same auth posture as the rest of the server (loopback or X-API-Key)
curl -s 'http://127.0.0.1:8000/observe/view?fixture=true&refresh=true'
```

Returns the last fused+gated snapshot (`events`, `assessment_verdict`,
`actionable_count`, …). Never executes remediations.

## Feed notes

| Feed | Keyless? | Notes |
|---|---|---|
| USGS GeoJSON | Yes | Reliable; used for seismic |
| GDELT Doc API | Yes | Can be slow/timeout; adapter returns `[]` fail-safe |
| Polymarket Gamma | Yes | Public events list; odds for markets |

## What is deliberately not built

- No forecast / prophecy engine  
- No globe UI / SSE  
- No persona swarm (use existing deliberation + personas)

## Tests

```bash
pytest tests/test_observe.py -q
# adapters parse fixtures only — no live network in CI
```
