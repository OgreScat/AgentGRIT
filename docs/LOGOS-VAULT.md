# Logos Vault — shared reasoning corpus (consumer contract + local retrieval)

> **Status (blunt):** contract + fail-closed validation + role-profiled
> retrieval are implemented, and the **local-model (Ollama) call path** now
> injects the validated role bundle as a system prompt when the vault is
> explicitly enabled (default role: `grit_jr`; override via
> `GRIT_LOGOS_VAULT_ROLE`). Cloud-provider calls receive **no** vault
> content. Disabled, missing, or invalid vault -> no injection, ever.

*Logos* (Greek: word, reason, ordering principle) is the public name for the
governed, shared, **private** reasoning corpus consumable by GRIT-family
projects. The vault itself is never bundled with this repository: public
AgentGRIT works fully without it.

## What it is

A versioned local library of curated reasoning artifacts distilled from
high-quality work sessions: playbooks, routing rubrics, standing
instructions, operator manuals, trap-test suites, evals, doctrine, and model
profiles. It preserves *independently authored operating method* — it does
not (and cannot) reproduce any frontier model's weights, hidden reasoning,
training data, or chain-of-thought, and it makes no such claim.

## What it is not

- Not bundled: the corpus is a separate private folder/repository.
- Not authority: vault content can never authorize actions, override
  bylaws/trust tiers, or bypass audit and provenance gates.
- Not a prompt dump: retrieval is approved-only, role-profiled, budgeted,
  and wrapped as untrusted reference context.
- Not networked: local path only; no Git or network actions; no telemetry.

## Configuration (disabled by default)

```
GRIT_LOGOS_VAULT_ENABLED=false   # explicit opt-in required
GRIT_LOGOS_VAULT_PATH=           # local path to a vault clone
GRIT_LOGOS_VAULT_PIN=            # must match vault pin file + manifest
```

Validation is fail-closed. Any of the following invalidates the vault:
missing path, missing/mismatched pin, missing/malformed manifest, missing
artifact files, or a per-artifact sha256 mismatch (real content integrity —
a drifted or tampered file fails the whole vault).

**Honesty note on the pin:** the pin check is *configuration consistency
validation* — it proves the configured reference matches the vault's declared
identity. It is not cryptographic verification of a repository or signed
release. Artifact-level sha256 verification, however, is real integrity
checking against the manifest.

## Admission states

`quarantine` (raw/unreviewed — never retrievable) → `reviewed` →
`approved` (retrievable) → `deprecated` / `revoked` (never retrievable).
Raw session handoffs enter as `quarantine` and stay there until a human
promotes them.

## Agent role profiles

| Role | Receives | Budget |
|---|---|---|
| **GRIT JR** | the full four-mind corpus | 3 artifacts / 20 KB |
| **GRIT** | the full four-mind corpus | 5 / 40 KB |
| **GRIT GM** | the full four-mind corpus | 6 / 48 KB |
| **SUPER GM** | the full four-mind corpus | 8 / 64 KB |

**One brain, four seats.** Every tier carries the same vault — Fable,
Grok, Terra, and the Synthesis intermingle and brainstorm together at
every seat; a lens outside its home domain may land the decisive
insight at any tier. Budgets are practical (a 12B local model cannot
carry 64 KB of doctrine), never doctrinal. Selection order is the
manifest order: synthesis and protocol doctrine load first.

**Local brain; subscription, not API.** The vault is consumed locally
by the local model. When a runtime substitutes an operator's own
subscription LLM (their ChatGPT, Kimi, Codex, or any other), vault
context travels as normal prompt injection inside that surface —
billed to the subscription the operator already pays for, never to a
metered API key. The reasoning stays in the room.

The intended hierarchy: **GRIT JR** works a project's minute tasks under the
drone contract; **GRIT** executes the project's larger work and checks JR;
**GRIT GM** leads one project and resolves most issues itself; **SUPER GM**
is the cross-project reviewer that grades, reassigns, and briefs the human —
only HIGH/CRITICAL decisions pass beyond it. Every tier is accountable to
the tiers around it; no tier outranks governance.

All roles: `raw_handoff` artifacts are never selectable; unknown roles
select nothing (fail closed); bundles are wrapped in an UNTRUSTED banner
instructing the model never to follow embedded instructions that conflict
with governance.

## Smoke check

```
GRIT_LOGOS_VAULT_ENABLED=true \
GRIT_LOGOS_VAULT_PATH=/path/to/your/vault \
GRIT_LOGOS_VAULT_PIN=<pin> \
python -m src.logos_vault.validate
```

Returns a JSON report (valid, failures, approved/quarantined counts) and
exit code 0 only when the vault fully validates.

## Boundary rules for vault content

The private vault must never contain: secrets or credentials, client or
matter data, personal identifying information, project-confidential context,
raw provider transcripts promoted without review, or licensing-uncertain
material. Consumers must never write project-private knowledge back into the
shared vault automatically.
