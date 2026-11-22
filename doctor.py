"""bin/voice-doctor: which vendor fills each role, why, and what to do about what is missing."""

import asyncio
import os
import socket
import sys
import textwrap

import no_telemetry  # noqa: F401  (before anything imports onnxruntime)
import local
import setups
import vendors

ROLES = [("brain", "CLAUDE_VOICE_BRAIN", vendors.BRAIN_ORDER), ("reader", "CLAUDE_VOICE_READER", vendors.READER_ORDER),
         ("checker", "CLAUDE_VOICE_CHECKER", vendors.CHECKER_ORDER), ("ears", "CLAUDE_VOICE_EARS", vendors.EARS_ORDER),
         ("mouth", "CLAUDE_VOICE_MOUTH", vendors.MOUTH_ORDER)]


# Whole setups through the real audio suite (tests/e2e/run_all.sh), keyed by the vendors whose roles run. Busy hour: 60 replies
# of 30 words, 10 reports, two ears streams, by arithmetic from docs/benchmarks.md, not a metered bill.
MEASURED = {
    frozenset({"anthropic", "soniox", "gemini", "elevenlabs"}): ("34 of 35 audio checks passed, echo 4 of 4", "about $1 an hour"),
    frozenset({"anthropic", "soniox"}): ("30 of 35 audio checks passed (31 on a rerun), echo 3 of 4", "about $1.20 an hour"),
    frozenset({"gemini"}): ("28 of 35 audio checks passed: replies take about 4 s, no echo guard: use headphones", "about $0.70 to $0.95 an hour"),
    frozenset({"openai"}): ("24 of 35 audio checks passed, echo 0 of 4: use headphones", "about $0.95 an hour"),
}
# The next key, by how much it measurably improves a role (docs/benchmarks.md).
NEXT_KEY = [
    ("soniox", "ears get 95.9% of intents right, against 92.0% on Gemini and 90.9% on OpenAI, and the echo guard lets "
               "you use speakers"),
    ("anthropic", "the brain answers in 1.8 s at the median, against 2.7 s on Gemini; their accuracy is within the margin"),
    ("elevenlabs", "the voice starts in 0.21 s, against 0.44 s on Gemini and 0.80 s on OpenAI"),
    ("gemini", "the check on each send is the fastest measured"),
]
# Fully local (`pointe local`), measured on an M5 Pro with 64 GB: docs/features/local.md.
LOCAL_MEASURED = ("10 of 19 single-session audio checks passed, every approval check among them; replies took 6 to 12 s "
                  "and a Hebrew reply is not spoken: use headphones and English.")
# Voice stays on your Mac (`pointe local voice`), measured the same way: docs/features/voice-stays-local.md.
VOICE_LOCAL_MEASURED = ("30 of 35 audio checks passed (Anthropic and Gemini keys); English speech only, and on speakers a "
                        "spoken interruption takes 3 to 4 s: use headphones")
TEXT_VENDORS, AUDIO_VENDORS = {"anthropic", "gemini", "openai"}, {"soniox", "gemini", "openai", "elevenlabs"}


def advice(present: set[str], used: set[str]) -> list[str]:
    """What this setup measured, and the one key that would improve it most."""
    if not present & TEXT_VENDORS and not present & AUDIO_VENDORS:
        return ["Start with one Gemini key: the cheapest single key, and its ears and brain score above OpenAI's."]
    if not present & TEXT_VENDORS:
        return ["Add an Anthropic key: it runs the brain and the reader, the parts that decide and report."]
    if not present & AUDIO_VENDORS:
        return ["Add a Soniox key: it hears you and speaks, and its echo guard lets you use speakers."]
    measured = MEASURED.get(frozenset(used))
    lines = [f"This setup: {measured[0]}. Cost: {measured[1]}." if measured
             else "This setup: not run through the audio suite yet."]
    for vendor, why in NEXT_KEY:
        if vendor not in present:
            return lines + [f"Next key: {vendor}. With it, {why}."]
    return lines + ["You have every key of the fastest and most accurate voice setup."]


