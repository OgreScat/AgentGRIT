"""CLI entry: fetch → fuse → gate → print scored report.

  python -m src.observe.run
  python -m src.observe.run --feed usgs_earthquakes
  python -m src.observe.run --fixture-dir tests/fixtures/observe
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .fuse import fuse
from .gate import gate, render_report
from .registry import default_registry, FeedRegistry
from .schema import ObserveEvent


def _load_fixture_events(fixture_dir: Path, feed: str | None) -> list[ObserveEvent]:
    """Parse offline fixtures (no network). Used by tests and --fixture-dir."""
    from .adapters.usgs_earthquakes import parse_payload as usgs_parse
    from .adapters.gdelt import parse_payload as gdelt_parse
    from .adapters.polymarket import parse_payload as poly_parse

    mapping = {
        "usgs_earthquakes": ("usgs_earthquakes.json", usgs_parse),
        "gdelt": ("gdelt.json", gdelt_parse),
        "polymarket": ("polymarket.json", poly_parse),
    }
    feeds = [feed] if feed else list(mapping.keys())
    events: list[ObserveEvent] = []
    for fid in feeds:
        if fid not in mapping:
            continue
        fname, parser = mapping[fid]
        path = fixture_dir / fname
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            events.extend(parser(data))
        except Exception:
            continue
    return events


def run_observe(
    *,
    feed: str | None = None,
    fixture_dir: Path | None = None,
    record_decision: bool = True,
    registry: FeedRegistry | None = None,
) -> tuple[Any, str]:
    """Execute one observe cycle. Returns (GateResult, report_text)."""
    if fixture_dir is not None:
        raw = _load_fixture_events(Path(fixture_dir), feed)
    else:
        reg = registry or default_registry()
        ids = [feed] if feed else None
        raw = reg.fetch_all(ids)

    fused = fuse(raw)
    label = feed or "all"
    result = gate(fused, feed_label=label, record_decision=record_decision)
    return result, render_report(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="GRIT Observe — fetch keyless feeds, score, refuse weak signals",
    )
    parser.add_argument(
        "--feed",
        choices=["usgs_earthquakes", "gdelt", "polymarket"],
        default=None,
        help="Single feed (default: all registered)",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=None,
        help="Parse offline fixtures instead of live network",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Skip decision_record write",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit GateResult JSON instead of text report",
    )
    args = parser.parse_args(argv)

    result, text = run_observe(
        feed=args.feed,
        fixture_dir=args.fixture_dir,
        record_decision=not args.no_record,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
