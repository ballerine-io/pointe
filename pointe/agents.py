"""Agents built on agent frameworks (OpenClaw, Hermes Agent, any A2A or OpenAI-compatible agent), talked to through
their own conversation surface (docs/design/agents.md). Off unless POINTE_AGENTS=on.

    pointe agent add <kind> <url> [--name NAME] [--agent ID]   connect an agent; its credential is asked for, hidden
    pointe agents                                              the agents, and whether each answers
    pointe agent remove <name>                                 take one out, with its saved credential

<kind> is openclaw, hermes, a2a or openai.

This module holds the list ($STATE/agents.json, 0600: names, kinds, addresses, never a credential), the credential's
place in the Keychain, the checks an address passes, and the routes the screens use. Each agent joins the voice as a
session of its kind's harness (pointe/harnesses/agent.py).
"""

import ipaddress
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)

FLAG = "POINTE_AGENTS"
KINDS = {  # kind -> (what the screens call it, what the voice calls the agent)
    "openclaw": ("OpenClaw", "OpenClaw"),
    "hermes": ("Hermes Agent", "Hermes"),
    "a2a": ("Any A2A agent", "the agent"),
    "openai": ("Any OpenAI-compatible agent", "the agent"),
}
ITEM_PREFIX = "pointe.agent."  # the Keychain item of an agent's credential: pointe.agent.<name>
NAME_MAX = 30
SECRET_MAX = 512


def enabled() -> bool:
    return os.environ.get(FLAG, "off").strip().lower() in ("on", "1", "true", "yes")


@dataclass
class Agent:
    name: str
    kind: str
    url: str
    agent: str = ""  # the agent inside the framework (OpenClaw: an agent id; openai: the model name); "" for its default
    added: float = field(default_factory=time.time)

    @property
    def item(self) -> str:
        return ITEM_PREFIX + self.name

    @property
    def session_id(self) -> str:
        return "agent-" + re.sub(r"[^\w-]+", "-", self.name.lower()).strip("-")

    def public(self) -> dict:
        return {"name": self.name, "kind": self.kind, "url": self.url, "agent": self.agent, "title": KINDS[self.kind][0],
                "session_id": self.session_id}


class Store:
    """$STATE/agents.json. A damaged file or entry is skipped, never fatal."""

    def __init__(self, state_dir: Path):
        self.path = Path(state_dir) / "agents.json"
        self.agents: dict[str, Agent] = {}
        self.load()

    def load(self) -> None:
        self.agents = {}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        for raw in data.get("agents", []) if isinstance(data, dict) else []:
            try:
                a = Agent(**{k: raw[k] for k in ("name", "kind", "url", "agent", "added") if k in raw})
            except (TypeError, KeyError):
                continue
            if a.kind in KINDS and not name_problem(a.name) and not url_problem(a.url):
                self.agents[a.name.lower()] = a

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"agents": [asdict(a) for a in self.agents.values()]}, indent=1))
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def get(self, name: str) -> Agent | None:
        return self.agents.get(str(name).strip().lower())

    def by_session(self, session_id: str) -> Agent | None:
        return next((a for a in self.agents.values() if a.session_id == session_id), None)

    def put(self, agent: Agent) -> None:
        self.agents[agent.name.lower()] = agent
        self.save()

    def remove(self, name: str) -> Agent | None:
        gone = self.agents.pop(str(name).strip().lower(), None)
        if gone:
            self.save()
        return gone


def name_problem(name) -> str | None:
    """Why an agent cannot be called `name`, in words for the user, or None. The session rules (speakable, no yes or no
    word, no clash) are checked again by the registry when it joins."""
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][\w -]{0,%d}" % (NAME_MAX - 1), name.strip()):
        return f"A name is 1 to {NAME_MAX} letters, digits, spaces or dashes, starting with a letter."
    return None


def _private(host: str) -> bool:
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")  # CGNAT: Tailscale, Twingate


def normalized(url) -> str:
    """An address typed without a scheme ("127.0.0.1:18789") is http: what a local gateway serves."""
    url = str(url or "").strip()
    return url if "://" in url or not url else "http://" + url


def url_problem(url) -> str | None:
    """Why `url` cannot be an agent's address, or None. https anywhere; http only to this machine or a private network:
    the credential goes with every request, and over plain http on the internet anyone on the path could read it."""
    if not isinstance(url, str) or len(url) > 300:
        return "The address must be an http or https URL."
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "The address must be an http or https URL."
    if parsed.username or parsed.password:
        return "Put the credential in its own field, not in the address."
    if parsed.scheme == "http" and not _private(parsed.hostname.lower()):
        return "Plain http only to this machine or a private network: use https for an agent on the internet."
    return None


