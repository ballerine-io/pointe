"""What a plugin command lets the model run without a prompt, and what `pointe start` refuses to pass to Claude Code.

A command file's `allowed-tools` holds for that command's whole turn, in a session that may have read a stranger's text.
So each rule names one command the file tells the model to run, never a program that runs whatever follows it."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from harnesses import base  # noqa: E402

COMMANDS = sorted((ROOT / "plugin" / "commands").glob("*.md"))
BIN = "${CLAUDE_PLUGIN_ROOT}/bin/"
# Programs that run any code or command handed to them, or open any file: never pre-approved with a wildcard.
PRIMITIVES = {"open", "echo", "bash", "sh", "zsh", "env", "xargs", "eval", "exec", "command", "python", "python3", "node",
              "npx", "npm", "uv", "uvx", "osascript", "curl", "wget", "claude", "git", "sudo"}
# Pointe's own commands that start Claude Code with any arguments, open the daemon to a network, print a secret or remove
# Pointe: each asks the person, whichever command file is running.
NEVER = ("pointe start", "pointe pair", "pointe hub", "pointe uninstall", "pointe join", "pointe leave")


def _parts(path: Path) -> tuple[list[tuple[str, str]], str]:
    """([(tool, spec)], the instructions after the front matter)."""
    _, front, body = path.read_text().split("---", 2)
    tools = re.search(r"^allowed-tools: (.*)$", front, re.M).group(1)
    return re.findall(r"(\w+)\(([^)]*)\)", tools), body


def _instructions(path: Path) -> str:
    """What the file tells the model to run."""
    return _parts(path)[1]


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.name)
def test_each_command_pre_approves_only_what_it_tells_the_model_to_run(path):
    tools, _ = _parts(path)
    text = _instructions(path)
    for tool, spec in tools:
        assert tool in ("Bash", "Read"), f"{path.name}: {tool}({spec})"
        if tool == "Read":
            assert spec.startswith("${CLAUDE_PLUGIN_ROOT}/") and "*" not in spec, spec
            continue
        command = spec.removesuffix(":*")
        assert "*" not in command, f"{path.name}: Bash({spec}) has a wildcard inside it"
        assert command.split()[0] not in PRIMITIVES and command != f"{BIN}pointe", \
            f"{path.name}: Bash({spec}) pre-approves a program that runs whatever follows it"
        assert command in text, f"{path.name}: Bash({spec}) is not a command this file tells the model to run"
        assert not any(command.removeprefix(BIN).startswith(never) for never in NEVER), \
            f"{path.name}: Bash({spec}) must ask the person each time"


def test_pointe_voice_pre_approves_only_joining_and_none_of_setup():
    """/pointe:voice runs on every join, often in a session that has read a stranger's text: there it must not be able to
    switch the setup (a free tier a vendor may review), add a key or install anything without a prompt. A first run
    sends the person to /pointe:setup, which carries its own list."""
    voice = ROOT / "plugin" / "commands" / "voice.md"
    tools, body = _parts(voice)
    assert {spec for _, spec in tools} == {f"{BIN}claude-voice-attach:*", f"{BIN}pointe node status:*", f"{BIN}voice-first-run:*"}
    setup_only = {spec for _, spec in _parts(voice.with_name("setup.md"))[0]} - {f"{BIN}claude-voice-attach:*"}
    assert not setup_only & {spec for _, spec in tools}
    assert "/pointe:setup" in body and "setup.md" not in body, "a first run is the person's /pointe:setup, not read here"


def test_the_check_refuses_the_old_rules(tmp_path):
    """The test above, on the rules /pointe:voice and /pointe:setup had: each is refused."""
    for spec in (f"{BIN}pointe:*", "open:*", "echo:*", f"{BIN}pointe pair:*", "command -v:*"):
        bad = tmp_path / "setup.md"
        bad.write_text(f"---\nallowed-tools: Bash({spec})\n---\nRun `{BIN}pointe pair link` and `open x` and `echo hi`.\n")
        with pytest.raises(AssertionError):
            test_each_command_pre_approves_only_what_it_tells_the_model_to_run(bad)


BYPASS = ["--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "--permission-mode=bypassPermissions",
          "--settings={\"permissions\":{\"defaultMode\":\"bypassPermissions\"}}"]


@pytest.mark.parametrize("args", [[a] for a in BYPASS] + [["--permission-mode", "bypassPermissions"],
                                                           ["-p", "hello", "--Dangerously-Skip-Permissions"]])
def test_pointe_start_refuses_a_session_that_skips_its_prompts(args, tmp_path):
    """No `claude`, `node`, daemon or browser runs: the refusal comes before any of them."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    ran = tmp_path / "ran"
    for name in ("claude", "node", "npm", "open", "uv"):
        (stubs / name).write_text(f"#!/bin/sh\necho {name} \"$@\" >>{ran}\n")
        (stubs / name).chmod(0o755)
    env = {"PATH": f"{stubs}:/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_VOICE_STATE": str(tmp_path / "state"),
           "CLAUDE_VOICE_DAEMON_PORT": "1", "CLAUDE_VOICE_NO_BROWSER": "1"}
    got = subprocess.run([str(ROOT / "bin" / "pointe"), "start", *args], env=env, capture_output=True, text=True, timeout=30)
    assert got.returncode == 2 and "skips its permission prompts" in got.stderr, got.stderr
    assert not ran.exists(), ran.read_text()
    assert not (tmp_path / "state").exists(), "refused before the daemon or a session folder"


def test_pointe_start_refuses_the_same_words_as_every_other_starter():
    script = (ROOT / "bin" / "claude-voice").read_text()
    words = re.search(r"\n\s*(\*\S+\*(?:\|\*\S+\*)*)\)", script).group(1)
    assert {w.strip("*") for w in words.split("|")} == set(base._BYPASS)
