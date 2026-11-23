"""`pointe node`: pair this machine with a hub, show the link, leave. The running node is node.py.

    node_cli.py join '<invite>' [--name NAME]   pair with a hub (preflight, certificate pin, then the invite code)
    node_cli.py status                          the hub, the link, sessions here, the key fingerprint
    node_cli.py leave                           forget the hub
"""

import argparse
import asyncio
import hashlib
import hmac
import json
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

import aiohttp

import guards
from node import (DAEMON_HERE, PORT, ROOT, STATE, _daemon_here, _netloc, _os, _read_json, _version, _write_private,
                  forget, nodelink, pairing)

def peer_fingerprint(host: str, port: int, timeout: float = 10) -> str:
    """The SHA-256 of the certificate the listener presents, read with verification off: the pin is the check."""
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw, \
            context.wrap_socket(raw, server_hostname=host if not _is_address(host) else None) as tls:
        return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()


def _is_address(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _local(path: str, port: int, state: Path, body: dict | None = None) -> dict | None:
    """A call to the node running on this machine, or None when none answers."""
    try:
        token = (state / "token").read_text().strip()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", method="POST" if body is not None else "GET",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(request, timeout=5).read())
    except (OSError, ValueError):
        return None


def can_tell_who_listens() -> bool:
    """The permission hook releases a prompt only to our own process on the port: it needs lsof, ss or /proc to know."""
    return bool(shutil.which("lsof") or shutil.which("ss") or Path("/proc/net/tcp").exists())


def join(invite: str, name: str | None, state: Path = STATE, port: int = PORT, start: bool = True) -> None:
    if pairing(state) or (state / "node.json").exists():
        hub = (_read_json(state / "node.json").get("hub") or {}).get("name") or "a hub"
        raise SystemExit(f"this machine is paired with {hub}: leave {hub} first: pointe node leave")
    invited = nodelink.parse_invite(invite)
    if not can_tell_who_listens():
        raise SystemExit("install lsof or iproute2 (ss): the permission hook needs one to check that the answer comes "
                         "from this machine's node")
    if not shutil.which("ps"):  # how a session's process is checked (harnesses/claude_code.py): slim images lack it
        raise SystemExit("install procps (ps): the node checks that each session's process still runs")
    if start and not (shutil.which("uv") or (Path.home() / ".local/bin/uv").exists()):
        raise SystemExit("uv is missing. Install it: https://docs.astral.sh/uv/")
    if _daemon_here(port):
        raise SystemExit(DAEMON_HERE.format(port=port))
    try:
        seen = peer_fingerprint(invited["host"], invited["port"])
    except OSError as e:
        raise SystemExit(f"cannot reach the hub at {invited['host']}:{invited['port']} ({type(e).__name__}). It must "
                         f"be on the same private network (Tailscale, Twingate, the LAN)")
    if not hmac.compare_digest(seen, invited["fp"]):
        raise SystemExit("the hub's certificate is not the one in the invite. If the hub re-paired or rotated its "
                         "certificate (pointe pair rotate), ask for a new invite.")
    name = name or socket.gethostname().split(".")[0].lower()
    body = {"code": invited["code"], "name": name, "os": _os(), "arch": platform.machine(), "version": _version()}
    got = _checked(asyncio.run(_pair_request(invited, body)), name)
    name = got["name"]  # the hub's invite may have named this machine: that is the name it knows
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    hub = got["hub"]
    _write_private(state / "node_keys" / str(hub["id"]), got["node_key"])
    _write_private(state / "node.json", json.dumps({
        "id": got["node_id"], "name": name,
        "hub": {"id": hub["id"], "name": hub["name"], "host": invited["host"], "port": invited["port"],
                "fp": invited["fp"]}}) + "\n")  # one line: bin/voice-node and bin/voice-open read it with sed
    vendors = ", ".join(got.get("vendors") or []) or "none (fully local)"
    if start:
        subprocess.run([str(ROOT / "bin" / "voice-node"), "ensure"], check=False)
    print(f"Paired with {hub['name']} as {name} (key {nodelink.fingerprint(got['node_key'])}). Sessions you join here "
          f"reach its voice: /pointe:voice in Claude Code, pointe join opencode|codex in a folder. Their transcripts "
          f"(credentials masked) go to {hub['name']} and its vendors: {vendors}.")


async def _pair_request(invited: dict, body: dict) -> dict:
    url = f"https://{_netloc(invited['host'], invited['port'])}{nodelink.PAIR_PATH}"
    try:
        async with aiohttp.ClientSession() as http, http.post(
                url, json=body, ssl=aiohttp.Fingerprint(bytes.fromhex(invited["fp"])),
                timeout=aiohttp.ClientTimeout(total=20)) as response:
            text = await response.text()
            if response.status != 200:
                raise SystemExit(f"the hub refused: {text.strip() or response.status}")
            got = json.loads(text)
    except aiohttp.ServerFingerprintMismatch:
        raise SystemExit("the hub's certificate is not the one in the invite. If the hub re-paired or rotated its "
                         "certificate (pointe pair rotate), ask for a new invite.")
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        raise SystemExit(f"pairing failed: {type(e).__name__}")
    return got


_HEX16, _HEX64 = re.compile(r"[0-9a-f]{16}"), re.compile(r"[0-9a-f]{64}")
_HUB_NAME = re.compile(r'[^\x00-\x1f\x7f"\\{}]{1,64}')  # node.json is read with sed by bin/voice-node and bin/voice-open


def _checked(got, name: str) -> dict:
    """The hub's pairing answer, every field in the form the hub mints it (hub_nodes.NodesRegistry), before anything is
    written: the hub id names a file under node_keys/, so a hub that answers "../../.ssh/authorized_keys" must not get
    to write there."""
    if not isinstance(got, dict) or not isinstance(hub := got.get("hub"), dict):
        raise SystemExit("the hub's answer is not a pairing")
    name = got.get("name") or name
    if not (isinstance(hub.get("id"), str) and _HEX16.fullmatch(hub["id"]) and isinstance(hub.get("name"), str)
            and _HUB_NAME.fullmatch(hub["name"]) and isinstance(got.get("node_key"), str)
            and _HEX64.fullmatch(got["node_key"]) and isinstance(got.get("node_id"), str)
            and _HEX16.fullmatch(got["node_id"]) and isinstance(name, str) and guards.valid_name(name)):
        raise SystemExit("the hub's answer is not a pairing")
    return {**got, "name": name}


def status(state: Path = STATE, port: int = PORT) -> None:
    paired = pairing(state)
    if paired is None:
        print("This machine is not paired with a hub. Pair it: pointe node join '<invite from pointe hub invite>'")
        return
    config, key = paired
    hub = config["hub"]
    live = _local("/voice/status", port, state)
    print(f"Node {config.get('name')}, paired with {hub['name']} at {hub['host']}:{hub.get('port')}, "
          f"key {nodelink.fingerprint(key)}")
    if live is None or not live.get("node"):
        print("The node is not running here: bin/voice-node ensure (or /pointe:voice in a session) starts it.")
        return
    link = "up" if live["link"] == "up" else f"down ({live.get('link_error') or 'connecting'})"
    print(f"Link: {link}" + (f", round trip {live['rtt_ms']} ms" if live.get("rtt_ms") is not None else ""))
    print(f"Call on {hub['name']}: {'up' if live.get('connected') else 'not up'}. Remote taps: "
          f"{'only for requests that can be read out' if live.get('remote_taps') == 'readable_only' else 'trusted'}.")
    vendors = ", ".join(live.get("vendors") or []) or "none known yet"
    print(f"Transcripts of sessions here (credentials masked) go to {hub['name']} and its vendors: {vendors}.")
    for s in live.get("sessions") or []:
        print(f"  {s['name']} ({s['harness']}, {s['cwd']})" + ("  waiting on an approval" if s.get("pending") else ""))
    if not live.get("sessions"):
        print("  no sessions here yet: /pointe:voice in Claude Code, pointe join opencode|codex")


def leave(state: Path = STATE, port: int = PORT) -> None:
    config = _read_json(state / "node.json")
    if not config:
        print("This machine is not paired with a hub.")
        return
    hub = (config.get("hub") or {}).get("name") or "the hub"
    told = _local("/voice/node/leave", port, state, {})  # the running node says `bye`, so the hub forgets it too
    forget(state)
    if told is not None:
        subprocess.run([str(ROOT / "bin" / "voice-node"), "stop"], check=False, capture_output=True)
    if told is None:
        why = "The node was not running"
    elif told.get("told_hub") is False:
        why = f"The link to {hub} was down"
    else:
        return print(f"Left {hub}.")
    print(f"Left {hub}. {why}, so {hub} still lists this machine: pointe hub revoke {config.get('name')} there.")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="pointe node",
                                     description="This machine's sessions, on another machine's voice")
    sub = parser.add_subparsers(dest="command", required=True)
    joining = sub.add_parser("join", help="pair with a hub: pointe node join '<invite>'")
    joining.add_argument("invite")
    joining.add_argument("--name")
    joining.add_argument("--no-start", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("status")
    sub.add_parser("leave")
    args = parser.parse_args(argv)
    if args.command == "join":
        try:
            join(args.invite, args.name, start=not args.no_start)
        except ValueError as e:
            raise SystemExit(str(e))
    elif args.command == "status":
        status()
    else:
        leave()


if __name__ == "__main__":
    main(sys.argv[1:])
