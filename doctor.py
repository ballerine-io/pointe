"""pointe doctor: first whether Pointe is ready and the one fix, then which vendor fills each role, why, and what to do
about what is missing. `--preflight` runs before the daemon starts: a missing key, or a key its vendor refuses, is said
in words there, and the tab never opens on a call that cannot hear."""

import asyncio
import contextlib
import io
import json
import os
import shutil
import socket
import sys
import textwrap
import urllib.request
from pathlib import Path

import no_telemetry  # noqa: F401  (before anything imports onnxruntime)
import childenv
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


def advice(present: set[str], used: set[str], setup=None) -> list[str]:
    """What this setup measured, and the one key that would improve it most. With a setup chosen, Pointe uses exactly
    its vendors, so a key alone changes nothing: the advice names the setup that would use it."""
    if not present & TEXT_VENDORS and not present & AUDIO_VENDORS:
        return ["Start with one Gemini key: the cheapest single key, and its ears and brain score above OpenAI's."]
    if not present & TEXT_VENDORS:
        return ["Add an Anthropic key: it runs the brain and the reader, the parts that decide and report."]
    if not present & AUDIO_VENDORS:
        return ["Add a Soniox key: it hears you and speaks, and its echo guard lets you use speakers."]
    measured = MEASURED.get(frozenset(used))
    lines = [f"This setup: {measured[0]}. Cost: {measured[1]}." if measured
             else "This setup: not run through the audio suite yet."]
    if setup is not None and setup.id != "full":
        best = setups.BY_ID["full"]
        missing = [v for v in best.keys if v not in present]
        why = next((w for v, w in NEXT_KEY if v in missing or (not missing and v not in setup.keys)), "")
        if not missing:
            return lines + [f"Next: pointe setup full, the {best.name.lower()}: your keys already fill it, and {why}."]
        return lines + [f"Next: the {best.name.lower()} (pointe setup full) needs the "
                        f"{' and the '.join(setups.NAMES[v] for v in missing)} key{'s' if len(missing) > 1 else ''}. With "
                        f"it, {why}. Pointe uses only the {setup.name} setup's keys until you switch."]
    for vendor, why in NEXT_KEY:
        if vendor not in present:
            return lines + [f"Next key: {vendor}. With it, {why}."]
    return lines + ["You have every key of the fastest and most accurate voice setup."]


NAMES = {"anthropic": "Anthropic", "gemini": "Gemini", "openai": "OpenAI", "local": "the local model"}


POINTE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "pointe")
NO_KEY_ABOUT = f"""What do I need?
{textwrap.fill(vendors.WHAT_YOU_NEED, 118)}
{textwrap.fill(vendors.WHY_KEYS, 118)}

Setups (choose one: pointe setup <id>):
{setups.text_table()}"""
NO_KEY_ELSEWHERE = """Without a Keychain (Linux, CI): export GOOGLE_API_KEY=... (or OPENAI_API_KEY, ANTHROPIC_API_KEY, SONIOX_API_KEY,
ELEVENLABS_API_KEY). Or no key at all: `pointe local` runs every model on this Mac, and nothing leaves it
(docs/features/local.md)."""
NO_KEY = f"""No model key yet. {NO_KEY_ABOUT}

  In Claude Code: /pointe:setup compares the vendors and saves each key for you.
  Or yourself:    {POINTE} key gemini
                  opens Google's key page and a Mac window; the key goes straight to your Keychain, never into a file
                  or this chat. Get one at https://aistudio.google.com/apikey

{NO_KEY_ELSEWHERE}"""


def preflight() -> int:
    """Run before the daemon starts: a missing key is reported here, in words, not as a daemon that died."""
    if vendors.local_only() and not local.answering():
        print(f"Fully local mode is on, but the local text model does not answer at "
              f"{vendors.config().get('local_url') or local.url()}. Start it: pointe local start (or run pointe local).")
        return 1
    try:
        resolved = vendors.resolve(os.environ.get("CLAUDE_VOICE_FRONT", "brain"))
        for note in resolved.notes:
            print(note)
        return check_keys(resolved)
    except SystemExit as e:
        present = {v for v in vendors.KEYS if vendors.has(v)}
        chosen = setups.chosen(vendors.config())
        status = vendors.key_status(present, vendors.voice_local(), chosen)
        if not present and chosen is None:
            print(NO_KEY)
        elif status["needed"]:
            print(f"{status['line']}\n  Fix it: pointe key {status['fix']} (opens the key page and a Mac window, and checks the "
                  f"key), or /pointe:setup in Claude Code. The full path: {POINTE}\n\nWhat do I need? "
                  f"{textwrap.fill(vendors.WHAT_YOU_NEED, 100)}\n{textwrap.fill(vendors.WHY_KEYS, 118)}\n"
                  "pointe doctor shows each role.")
        else:
            print(f"{e}\n\npointe doctor shows each role.")
        return 1


