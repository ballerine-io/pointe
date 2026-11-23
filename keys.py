"""Save a model key in the macOS Keychain without it ever touching a command line, a chat, a file or a log.

    pointe key gemini|anthropic|openai|soniox|elevenlabs
                                  opens the vendor's key page, asks for the key in a Mac window, checks it with one tiny
                                  live call (asks again when it is refused), saves it, and restarts Pointe if it runs
        --no-open                 without opening the vendor's page
        --no-restart              without restarting Pointe (the caller does it)
    pointe key check <vendor>     one tiny live call with the saved key: works, refused, or unreachable


A native dialog with hidden input asks for the key; `security` receives it through its own password prompt (a pty), so it
is never an argument. Made for people who do not use a terminal: Claude Code can run this for them.
"""

import os
import pty
import select
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)
import childenv  # noqa: E402
import vendors  # noqa: E402
from vendors import KEYS  # noqa: E402

BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
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


def prompt(vendor: str, refused: bool = False) -> str:
    """The dialog's text: three numbered lines, after the reason it is back when the last key was refused."""
    head = f"{LABEL[vendor]} refused that key: it may be mistyped, revoked or out of credit. Try again.\\n\\n" if refused else ""
    return (f"{head}1. Open {_site(vendor)} (Pointe opened it in your browser).\\n"
            f"2. {CREATE[vendor]}\\n"
            f"3. Paste it here and press Save.\\n\\n"
            f"It goes to your Mac's Keychain, nowhere else. Pointe never shows it.")


def ask(vendor: str, refused: bool = False) -> str | None:
    """A macOS dialog with hidden typing. None if the user cancelled."""
    script = (f'display dialog "{prompt(vendor, refused)}" default answer "" with hidden answer '
              f'with title "Pointe: {LABEL[vendor]} key" buttons {{"Cancel", "Save"}} default button "Save"\n'
              f'text returned of result')
    got = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, env=childenv.child_env())
    return got.stdout.strip() if got.returncode == 0 and got.stdout.strip() else None


def open_page(vendor: str) -> None:
    """The vendor's key page in the browser, so the person does not have to find it."""
    try:
        subprocess.run(["open", WHERE[vendor]], capture_output=True, timeout=10, env=childenv.child_env())
    except (OSError, subprocess.TimeoutExpired):
        pass


def save(item: str, secret: str) -> bool:
    """`security` asks for the password on its terminal: answer it there, twice, so the key never is an argument."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execve("/usr/bin/security", ["security", "add-generic-password", "-U", "-s", item, "-a", os.environ.get("USER", "pointe"),
                             "-w"], childenv.child_env())
    answered, deadline = 0, time.time() + 15
    try:
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if ready:
                try:
                    chunk = os.read(fd, 256)
                except OSError:
                    chunk = b""
                if chunk.rstrip().endswith(b":") and answered < 2:  # "password data for new item:", then "retype ...:"
                    os.write(fd, secret.encode() + b"\n")
                    answered += 1
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                return os.waitstatus_to_exitcode(status) == 0
        os.kill(pid, 9)
        os.waitpid(pid, 0)
        return False
    finally:
        os.close(fd)


# The audio-only vendors have no text model: a list of their models is the smallest call their key must authorise.
AUDIO_CHECK = {"soniox": ("https://api.soniox.com/v1/models", "Authorization", "Bearer {}"),
               "elevenlabs": ("https://api.elevenlabs.io/v1/models", "xi-api-key", "{}")}


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
            urllib.request.urlopen(urllib.request.Request(url, headers={header: form.format(secret)}), timeout=15).close()
        else:
            # Their own choice first: on another host (openai_url) the default model names are not deployed.
            configured = [c for c in (vendors.config().get(r) for r in ("checker", "brain", "reader")) if c]
            model = next(c for c in [*configured, *vendors.CHECKER_ORDER] if c.startswith(f"{vendor}:")).split(":", 1)[1]
            asyncio.run(vendors._TEXT[vendor](model, "Reply with the word ok.", None, False, None, 16, 0.0))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, vendors.refused_help(vendor)
        return None, f"The {vendor} key could not be checked: the vendor answered HTTP {e.code}. Try again later."
    except urllib.error.URLError:
        return None, f"The {vendor} key could not be checked: no connection to {vendor}."
    except Exception as e:
        if vendors.refused_key(f"{type(e).__name__} {e}") is not None:
            return False, vendors.refused_help(vendor)
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
    if not save(item, secret):
        print(f"Could not save it in the Keychain (item {item}).")
        return 1
    works = f"The {LABEL[vendor]} key works" if ok else f"Saved the {LABEL[vendor]} key, but it could not be checked ({said})"
    if "--no-restart" in flags or not running():
        print(f"{works}. It is saved in your Keychain.")
        return 0
    if restart():
        print(f"{works}. It is saved in your Keychain, and Pointe restarted to use it.")
        return 0
    print(f"{works}. It is saved in your Keychain, but Pointe did not start again: run /pointe:doctor.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
