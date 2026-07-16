"""Phase 1 pipeline: produce VideoEvidenceBundle without any LLM.

Modes:
  --fixture PATH   load a JSON manifest fixture (offline tests / CI)
  --uri PATH       best-effort local file: checksum + optional ffprobe

Does not call cloud models. yt-dlp/ffmpeg integration is stubbed until Phase 1b.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .policy import default_sensitivity_for_uri
from .schema import (
    ExtractionPolicy,
    FocusWindow,
    FrameRef,
    PolicyInfo,
    Provenance,
    Segment,
    SourceInfo,
    TranscriptUtterance,
    VideoEvidenceBundle,
    bundle_from_dict,
    validate_bundle,
)


def _sha256_file(path: Path) -> str:
    """Full-file sha256 — evidence checksums are never truncated.

    A field named checksum_sha256 must match shasum -a 256 on the file,
    or provenance verification is theater.
    """
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _ffprobe(path: Path) -> dict[str, Any]:
    if not shutil.which("ffprobe"):
        return {}
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if out.returncode != 0:
            return {}
        return json.loads(out.stdout or "{}")
    except Exception:
        return {}


def build_from_fixture(fixture_path: Path) -> VideoEvidenceBundle:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    if "source" not in data:
        # wrap bare partial
        data = {"source": {"uri": f"fixture://{fixture_path.name}", "acquisition": "fixture"}, **data}
    if "acquisition" not in (data.get("source") or {}):
        data.setdefault("source", {})["acquisition"] = "fixture"
    bundle = bundle_from_dict(data)
    if "ocr" not in bundle.provenance.missing and not any(f.ocr_text for f in bundle.frames):
        bundle.provenance.missing.append("ocr")
    if "diarization" not in bundle.provenance.missing:
        bundle.provenance.missing.append("diarization")
    return bundle


def build_from_local_uri(
    uri: str,
    *,
    max_frames: int = 48,
    start_s: float | None = None,
    end_s: float | None = None,
    sensitivity: str | None = None,
) -> VideoEvidenceBundle:
    """Phase 1: metadata-only local probe (no frame extract yet without ffmpeg write path)."""
    path = Path(uri.removeprefix("file://")).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"not a local file: {uri}")
    sens = sensitivity or default_sensitivity_for_uri(str(path))
    probe = _ffprobe(path)
    duration = 0.0
    codec = ""
    width = height = 0
    fps = 0.0
    fmt = probe.get("format") or {}
    try:
        duration = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    for stream in probe.get("streams") or []:
        if stream.get("codec_type") == "video":
            codec = str(stream.get("codec_name") or "")
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            fr = stream.get("r_frame_rate") or "0/1"
            try:
                a, b = fr.split("/")
                fps = float(a) / float(b) if float(b) else 0.0
            except Exception:
                fps = 0.0
            break
    tools = []
    if probe:
        tools.append({"name": "ffprobe", "version": "host"})
    warnings = []
    missing = ["ocr", "diarization", "frame_extract"]
    if not probe:
        warnings.append("ffprobe unavailable or failed — duration/codec unknown")
        missing.append("ffprobe")
    # Placeholder single segment for whole media
    seg_end = duration or 0.0
    if end_s is not None:
        seg_end = end_s
    seg_start = start_s or 0.0
    bundle = VideoEvidenceBundle(
        source=SourceInfo(
            uri=str(path.resolve()),
            checksum_sha256=_sha256_file(path),
            duration_s=duration,
            codec=codec,
            width=width,
            height=height,
            fps=fps,
            acquisition="local_copy",
            captions_available=False,
        ),
        policy=PolicyInfo(
            sensitivity=sens,
            privacy_boundary="local_only" if sens == "private" else "local_only",
            allowed_model_classes=["A", "B", "C"] if sens != "private" else ["B", "C"],
        ),
        segments=[Segment(start_s=seg_start, end_s=seg_end or seg_start)],
        frames=[],  # Phase 1b: ffmpeg extract
        transcript=[],
        provenance=Provenance(
            tools=tools,
            commands=[],
            warnings=warnings,
            missing=missing,
        ),
        focus=FocusWindow(start_s=start_s, end_s=end_s),
        extraction_policy=ExtractionPolicy(max_frames=max_frames),
    )
    return bundle


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phase 1: build VideoEvidenceBundle (no LLM)")
    p.add_argument("--fixture", type=Path, help="JSON fixture manifest")
    p.add_argument("--uri", type=str, help="Local media path")
    p.add_argument("-o", "--output", type=Path, default=None, help="Write bundle JSON")
    p.add_argument("--start", type=float, default=None)
    p.add_argument("--end", type=float, default=None)
    p.add_argument("--max-frames", type=int, default=48)
    p.add_argument("--query", type=str, default="", help="Optional: print ROUTE decision")
    args = p.parse_args(argv)

    if args.fixture:
        bundle = build_from_fixture(args.fixture)
    elif args.uri:
        bundle = build_from_local_uri(
            args.uri,
            max_frames=args.max_frames,
            start_s=args.start,
            end_s=args.end,
        )
    else:
        p.error("provide --fixture or --uri")
        return 2

    errs = validate_bundle(bundle)
    if errs:
        print("VALIDATION WARNINGS:", "; ".join(errs))

    if args.output:
        bundle.write_json(args.output)
        print(f"wrote {args.output}")
    else:
        print(bundle.to_json())

    if args.query:
        from .router import route
        decision = route(args.query, bundle)
        print()
        print(decision.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