def check_keys(resolved) -> int:
    """One tiny live call per key the call will use, at once. Only a refusal stops the start: offline, or a vendor that
    does not answer, may still be a working call. CLAUDE_VOICE_SKIP_KEY_CHECK=1 skips it."""
    if os.environ.get("CLAUDE_VOICE_SKIP_KEY_CHECK") == "1":
        return 0
    from concurrent.futures import ThreadPoolExecutor

    import keys

    roles = (resolved.brain, resolved.reader, resolved.checker, resolved.ears, resolved.mouth)
    used = sorted({c.split(":")[0] for c in roles if c} & set(vendors.KEYS))
    if not used:
        return 0
    with ThreadPoolExecutor(len(used)) as pool:
        results = dict(zip(used, pool.map(keys.check, used)))
    refused = [v for v, (ok, _) in results.items() if ok is False]
    for vendor in refused:
        print(f"{results[vendor][1]}\n  Fix it: pointe key {vendor} (opens {vendor}'s key page and a Mac window, checks the "
              "new key and restarts Pointe), or /pointe:setup in Claude Code.")
    return 1 if refused else 0


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
            up = subprocess.run(["opencode", "service", "status"], capture_output=True, text=True, timeout=5,
                                env=childenv.child_env()).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            up = False
        lines.append(f"  found    OpenCode      join: pointe join opencode, in the session's folder"
                     + ("" if up else " (its service is not running: start opencode first)"))
    if shutil.which("codex"):
        lines.append('  found    Codex         join: start it with codex --remote unix:// -C "$PWD", then pointe join codex in that folder')
    return lines


def install_lines() -> list[str]:
    """Which copies of Pointe are installed (bin/pointe-installs: the Claude Code plugin, the standalone install), which
    one `pointe` and every start use (the newest), and which one the running daemon came from."""
    import subprocess

    root = Path(__file__).resolve().parent
    names = {"plugin": "Claude Code plugin", "standalone": "standalone install"}
    try:
        got = subprocess.run([str(root / "bin" / "pointe-installs"), "list"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        got = ""
    rows = [line.split("\t") for line in got.splitlines() if line.count("\t") == 2]
    lines = [f"  {names[kind]:18} {version:8} {path}" + ("   (the newest: pointe and each start use it)" if not i else "")
             for i, (kind, version, path) in enumerate(rows)]
    if not rows:
        lines.append(f"  none: this copy runs from a folder ({root})")
    try:
        os.kill(int((state_dir() / "daemon.pid").read_text()), 0)
        ran = Path((state_dir() / "daemon.root").read_text().strip()).resolve()
    except (OSError, ValueError):
        return lines
    which = next(((kind, version) for kind, version, path in rows if Path(path).resolve() == ran), None)
    lines.append(f"  running: {f'the {names[which[0]]}, {which[1]}' if which else ran}")
    if rows and Path(rows[0][2]).resolve() != ran:
        lines.append(f"  The {names[rows[0][0]]} is newer ({rows[0][1]}): pointe restart runs it.")
    return lines


def state_dir() -> Path:
    return Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))


