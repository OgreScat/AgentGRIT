"""Tests for governed skill-discovery -- ranking passes + the reviewed install decision.

Most installs auto-clear (GM green-lights); only the consequential residue (unvetted code,
secret access, high-stakes) is left requires_human_confirm; the clearly-bad is auto-rejected.
"""

from src.execution.skill_discovery import Skill, discover, vet


def _catalog():
    return [
        Skill(name="Video Frame Extractor", description="extract keyframes from video files",
              source="github:someone/vidframe", stars=200, tags=("video", "frames"),
              runs_code=True),
        Skill(name="Markdown Linter", description="lint markdown docs", source="github:x/mdlint",
              stars=10, tags=("docs", "lint"), runs_code=False),
        Skill(name="Media Digest", description="creates digests", source="github:y/digest",
              stars=80, tags=("video", "summary"), runs_code=False),
    ]


def test_direct_match_ranks_first():
    out = discover("extract frames from a video", _catalog())
    assert out[0].skill.name == "Video Frame Extractor"
    assert out[0].pass_name == "direct"


def test_vetted_bounded_code_skill_auto_greenlit():
    out = discover("extract frames from a video", _catalog())
    top = out[0]
    assert top.decision == "approve"
    assert top.auto_greenlight is True
    assert top.requires_human_confirm is False


def test_unvetted_code_skill_needs_human():
    sk = Skill(name="frame extractor", description="extract frames from video",
               source="github:rando/x", stars=3, runs_code=True)
    out = discover("extract frames from video", [sk])
    assert out[0].decision == "review"
    assert out[0].requires_human_confirm is True


def test_secret_access_needs_human_even_if_vetted():
    sk = Skill(name="frame extractor", description="extract frames from video",
               source="github:big/x", stars=999, runs_code=True, permissions=("secrets",))
    out = discover("extract frames from video", [sk])
    assert out[0].requires_human_confirm is True


def test_unvetted_broad_code_auto_rejected():
    sk = Skill(name="frame extractor", description="extract frames from video",
               source="github:rando/x", stars=1, runs_code=True,
               permissions=("filesystem", "network"))
    out = discover("extract frames from video", [sk])
    assert out[0].decision == "reject"
    assert out[0].requires_human_confirm is False


def test_docs_only_vetted_auto_approved():
    sk = Skill(name="markdown formatter", description="format markdown docs nicely",
               source="github:z/fmt", stars=500, tags=("docs",), runs_code=False)
    out = discover("format markdown docs", [sk])
    assert out[0].decision == "approve"
    assert out[0].requires_human_confirm is False


def test_unvetted_source_flagged():
    ok, why = vet(Skill(name="x", stars=3, source="github:rando/x"))
    assert ok is False and "unvetted" in why


def test_adjacent_pass_when_no_direct():
    out = discover("summarize a video", [_catalog()[2]])  # Media Digest, tags video/summary
    assert out and out[0].pass_name == "adjacent"


def test_recombination_proposed_without_direct_hit():
    cat = [
        Skill(name="Media Digest", description="creates digests", stars=80,
              source="github:a/d", tags=("video", "summary")),
        Skill(name="Transcript Tool", description="handles text", stars=90,
              source="github:b/t", tags=("video", "audio")),
    ]
    out = discover("summarize a video", cat)
    assert any(c.pass_name == "recombination" for c in out)


def test_no_match_returns_empty():
    assert discover("bake a sourdough loaf", _catalog()) == []
