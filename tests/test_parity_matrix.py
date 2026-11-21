"""The page, the iPhone app and the Mac app have the same features (docs/design/parity.md).

tools/parity.py reads the code of all three and writes docs/design/parity-matrix.md. These tests fail when that file
is stale, when a feature is on one surface and not on another without a reason in the table, and when the scan itself
stops telling the truth (a control removed from a surface must flip its cell).
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import parity  # noqa: E402

# A gap that is known and being closed. Each entry is (feature id, surface). The test fails for a gap that is not
# listed, and for a listed gap that is closed: delete the entry in the change that closes it. The aim is an empty set.
KNOWN_GAPS: set[tuple[str, str]] = {
    ("about", "mac"),
    ("approve.more", "mac"),
    ("briefing.ready", "mac"),
    ("briefing.schedule", "mac"),
    ("briefing.sheet", "mac"),
    ("call.context", "mac"),
    ("call.new-pill", "mac"),
    ("call.polish", "mac"),
    ("call.recent", "mac"),
    ("call.rtl", "mac"),
    ("challenge.panel", "mac"),
    ("conflicts.card", "mac"),
    ("conflicts.settings", "mac"),
    ("demo", "mac"),
    ("dictionary.sheet", "mac"),
    ("dictionary.toast", "mac"),
    ("drive.screen", "mac"),
    ("drive.start", "mac"),
    ("drive.start", "web"),
    ("dump.challenge", "mac"),
    ("help", "mac"),
    ("lock.enrol", "mac"),
    ("lock.ignored", "mac"),
    ("machines.invite", "mac"),
    ("machines.list", "mac"),
    ("meeting.ask", "mac"),
    ("meeting.end", "mac"),
    ("meeting.hand", "mac"),
    ("meeting.mode", "mac"),
    ("meeting.notes", "mac"),
    ("meeting.settings", "mac"),
    ("meeting.speakers", "mac"),
    ("meeting.start", "mac"),
    ("pair.show", "mac"),
    ("sessions.filter", "mac"),
    ("sessions.mode", "mac"),
    ("sessions.rename", "mac"),
    ("show.card", "mac"),
    ("show.setting", "mac"),
    ("talk.switch", "ios"),
    ("talk.switch", "mac"),
    ("whisper", "mac"),
}

MATRIX = parity.scan()


def test_the_matrix_file_is_what_the_code_says():
    baseline = parity.json.loads((ROOT / parity.BASELINE).read_text())
    assert (ROOT / parity.OUT).read_text() == parity.render(MATRIX, baseline), "run python3 tools/parity.py"


def test_every_feature_is_on_every_surface_that_can_have_it():
    gaps = {(fid, s) for fid, row in MATRIX.items() for s, cell in row.items() if cell.state in ("no", "partial")}
    new = gaps - KNOWN_GAPS
    detail = "\n".join(f"  {fid} on {s}: not found {MATRIX[fid][s].missing}" for fid, s in sorted(new))
    assert not new, f"a feature is missing from a surface (build it, or give the reason in tools/parity.py):\n{detail}"
    closed = KNOWN_GAPS - gaps
    assert not closed, f"closed: take these out of KNOWN_GAPS: {sorted(closed)}"


def test_each_row_is_real_and_each_exception_has_a_reason():
    ids = [f.id for f in parity.FEATURES]
    assert len(ids) == len(set(ids)), "feature ids are unique"
    for f in parity.FEATURES:
        assert set(f.bound) < set(parity.SURFACES), f"{f.id}: a feature on no surface is not a feature"
        for surface, why in f.bound.items():
            assert len(why) > 20, f"{f.id}: say why {surface} cannot have it"
        assert any(MATRIX[f.id][s].state == "yes" for s in parity.SURFACES), f"{f.id}: on no surface at all"
    # nothing is "bound" on a surface whose code has it: an exception must not hide a feature that exists
    files = {s: parity.sources(s) for s in parity.SURFACES}
    for f in parity.FEATURES:
        for surface in set(f.bound) & {"ios", "mac"}:
            twin = "mac" if surface == "ios" else "ios"
            if twin in f.bound or not f.needs(twin):
                continue
            found = [parity._find(p, files[surface]) for p in f.needs(twin)]
            assert not all(found), f"{f.id}: {surface} is marked as unable, and its code has all of it: {found}"

def test_a_branch_the_platform_does_not_compile_does_not_count():
    source = "\n".join([
        "struct Both {}",
        "#if os(iOS)",
        "struct PhoneOnly {}",
        "#elseif os(macOS)",
        "struct MacOnly {}",
        "#endif",
        "#if !os(macOS)",
        "struct NotMac {}",
        "#else",
        "struct MacElse {}",
        "#endif",
        "#if DEBUG",
        "struct Debug {}",
        "#if canImport(UIKit)",
        "struct Touch {}",
        "#endif",
        "#endif",
    ])
    ios, mac = parity.for_platform(source, "ios"), parity.for_platform(source, "mac")
    for name, on_ios, on_mac in (("Both", True, True), ("PhoneOnly", True, False), ("MacOnly", False, True), ("NotMac", True, False),
                                 ("MacElse", False, True), ("Debug", True, True), ("Touch", True, False)):
        assert (f"struct {name} " in ios) == on_ios, f"{name} on the iPhone"
        assert (f"struct {name} " in mac) == on_mac, f"{name} on the Mac"
    assert ios.count("\n") == mac.count("\n") == source.count("\n"), "line numbers are kept"


def test_removing_a_control_from_one_surface_fails_the_scan(tmp_path):
    """The scan is the guard: with the page's Clean up my words control gone, and with the Mac compiled without the
    dictionary, those two cells are no longer yes."""
    for name in ("ui.html", "ui_dictionary.html", "ui_whisper.html", "product_help.json"):
        shutil.copy(ROOT / name, tmp_path / name)
    for folder in ("ios/Pointe", "macos/PointeMac", "apple/PointeKit/Sources"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    assert parity.scan(tmp_path)["call.polish"]["web"].state == "yes"
    page = tmp_path / "ui.html"
    page.write_text(page.read_text().replace('id="polish"', 'id="gone"'))
    assert parity.scan(tmp_path)["call.polish"]["web"].state == "partial"

    row = parity.scan(tmp_path)["dictionary.sheet"]
    if row["mac"].state == "yes" and row["mac"].refs[0] == row["ios"].refs[0]:  # one shared source: compile it out of the Mac
        shared = tmp_path / row["mac"].refs[0].rsplit(":", 1)[0]
        shared.write_text("#if os(iOS)\n" + shared.read_text() + "\n#endif\n")
        after = parity.scan(tmp_path)["dictionary.sheet"]
        assert after["ios"].state == "yes" and after["mac"].state != "yes"
