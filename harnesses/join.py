"""Join a session of another harness to the voice, or take it off, from that session's folder.

    pointe join <harness> [harness options]      e.g. pointe join opencode [--session ses_...] [--name NAME]
    pointe leave <harness> [harness options]
Each harness's adapter reads its own options (Harness.join); this file only talks to the daemon.
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATE = Path(os.environ.get("CLAUDE_VOICE_STATE", Path.home() / ".claude-voice"))
PORT = os.environ.get("CLAUDE_VOICE_DAEMON_PORT", "7860")


def daemon(path: str, body: dict) -> dict:
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {(STATE / 'token').read_text().strip()}", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read())


def main(argv: list[str], leave: bool = False) -> None:
    import harnesses

    if not argv or argv[0] not in harnesses.names() or argv[0] == "claude-code":
        others = [n for n in harnesses.names() if n != "claude-code"]
        raise SystemExit(f"usage: pointe {'leave' if leave else 'join'} {'|'.join(others)} [options]  "
                         f"(Claude Code sessions use /pointe:voice and /pointe:leave)")
    harness = harnesses.get(argv[0])
    body = harness.join(argv[1:])
    if not body:  # the adapter did something else (installed a command): nothing to send
        return
    if leave:
        try:
            daemon("/voice/disconnect", {"id": body["id"]})
            print(f"{harness.label} session {body['id']} left the voice.")
        except urllib.error.HTTPError:
            print("That session was not on the voice.")
        return
    subprocess.run([str(ROOT / "bin" / "voice-daemon"), "ensure"], check=True, capture_output=True)
    joined = daemon("/voice/register", {**body, "harness": harness.name})
    print(f"{harness.label} session \"{body.get('harness_data', {}).get('title') or body['id']}\" is on the voice as {joined['name']}.")


if __name__ == "__main__":
    main(sys.argv[1:])