NAMES = {"anthropic": "Anthropic", "gemini": "Gemini", "openai": "OpenAI", "local": "the local model"}


POINTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "pointe")
NO_KEY = f"""No model key yet. What do I need?
{textwrap.fill(vendors.WHAT_YOU_NEED, 118)}
{textwrap.fill(vendors.WHY_KEYS, 118)}

Setups (choose one: pointe setup <id>):
{setups.text_table()}

  In Claude Code: /pointe:setup compares the vendors and saves each key for you.
  Or yourself:    {POINTE} key gemini
                  opens a Mac window; the key goes straight to your Keychain, never into a file or this chat.
                  Get one at https://aistudio.google.com/apikey

Without a Keychain (Linux, CI): export GOOGLE_API_KEY=... (or OPENAI_API_KEY, ANTHROPIC_API_KEY, SONIOX_API_KEY,
ELEVENLABS_API_KEY). Or no key at all: `pointe local` runs every model on this Mac, and nothing leaves it
(docs/features/local.md)."""


def preflight() -> int:
    """Run before the daemon starts: a missing key is reported here, in words, not as a daemon that died."""
    if vendors.local_only() and not local.answering():
        print(f"Fully local mode is on, but the local text model does not answer at "
              f"{vendors.config().get('local_url') or local.url()}. Start it: pointe local start (or run pointe local).")
        return 1
    try:
        for note in vendors.resolve(os.environ.get("CLAUDE_VOICE_FRONT", "brain")).notes:
            print(note)
    except SystemExit as e:
        present = {v for v in vendors.KEYS if vendors.has(v)}
        chosen = setups.chosen(vendors.config())
        status = vendors.key_status(present, vendors.voice_local(), chosen)
        if not present and chosen is None:
            print(NO_KEY)
        elif status["needed"]:
            print(f"{status['line']}\n  Save it:  {POINTE} key {status['fix']}\n  Check it: {POINTE} key check {status['fix']}\n\nWhat do I need? "
                  f"{textwrap.fill(vendors.WHAT_YOU_NEED, 100)}\n{textwrap.fill(vendors.WHY_KEYS, 118)}\n"
                  "bin/voice-doctor shows each role.")
        else:
            print(f"{e}\n\nbin/voice-doctor shows each role.")
        return 1
    return 0


def harnesses_here() -> list[str]:
    """Which coding agents this Mac has, and how each joins the voice. None is required: any one is enough."""
    import shutil
    import subprocess

    lines = []
    if shutil.which("claude"):
        lines.append("  found    Claude Code   join: /pointe:voice in a session")
    else:
        lines.append("  missing  Claude Code   (optional) https://code.claude.com")
    if shutil.which("opencode"):
        try:
            up = subprocess.run(["opencode", "service", "status"], capture_output=True, text=True, timeout=5).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            up = False
        lines.append(f"  found    OpenCode      join: pointe join opencode, in the session's folder"
                     + ("" if up else " (its service is not running: start opencode first)"))
    if shutil.which("codex"):
        lines.append('  found    Codex         join: start it with codex --remote unix:// -C "$PWD", then pointe join codex in that folder')
    return lines