def running_status() -> dict | None:
    """/voice/status of the Pointe running on this Mac, by its token, or None when none answers: what the call is
    seeing now (a key refused, a vendor out of quota) that the checks here cannot."""
    port = int(os.environ.get("CLAUDE_VOICE_DAEMON_PORT", "7860"))
    try:
        os.kill(int((state_dir() / "daemon.pid").read_text()), 0)  # this state dir's own daemon or node, nothing else
        token = (state_dir() / "token").read_text().strip()
        request = urllib.request.Request(f"http://127.0.0.1:{port}/voice/status", headers={"Authorization": f"Bearer {token}"})
        got = json.loads(urllib.request.urlopen(request, timeout=3).read())
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def node_lines() -> list[str] | None:
    """On a node (node.json from `pointe node join`): the verdict for a node, which has no models and no keys. None
    elsewhere."""
    try:
        config = json.loads((state_dir() / "node.json").read_text())
    except (OSError, ValueError):
        return None
    hub = config.get("hub") or {}
    if not hub.get("host") or not (state_dir() / "node_keys" / str(hub.get("id"))).exists():
        return None
    name = hub.get("name") or hub["host"]
    live = running_status()
    if live is None or not live.get("node"):
        return [f"Pointe is not running here. This machine is a node of {name}: it needs no keys and no models.",
                "Fix: bin/voice-node ensure (or /pointe:voice in a session here) starts it. Details: pointe node status"]
    if live.get("link") != "up":
        return [f"Pointe is not ready: this node's link to {name} is down ({live.get('link_error') or 'connecting'}).",
                f"Fix: check that {name} is running and reachable at {hub['host']}. Details: pointe node status"]
    taps = "only for requests that can be read out" if live.get("remote_taps") == "readable_only" else "trusted"
    return [f"Pointe is ready as a node of {name}: no keys and no models here; {name}'s call hears these sessions.",
            f"Taps on prompts from {name}: {taps}. Details: pointe node status"]


def _refused(vendor: str) -> bool:
    if os.environ.get("CLAUDE_VOICE_SKIP_KEY_CHECK") == "1":
        return False
    import keys

    return keys.check(vendor)[0] is False


def verdict(problems: int, status: dict, setup, refused: list[str], faults: list[tuple[str, str]] = ()) -> list[str]:
    """The first lines: ready or not, and the one fix. `faults`: (kind, vendor) from vendors.fault, a key that works but
    cannot be used now (out of quota, the vendor failing)."""
    name = f" Setup: {setup.name}." if setup else ""
    if not problems and not status["needed"] and not refused and not faults:
        start = ("/pointe:voice in Claude Code" if shutil.which("claude") else
                 "pointe open, then pointe join codex or pointe join opencode in a session's folder")
        return [f"Pointe is ready.{name} Start a call: {start}."]
    if refused:
        vendor = refused[0]
        return [f"Pointe is not ready: the {NAMES.get(vendor, vendor)} key was refused.",
                f"Fix: pointe key {vendor}   (opens {vendor}'s key page and a Mac window, checks the new key)"]
    if faults:
        kind, vendor = faults[0]
        if kind == "lost":
            return [f"Pointe is not ready: the call's connection to {setups.NAMES.get(vendor, 'a vendor')} dropped; Pointe is "
                    "reconnecting. Check this Mac's network."]
        return ["Pointe is not ready: " + vendors.fault_help(kind, vendor)]
    if status["fix"]:
        vendor = status["fix"]
        where = f" (get one: {keys_where(vendor)})" if keys_where(vendor) else ""
        return [f"Pointe is not ready: it needs {'an' if vendor in ('anthropic', 'openai', 'elevenlabs') else 'a'} "
                f"{setups.NAMES[vendor]} key.", f"Fix: pointe key {vendor}{where}",
                "In Claude Code, /pointe:setup does this for you. Other setups: pointe setup"]
    return ["Pointe is not ready: see the roles below.", "Fix: pointe setup, or /pointe:setup in Claude Code."]


def keys_where(vendor: str) -> str:
    import keys

    return keys.WHERE.get(vendor, "")


def main() -> int:
    if "--preflight" in sys.argv:
        return preflight()
    if (node := node_lines()) is not None:
        print("\n".join(node))
        return 0 if node[0].startswith("Pointe is ready") else 1
    details = io.StringIO()
    with contextlib.redirect_stdout(details):
        problems, status, setup, refused, faults = _details()
    print("\n".join(verdict(problems, status, setup, refused, faults)))
    print("\nDetails:" + details.getvalue().rstrip("\n"))
    return 1 if problems or status["needed"] or refused or faults else 0


