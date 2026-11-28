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


def test_the_mac_app_design_names_the_call_protocol_the_daemon_speaks():
    import phone

    text = (ROOT / "docs" / "design" / "macos-app.md").read_text()
    current = text[:text.index("## Verification")]  # the dated record below says what was true that day
    said = set(re.findall(r"protocol (\d+)", current))
    assert said == {str(phone.PROTOCOL)}, said
    swift = (ROOT / "apps" / "PointeKit" / "Sources" / "PointeKit" / "Wire.swift").read_text()
    assert f"protocolVersion = {phone.PROTOCOL}" in swift


def test_the_multi_machine_design_does_not_call_the_built_hub_unbuilt():
    status = next(l for l in (ROOT / "docs" / "design" / "multi-machine.md").read_text().splitlines()
                  if l.startswith("Status:"))
    assert "not built;" not in status and (ROOT / "pointe" / "hub_nodes.py").exists(), status


def test_the_people_guides_say_a_person_who_may_send_can_answer_prompts_and_start_sessions():
    """guests.Host.offer puts a prompt to people after the owner-first time, and `start` is on by default."""
    import guests

    assert guests.DEFAULTS["start"] == "on"
    stale = ("No approval by an invited person yet", "and no approvals.", "the prompt is the owner's",
             "offered to Avi's voice and the session's terminal only", "cannot approve a permission prompt or start a session",
             "not its permission requests", "No new session on another machine.", "An invited person cannot approve a prompt")
    for path in ("docs/multi-machine.md", "docs/linux.md", "docs/limits.md", "SECURITY.md"):
        text = _flat(path)
        assert not [s for s in stale if s in text], path
    for setting in ("approvals on|off", "starts on|off", "window <seconds>", "hold <seconds>"):
        assert setting in guests.__doc__ and setting.replace("|", "\\|") in _flat("docs/multi-machine.md"), setting


def test_install_names_every_claude_code_hook_the_plugin_adds():
    import json

    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    words = {2: "two", 3: "three", 4: "four", 5: "five"}
    text = _flat("docs/install.md")
    assert f"Adds {words[len(hooks)]} Claude Code hooks" in text
    line = text[text.index("Claude Code hooks"):][:700]
    assert all(f"`{name}`" in line for name in hooks), line


def test_the_iphone_app_is_not_described_as_built_from_source_only():
    for path in ("docs/README.md", "docs/comparison.md", "docs/releasing.md"):
        text = _flat(path)
        assert "until it is in the App Store" not in text and "built from source for now" not in text, path
        assert "Until the iPhone app has a download" not in text, path


def test_harnesses_counts_the_capabilities_its_table_lists():
    text = (ROOT / "docs" / "harnesses.md").read_text()
    table = text[text.index("| Capability |"):].split("\n\n", 1)[0].splitlines()[2:]
    words = {5: "five", 6: "six", 7: "seven"}
    assert f"It needs {words[len(table)]} things from the agent" in " ".join(text.split())


def test_the_commands_the_architecture_docs_name_exist():
    assert (ROOT / "plugin" / "commands" / "voice-review.md").exists()
    assert "`/pointe:voice-review`" in _flat("docs/how-it-works.md")
    assert "`pointe share <name> --shared`" in _flat("docs/agents.md")  # a bare `pointe share` makes it private


def test_security_says_pair_rotate_removes_the_invited_people():
    """pair.rotate and pair.off call _sign_everyone_out, which empties people.json's people."""
    import inspect

    import pair

    assert "_sign_everyone_out()" in inspect.getsource(pair.rotate)
    text = _flat("SECURITY.md")
    assert "It does not remove the people invited to this machine" not in text
    assert "since 1.30.0" not in text  # no such version: verbatim read-outs shipped in 0.8.4


def test_design_docs_name_functions_and_keys_that_exist():
    daemon = (ROOT / "pointe" / "daemon.py").read_text()
    assert "_attach_line" not in daemon and "_attach_line" not in _flat("docs/design/attach-by-voice.md")
    assert '"agent_disclosure"' in daemon and "`agent_disclosure`" in _flat("docs/design/agents.md")