def secret_problem(secret) -> str | None:
    if not isinstance(secret, str) or not secret.strip():
        return "The agent's token, key or password is needed."
    if len(secret) > SECRET_MAX or not (secret.isascii() and secret.strip().isprintable()):
        return "That does not look like a token: it has a line break or a character outside plain ASCII."
    return None


def read_secret(agent: Agent) -> str | None:
    """The agent's credential from the Keychain (the Secret Service on Linux), or None. Never cached on disk."""
    import vendors

    try:
        return vendors.from_store(agent.item)
    except (OSError, Exception):  # a locked keyring, a timeout: the turn says the credential could not be read
        return None


def save_secret(agent: Agent, secret: str) -> str | None:
    """Into the Keychain as pointe.agent.<name>; None when saved and read back, else why not (no part of the secret)."""
    import keys

    return keys.save(agent.item, secret.strip())


def delete_secret(agent: Agent) -> None:
    import subprocess

    import childenv

    command = (["/usr/bin/security", "delete-generic-password", "-s", agent.item] if sys.platform == "darwin"
               else ["secret-tool", "clear", "service", agent.item])
    try:
        subprocess.run(command, capture_output=True, timeout=10, env=childenv.child_env())
    except (OSError, subprocess.TimeoutExpired):
        pass


def vendors_line(names: list[str], agent: str) -> str:
    """What `pointe agent add` and the screens say once: where the agent's words go."""
    if not names:
        return f"What {agent} says stays on this Mac: your setup is fully local."
    return (f"What {agent} says is transcribed into your call like a session's: it reaches "
            f"{', '.join(names[:-1]) + ' and ' + names[-1] if len(names) > 1 else names[0]}, the services your voice uses.")


# ---------- the command line: pointe agent ... ----------

def _ask_secret(kind: str) -> str | None:
    """Hidden typing: a Mac dialog, as `pointe key` asks; the terminal's own hidden prompt elsewhere."""
    import getpass
    import subprocess

    import childenv

    what = {"openclaw": "the gateway token (or password)", "hermes": "the API server key (API_SERVER_KEY)",
            "a2a": "the bearer token this agent gave you", "openai": "the API key"}[kind]
    if sys.platform != "darwin":
        if not sys.stdin.isatty():
            return None
        try:
            return getpass.getpass(f"Paste {what} (the typing is hidden), then press Enter: ").strip() or None
        except (EOFError, KeyboardInterrupt):
            return None
    script = (f'display dialog "Paste {what}. It goes to your Mac\'s Keychain, nowhere else." default answer "" '
              f'with hidden answer with title "Pointe: connect {KINDS[kind][0]}" buttons {{"Cancel", "Save"}} '
              f'default button "Save"\ntext returned of result')
    got = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, env=childenv.child_env())
    return got.stdout.strip() if got.returncode == 0 and got.stdout.strip() else None


def main(argv: list[str]) -> None:
    from hub_nodes import _daemon

    command = argv[0] if argv else "list"
    if command in ("list", "ls"):
        listed = _daemon("GET", "/voice/agents")
        if not listed.get("enabled"):
            return print(f"Agents are off. Start Pointe with {FLAG}=on to use them.")
        if not listed["agents"]:
            return print("No agents yet. Connect one: pointe agent add openclaw|hermes|a2a|openai <url>")
        for a in listed["agents"]:
            print(f"{a['name']}  {a['title']}  {a['url']}  {a['state']}" + (f": {a['why']}" if a.get("why") else ""))
        return
    if command == "add" and len(argv) >= 3 and argv[1] in KINDS:
        kind, url, rest = argv[1], normalized(argv[2]), argv[3:]
        name = rest[rest.index("--name") + 1] if "--name" in rest[:-1] else kind
        agent = rest[rest.index("--agent") + 1] if "--agent" in rest[:-1] else ""
        if problem := name_problem(name) or url_problem(url):
            raise SystemExit(problem)
        secret = _ask_secret(kind)
        if not secret:
            raise SystemExit("Not added: no credential was given.")
        added = _daemon("POST", "/voice/agents", {"kind": kind, "url": url, "name": name, "agent": agent, "secret": secret},
                        timeout=40)
        secret = None
        print(f"Added {added['name']}: {added['title']} at {added['url']}. Say \"talk to {added['name']}\", or "
              f"\"ask {added['name']} to ...\".")
        print(added.get("vendors_line", ""))
        _daemon("POST", "/voice/agents/seen", {"name": added["name"]})  # said here: not again on a screen
        return
    if command in ("remove", "rm") and len(argv) > 1:
        name = " ".join(argv[1:])
        _daemon("DELETE", f"/voice/agents/{name}")
        print(f"{name} is no longer in your voice; its saved credential is deleted.")
        return
    print(__doc__.split("\n\n")[1].rstrip())


if __name__ == "__main__":
    main(sys.argv[1:])
