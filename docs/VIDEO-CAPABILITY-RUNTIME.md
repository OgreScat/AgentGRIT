# Video Capability Runtime — migration spec (AgentGRIT)

**Status:** Phase 1 scaffold in `src/video/`. Not a Claude skill.  
**Reference only:** [bradautomates/claude-video](https://github.com/bradautomates/claude-video) is an *ingestion-layer* PoC — keep pipeline shape, drop Claude-specific last mile.  
**Success condition:** one deterministic evidence run → many governed consumers → explicit refuse when model below floor → no provenance/privacy loss when swapping vendors.

---

## 1. Architecture review

### What to keep from claude-video
- yt-dlp / ffmpeg first-run setup philosophy  
- Focus windows (`start` / `end` / timestamps)  
- Frame budget + perceptual dedup  
- Caption-first, Whisper-fallback economics  
- Explicit detail/coverage modes (as *extraction policy*, not the final product contract)

### What to rewrite
| Claude-video | In-house target |
|---|---|
| “Paths Claude can Read” | Versioned `VideoEvidenceBundle` |
| Skill host as core | One *surface*; core is a service |
| Detail mode = fixed extraction dial | Query-aware retrieval (Phase 6) |
| Single-model handoff | Capability registry + adapters |

### Two planes
1. **Deterministic media intelligence** — fetch, probe, segment, frames, OCR, ASR, package, cache, provenance. **No LLM.**  
2. **Model adapter plane** — translate the same bundle into Class A/B/C model inputs; never re-extract per vendor.

### AgentGRIT fit
| GRIT primitive | Video use |
|---|---|
| `capability_map` / provenance | Adapter manifests + approved local VLMs |
| Cost-first router | Cheapest class that can finish the *query type* |
| Bylaws / autonomy | Privacy wall, cloud offload clearance, escalate secret/UI leaks |
| `decision_record` / `brief_record` | One record per analyze run |
| `research_quality` / observe gate pattern | Post-answer: claims must cite bundle times/frames |

Anti-patterns (refuse in design reviews):
- Rename Claude → “multi-provider” without evidence schema  
- Per-adapter extraction  
- Prompts as data model  
- Cloud OCR on private screencasts by default  
- “Verified” without provenance  
- Self-certifying multimodal answers  

---

## 2. Target tree (under AgentGRIT)

```
src/video/
  __init__.py
  schema.py              # VideoEvidenceBundle v1
  interfaces.py          # Protocols: Ingest, Analyze, Adapter, Store
  capability_registry.py # Class A/B/C + provider manifests
  router.py              # Query class → adapter floor + refuse
  policy.py              # Privacy wall, sensitivity, cloud clearance
  pipeline.py            # Phase 1: local file/URL → bundle (deterministic)
  ingest/
    download.py          # yt-dlp + checksum (Phase 1 stubs OK)
    probe.py             # ffprobe
    cache.py             # content-addressed cache
  analyze/
    frames.py            # ffmpeg extract + dedup + focus window
    captions.py          # native captions first
    asr.py               # Whisper / local ASR fallback
    ocr.py               # Phase 2
    shots.py             # Phase 3 shot boundaries
  retrieval/             # Phase 6
    select.py
  adapters/
    base.py
    text_bundle.py       # Class C filesystem/prompt bundle
    anthropic.py         # Phase 3+
    openai.py
    google.py
    ollama.py
  surfaces/
    cli.py               # python -m src.video.pipeline
    # later: api, agent-skill, telegram
tests/
  test_video_schema.py
  fixtures/video/        # tiny synthetic manifests only (no large media in git)
docs/
  VIDEO-CAPABILITY-RUNTIME.md   # this file
```

External tools (host deps, not vendored): `ffmpeg`, `ffprobe`, optional `yt-dlp`, optional local Whisper.

---

## 3. VideoEvidenceBundle schema (v1)

See `src/video/schema.py` for the live dataclasses. Conceptual map:

```json
{
  "schema_version": "1.0",
  "bundle_id": "uuid-or-hash",
  "created_at": "ISO-8601",
  "source": {
    "uri": "file://…|https://…",
    "checksum_sha256": "…",
    "duration_s": 0.0,
    "codec": "…",
    "width": 0, "height": 0, "fps": 0.0,
    "acquisition": "local_copy|yt_dlp|fixture",
    "captions_available": false
  },
  "policy": {
    "sensitivity": "public|internal|private",
    "privacy_boundary": "local_only|cloud_cleared",
    "allowed_model_classes": ["A","B","C"],
    "retention": "session|days:7|persistent"
  },
  "segments": [
    {"start_s": 0, "end_s": 12, "shot_type": "unknown", "motion_score": 0.0,
     "speech_density": 0.0, "ocr_density": 0.0}
  ],
  "frames": [
    {"frame_id": "f0001", "t_s": 1.0, "path": "artifacts/…/f0001.jpg",
     "thumb_hash": "…", "ocr_text": "", "visual_tags": [], "dedup_parent": null}
  ],
  "transcript": [
    {"t_start_s": 0, "t_end_s": 2.5, "text": "…", "speaker": null,
     "source": "native_caption|whisper_local|whisper_cloud|none", "confidence": 0.0}
  ],
  "entities": [],
  "indexes": {
    "keywords": [],
    "topic_windows": [],
    "frame_text_crosswalk": []
  },
  "provenance": {
    "tools": [{"name": "ffmpeg", "version": "…"}],
    "commands": [{"cmd": "…", "exit_code": 0}],
    "warnings": [],
    "missing": ["ocr", "diarization"]
  },
  "focus": {"start_s": null, "end_s": null, "timestamps": []},
  "extraction_policy": {"mode": "balanced", "max_frames": 48, "dedup": true}
}
```

**Hard rules**
- Bundle is the unit of truth; prompts are projections.  
- `missing[]` is mandatory honesty (empty OCR is not “verified visual”).  
- Private sensitivity ⇒ `privacy_boundary=local_only` by default; cloud adapters must refuse without clearance.

---

## 4. Python interfaces (see `src/video/interfaces.py`)

```python
class MediaIngest(Protocol):
    def acquire(self, uri: str, *, cache_dir: Path) -> SourceMedia: ...

class FrameExtractor(Protocol):
    def extract(self, media: SourceMedia, policy: ExtractionPolicy) -> list[FrameRef]: ...

class TranscriptProvider(Protocol):
    def transcribe(self, media: SourceMedia) -> list[TranscriptUtterance]: ...

class BundleBuilder(Protocol):
    def build(...) -> VideoEvidenceBundle: ...

class ModelAdapter(Protocol):
    manifest: AdapterManifest
    def project(self, bundle: VideoEvidenceBundle, query: str) -> ModelPacket: ...
    def invoke(self, packet: ModelPacket) -> ModelAnswer: ...  # Phase 3+

class VideoRouter(Protocol):
    def route(self, query: str, bundle: VideoEvidenceBundle) -> RouteDecision: ...
```

---

## 5. Routing / capability design

### Query classes (not vendor names)
| Query class | Floor | Default path |
|---|---|---|
| `summary` | C if captions dense; else B | Transcript-heavy |
| `temporal_visual` | B minimum, A preferred | Frames near window |
| `ui_code_screencast` | B + OCR required | OCR-first; local-only default |
| `safety_sensitive` | Judge-class + human if secrets | Escalate; no cloud without clearance |

### Adapter classes
| Class | supports_images | max_images (order) | Use |
|---|---|---|---|
| **A** | yes | high (e.g. 50+) | Dense windows + full transcript slices |
| **B** | yes | medium (e.g. 8–16) | Retrieval-selected frames + compressed transcript |
| **C** | no / weak | 0–2 | OCR + ASR + manifests only |

### RouteDecision (must be recorded)
```text
ROUTE
  query_class: temporal_visual
  chosen_class: B
  adapter: anthropic.claude-… 
  refuse: false
  reasons: [captions weak, need vision]
  downgrades: [max_images 12]
  privacy: local_only
```

Refuse when: required class &gt; adapter class; private + cloud; missing OCR for UI query; no frames and vision required.

No model self-certifies: answers attach `cited_frame_ids` / `cited_t_ranges` or are graded NEEDSWORK.

---

## 6. Phased migration plan

| Phase | Deliverable | Done when |
|---|---|---|
| **0** | This doc + tree decision | Team agrees evidence-first, not skill-first |
| **1** | Schema + validate + local/fixture pipeline + CLI | Bundle JSON written without any LLM |
| **2** | Local OCR + local ASR | Private video useful offline |
| **3** | Adapter contract + text_bundle + one cloud multimodal | Same bundle → two consumers |
| **4** | Capability registry + video router + policy refuse | Bad routes hard-fail with reason |
| **5** | AgentGRIT agent/surface + decision_record | Governed `video_analyzer` capability |
| **6** | Query-aware retrieval | Beats fixed detail modes on cost/quality evals |

**Do not** implement all vendors in Phase 3. One local Class C + one cloud Class A/B is enough to prove the contract.

---

## 7. Phase 1 starter (implemented)

| Module | Role |
|---|---|
| `schema.py` | Dataclasses + `to_dict` / `from_dict` / `validate` |
| `interfaces.py` | Protocols + `AdapterManifest`, `RouteDecision` |
| `capability_registry.py` | Built-in Class A/B/C stubs |
| `router.py` | Query classification + floor check (no network) |
| `policy.py` | Privacy default + cloud clearance gate |
| `pipeline.py` | Build bundle from **fixture** or **local path metadata** (ffmpeg optional) |
| `tests/test_video_schema.py` | Offline pure tests |

Phase 1 success = tests green **without** yt-dlp/ffmpeg if using fixture mode.

---

## 8. Eval / certification (later)

- Summary fidelity vs gold captions  
- Temporal localization (±1s)  
- UI/OCR string recovery  
- Privacy: private fixture must never select cloud route  
- Refuse tests: Class C on temporal_visual must refuse or downgrade with flag  

---

## 9. First commands (after scaffold)

```bash
# Schema / router pure tests
pytest tests/test_video_schema.py -q

# Fixture bundle (no media tools required)
python -m src.video.pipeline --fixture tests/fixtures/video/sample_manifest.json -o /tmp/veb.json
```
