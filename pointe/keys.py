"""Save a model key in the macOS Keychain without it ever touching a command line, a chat, a file or a log.

    pointe key gemini|anthropic|openai|soniox|elevenlabs
                                  opens the vendor's key page, asks for the key in a Mac window, checks it with one tiny
                                  live call (asks again when it is refused), saves it, and restarts Pointe if it runs
        --no-open                 without opening the vendor's page
        --no-restart              without restarting Pointe (the caller does it)
    pointe key check <vendor>     one tiny live call with the saved key: works, refused, or unreachable


A native dialog with hidden input asks for the key; `security -i` reads the command that saves it from its standard input,
so it is never an argument, and the saved item is read back and compared before Pointe says it is saved. Made for people
who do not use a terminal: Claude Code can run this for them.

On Linux the terminal asks, with hidden typing, and the key goes to the login keyring through the freedesktop Secret
Service (libsecret's `secret-tool`, on its standard input). Where no Secret Service runs, nothing is saved: the words say
which variable to set for the one command that starts Pointe instead (docs/linux.md).
"""

import getpass
import os
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)
import childenv  # noqa: E402
import vendors  # noqa: E402
from vendors import KEYS  # noqa: E402

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
WHERE = {
    "gemini": "https://aistudio.google.com/apikey",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
    "soniox": "https://console.soniox.com",
    "elevenlabs": "https://elevenlabs.io/app/settings/api-keys",
}
LABEL = {"gemini": "Google Gemini", "anthropic": "Anthropic", "openai": "OpenAI", "soniox": "Soniox",
         "elevenlabs": "ElevenLabs"}  # the Mac app's Vendor.label (tests/test_key_setup.py)
# What to press on each vendor's key page, in its own words.
CREATE = {"gemini": "Sign in, press Create API key, then copy the key.",
          "anthropic": "Sign in, press Create Key, then copy the key.",
          "openai": "Sign in, press Create new secret key, then copy the key.",
          "soniox": "Sign in, open API Keys, create a key, then copy it.",
          "elevenlabs": "Sign in, press Create API Key, then copy the key."}


def _site(vendor: str) -> str:
    return WHERE[vendor].removeprefix("https://")


def on_a_mac() -> bool:
    return sys.platform == "darwin"


def store_name() -> str:
    """Where a saved key lives, in the words said to the person."""
    return "your Keychain" if on_a_mac() else "your login keyring"


def prompt(vendor: str, refused: bool = False) -> str:
    """The dialog's text: three numbered lines, after the reason it is back when the last key was refused."""
    head = f"{LABEL[vendor]} refused that key: it may be mistyped, revoked or out of credit. Try again.\\n\\n" if refused else ""
    return (f"{head}1. Open {_site(vendor)} (Pointe opened it in your browser).\\n"
            f"2. {CREATE[vendor]}\\n"
            f"3. Paste it here and press Save.\\n\\n"
            f"It goes to your Mac's Keychain, nowhere else. Pointe never shows it.")


def ask(vendor: str, refused: bool = False) -> str | None:
    """A macOS dialog with hidden typing; on Linux the terminal's own hidden prompt. None if the user cancelled, or on
    Linux with no terminal to type in."""
    if not on_a_mac():
        if not sys.stdin.isatty():
            return None
        head = f"{LABEL[vendor]} refused that key: it may be mistyped, revoked or out of credit. Try again.\n" if refused else ""
        try:
            got = getpass.getpass(f"{head}Open {WHERE[vendor]}. {CREATE[vendor]}\nPaste the {LABEL[vendor]} key here "
                                  "(the typing is hidden), then press Enter: ")
        except (EOFError, KeyboardInterrupt):
            return None
        return got.strip() or None
    script = (f'display dialog "{prompt(vendor, refused)}" default answer "" with hidden answer '
              f'with title "Pointe: {LABEL[vendor]} key" buttons {{"Cancel", "Save"}} default button "Save"\n'
              f'text returned of result')
    got = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, env=childenv.child_env())
    return got.stdout.strip() if got.returncode == 0 and got.stdout.strip() else None


def open_page(vendor: str) -> None:
    """The vendor's key page in the browser, so the person does not have to find it."""
    opener = "open" if on_a_mac() else "xdg-open"
    if not on_a_mac() and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return  # no desktop to open it on (SSH): the prompt names the page
    try:
        subprocess.run([opener, WHERE[vendor]], capture_output=True, timeout=10, env=childenv.child_env())
    except (OSError, subprocess.TimeoutExpired):
        pass


