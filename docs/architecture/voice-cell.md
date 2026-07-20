# Voice Cell — design lock (Phase 0)

*GRIT-native governed speech I/O. Adopt the capability, not the repository.
Reference substrate: supertone-inc/supertonic (code MIT, model weights
OpenRAIL-M — pin + hash + license review before any packaged distribution).*

## Identity

A local, policy-governed speech runtime that lets any GRIT agent speak
concise, attributable, permission-bounded updates — with typed provenance,
replay, privacy, and owner control. Zero marginal API cost: local model
proposes, deterministic policy authorizes, local ONNX synthesizes, local
playback delivers. Voice is an interface to the shared event model, never
an authority channel.

## The non-negotiable

**No agent may send arbitrary prose directly to TTS.** The permitted
pipeline, always:

```
agent output -> typed VoiceIntent -> deterministic policy check
  -> evidence-linked template compiler -> local synthesis
  -> playback + immutable receipt
```

Models propose speech; policy decides whether the system speaks, what it
may say, to whom, and whether human confirmation is mandatory. Spoken
commands never execute anything — "GRIT, deploy it" creates a typed
proposal on the approval surface.

## Five cells

1. **Policy** — authorization, severity, rate limits, quiet hours,
   redaction, allowed audiences. Fail closed.
2. **Composition** — deterministic versioned templates + agent attribution
   + normalization. No raw LLM text reaches synthesis.
3. **Runtime** — local ONNX engine behind a stable interface; queue,
   cancellation, TTL, cache, priority preemption.
4. **Delivery** — local playback only by default; notification escalation;
   never public, never cloud fallback without explicit owner opt-in.
5. **Evidence** — intent + verdict + source events + text hash + audio
   hash + playback/interrupt state, immutably linked.

## Typed contracts (Python-native)

```python
@dataclass
class VoiceIntent:
    intent_id: str; workspace: str; agent_id: str
    purpose: str      # status|briefing|warning|critical_alert|approval_request|completion
    priority: int     # 0..4; critical preempts
    audience: str     # owner|local_operator
    delivery: str     # speak_now|queue|silent_transcript
    source_event_ids: list[str]
    template_id: str; template_data: dict
    voice_profile: str  # grit-calm|grit-direct|grit-urgent
    expires_at: str

@dataclass
class VoicePolicyVerdict:
    allowed: bool
    normalized_text: str = ""       # only when allowed
    redactions: list[str] = ...
    interruptible: bool = True
    requires_confirmation: bool = False
    deny_reason: str = ""  # muted|quiet_hours|rate_limited|unverified_claim|
                           # sensitive_content|expired|insufficient_authority

@dataclass
class VoiceRenderReceipt:
    intent_id: str; engine: str; model_version: str
    text_hash: str; audio_hash: str
    render_ms: int; duration_ms: int
    played_at: str | None; interrupted_at: str | None
```

Engine interface: `synthesize(text, voice_profile, language, speed,
quality, abort) -> (wav_bytes, duration_ms, render_ms, engine_version)`
with `health()`. Adapters are swappable (proof: supertonic localhost;
production: in-process ONNX); the contract is ours.

## Voice roles (policy + style, not speaker gimmicks)

| Profile | Use | Rules |
|---|---|---|
| grit-calm | routine status, completions, daily review | one thought, interruptible |
| grit-direct | owner decision request | names agent, decision, evidence, options, deadline |
| grit-urgent | security/risk/system fault | short, repeat-limited, source-linked, always interruptible |

## Threat model (controls are gates, not advice)

Injection-to-speech -> templates + constrained fields only. Sensitive
leakage -> redaction + audience + local-only. Alert fatigue -> priority
ladder, coalescing, cooldowns, daily voice budget. False authority ->
certainty state required; say "unverified" when true. Stale speech -> TTL
+ freshness recheck before playback. Queue blockage -> critical preemption.
Asset compromise -> pinned versions + sha256 manifest, no silent downloads
in production. Local service exposure -> loopback only, least privilege.

## Fixture set (write before audio exists — 25 cases)

Allowed routine update · muted update · quiet-hours queue · rate-limited
coalesce · expired alert never plays · resolved-then-recheck cancel ·
secret-pattern text -> deny record · injection marker -> deny record ·
unverified claim -> spoken with "unverified" label · critical preempts
briefing mid-sentence · interruption receipt · TTL expiry receipt ·
approval request requires confirmation flag · silent_transcript renders no
audio · unknown agent -> insufficient_authority · oversized template data
-> deny · non-owner audience -> deny · daily budget exhausted -> queue ·
engine down -> transcript + notification fallback · cancellation race ·
duplicate intent idempotent · malformed intent fail-closed · redaction
list recorded · language fallback · disabled cell blocks nothing else.

## Acceptance gates (Phase completion = all true)

100% of speech originates from a durable VoiceIntent; 100% of audio has a
verdict + source links; critical preempts within budget; expired/resolved
never plays; secret/injection fixtures produce denials, not audio; offline
works after provisioning; mute/quiet-hours work even with malfunctioning
agents; disabling Voice Cell cannot block any other GRIT operation; every
high-stakes statement traces to evidence or is labeled interpretation.

## Build order

Phase 1 invisible core (contracts+policy+templates+queue+receipts, fake
renderer) -> Phase 2 supertonic localhost proof adapter + benchmarks ->
Phase 3 in-process production adapter, pinned hashes, health panel, golden
audio -> Phase 4 constrained JSON briefing compilation by the local model,
SUPER-GM-graded above low-risk, feedback into templates not personality.
