"""The setups a person chooses from: which keys each needs, what each key does there, what it measured, what it costs
and where your words go. One source: tools/setups.py writes docs/setups.md and the tables in README.md and
/pointe:setup from it; the doctor, the page and the Mac app read it (the Mac app's copy is held to it by
tests/test_setups.py). Every number names the file and row it comes from; nothing here is measured anew.

    pointe setup              the table, and the setup in use
    pointe setup <id>         use that setup from now on: exactly its vendors (config.json "setup")

Standard library only: tools/setups.py imports it without the project's packages.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The roles, in plain words. "checker" is the config name; people read "gate" in the doctor.
ROLES = {
    "brain": "understands you and replies",
    "reader": "turns session output into short reports",
    "checker": "a safety check on each send and approval",
    "ears": "speech to text",
    "mouth": "the voice",
}
NAMES = {"gemini": "Gemini", "openai": "OpenAI", "anthropic": "Anthropic", "soniox": "Soniox", "elevenlabs": "ElevenLabs"}

WHY_KEYS = ("Why its own keys? Pointe runs its own models next to Claude Code: the brain, the reader and the checker, "
            "the ears and the voice. Your Claude subscription (Pro or Max) runs Claude Code, but has no interface other "
            "apps can use, so Pointe's voice needs its own API key from console.anthropic.com, or one Gemini or OpenAI "
            "key. An API key is billed per use: about $1 for a busy hour of talk.")

BUSY_HOUR = ("A busy hour: 60 spoken replies, 10 session reports and the call open for the hour, by arithmetic from "
             "measured and list prices (docs/benchmarks.md, \"Cost arithmetic\"), not a metered bill.")


@dataclass(frozen=True)
class Setup:
    id: str
    name: str
    keys: tuple  # every one is needed
    does: dict  # vendor (or "this Mac") -> the roles it fills in this setup; tests/test_setups.py holds it to vendors.filled
    measured: tuple  # (claim, source): each number with the file and row it comes from
    speed: tuple
    cost: str
    privacy: str
    pick_for: str  # reads after "Best for": "Best for daily use."
    optional: tuple = ()  # used when present, never asked for
    needs: str = ""  # beyond a Mac and Chrome
    local: str = ""  # "voice": ears and mouth on this Mac; "all": every model on this Mac
    short: str = ""  # one line for the apps' and the page's lists
    extra: dict = field(default_factory=dict)


SETUPS = (
    Setup("free", "Free start", ("gemini",), {"gemini": ("brain", "reader", "checker", "ears", "mouth")},
          measured=(("28 of 35 audio checks on a paid key; a free-tier key ran out of quota in the run (3 of 19)",
                     "bench/results/combinations.md, \"Gemini only\""),
                    ("brain 94.9% against Sonnet's 91.9%: within the margin (the 95% intervals overlap)",
                     "docs/benchmarks.md, \"Brain and reader\""),
                    ("ears 92.0% of intents against Soniox's 95.9%; no echo guard, so use headphones",
                     "docs/benchmarks.md, ears table")),
          speed=(("replies took 4.0 to 4.5 s", "bench/results/combinations.md, \"Gemini only\""),),
          cost="$0 until the free quota ends; about $0.70 to $0.95 with billing on",
          privacy="Speech and session text go to Google. On the free tier Google may use and review them: not for "
                  "confidential work.",
          pick_for="trying Pointe at no cost",
          short="One Gemini key. Free to try; slower replies, headphones."),
    Setup("openai", "One OpenAI key", ("openai",), {"openai": ("brain", "reader", "checker", "ears", "mouth")},
          measured=(("24 of 35 audio checks", "bench/results/combinations.md, \"OpenAI only\""),
                    ("brain 87.9% against Sonnet's 95.5% in the same run: the 95% intervals overlap",
                     "bench/results/brain_substance.md, gpt-6-sol (v7openai)"),
                    ("ears 90.9% of intents; no echo guard, so use headphones", "docs/benchmarks.md, ears table")),
          speed=(("whole replies not measured; the brain answers in 2.4 s at the median",
                  "bench/results/brain_substance.md, gpt-6-sol (v7openai)"),),
          cost="about $0.95", privacy="Speech and session text go to OpenAI.",
          pick_for="people who already pay for OpenAI",
          needs="headphones; English speech only",  # its ears misheard mixed Hebrew and English, with or without a language set
          short="One OpenAI key. Headphones, English speech only; weakest audio result."),
    Setup("two", "Two keys", ("soniox", "anthropic"),
          {"anthropic": ("brain", "reader", "checker"), "soniox": ("ears", "mouth")},
          measured=(("30 of 35 audio checks (31 on a rerun); echo guard 3 of 4, so speakers work",
                     "bench/results/combinations.md, \"Anthropic, Soniox\""),
                    ("ears 95.9% of intents, the highest measured", "docs/benchmarks.md, ears table, Soniox v6")),
          speed=(("whole replies not measured; the brain answers in 1.8 s at the median; in the voice benchmark the voice "
                  "starts in 301 ms (the voice alone, not a call)",
                  "docs/benchmarks.md, \"Brain and reader\" and the mouth table"),),
          cost="about $1.20", privacy="Speech goes to Soniox; session text to Anthropic.",
          pick_for="the best ears with two accounts, on laptop speakers",
          short="Soniox and Anthropic. Best ears, works on speakers."),
    Setup("full", "Fastest and most accurate voice", ("anthropic", "soniox", "elevenlabs", "gemini"),
          {"anthropic": ("brain", "reader"), "gemini": ("checker",), "soniox": ("ears",), "elevenlabs": ("mouth",)},
          measured=(("34 of 35 audio checks, echo guard 4 of 4: the highest whole-setup result",
                     "bench/results/combinations.md, \"(default)\""),
                    ("ears 95.9% of intents (next: Gemini 92.0%)", "docs/benchmarks.md, ears table"),
                    ("voice word error 0.00 in English, the lowest", "docs/benchmarks.md, mouth table, eleven_v4_turbo"),
                    ("brain: Sonnet 91.9% against Gemini's 94.9%, within the margin; Sonnet is the faster one",
                     "docs/benchmarks.md, \"Brain and reader\"")),
          speed=(("replies in 2.4 s at the median (2.0 to 2.6), the fastest measured",
                  "docs/features/voice-stays-local.md, \"Measured\""),
                 ("in the voice benchmark the voice starts in 213 ms (the voice alone, not a call)",
                  "docs/benchmarks.md, mouth table")),
          cost="about $1",
          privacy="Speech goes to Soniox; session text to Anthropic and Gemini (paid tier); the replies' text to "
                  "ElevenLabs.",
          pick_for="daily use",
          short="Anthropic, Soniox, ElevenLabs, Gemini. Fastest replies, best ears and voice."),
    Setup("voice-local", "Voice stays on your Mac", ("anthropic",),
          {"anthropic": ("brain", "reader", "checker"), "this Mac": ("ears", "mouth")},
          optional=("gemini",),
          measured=(("30 of 35 audio checks, with Anthropic and Gemini keys", "bench/results/combinations.md, "
                                                                              "\"Voice stays on your Mac\""),
                    ("ears 82.7% of intents on the Mac, against Soniox's 94.6% in the same run; English speech only",
                     "docs/features/voice-stays-local.md, \"Measured\"")),
          speed=(("replies in 4.1 s at the median", "docs/features/voice-stays-local.md, \"Measured\""),),
          cost="about $0.40 (Anthropic and Gemini)",
          privacy="No audio leaves the Mac. Your words, as text, and session text go to Anthropic (and Gemini, if set).",
          pick_for="confidential work where text may leave the Mac but your voice may not",
          needs="an Apple-silicon Mac, about 2 GB of disk, headphones", local="voice",
          short="One Anthropic key; ears and voice on the Mac. No audio leaves it."),
    Setup("local", "Fully local", (), {"this Mac": ("brain", "reader", "checker", "ears", "mouth")},
          measured=(("10 of 19 one-session audio checks, every approval check among them", "bench/results/combinations.md, "
                                                                                             "\"None: fully local\""),
                    ("brain 76.9% against Sonnet's 91.9%", "docs/benchmarks.md, \"Fully local\"")),
          speed=(("replies took 5.8 to 11.6 s", "bench/results/combinations.md, \"None: fully local\""),),
          cost="$0", privacy="Nothing leaves the Mac.",
          pick_for="work where nothing may leave the Mac, on a 32 GB Mac",
          needs="an Apple-silicon Mac with 32 GB of memory, about 19 GB of disk, headphones; English only", local="all",
          short="No key. Every model on the Mac; slow, English only."),
)
BY_ID = {s.id: s for s in SETUPS}
DEFAULT = "free"  # the one /pointe:setup offers first: one key, about 5 minutes


def _keys(s: Setup) -> str:
    keys = " + ".join(NAMES[k] for k in s.keys) or "none"
    return keys + (f" ({', '.join(NAMES[k] for k in s.optional)} optional)" if s.optional else "")


def _does(s: Setup) -> str:
    return "; ".join(f"{NAMES.get(v, v)}: {', '.join(roles)}" for v, roles in s.does.items())


def table(full: bool = True) -> str:
    """The Markdown table: full with sources (docs/setups.md), or the short one for the README and /pointe:setup."""
    if not full:
        rows = ["| Setup (`pointe setup <id>`) | Keys | Measured | A busy hour | Best for |", "|---|---|---|---|---|"]
        for s in SETUPS:
            rows.append(f"| {s.name} (`{s.id}`) | {_keys(s)} | {s.measured[0][0]}; {s.speed[0][0]} | {s.cost} | {s.pick_for} |")
        return "\n".join(rows)
    rows = ["| Setup | Keys | What each one does | Measured | Speed | A busy hour | Where your words go | Best for |",
            "|---|---|---|---|---|---|---|---|"]
    for s in SETUPS:
        cite = lambda claims: "<br>".join(f"{c} ({src})" for c, src in claims)  # noqa: E731
        rows.append(f"| **{s.name}** (`{s.id}`){'<br>Needs ' + s.needs if s.needs else ''} | {_keys(s)} | {_does(s)} | "
                    f"{cite(s.measured)} | {cite(s.speed)} | {s.cost} | {s.privacy} | {s.pick_for} |")
    return "\n".join(rows)


def text_table() -> str:
    """The same choice for a terminal: the doctor and `pointe setup`."""
    lines = []
    for s in SETUPS:
        keys = _keys(s) if s.keys else "no key"
        lines.append(f"  {s.id:12} {s.name}: {keys}. A busy hour: {s.cost}. Best for {s.pick_for}.")
        lines.append(f"  {'':12} {s.measured[0][0]}; {s.speed[0][0]}.")
    return "\n".join(lines)


# ---------- the choice, in config.json ----------

ROLE_KEYS = ("brain", "reader", "checker", "ears", "mouth")


def state() -> Path:
    return Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))


def chosen(config: dict) -> Setup | None:
    return BY_ID.get(config.get("setup", ""))


def choose(setup_id: str) -> dict:
    """Use this setup from now on, exactly its vendors: a role chosen by hand, and a local mode, give way to it.
    Returns the config written. The local setups are written by `pointe local` (local.py), which calls this first."""
    path = state() / "config.json"
    try:
        current = json.loads(path.read_text())
    except FileNotFoundError:
        current = {}
    setup = BY_ID.get(setup_id)
    host = os.environ.get("CLAUDE_VOICE_OPENAI_URL") or current.get("openai_url")
    if host and setup and any(r in ("ears", "mouth") for r in setup.does.get("openai", ())):
        # The OpenAI key belongs to that host (docs/features/openai-url.md); OpenAI's ears and mouth would send it to OpenAI.
        raise SystemExit(f"The {setup.name} setup uses OpenAI's ears and mouth, but openai_url sends the OpenAI key to "
                         "another host. Choose a setup with other ears and mouth, or remove openai_url.")
    for gone in (*ROLE_KEYS, "local_only", "local_url", "voice_local"):
        current.pop(gone, None)
    current["setup"] = setup_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2) + "\n")
    (state() / "local" / "config.before-local.json").unlink(missing_ok=True)  # `pointe local off` must not bring back the old choice
    return current


def main(argv: list[str]) -> int:
    try:
        current = json.loads((state() / "config.json").read_text())
    except FileNotFoundError:
        current = {}
    if not argv:
        now = chosen(current)
        print(f"{WHY_KEYS}\n\nSetups (pointe setup <id> to use one):\n{text_table()}\n\n{BUSY_HOUR}\n")
        print(f"In use: {now.name} ({now.id})." if now else "In use: none chosen, so each role takes the first vendor with a "
              f"key. Recommended to start: pointe setup {DEFAULT}.")
        return 0
    if len(argv) != 1 or argv[0] not in BY_ID:
        print(f"usage: pointe setup [{'|'.join(BY_ID)}]")
        return 2
    s = BY_ID[argv[0]]
    choose(s.id)
    print(f"Setup: {s.name}. Pointe now uses {_keys(s) if s.keys else 'no key'}"
          f"{' and the models on this Mac' if s.local else ''}, and no other vendor.")
    for vendor in s.keys:
        print(f"  Its {NAMES[vendor]} key: pointe key {vendor} opens the key page and a Mac window, and checks the key.")
    missing = _missing_keys(s)
    if missing:
        print(f"Not saved yet: the {' and the '.join(NAMES[v] for v in missing)} key. Save "
              f"{'it' if len(missing) == 1 else 'them'} first ({'; '.join(f'pointe key {v}' for v in missing)}): until then "
              "Pointe cannot start on this setup, and pointe restart keeps it running as it is.")
    else:
        print("If Pointe is running, restart it to use the setup: pointe restart.")
    return 0


def _missing_keys(s: Setup) -> list[str]:
    """The setup's keys that are neither in the environment nor in the Keychain. Empty when this cannot be told (run
    without the project's packages, as tools/setups.py does)."""
    try:
        import vendors
    except ImportError:
        return []
    return [v for v in s.keys if not vendors.saved(v)]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
