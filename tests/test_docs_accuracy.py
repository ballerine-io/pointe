"""Words that told a reader something untrue, found by the docs review: each is held to what the code does."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]


def test_pointe_pair_help_says_a_cloudflare_tunnel_is_for_the_phones_browser_only():
    """The app pins this Mac's own certificate (PinnedDelegate), and a Cloudflare Tunnel shows Cloudflare's instead."""
    import pair

    line = next(l for l in pair.__doc__.splitlines() if "Cloudflare" in l)
    assert "browser" in line, line
    assert "browser only" in (ROOT / "docs" / "phone" / "cloudflare.md").read_text()


def test_setup_points_to_where_the_build_failures_table_is():
    setup = " ".join((ROOT / "plugin" / "commands" / "setup.md").read_text().split())
    said = re.search(r"the same table is in (\S+), \"([^\"]+)\"", setup)
    assert said, "setup.md names the file and section of the build-failure table"
    doc, section = said.groups()
    text = (ROOT / doc).read_text()
    assert section in text and "| What you see | What it means | Fix |" in text[text.index(section):]


def test_security_says_unpair_all_replaces_the_pairing_link():
    """tests/test_phone_connect.py proves it: Unpair all gives remote_token, the link's secret, a new value."""
    text = " ".join((ROOT / "SECURITY.md").read_text().split())
    assert "no rotate command" not in text
    limits = text[text.index("Limits: the pairing link is a lasting secret"):]
    assert "Unpair all" in limits[:400], limits[:400]
    assert "def test_unpair_all_also_signs_out_a_phone_browser_paired_by_the_pairing_link" in \
        (ROOT / "tests" / "test_phone_connect.py").read_text()


def test_the_parity_matrix_names_the_talk_shortcut_the_mac_app_sets():
    shortcut = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeMacKit" / "Shortcut.swift").read_text()
    standard = re.search(r"/// (\S+): [^\n]*\n\s*public static let standard", shortcut).group(1)
    assert standard == "⌃⌥Space"
    for path in ("tools/parity.py", "docs/design/parity-matrix.md"):
        text = (ROOT / path).read_text()
        assert f"Hold {standard}" in text and "Hold ⌥Space" not in text, path


def test_the_features_index_lists_clean_up_my_words():
    index = (ROOT / "docs" / "features" / "README.md").read_text()
    row = next((l for l in index.splitlines() if "(clean-up-my-words.md)" in l), "")
    assert row.startswith("| [Clean up my words](clean-up-my-words.md) | "), row
    assert (ROOT / "docs" / "features" / "clean-up-my-words.md").exists()


def _flat(path: str) -> str:
    return " ".join((ROOT / path).read_text().split())


def test_the_docs_say_invited_people_may_answer_prompts_after_the_owner_first_time():
    """Since 0.10.2 a person who may send can answer a shared session's prompt (guests.Host.offer); docs said they
    could not. The owner-first time the README states is the code's default."""
    import guests

    assert guests.DEFAULTS["approve"] != "off"
    secs = f"{guests.OWNER_FIRST_SECS:g} seconds"
    for path in ("README.md", "docs/architecture.md", "docs/multi-machine.md", "SECURITY.md"):
        text = _flat(path)
        assert "cannot approve its prompts" not in text and "owner's voice and terminal only" not in text, path
    assert secs in _flat("README.md") and secs in _flat("docs/architecture.md")


def test_the_docs_say_a_request_with_no_short_form_is_read_word_for_word():
    """guards.spoken_request falls back to verbatim_request: only a credential-like request goes to a tap."""
    import guards

    command = {"command": "python3 -c 'print(1)'"}
    assert guards.readable_request("Bash", command) is None and guards.verbatim_request("Bash", command)
    for path in ("README.md", "docs/architecture.md"):
        text = _flat(path)
        assert "A command it cannot read out waits for a tap" not in text, path
        assert "Anything else waits for a tap" not in text, path
    assert "word for word" in _flat("docs/architecture.md")

