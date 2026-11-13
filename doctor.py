"""bin/voice-doctor: which vendor fills each role, why, and what to do about what is missing."""

import asyncio
import os
import socket
import sys

import vendors

ROLES = [("brain", "CLAUDE_VOICE_BRAIN", vendors.BRAIN_ORDER), ("reader", "CLAUDE_VOICE_READER", vendors.READER_ORDER),
         ("gate", "CLAUDE_VOICE_CHECKER", vendors.CHECKER_ORDER), ("ears", "CLAUDE_VOICE_EARS", vendors.EARS_ORDER),
         ("mouth", "CLAUDE_VOICE_MOUTH", vendors.MOUTH_ORDER)]


# Whole setups through the real audio suite (tests/e2e/run_all.sh), keyed by the vendors whose roles run. Busy hour: 60 replies
# of 30 words, 10 reports, two ears streams, by arithmetic from docs/benchmarks.md, not a metered bill.
MEASURED = {
    frozenset({"anthropic", "soniox", "gemini", "elevenlabs"}): ("33 of 35 audio checks passed, echo 4 of 4", "about $1 an hour"),
    frozenset({"anthropic", "soniox"}): ("30 of 35 audio checks passed, echo 2 of 4 (3 of 4 on a rerun)", "about $1.20 an hour"),
    frozenset({"gemini"}): ("27 of 35 audio checks passed: replies take about 4 s, and a Hebrew yes is heard as \"Ken\"", "about $0.40 an hour plus Gemini ears, not priced here"),
    frozenset({"openai"}): ("29 of 35 audio checks passed, echo 1 of 4: use headphones", "about $0.60 an hour plus OpenAI ears, not priced here"),
}
# The next key, by how much it measurably improves a role (docs/benchmarks.md).
NEXT_KEY = [
    ("soniox", "ears get 94.6% of intents right, against 88 to 90%, and the echo guard lets you use speakers"),
    ("anthropic", "the brain passes 95.5% of cases, against 90.9% on Gemini and 87.9% on OpenAI"),
    ("elevenlabs", "the voice starts in 0.21 s, against 0.44 s on Gemini and 0.80 s on OpenAI"),
    ("gemini", "the check on each send is the fastest measured"),
]
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
    return lines + ["You have every key the best measured setup uses."]


POINTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "pointe")
NO_KEY = f"""No model key yet. One key is enough to start: Gemini alone runs every role (free tier available).

  In Claude Code: /pointe:setup compares the vendors and saves each key for you.
  Or yourself:    {POINTE} key gemini
                  opens a Mac window; the key goes straight to your Keychain, never into a file or this chat.
                  Get one at https://aistudio.google.com/apikey

The best setup uses four: Anthropic (brain, reader), Soniox (ears, echo guard), ElevenLabs (mouth), Gemini (gate).
Without a Keychain (Linux, CI): export GOOGLE_API_KEY=... (or OPENAI_API_KEY, ANTHROPIC_API_KEY, SONIOX_API_KEY,
ELEVENLABS_API_KEY). Or no key at all: see "Run without any cloud" in the README."""


def preflight() -> int:
    """Run before the daemon starts: a missing key is reported here, in words, not as a daemon that died."""
    try:
        for note in vendors.resolve(os.environ.get("CLAUDE_VOICE_FRONT", "brain")).notes:
            print(note)
    except SystemExit as e:
        if not any(vendors.has(v) for v in vendors.KEYS):
            print(NO_KEY)
        else:
            print(f"{e}\n\nThese keys alone cannot fill every role. A Gemini key or an OpenAI key can. bin/voice-doctor shows each role.")
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
        lines.append("  found    Codex         not supported yet: coming next")
    return lines


def main() -> int:
    if "--preflight" in sys.argv:
        return preflight()
    live, problems = "--live" in sys.argv, 0
    print("\nCoding agents:")
    print("\n".join(harnesses_here()))
    print("\nKeys (value never shown):")
    for vendor in vendors.KEYS:
        print(f"  {'found  ' if vendors.has(vendor) else 'missing'}  {vendor}")
    print("\nRoles:")
    chosen, keyless = {}, not any(vendors.has(v) for v in vendors.KEYS)
    for role, env, order in ROLES:
        try:
            chosen[role] = vendors.pick(env, order)
            print(f"  {role:7} {chosen[role]}")
        except SystemExit as e:
            problems += 1
            print(f"  {role:7} needs a key" if keyless else f"  {role:7} NOT AVAILABLE: {e}")
    if problems and keyless:
        print("\n" + NO_KEY)
    if chosen.get("ears") and chosen["ears"] != "soniox":
        print("\nNo Soniox ears: the echo guard has no mirror stream. Use headphones.")
    present = {v for v in vendors.KEYS if vendors.has(v)}
    print("\n" + "\n".join(advice(present, {c.split(":")[0] for c in chosen.values()})))
    port = int(os.environ.get("CLAUDE_VOICE_DAEMON_PORT", "7860"))
    with socket.socket() as s:
        in_use = s.connect_ex(("127.0.0.1", port)) == 0
    print(f"\nPort {port}: {'in use (the daemon, or something else: bin/voice-daemon status tells which)' if in_use else 'free'}")
    if live:
        print("\nLive check, one short call per text model:")
        for role in ("brain", "reader", "gate"):
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
    print("\nChange a role: CLAUDE_VOICE_<ROLE>=vendor:model, or ~/.claude-voice/config.json (for the gate, the name is \"checker\").")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