def main() -> int:
    if "--preflight" in sys.argv:
        return preflight()
    live, problems = "--live" in sys.argv, 0
    print("\nCoding agents:")
    print("\n".join(harnesses_here()))
    present = {v for v in vendors.KEYS if vendors.has(v)}
    setup = setups.chosen(vendors.config())
    status = vendors.key_status(present, vendors.voice_local() and not vendors.local_only(), setup)
    print(f"\nSetup: {setup.name} ({setup.id}). Switch: pointe setup" if setup else
          "\nSetup: none chosen, so each role takes the first vendor with a key. Choose one: pointe setup")
    chosen, keyless, failed = {}, not present, {}
    for role, env, order in ROLES:
        try:
            chosen[role] = vendors.pick(env, order)
        except SystemExit as e:
            failed[role] = e
    print("\nKeys (value never shown):" + (" none is read in fully local mode" if vendors.local_only() else ""))
    for vendor in vendors.KEYS:
        uses = [role for role, choice in chosen.items() if choice.split(":")[0] == vendor]
        if vendor in vendors.AUDIO_ONLY and vendors.voice_local() and not vendors.local_only():
            print(f"  not read {vendor} (audio only: the voice stays on this Mac)")
        elif vendor in present:
            print(f"  found    {vendor} ({', '.join(uses) if uses else 'not used: another key fills its roles'})")
        elif status["keys"][vendor] == "needed":
            print(f"  needed   {vendor} (" + (f"the setup uses it: pointe key {vendor}" if setup else
                                            f"the one key that fills {', '.join(status['empty'])}") + ")")
        elif setup is not None:
            print(f"  optional {vendor} (the {setup.name} setup does not use it)")
        else:
            print(f"  optional {vendor}" + ("" if status["empty"] or vendors.local_only() else " (not needed with your current keys)"))
    print("\n" + "\n".join(local.status_lines()))
    print("\nRoles:")
    for role, _env, _order in ROLES:
        if role in chosen:
            print(f"  {role:7} {chosen[role]}")
        else:
            problems += 1
            print(f"  {role:7} needs a key" if keyless else f"  {role:7} NOT AVAILABLE: {failed[role]}")
    if problems and keyless:
        print("\n" + NO_KEY)
    if chosen.get("ears") and chosen["ears"] != "soniox":
        print("\nNo Soniox ears: the echo guard has no mirror stream. Use headphones.")
    if vendors.voice_local() and not vendors.local_only():
        text = sorted({NAMES.get(v, v) for v in (chosen[r].split(":")[0] for r in ("brain", "reader", "checker") if r in chosen)})
        print(f"\nThis setup: {vendors.VOICE_LOCAL}. Your voice is heard and spoken on this Mac, and no audio goes to any "
              f"vendor; {' and '.join(text) or 'the text models'} {'gets' if len(text) == 1 else 'get'} text only. {VOICE_LOCAL_MEASURED}. "
              "Back to your vendors: pointe local off.")
    elif vendors.local_only():
        print(f"\nThis setup: fully local, no key read. {LOCAL_MEASURED} Back to vendors: pointe local off.")
    else:
        print("\n" + "\n".join(advice(present, {c.split(":")[0] for c in chosen.values()})))
    port = int(os.environ.get("CLAUDE_VOICE_DAEMON_PORT", "7860"))
    with socket.socket() as s:
        in_use = s.connect_ex(("127.0.0.1", port)) == 0
    print(f"\nPort {port}: {'in use (the daemon, or something else: bin/voice-daemon status tells which)' if in_use else 'free'}")
    if live:
        print("\nLive check, one short call per text model:")
        for role in ("brain", "reader", "checker"):
            if role in chosen:
                try:
                    asyncio.run(vendors.text(chosen[role], "Reply with the word ok."))
                    vendors._clients.clear()
                    print(f"  ok      {role} {chosen[role]}")
                except Exception as e:
                    problems += 1
                    vendor = chosen[role].split(":")[0]
                    why = (vendors.refused_help(vendor) if vendors.refused_key(f"{type(e).__name__} {e}") is not None
                           else "Check the key and that it can use this model.")
                    print(f"  FAILED  {role} {chosen[role]}: {type(e).__name__}. {why}")
    print("\nChange the setup: pointe setup. One role by hand: CLAUDE_VOICE_<ROLE>=vendor:model, or ~/.claude-voice/config.json.")
    return 1 if problems else 0


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # pipecat, imported for the local status, logs a banner: this output is for people
    sys.exit(main())
