"""Keys on Linux: the freedesktop Secret Service (libsecret's `secret-tool`) stands where the Keychain does on a Mac, and
the environment still comes first. A fake `secret-tool` on PATH plays the keyring: it keeps each item in a folder of its
own, records every command line it was given, and refuses to run when a key is on one. Every key here is invented."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
import keys  # noqa: E402
import uninstall  # noqa: E402
import vendors  # noqa: E402

SECRET = "AIza-synthetic-0123456789-not-a-real-key"

# store: the secret on stdin, attributes on the command line. lookup: the secret on stdout. clear: forget it.
# Exit 1 with nothing on stdout when the item is missing, as libsecret's secret-tool does.
FAKE = r"""#!/bin/sh
dir="$FAKE_KEYRING"
printf '%s\n' "$*" >> "$dir/argv.log"
[ -n "$FAKE_NO_SERVICE" ] && { echo "secret-tool: Cannot autolaunch D-Bus without X11 \$DISPLAY" >&2; exit 1; }
cmd="$1"; shift
[ "$cmd" = store ] && shift  # --label=...
attrs="$1_$2"  # service <name>: a lookup by a subset of the attributes finds the item, as in libsecret
case "$cmd" in
  store)  cat > "$dir/item.$attrs" ;;
  lookup) [ -f "$dir/item.$attrs" ] || exit 1; cat "$dir/item.$attrs" ;;
  clear)  rm -f "$dir/item.$attrs" ;;
  *) exit 2 ;;
esac
"""


@pytest.fixture
def linux(tmp_path, monkeypatch):
    """This process as if on Linux, with the fake keyring first on PATH and no vendor key in the environment."""
    keyring, fake = tmp_path / "keyring", tmp_path / "fakebin"
    keyring.mkdir()
    fake.mkdir()
    (fake / "secret-tool").write_text(FAKE)
    (fake / "secret-tool").chmod(0o755)
    monkeypatch.setenv("FAKE_KEYRING", str(keyring))
    monkeypatch.setenv("PATH", f"{fake}:/usr/bin:/bin")
    monkeypatch.setenv("USER", "avi")
    for env in vendors.KEY_ENVS:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(vendors.sys, "platform", "linux")
    monkeypatch.setattr(keys.sys, "platform", "linux")
    vendors._found.clear()

    class Linux:
        def argv(self) -> str:
            log = keyring / "argv.log"
            return log.read_text() if log.exists() else ""

        def items(self) -> dict[str, str]:
            return {p.name: p.read_text() for p in keyring.glob("item.*")}

    return Linux()


def test_a_key_saved_on_linux_is_read_back_from_the_secret_service(linux):
    assert keys.save("pointe.gemini-api-key", SECRET) is None
    assert vendors.key("gemini") == SECRET
    assert vendors.saved("gemini")


def test_the_key_goes_to_secret_tool_on_its_standard_input_never_its_command_line(linux):
    assert keys.save("pointe.gemini-api-key", SECRET) is None
    assert SECRET not in linux.argv()
    assert "store" in linux.argv() and "service pointe.gemini-api-key" in linux.argv()
    assert list(linux.items().values()) == [SECRET]  # exactly the key: no newline added


def test_no_key_file_is_written_anywhere_pointe_keeps_state(linux):
    assert keys.save("pointe.gemini-api-key", SECRET) is None
    state = Path(os.environ["CLAUDE_VOICE_STATE"])
    for path in state.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(errors="ignore"), path


def test_the_environment_comes_before_the_secret_service(linux, monkeypatch):
    assert keys.save("pointe.gemini-api-key", SECRET) is None
    monkeypatch.setenv("GOOGLE_API_KEY", "from-the-environment")
    assert vendors.key("gemini") == "from-the-environment"


def test_only_pointes_own_item_is_read_on_linux(linux):
    """The pre-release names are a Mac Keychain history; on Linux another tool may own `gemini-api-key`."""
    assert keys.save("gemini-api-key", "another-tools-key") is None
    before = len(linux.argv())
    assert vendors.key("gemini") is None
    assert linux.argv()[before:] == "lookup service pointe.gemini-api-key\n"


def test_no_secret_service_means_no_key_and_no_crash(linux, monkeypatch):
    monkeypatch.setenv("FAKE_NO_SERVICE", "1")
    assert vendors.key("gemini") is None
    said = keys.save("pointe.gemini-api-key", SECRET)
    assert said is not None and SECRET not in said
    assert "keyring" in said and "GOOGLE_API_KEY" not in said  # the save does not know the vendor: main() says the variable


def test_without_secret_tool_the_save_says_what_to_install(linux, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert vendors.key("gemini") is None
    said = keys.save("pointe.gemini-api-key", SECRET)
    assert said is not None and "libsecret-tools" in said


def test_pointe_key_on_linux_asks_in_the_terminal_with_hidden_typing(linux, monkeypatch, capsys):
    asked = []
    monkeypatch.setattr(keys.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(keys.getpass, "getpass", lambda prompt: asked.append(prompt) or SECRET)
    monkeypatch.setattr(keys, "check", lambda vendor, secret=None: (True, "The gemini key works."))
    monkeypatch.setattr(keys, "running", lambda: False)
    assert keys.main(["gemini", "--no-open"]) == 0
    assert asked and "aistudio.google.com" in asked[0]
    assert vendors.key("gemini") == SECRET
    out = capsys.readouterr().out
    assert "keyring" in out and "Keychain" not in out and SECRET not in out


def test_pointe_key_on_linux_without_a_terminal_says_how_instead_of_hanging(linux, monkeypatch, capsys):
    monkeypatch.setattr(keys.sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr(keys.getpass, "getpass", lambda prompt: pytest.fail("no terminal: nothing may wait for typing"))
    assert keys.main(["gemini", "--no-open"]) == 1
    assert "pointe key gemini" in capsys.readouterr().out


def test_a_key_the_secret_service_cannot_keep_names_the_environment_variable(linux, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_NO_SERVICE", "1")
    monkeypatch.setattr(keys.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(keys.getpass, "getpass", lambda prompt: SECRET)
    monkeypatch.setattr(keys, "check", lambda vendor, secret=None: (True, "The gemini key works."))
    assert keys.main(["gemini", "--no-open"]) == 1
    out = capsys.readouterr().out
    assert "GOOGLE_API_KEY" in out and SECRET not in out


def test_the_page_does_not_open_a_key_window_on_linux(monkeypatch):
    """Settings → Model keys, Add…: on a Mac a window opens; on Linux nothing could ask, so the page is told what to run."""
    import daemon
    from fastapi.testclient import TestClient

    ran = []
    monkeypatch.setattr(daemon.sys, "platform", "linux")
    monkeypatch.setattr(daemon, "_run_on_the_mac", lambda *commands: ran.append(commands))
    client = TestClient(daemon.app, base_url="http://127.0.0.1:7860", cookies={"pointe_local": daemon.PAGE_KEY})
    got = client.post("/voice/key", json={"vendor": "gemini"})
    assert got.status_code == 409 and not ran
    assert "pointe key gemini" in got.json()["detail"]


def test_uninstall_finds_and_forgets_a_linux_key_by_name(linux, monkeypatch):
    assert keys.save("pointe.gemini-api-key", SECRET) is None
    monkeypatch.setattr(uninstall.sys, "platform", "linux")
    assert uninstall._in_keychain("pointe.gemini-api-key")
    assert not uninstall._in_keychain("pointe.openai-api-key")
    assert uninstall.remove(uninstall.Item("x", keychain="pointe.gemini-api-key")) == "done"
    assert linux.items() == {}
    assert SECRET not in linux.argv()
