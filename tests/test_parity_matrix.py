"""The page, the iPhone app, the Mac app and the Linux hub have the same features (docs/design/parity.md).

tools/parity.py reads the code of all four and writes docs/design/parity-matrix.md. These tests fail when that file
is stale, when a feature is on one surface and not on another without a reason in the table, and when the scan itself
stops telling the truth (a control removed from a surface must flip its cell). The Linux hub serves the page; every
Mac-only branch in pointe/ must say what it means there (parity.LINUX_BRANCHES).
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import parity  # noqa: E402
from generated import same_as_generated  # noqa: E402

# A gap that is known and being closed. Each entry is (feature id, surface). The test fails for a gap that is not
# listed, and for a listed gap that is closed: delete the entry in the change that closes it. The aim is an empty set.
KNOWN_GAPS: set[tuple[str, str]] = set()

MATRIX = parity.scan()


def test_the_matrix_file_is_what_the_code_says():
    baseline = parity.json.loads((ROOT / parity.BASELINE).read_text())
    same_as_generated((ROOT / parity.OUT).read_text(), parity.render(MATRIX, baseline), "run python3 tools/parity.py", str(parity.OUT))


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

def test_every_mac_only_branch_says_what_it_means_on_a_linux_hub():
    found = parity.mac_only_branches()
    missing = sorted(set(found) - set(parity.LINUX_BRANCHES))
    assert not missing, ("a branch in pointe/ asks which system it runs on, and tools/parity.py's LINUX_BRANCHES does not "
                         "say what a Linux hub does instead: " + ", ".join(f"{k} (line {found[k][0]})" for k in missing))
    gone = sorted(set(parity.LINUX_BRANCHES) - set(found))
    assert not gone, f"no such Mac-only branch any more: take these out of LINUX_BRANCHES: {gone}"
    ids = {f.id: f for f in parity.FEATURES}
    for key, branch in parity.LINUX_BRANCHES.items():
        assert branch.kind in ("path", "limit", "bound"), f"{key}: kind {branch.kind!r}"
        assert len(branch.linux) > 20, f"{key}: say what a Linux hub does"
        assert set(branch.features) <= set(ids), f"{key}: no feature {set(branch.features) - set(ids)}"
        assert branch.features or branch.kind == "path", f"{key}: a limit or a bound names the features it takes away"
        for fid in branch.features if branch.kind == "bound" else ():
            assert "linux" in ids[fid].bound, f"{key} binds {fid} on Linux, and the row gives no Linux reason"


def test_the_linux_scan_finds_a_new_mac_only_branch(tmp_path):
    (tmp_path / "pointe" / "harnesses").mkdir(parents=True)
    (tmp_path / "pointe" / "harnesses" / "x.py").write_text(
        "import platform, sys\n"
        "WHERE = '/a' if sys.platform == 'darwin' else '/b'\n"
        "class A:\n    def start(self):\n        if sys.platform != 'darwin':\n            return 1\n"
        "async def idle():\n    return platform.system() == 'Darwin'\n"
        "def plain():\n    return sys.argv\n")
    assert parity.mac_only_branches(tmp_path) == {"harnesses/x.py:<module>": [2], "harnesses/x.py:A.start": [5],
                                                  "harnesses/x.py:idle": [8]}


def test_the_linux_hub_reads_the_page():
    assert parity.sources("linux") == parity.sources("web")
    assert parity.scan()["call.keep-awake"]["linux"].why == parity.LINUX_POWER, "a Linux reason replaces the page's"


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
    (tmp_path / "pointe").mkdir()
    for name in ("ui.html", "ui_dictionary.html", "ui_whisper.html", "ui_quick.html", "product_help.json"):
        shutil.copy(ROOT / "pointe" / name, tmp_path / "pointe" / name)
    for folder in ("apps/ios/Pointe", "apps/ios/Pointe.xcodeproj", "apps/macos/PointeMac", "apps/macos/PointeMac.xcodeproj", "apps/PointeKit/Sources"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    shutil.copy(ROOT / "apps/PointeKit/Package.swift", tmp_path / "apps/PointeKit/Package.swift")
    assert parity.scan(tmp_path)["call.polish"]["web"].state == "yes"
    page = tmp_path / "pointe" / "ui_quick.html"
    page.write_text(page.read_text().replace("toggle('qs-polish'", "toggle('qs-gone'"))
    assert parity.scan(tmp_path)["call.polish"]["web"].state == "partial"

    row = parity.scan(tmp_path)["dictionary.sheet"]
    if row["mac"].state == "yes" and row["mac"].refs[0] == row["ios"].refs[0]:  # one shared source: compile it out of the Mac
        shared = tmp_path / row["mac"].refs[0].rsplit(":", 1)[0]
        shared.write_text("#if os(iOS)\n" + shared.read_text() + "\n#endif\n")
        after = parity.scan(tmp_path)["dictionary.sheet"]
        assert after["ios"].state == "yes" and after["mac"].state != "yes"


def test_the_design_doc_states_the_counts_the_scan_finds():
    """docs/design/parity.md's "Where it stood" table repeats the counts; it drifted once (a stale version, no Linux row)."""
    doc = (ROOT / "docs" / "design" / "parity.md").read_text()
    now = parity.counts(MATRIX)
    for surface in parity.SURFACES:
        c = now[surface]
        row = next((line for line in doc.splitlines() if line.startswith(f"| {parity.NAMES[surface]} |")), None)
        assert row, f"docs/design/parity.md has no row for {parity.NAMES[surface]}"
        cells = [x.strip() for x in row.strip("|").split("|")]
        assert cells[-3:] == [str(c["yes"]), str(c["no"]), str(c["n/a"])], f"{row}: the scan says {c}"