# `security -i` reads one command per line into a 4096-byte buffer, the newline included: a longer line is cut, and
# the cut command fails with its words, the key among them, on stderr.
LINE_MAX = 4096


def _word(text: str) -> str:
    """One word of a `security -i` line: in double quotes, its backslashes and double quotes escaped with a backslash."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(item: str, secret: str, keychain: str | None = None) -> str | None:
    """Save `secret` as the Keychain item `item`, then read it back. None when the Keychain gives back exactly `secret`,
    else why not, in words that hold no part of it. `keychain`: a keychain file instead of the default one (tests).

    Never through `security`'s own password prompt (`-w` last): it keeps the first 128 characters only. On Linux,
    `secret-tool store` reads the key from its standard input (save_linux)."""
    if not (secret.isascii() and secret.isprintable()):
        # `security find-generic-password -w`, the daemon's reader, prints such a value in hex: it would never read back.
        return "it has a character no key has (a line break, a tab, or one outside plain ASCII)"
    if not on_a_mac():
        return save_linux(item, secret)
    words = ["add-generic-password", "-U", "-s", _word(item), "-a", _word(os.environ.get("USER", "pointe")),
             "-w", _word(secret), *([_word(keychain)] if keychain else [])]
    line = " ".join(words) + "\n"
    if len(line.encode()) > LINE_MAX:
        return "it is too long for the Keychain tool"
    try:
        # Its output is never shown: a command it could not parse comes back with the key in it.
        subprocess.run(["/usr/bin/security", "-i"], input=line.encode(), capture_output=True, timeout=60,
                       env=childenv.child_env())
        saved = vendors.from_keychain(item, keychain, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return "the Keychain did not answer"
    if saved is None:
        return "the Keychain has no such item after saving"
    if saved != secret:  # `security -i`'s exit status says nothing about a command that failed: only this does
        return "the Keychain gave back a different key from the one pasted"
    return None


NO_SECRET_TOOL = "secret-tool is not installed: sudo apt install libsecret-tools (Fedora: libsecret), then try again"
NO_SECRET_SERVICE = ("no keyring answered (the Secret Service runs with a desktop login; over SSH or on a server there is "
                     "usually none)")


def save_linux(item: str, secret: str) -> str | None:
    """`secret` into the login keyring as the item whose attribute `service` is `item`, then read back. The key goes on
    secret-tool's standard input, never its command line; its output is never shown."""
    tool = vendors.shutil.which("secret-tool")
    if tool is None:
        return NO_SECRET_TOOL
    try:
        got = subprocess.run([tool, "store", f"--label=Pointe: {item}", "service", item,
                              "account", os.environ.get("USER", "pointe")],
                             input=secret.encode(), capture_output=True, timeout=60, env=childenv.child_env())
        if got.returncode != 0:
            return NO_SECRET_SERVICE
        saved = vendors.from_secret_service(item, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return NO_SECRET_SERVICE
    if saved is None:
        return "the keyring has no such item after saving"
    if saved != secret:
        return "the keyring gave back a different key from the one pasted"
    return None


# The audio-only vendors have no text model: a list of their models is the smallest call their key must authorise.
AUDIO_CHECK = {"soniox": ("https://api.soniox.com/v1/models", "Authorization", "Bearer {}"),
               "elevenlabs": ("https://api.elevenlabs.io/v1/models", "xi-api-key", "{}")}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # the 3xx is raised as an HTTPError: answered, not checked


def check(vendor: str, secret: str | None = None) -> tuple[bool | None, str]:
    """One tiny live call with the saved key, or with `secret` before it is saved. (True, ...) works, (False, ...)
    refused or missing, (None, ...) could not be checked. The answer never holds the key or the vendor's own error text
    (some echo part of the key back)."""
    import asyncio
    import urllib.error
    import urllib.request

    env = KEYS[vendor][0]
    before = os.environ.get(env)
    if secret is not None:
        os.environ[env] = secret  # this process only: the vendor's client reads its key from here
        vendors._clients.pop(vendor, None)
    try:
        return _check(vendor, asyncio, urllib)
    finally:
        if secret is not None:
            vendors._clients.pop(vendor, None)
            if before is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = before


def _check(vendor: str, asyncio, urllib) -> tuple[bool | None, str]:
    secret = vendors.key(vendor)
    if not secret:
        return False, f"No {vendor} key found: save one with pointe key {vendor}."
    try:
        if vendor in AUDIO_CHECK:
            url, header, form = AUDIO_CHECK[vendor]
            opener = urllib.request.build_opener(_NoRedirect)  # urllib would send the key on to wherever a 3xx points
            opener.open(urllib.request.Request(url, headers={header: form.format(secret)}), timeout=15).close()
        else:
            # Their own choice first: on another host (openai_url) the default model names are not deployed.
            configured = [c for c in (vendors.config().get(r) for r in ("checker", "brain", "reader")) if c]
            model = next(c for c in [*configured, *vendors.CHECKER_ORDER] if c.startswith(f"{vendor}:")).split(":", 1)[1]
            asyncio.run(vendors._TEXT[vendor](model, "Reply with the word ok.", None, False, None, 16, 0.0))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, vendors.refused_help(vendor)
        if fault := vendors.fault(f"HTTP {e.code} {vendor}"):
            return None, vendors.fault_help(fault[0], vendor)
        return None, f"The {vendor} key could not be checked: the vendor answered HTTP {e.code}. Try again later."
    except urllib.error.URLError:
        return None, f"The {vendor} key could not be checked: no connection to {vendor}."
    except Exception as e:
        if vendors.refused_key(f"{type(e).__name__} {e}") is not None:
            return False, vendors.refused_help(vendor)
        if fault := vendors.fault(e):  # the key is accepted; its quota, or the vendor, is the problem
            return None, vendors.fault_help(fault[0], vendor)
        return None, f"The {vendor} key could not be checked: {type(e).__name__}. Try again, or run /pointe:doctor."
    return True, f"The {vendor} key works."


def running() -> bool:
    got = subprocess.run([os.path.join(BIN, "voice-daemon"), "status"], capture_output=True, text=True, env=childenv.child_env())
    return got.stdout.startswith("running")


def restart() -> bool:
    """Stop Pointe and start it again on the new key: the joined sessions and the page's key outlast it."""
    daemon = os.path.join(BIN, "voice-daemon")
    subprocess.run([daemon, "stop"], capture_output=True)
    return subprocess.run([daemon, "ensure"], capture_output=True).returncode == 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "check" and argv[1] in KEYS:
        ok, said = check(argv[1])
        print(said)
        return 0 if ok else 1
    flags = [a for a in argv if a.startswith("--")]
    names = [a for a in argv if not a.startswith("--")]
    if len(names) != 1 or names[0] not in KEYS or not set(flags) <= {"--no-open", "--no-restart"}:
        print(f"usage: pointe key {'|'.join(KEYS)} [--no-open] [--no-restart], or pointe key check <vendor>")
        return 2
    vendor = names[0]
    if "--no-open" not in flags:
        open_page(vendor)
    if not on_a_mac() and not sys.stdin.isatty():
        print(f"No terminal to type the key in: run pointe key {vendor} in a terminal on this machine. The key goes to "
              f"{store_name()} (docs/linux.md).")
        return 1
    refused, said = False, ""
    while True:
        secret = ask(vendor, refused)
        if not secret:
            print("Cancelled: nothing saved." + (f" {LABEL[vendor]} refused the last key." if refused else ""))
            return 1
        ok, said = check(vendor, secret)
        if ok is not False:
            break
        refused = True  # the same window again, saying why
    item = KEYS[vendor][1]
    if failed := save(item, secret):
        if on_a_mac():
            print(f"Could not save the {LABEL[vendor]} key in the Keychain (item {item}): {failed}. Copy the key again "
                  f"and run pointe key {vendor}.")
        else:
            env = KEYS[vendor][0]
            print(f"Could not save the {LABEL[vendor]} key in your login keyring: {failed}. Without a keyring, give it to "
                  f"Pointe for one start only, from your own secret store: {env}=\"$(<your command that prints it>)\" "
                  f"pointe restart. Never put it in a file or your shell's startup file (docs/linux.md).")
        return 1
    works = f"The {LABEL[vendor]} key works" if ok else f"Saved the {LABEL[vendor]} key, but it could not be checked ({said})"
    where = store_name()
    if "--no-restart" in flags or not running():
        print(f"{works}. It is saved in {where}.")
        return 0
    if restart():
        print(f"{works}. It is saved in {where}, and Pointe restarted to use it.")
        return 0
    print(f"{works}. It is saved in {where}, but Pointe did not start again: run /pointe:doctor.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
