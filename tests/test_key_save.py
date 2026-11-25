"""`pointe key` saves the whole key, or says it did not. `security`'s own password prompt kept the first 128 characters
of a 147-character Soniox key, and setup still said "works": the key was checked before the save, never after.

The tests that touch a Keychain use a throwaway keychain file under /tmp with its own password, never the login keychain
or the search list. Every key here is invented."""

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import keys  # noqa: E402
import vendors  # noqa: E402

SECURITY = "/usr/bin/security"
on_a_mac = pytest.mark.skipif(not os.path.exists(SECURITY), reason="the Keychain is macOS only")
LONG = "sk_" + "".join(chr(ord("a") + i % 26) for i in range(144))  # 147 characters, as the Soniox key reported


def _security(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([SECURITY, *args], capture_output=True, text=True, timeout=30)


@pytest.fixture
def keychain():
    """A keychain file of its own, unlocked, that never locks by itself and is never on the search list. The test's item
    name is unique: after the test, the login keychain must not hold it (a save that lost its keychain would land there)."""
    before = (_security("list-keychains", "-d", "user").stdout, _security("default-keychain", "-d", "user").stdout)
    folder = tempfile.mkdtemp(prefix="pointe-keychain-", dir="/tmp")
    path, password = os.path.join(folder, "test.keychain-db"), secrets.token_hex(16)
    assert _security("create-keychain", "-p", password, path).returncode == 0
    item = f"pointe-test.{secrets.token_hex(4)}-api-key"
    try:
        assert _security("unlock-keychain", "-p", password, path).returncode == 0
        assert _security("set-keychain-settings", path).returncode == 0
        yield path, item
    finally:
        _security("delete-keychain", path)
        shutil.rmtree(folder, ignore_errors=True)
        stray = _security("find-generic-password", "-s", item).returncode == 0  # attributes only: no value is read
        if stray:
            _security("delete-generic-password", "-s", item)
        assert not stray, "the save reached the default keychain"
        assert (_security("list-keychains", "-d", "user").stdout, _security("default-keychain", "-d", "user").stdout) == before


@on_a_mac
def test_a_147_character_key_reads_back_whole(keychain):
    path, item = keychain
    assert keys.save(item, LONG, keychain=path) is None
    got = vendors.from_keychain(item, path)
    assert got == LONG, f"read back {len(got or '')} of {len(LONG)} characters"


@on_a_mac
@pytest.mark.parametrize("secret", [
    'sk-with"double"quotes', "sk-with'single'quotes", "sk-back\\slash", "sk-ends-in-a-backslash\\", 'sk-\\"both',
    "sk with  spaces", "sk-#$;&|`<>*?~!(){}[]", "-w", "sk-" + "x" * 1000,
], ids=["double-quotes", "single-quotes", "backslash", "trailing-backslash", "backslash-quote", "spaces", "shell-signs",
        "an-option", "1003-characters"])
def test_a_key_with_awkward_characters_reads_back_exactly(keychain, secret):
    path, item = keychain
    assert keys.save(item, secret, keychain=path) is None
    assert vendors.from_keychain(item, path) == secret


@on_a_mac
def test_saving_again_replaces_the_key(keychain):
    path, item = keychain
    assert keys.save(item, "sk-first-synthetic", keychain=path) is None
    assert keys.save(item, LONG, keychain=path) is None
    assert vendors.from_keychain(item, path) == LONG


@on_a_mac
@pytest.mark.parametrize("secret", ["sk-ключ-🔑", "sk-é", "sk-a\tb", "sk-a\nadd-generic-password -s x -w y", "sk-a\x00b",
                                    "sk-a\rb", "sk-a\x7fb"],
                         ids=["unicode", "accent", "tab", "line-break", "nul", "carriage-return", "delete"])
def test_a_key_the_daemon_could_not_read_back_is_refused_and_the_saved_one_stays(keychain, secret):
    """`security find-generic-password -w` prints a value with such a character in hex, so the daemon would read
    another key. Refused before anything is written: the key saved before still works."""
    path, item = keychain
    assert keys.save(item, LONG, keychain=path) is None
    said = keys.save(item, secret, keychain=path)
    assert said and "character" in said and secret not in said
    assert vendors.from_keychain(item, path) == LONG


@on_a_mac
def test_the_longest_key_one_line_holds_saves_and_one_more_character_is_refused(keychain):
    path, item = keychain
    fixed = len(f'add-generic-password -U -s "{item}" -a "{os.environ.get("USER", "pointe")}" -w "" "{path}"\n'.encode())
    longest = "k" * (keys.LINE_MAX - fixed)
    assert keys.save(item, longest, keychain=path) is None
    assert vendors.from_keychain(item, path) == longest
    assert keys.save(item, longest + "k", keychain=path) == "it is too long for the Keychain tool"
    assert vendors.from_keychain(item, path) == longest


@pytest.fixture
def offline(monkeypatch):
    """No real process at all: a save that went around the stand-in `subprocess.run` (a pty, an exec) would reach the
    login keychain. It fails the test instead."""
    import pty

    def refuse(*a, **k):
        raise AssertionError("an offline test started a real process")
    for module, name in [(pty, "fork"), (os, "fork"), (os, "forkpty"), (os, "execv"), (os, "execve"), (os, "posix_spawn"),
                         (subprocess, "Popen")]:
        monkeypatch.setattr(module, name, refuse)


@pytest.mark.usefixtures("on_a_mac")
def test_the_key_is_never_an_argument_and_the_tools_output_is_never_shown(offline, monkeypatch, capsys):
    """Offline: a stand-in `security` that saves what its standard input says. The key reaches it only there, never
    argv (which `ps` shows), and what it prints, which can hold the key, goes nowhere."""
    store, argvs = {}, []

    def security(cmd, **kw):
        argvs.append(cmd)
        if cmd[1:] == ["-i"]:
            store["it"] = LONG
            return subprocess.CompletedProcess(cmd, 0, f"security> echo {LONG}".encode(), f"error {LONG}".encode())
        return subprocess.CompletedProcess(cmd, 0, store["it"] + "\n", "")
    monkeypatch.setattr(subprocess, "run", security)
    assert keys.save("pointe-test.offline-api-key", LONG) is None
    assert [c[:2] for c in argvs] == [[SECURITY, "-i"], [SECURITY, "find-generic-password"]]
    assert not any(LONG in word for c in argvs for word in c)
    shown = capsys.readouterr()
    assert LONG not in shown.out + shown.err


@pytest.mark.usefixtures("on_a_mac")
@pytest.mark.parametrize("stored, exit_status", [(LONG[:128], 0), ("", 44)], ids=["cut-at-128", "missing"])
def test_a_save_that_does_not_read_back_says_so_and_never_works(offline, monkeypatch, capsys, stored, exit_status):
    """The reported failure, offline: the Keychain keeps the first 128 characters. `pointe key` says it could not save
    the key, never "works", and does not restart Pointe."""
    def security(cmd, **kw):
        if cmd[1:] == ["-i"]:
            return subprocess.CompletedProcess(cmd, 0, b"", b"")  # its exit status says nothing: it is 0 here
        return subprocess.CompletedProcess(cmd, exit_status, stored + "\n" if stored else "", "")
    monkeypatch.setattr(subprocess, "run", security)
    monkeypatch.setattr(keys, "ask", lambda vendor, refused=False: LONG)
    monkeypatch.setattr(keys, "check", lambda vendor, secret=None: (True, "The soniox key works."))
    restarted = []
    monkeypatch.setattr(keys, "running", lambda: True)
    monkeypatch.setattr(keys, "restart", lambda: restarted.append(1) or True)
    assert keys.main(["soniox", "--no-open"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("Could not save the Soniox key in the Keychain (item pointe.soniox-api-key): ")
    assert "works" not in out and LONG[:16] not in out and not restarted


@pytest.mark.usefixtures("on_a_mac")
def test_the_daemon_reads_a_long_key_whole(offline, tmp_path, monkeypatch):
    """The daemon's reader keeps all of what `security find-generic-password -w` prints, past 128 characters."""
    monkeypatch.setenv("CLAUDE_VOICE_STATE", str(tmp_path))
    for env in [*vendors.KEY_ENVS, "CLAUDE_VOICE_LOCAL_ONLY", "CLAUDE_VOICE_VOICE_LOCAL"]:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(vendors, "_found", {})
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, LONG + "\n", ""))
    assert vendors.key("soniox") == LONG