# Cells the scan would still call yes with the line it found blanked: the pattern matches elsewhere too (a shared
# PointeKit source the iPhone and the Mac both list, a word that is also in other text). Measured 2026-11-28 (72 of 528).
# Make one of these stronger and drop it from here; a new one fails the test below.
STILL_YES_WITHOUT_THEIR_LINE = {
    "about.version/mac", "alerts.actions/ios", "alerts.actions/mac", "alerts.approve/ios", "alerts.approve/mac",
    "alerts.background/ios", "alerts.notify/ios", "alerts.notify/mac", "appearance/mac", "approve.asked/ios",
    "approve.asked/mac", "approve.more/ios", "approve.more/linux", "approve.more/mac", "approve.more/web",
    "approve.offline/linux", "approve.offline/web", "approve.owner/ios", "approve.owner/mac", "approve.voice/ios",
    "approve.voice/linux", "approve.voice/mac", "approve.voice/web", "call.mute/mac", "call.new-pill/ios",
    "call.new-pill/mac", "call.polish/ios", "call.polish/mac", "call.problem/ios", "call.problem/mac",
    "call.recent/ios", "call.recent/mac", "call.redial/ios", "call.redial/mac", "call.rtl/linux", "call.rtl/web",
    "call.type-sending/linux", "call.type-sending/web", "drive.suggest/ios", "ios.airpods/ios", "ios.airpods/mac",
    "keys/linux", "keys/mac", "keys/web", "mac.keys/mac", "mac.login/mac", "machines.owner/linux",
    "machines.owner/web", "mute.writing/ios", "mute.writing/linux", "mute.writing/mac", "mute.writing/web",
    "night.readback/ios", "night.readback/mac", "people.settings/ios", "people.settings/mac", "quick.narrow/mac",
    "talk.closed-why/ios", "talk.closed-why/linux", "talk.closed-why/mac", "talk.closed-why/web", "talk.copy/ios",
    "talk.copy/mac", "talk.hold/ios", "talk.hold/mac", "talk.key/mac", "talk.ring/ios", "talk.ring/linux",
    "talk.ring/mac", "talk.ring/web", "thinking/ios", "thinking/mac"
}


def test_the_scan_notices_each_controls_line_removed_beyond_the_cells_known_to_match_twice():
    """docs/design/parity.md: the scan is the guard, so it must notice a control taken out. For every yes cell the line
    its first pattern found is blanked and the cell scanned again; it must no longer be yes, except the cells listed
    above. test_removing_a_control_from_one_surface_fails_the_scan holds two cells by hand; this holds every one."""
    files = {s: parity.sources(s) for s in parity.SURFACES}
    still_yes = set()
    for f in parity.FEATURES:
        for s in (s for s in parity.SURFACES if s not in f.bound and f.id != "help"):
            needs = f.needs(s)
            found = [parity._find(p, files[s]) for p in needs]
            if not all(found):
                continue
            path, line = found[0].rsplit(":", 1)
            lines = files[s][path].split("\n")
            lines[int(line) - 1] = ""
            if all(parity._find(p, {**files[s], path: "\n".join(lines)}) for p in needs):
                still_yes.add(f"{f.id}/{s}")
    assert still_yes <= STILL_YES_WITHOUT_THEIR_LINE, sorted(still_yes - STILL_YES_WITHOUT_THEIR_LINE)
