"""The voice daemon of the agents proof (docs/design/agents.md): daemon.py as it runs, on a throwaway state folder and
ports the run chose, the real brain, reader and checker, and two changes for a run with no microphone. Agents are on
through the saved setting, as the screens turn them on (live.py posts it), not POINTE_AGENTS. bench/agents/live.py
starts it; nothing else should.

    python -I bench/agents/voice.py <port>      CLAUDE_VOICE_STATE, CLAUDE_VOICE_TLS_PORT and POINTE_AGENTS_* set by the run

- Words come in as text. `POST /bench/heard {text}` takes them the way the ears' final transcript does
  (daemon.on_user_utterance, typed=False, then the text frame to the brain): a spoken yes, not a typed one. `/voice/say`
  stays the typed path, which never confirms a read-back.
- Keys: the model keys and the agents' credentials are read from the macOS Keychain by this process alone
  (/usr/bin/security with the real HOME, POINTE_AGENTS_KEY_HOME), and stay in its memory. An agent's credential is read
  from the Keychain item the run names for it (POINTE_AGENTS_SECRETS: name=item,...), so the lab's items are used as
  they are and nothing is written to the Keychain.
- Every model call is written down (POINTE_AGENTS_CALLS) with the vendor's token counts, for the spend.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE_PORTS = {7860, 7443}
STATE = Path(os.environ["CLAUDE_VOICE_STATE"])
CALLS = Path(os.environ.get("POINTE_AGENTS_CALLS") or STATE.parent / "calls.jsonl")
KEY_HOME = os.environ["POINTE_AGENTS_KEY_HOME"]
SECRETS = dict(p.split("=", 1) for p in os.environ.get("POINTE_AGENTS_SECRETS", "").split(",") if "=" in p)
MODEL_ITEMS = {"pointe.anthropic-api-key", "anthropic-api-key", "pointe.gemini-api-key", "gemini-api-key"}


def keychain(item: str) -> str | None:
    got = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", item, "-w"], capture_output=True, text=True,
                         timeout=10, env={"HOME": KEY_HOME, "PATH": "/usr/bin:/bin"})
    return (got.stdout.strip() or None) if got.returncode == 0 else None


def write(row: dict) -> None:
    with CALLS.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def install():
    assert ".claude-voice" not in str(STATE) and str(STATE).startswith(("/tmp/", "/private/tmp/")), "never the live state"
    os.environ.pop("POINTE_AGENTS", None)  # the saved setting decides, as on the owner's Mac
    sys.path[0:0] = [str(ROOT / "pointe"), str(ROOT)]
    import vendors

    assert not (set(os.environ) & vendors.KEY_ENVS - {"GOOGLE_API_KEY"}), "no key in this process's environment"
    os.environ.pop("GOOGLE_API_KEY", None)
    vendors.from_store = lambda name, timeout=5: keychain(name) if name in MODEL_ITEMS else None

    inner_step, inner_text = vendors.step, vendors.text

    async def step(choice, system, messages, tools, heard=None):
        began = time.time()
        result = await inner_step(choice, system, messages, tools, **({"heard": heard} if heard is not None else {}))
        write({"kind": "step", "choice": choice, "began": began, "ended": time.time(), "usage": result.usage,
               "calls": [{"name": c["name"], "args": c["args"]} for c in result.calls], "said": result.said[:600]})
        return result

    async def text(choice, prompt, system=None, *args, **kw):
        began = time.time()
        reply = await inner_text(choice, prompt, system, *args, **kw)
        write({"kind": "text", "choice": choice, "began": began, "ended": time.time(),
               "sent_chars": len(prompt) + len(system or ""), "reply_chars": len(reply or "")})
        return reply

    vendors.step, vendors.text = step, text
    import harnesses.claude_code
    import mac

    harnesses.claude_code.ROSTER = False
    harnesses.claude_code.DEFAULT_HOME = STATE / "claude-home"
    harnesses.claude_code.MANAGED_SETTINGS = STATE / "managed-settings.json"
    mac.SYSTEM = False
    import daemon
    from harnesses import agent as agent_harness

    daemon.COPY_SESSIONS = False
    daemon._call_ears = lambda terms=None: ([], [], None)  # no ears: words come in as text (/bench/heard)
    agent_harness.SECRET = lambda agent: keychain(SECRETS[agent.name]) if agent.name in SECRETS else None

    from fastapi import Request
    from pipecat.frames.frames import InputTextRawFrame

    @daemon.app.post("/bench/heard")
    async def heard(request: Request):
        """Words as the ears' final transcript gives them: spoken, so a yes to a read-back counts."""
        said = str((await request.json()).get("text") or "").strip()
        if not said or daemon.state.conn is None:
            return {"ok": False}
        daemon.state.heard_own_words, daemon.state.last_speaker = False, None
        await daemon.on_user_utterance(said)
        await daemon.state.conn.injector.push_frame(InputTextRawFrame(text=said))
        return {"ok": True}

    return daemon


if __name__ == "__main__":
    port = sys.argv[1]
    assert int(port) not in LIVE_PORTS and int(os.environ["CLAUDE_VOICE_TLS_PORT"]) not in LIVE_PORTS, "never the live daemon"
    daemon = install()
    sys.argv = ["daemon.py", "--port", port]
    daemon.main()