def _details() -> tuple:
    live, problems, refused, faults = "--live" in sys.argv, 0, [], []
    print("\nInstalled:")
    print("\n".join(install_lines()))
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
            unused = (f"not used: the {setup.name} setup does not use it" if setup and vendor not in setup.keys
                      + setup.optional else "not used: another key fills its roles")
            print(f"  found    {vendor} ({', '.join(uses) if uses else unused})")
        elif status["keys"][vendor] == "needed":
            print(f"  needed   {vendor} (" + (f"the setup uses it: pointe key {vendor}" if setup else
                                            f"the one key that fills {', '.join(status['empty'])}") + ")")
        elif setup is not None:
            print(f"  optional {vendor} (the {setup.name} setup does not use it)")
        else:
            print(f"  optional {vendor}" + ("" if status["empty"] or vendors.local_only() else " (not needed with your current keys)"))
    if vendors.openai_url():
        import urllib.parse

        print(f"\nOpenAI models come from {urllib.parse.urlsplit(vendors.openai_url()).hostname} (openai_url): text models "
              "only, and the OpenAI key is sent there. Name your deployments: brain, reader and checker as openai:<deployment>.")
    print("\n" + "\n".join(local.status_lines()))
    print("\nRoles:")
    for role, _env, _order in ROLES:
        if role in chosen:
            print(f"  {role:7} {chosen[role]}")
        else:
            problems += 1
            print(f"  {role:7} needs a key" if keyless else f"  {role:7} NOT AVAILABLE: {failed[role]}")
    if problems and keyless:
        print(f"\n{NO_KEY_ABOUT}\n\n{NO_KEY_ELSEWHERE}")  # the fix itself is the verdict's, said once
    if chosen.get("ears") and chosen["ears"] != "soniox" and not vendors.voice_local():
        print("\nUse headphones: on speakers Pointe can hear itself.")
    if vendors.voice_local() and not vendors.local_only():
        text = sorted({NAMES.get(v, v) for v in (chosen[r].split(":")[0] for r in ("brain", "reader", "checker") if r in chosen)})
        print(f"\nThis setup: {vendors.VOICE_LOCAL}. Your voice is heard and spoken on this Mac, and no audio goes to any "
              f"vendor; {' and '.join(text) or 'the text models'} {'gets' if len(text) == 1 else 'get'} text only. {VOICE_LOCAL_MEASURED}. "
              "Back to your vendors: pointe local off.")
    elif vendors.local_only():
        print(f"\nThis setup: fully local, no key read. {LOCAL_MEASURED} Back to vendors: pointe local off.")
    else:
        print("\n" + "\n".join(advice(present, {c.split(":")[0] for c in chosen.values()}, setup)))
    port = int(os.environ.get("CLAUDE_VOICE_DAEMON_PORT", "7860"))
    with socket.socket() as s:
        in_use = s.connect_ex(("127.0.0.1", port)) == 0
    print(f"\nPort {port}: {'in use (Pointe, or another program: pointe status tells which)' if in_use else 'free'}")
    running = running_status() if in_use else None
    if running is not None:  # what the running call sees: a key refused after the start check, a quota that ran out
        if (seen := running.get("key_refused")) and seen.get("vendor"):
            refused.append(seen["vendor"])
        elif (seen := running.get("vendor_fault")) and seen.get("kind") in ("quota", "rate", "down", "lost"):
            faults.append((seen["kind"], seen.get("vendor") or ""))
        print(f"Running Pointe {running.get('version') or ''}".rstrip() + ": "
              + (running.get("problem") or "no problem reported"))
    elif not live and not vendors.local_only() and chosen:
        # Not running: the start's own check, one tiny call per key, so a refused key is not "ready" while the start
        # refuses it. Offline or a vendor not answering stays unknown, as at the start.
        with contextlib.redirect_stdout(io.StringIO()):
            refused += [v for v in sorted({c.split(":")[0] for c in chosen.values()} & set(vendors.KEYS)) if _refused(v)]
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
                    fault = vendors.fault(e)
                    if vendors.refused_key(f"{type(e).__name__} {e}") is not None:
                        refused.append(vendor)
                        why = vendors.refused_help(vendor)
                    elif fault is not None:
                        faults.append((fault[0], vendor))
                        why = vendors.fault_help(fault[0], vendor)
                    else:
                        why = "Check the key and that it can use this model."
                    print(f"  FAILED  {role} {chosen[role]}: {type(e).__name__}. {why}")
    print("\nChange the setup: pointe setup. One role by hand: CLAUDE_VOICE_<ROLE>=vendor:model, or ~/.claude-voice/config.json.")
    return problems, status, setup, refused, faults


if __name__ == "__main__":
    from loguru import logger

    logger.remove()  # pipecat, imported for the local status, logs a banner: this output is for people
    sys.exit(main())
