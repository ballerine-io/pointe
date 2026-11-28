"""The public benchmark pages (site/pointe/benchmarks/, docs/benchmarks/README.md and the landing page's measured
figures) are written by bench/publish.py from one release's committed results; none is edited by hand, and every
number on them is recomputed from the rows by bench/release_report.py."""

import importlib.util
import json
import re
from pathlib import Path

import pytest
from generated import same_as_generated  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# The report scores with the dialogue suite's harness; its module names (core, dialogues) are shared with the other
# harnesses, so the conftest hook enters this one before each test (tests/conv_suite.py).
CONV_SUITE = "dialogues"
RELEASES = sorted(p for p in (ROOT / "bench" / "results").glob("20??-??-??-v*") if (p / "manifest.json").exists())


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "bench" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_there_is_a_published_release():
    assert RELEASES, "bench/results/<date>-<tag>/ with a manifest.json"


@pytest.mark.slow
def test_the_summary_is_what_the_rows_give():
    release = RELEASES[-1]
    report = load("release_report")
    committed = (release / "summary.json").read_text()
    report.main(release)
    try:
        same_as_generated(committed, (release / "summary.json").read_text(), "run bench/release_report.py and commit summary.json", "summary.json")
    finally:
        (release / "summary.json").write_text(committed)


def test_every_page_matches_the_release():
    publish = load("publish")
    for path, text in publish.build(RELEASES[-1]).items():
        same_as_generated(path.read_text(), text, "run bench/publish.py", str(path.relative_to(ROOT)))
    assert (publish.SITE / RELEASES[-1].name / "rows.tar.gz").read_bytes() == publish.tarball(RELEASES[-1])


def test_the_manifest_names_a_tag_and_its_commit():
    m = json.loads((RELEASES[-1] / "manifest.json").read_text())
    assert re.fullmatch(r"v\d+\.\d+\.\d+", m["release"]) and re.fullmatch(r"[0-9a-f]{40}", m["commit"])
    for key in ("date", "agent", "machine", "commands", "spend", "benchmarks"):
        assert m.get(key), key


def test_the_pages_name_the_baseline_and_label_model_judges_and_speech():
    page = (ROOT / "docs" / "benchmarks" / "README.md").read_text()
    for must in ("self-evaluation", "synthetic", "recorded people", "model judge", "not people's ratings",
                 "Where Pointe loses", "Withdrawn", "Raw results"):
        assert must in page, must
