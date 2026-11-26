"""A machine somebody invited this voice to (docs/design/people-and-machines.md): adding it from its owner's invite
line, the link this voice dials to it, and what the voice says when that machine refuses a request.

After the handshake (host.challenge, voice.hello, host.welcome) a dialed machine is a node to hub_nodes.Hub: it sends
NODE_FRAMES and this side HUB_FRAMES. So the mirror files, the heartbeat, resume, the names and every screen that
groups sessions by machine are the node link's, unchanged. It is an entry in nodes.json with `dial: {host, port, fp}`.

  pointe machine add '<line>' [--name NAME]   add a machine its owner invited you to
  pointe machine list                         the machines in your voice, and whose each one is
  pointe machine remove <name>                take one out: its sessions leave your voice
"""

import asyncio
import hashlib
import hmac
import json
import os
import re
import ssl
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import aiohttp
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run as a script in isolated mode (-I)
import hub_nodes  # noqa: E402
import nodelink  # noqa: E402
import skew  # noqa: E402
from nodelink import NODE_FRAMES, decode, encode  # noqa: E402

PEOPLE_PROTOCOL = 2  # the first link protocol in which a machine serves a person's voice: a dialed link speaks no older
HANDSHAKE_SECS = 10.0
PAIR_SECS = 20.0
MAX_ANSWER_BYTES = 16 << 10  # a pairing answer is a few hundred bytes; no more is read from a machine not yet trusted
OWN_MACHINE = "This is your own machine: its sessions are already in your voice."
CERTIFICATE_DIFFERS = ("The machine's certificate is not the one in the invite. If its owner paired it again or "
                       "rotated its certificate, ask them for a new invite.")
NOT_A_PAIRING = "The machine's answer is not a pairing. Ask its owner for a new invite."
_ID = re.compile(r"[\w-]{1,64}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_CLOCK = re.compile(r"\d{1,2}:\d{2}")


def _sentence(text: str) -> str:
    text = " ".join(str(text).split())
    return text[:1].upper() + text[1:] + ("" if text.endswith((".", "!", "?")) else ".")


def _label(raw, most: int = 40) -> str:
    """A name a machine gave (its own, its owner's, this person's there), as the daemon cleans a session's."""
    return " ".join(re.sub(r"[^\w ./-]+", " ", raw if isinstance(raw, str) else "").split())[:most].strip(" ./-")


def _netloc(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def own_fingerprint(state_dir: Path) -> str | None:
    """The SHA-256 of this voice's own certificate (the one its invites carry), or None when it has none yet."""
    try:
        pem = (state_dir / "tls" / "cert.pem").read_text()
        return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    except (OSError, ValueError):
        return None


# ---------- what the voice says when a machine refuses a request ----------

def refusal(session: str, machine: str, owner: str, turned_down: dict, clock=time.localtime) -> str:
    """One sentence for a send the machine refused, from `send.result.why`. The daemon says it word for word: a
    refusal is never worded by the model. `turned_down` is hub_nodes.Hub.send's record."""
    why, busy = turned_down.get("why"), turned_down.get("busy") or {}
    if why == "watch":
        whose = f"{owner} lets you" if owner else "You may"
        return f"Not sent. {whose} watch {machine}, not talk to its sessions."
    if why == "busy":
        by, since = _label(busy.get("by")), busy.get("since")
        if nodelink._num(since):
            since = time.strftime("%H:%M", clock(since + (turned_down.get("skew") or 0.0)))
        since = f" from {since}" if isinstance(since, str) and _CLOCK.fullmatch(since) else ""
        whose = f"{by}'s request" if by else "another person's request"
        return f"Not sent. {session} is working on {whose}{since}. Say send it anyway, and it goes."
    if why == "private":
        return f"Not sent. {owner or 'Its owner'} keeps {session} private now."
    if why == "prompt":
        return (f"Not sent. {session} waits on a permission prompt, and only {owner or 'its owner'} can answer it, "
                f"on {machine}.")
    if why == "consent":
        return (f"Not sent. {machine} takes no message that says somebody approved something: an approval comes "
                f"from the person who gives it.")
    return f"Not sent. {machine} refused it."


_ANYWAY = re.compile(r"^\W*(?:(?:ok(?:ay)?|yes|yeah|so|then|please|pointe)\W+)*(?:just\s+)?send\s+(?:it|that|mine)"
                     r"\s+anyway(?:\W+please)?\W*$", re.I)


def anyway_intent(text: str) -> bool:
    """A whole short utterance that pushes a refused request through: "send it anyway"."""
    return bool(_ANYWAY.match(text.strip()))


def skew_notice(name: str, reason, version: str = "") -> str:
    """The machine closed the link with 4426: one line that says which side to update (nodelink.too_old's reason,
    read from the voice's side; nodelink.skew_sentence is the same for the person at the machine)."""
    try:
        got = json.loads(reason) if isinstance(reason, str) else None
    except ValueError:
        got = None
    got = got if isinstance(got, dict) else {}
    how = got.get("how") if isinstance(got.get("how"), str) and len(got["how"]) < 80 else "pointe update"
    if got.get("update") == "host":
        runs = f" ({version})" if version else ""
        return f"{name} runs an older Pointe{runs}. Update it there to see its sessions: {how}"
    return f"{name} runs a newer Pointe than this machine. Update this one to see its sessions: {how}"


# ---------- the socket ----------

class Closed(Exception):
    """The machine closed the link, or it dropped."""


class Dialed:
    """A WebSocket this voice opened to a machine, with what hub_nodes.Hub uses of the one a node opens to it:
    accept, send_text, receive_text (raises once closed), close. `close_code` and `close_reason` are the machine's."""

    def __init__(self, ws: aiohttp.ClientWebSocketResponse, host: str):
        self.ws = ws
        self.client = SimpleNamespace(host=host)  # hub_nodes._peer
        self.close_code: int | None = None
        self.close_reason = ""

    async def accept(self) -> None:
        pass

    async def send_text(self, text: str) -> None:
        await self.ws.send_str(text)

    async def receive_text(self, timeout: float | None = None) -> str:
        while True:
            msg = await self.ws.receive(timeout)
            if msg.type == aiohttp.WSMsgType.TEXT:
                return msg.data
            if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR):
                if msg.type == aiohttp.WSMsgType.CLOSE:
                    self.close_code, self.close_reason = msg.data, str(msg.extra or "")
                elif self.close_code is None:
                    self.close_code = self.ws.close_code
                raise Closed()

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        await self.ws.close(code=code, message=(reason or "").encode()[:nodelink.CLOSE_REASON_BYTES])


# ---------- adding, dialing ----------

class Dialer:
    """One task for each machine this voice dials: connect, prove this person's key, hand the socket to the Hub, and
    after it drops wait and dial again (1, 2, 4 ... 30 s). A machine that removed this person, or one this voice
    forgot, is not dialed again."""

    def __init__(self, hub: hub_nodes.Hub, backoff: Callable[[int], float] = nodelink.backoff):
        self.hub, self.backoff = hub, backoff
        self.tasks: dict[str, asyncio.Task] = {}
        hub.on_forget = self.stop

    def _here(self) -> str:
        return hub_nodes._here(self.hub.state_dir)

    def start(self, node_id: str | None = None) -> None:
        """Dial this machine, or every dialed machine in nodes.json (at daemon start). In the event loop."""
        self.hub.nodes.refresh()
        for paired in list(self.hub.nodes.nodes.values()):
            if (node_id is None or paired["id"] == node_id) and isinstance(paired.get("dial"), dict) \
                    and paired.get("key") and not paired.get("removed") \
                    and (paired["id"] not in self.tasks or self.tasks[paired["id"]].done()):
                self.tasks[paired["id"]] = asyncio.get_running_loop().create_task(self._forever(paired["id"]))

    def stop(self, node_id: str) -> None:
        task = self.tasks.pop(node_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def close(self) -> None:
        tasks, self.tasks = list(self.tasks.values()), {}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _forever(self, node_id: str) -> None:
        attempt = 0
        while True:
            paired = self.hub.nodes.get(node_id)
            if paired is None or not paired.get("key") or paired.get("removed"):
                return
            try:
                linked = await self._once(paired)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(f"dialing {paired['name']} failed")
                linked = False
            attempt = 0 if linked else attempt + 1
            await asyncio.sleep(self.backoff(attempt))

    def _notice(self, paired: dict, line: str) -> None:
        """One line beside the machine while its link cannot come up. The Hub clears it when the machine links."""
        node = self.hub.live.get(paired["id"]) or self.hub._track(paired)
        if node.machine.notice != line:
            logger.warning(f"link to {paired['name']}: {line}")
        node.machine.notice, node.skewed = line, True

    async def _once(self, paired: dict) -> bool:
        """One connection: True if the machine welcomed this voice."""
        dial, name = paired["dial"], paired["name"]
        url = f"wss://{_netloc(dial['host'], int(dial['port']))}{nodelink.HOST_PATH}"
        try:
            # aiohttp checks the certificate's SHA-256 right after the TLS handshake, before the upgrade is written
            async with aiohttp.ClientSession() as http, http.ws_connect(
                    url, ssl=aiohttp.Fingerprint(bytes.fromhex(dial["fp"])), max_msg_size=nodelink.MAX_FRAME_BYTES,
                    autoping=True, timeout=aiohttp.ClientWSTimeout(ws_close=5)) as raw:
                ws = Dialed(raw, str(dial["host"]))
                try:
                    return await self._handshake(ws, paired)
                except (Closed, asyncio.TimeoutError):
                    return False
                finally:
                    self._closed(paired, ws)
        except aiohttp.ServerFingerprintMismatch:
            self._notice(paired, f"{name}'s certificate is not the one in its invite. If its owner paired it again or "
                                 f"rotated its certificate, ask them for a new invite")
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError, ValueError) as e:
            logger.debug(f"link to {name}: cannot reach {dial['host']}: {type(e).__name__}")
        return False

    async def _handshake(self, ws: Dialed, paired: dict) -> bool:
        name = paired["name"]
        challenge = decode(await ws.receive_text(HANDSHAKE_SECS), NODE_FRAMES)
        if challenge is None or challenge["t"] != "host.challenge":
            await ws.close(nodelink.CLOSE_BAD_HELLO, "no challenge")
            return False
        host, version = challenge["host"], hub_nodes._cut(challenge["host"]["version"], 20)
        if host["id"] != paired.get("host_id"):
            self._notice(paired, f"Another machine answers at {paired['dial']['host']}: this is not {name}")
            await ws.close(1000, "not the machine that was added")
            return False
        if nodelink.common(challenge["protocol"], challenge["protocol_min"], mine_min=PEOPLE_PROTOCOL) is None:
            older = challenge["protocol"] < PEOPLE_PROTOCOL
            self.hub._skewed(paired, version, older)
            await ws.close(nodelink.CLOSE_TOO_OLD, nodelink.too_old("host", PEOPLE_PROTOCOL, challenge["protocol"])
                           if older else nodelink.too_old("voice", challenge["protocol_min"], nodelink.PROTOCOL))
            return False
        await ws.send_text(encode(
            "voice.hello", auth=nodelink.answer(paired["key"], challenge["nonce"], host["id"]),
            person=str(paired.get("person") or ""), protocol=nodelink.PROTOCOL, protocol_min=PEOPLE_PROTOCOL,
            features=list(nodelink.FEATURES), voice={"name": self._here()[:nodelink.HELLO_CHARS], "version": skew.version()},
            vendors=[v[:nodelink.HELLO_CHARS] for v in self.hub._vendors()][:nodelink.MAX_FILES]))
        welcome = decode(await ws.receive_text(HANDSHAKE_SECS), NODE_FRAMES)
        if welcome is None or welcome["t"] != "host.welcome":
            return False  # the close code says why (_closed)
        if not PEOPLE_PROTOCOL <= welcome["protocol"] <= nodelink.PROTOCOL:
            older = welcome["protocol"] < PEOPLE_PROTOCOL
            self.hub._skewed(paired, version, older)
            await ws.close(nodelink.CLOSE_TOO_OLD, nodelink.too_old("host" if older else "voice", PEOPLE_PROTOCOL,
                                                                    welcome["protocol"]))
            return False
        self._welcomed(paired, welcome, host)
        # From here the machine is a node to the Hub: its welcome (resume, call state, vendors), then frames.
        await self.hub._linked(ws, str(paired["dial"]["host"]), paired, {
            "now": challenge["now"], "protocol": welcome["protocol"], "protocol_min": welcome["protocol"],
            "features": welcome.get("features", challenge.get("features")), "node": host})
        return True

    def _welcomed(self, paired: dict, welcome: dict, host: dict) -> None:
        """The machine says, at each link, whose it is and what this person may do there: kept, and shown."""
        owner, me, grant = _label(welcome["owner"]), _label(welcome["you"]["name"]), welcome["you"]["grant"]
        self.hub.nodes.update(paired["id"], owner=owner, grant=grant, person_name=me, os=_label(host["os"], 20))
        node = self.hub.live.get(paired["id"]) or self.hub._track(paired)
        node.machine.owner, node.machine.grant, node.machine.me = owner, grant, me
        node.machine.os = _label(host["os"], 20)
        node.skewed = node.skewed or bool(node.machine.notice)  # a line about a link that failed no longer holds

    def _closed(self, paired: dict, ws: Dialed) -> None:
        code = ws.close_code if ws.close_code is not None else ws.ws.close_code
        node = self.hub.live.get(paired["id"])
        if node is None:
            return
        if code == nodelink.CLOSE_UNAUTHORIZED:
            self.hub.removed(node)
        elif code == nodelink.CLOSE_TOO_OLD and ws.close_reason:
            self._notice(paired, skew_notice(paired["name"], ws.close_reason))

    # ---- adding a machine ----

    async def add(self, line, name=None) -> tuple[int, dict | str]:
        """POST /voice/machines/add: (200, {name, owner, grant, vendors}) once paired and dialing, else (status, one
        sentence). The certificate is checked against the invite's before anything is sent, and the name before the
        code is used, so a refused name does not spend the invite."""
        hub = self.hub
        try:
            invited = nodelink.parse_machine_invite(str(line or ""))
        except ValueError as e:
            return 400, _sentence(str(e))
        own = own_fingerprint(hub.state_dir)
        if own is not None and hmac.compare_digest(own, invited["fp"]):
            return 409, OWN_MACHINE
        hub.nodes.refresh()
        dialed = [n for n in hub.nodes.nodes.values() if isinstance(n.get("dial"), dict)]
        same = next((n for n in dialed if n["dial"].get("fp") == invited["fp"]), None) or next(
            (n for n in dialed if (n["dial"].get("host"), n["dial"].get("port")) == (invited["host"], invited["port"])), None)
        if same is not None and same.get("key") and same["dial"].get("fp") == invited["fp"]:
            return 409, (f"{same['name']} is already in your voice. To add it again, remove it first: "
                         f"pointe machine remove {same['name']}")
        wanted = " ".join(str(name or "").split()) or _label(invited["name"])
        if wanted and (problem := hub.name_problem(wanted, replacing=same["id"] if same else "")):
            return 409, f"{_sentence(problem)} Give the machine another name and add it again."
        status, got = await self._pair(invited)
        if status != 200:
            return status, got
        host, person = got["host"], got["person"]
        if host["id"] == hub.nodes.hub_id:
            return 409, OWN_MACHINE
        same = same or next((n for n in hub.nodes.nodes.values() if n.get("host_id") == host["id"]), None)
        if not wanted:  # the invite named no machine: the machine's own name, if it can be used
            wanted = _label(host["name"])
            if not wanted or hub.name_problem(wanted, replacing=same["id"] if same else ""):
                wanted = f"machine {host['id'][:4]}"
        fields = {"name": wanted, "os": _label(host["os"], 20), "key": got["key"], "host_id": host["id"],
                  "dial": {"host": invited["host"], "port": invited["port"], "fp": invited["fp"]},
                  "owner": _label(got["owner"]), "grant": person["grant"], "person": person["id"],
                  "person_name": _label(person["name"]), "disclose": True, "removed": False}
        if same is not None:  # added again (it removed this person, or its certificate changed): the same machine here
            old = hub.live.pop(same["id"], None)
            if old is not None:
                if old.socket is not None:
                    await hub_nodes._close(old.socket, 1000, "added again")
                if hub_nodes.sessions.MACHINES.get(old.name) is old.machine:
                    del hub_nodes.sessions.MACHINES[old.name]
            self.stop(same["id"])
            paired = hub.nodes.update(same["id"], **fields)
        else:
            paired = hub.nodes.add(wanted, fields.pop("os"), **{k: v for k, v in fields.items() if k != "name"})
        hub._track(paired)
        self.start(paired["id"])
        logger.info(f"added {wanted}, {paired['owner'] or 'somebody'}'s machine at {invited['host']} "
                    f"(this voice may {paired['grant']})")
        return 200, {"name": wanted, "owner": paired["owner"], "grant": paired["grant"], "vendors": hub._vendors()}

    async def _pair(self, invited: dict) -> tuple[int, dict | str]:
        """Trade the invite's code for this person's key on that machine."""
        url = f"https://{_netloc(invited['host'], invited['port'])}{nodelink.HOST_PAIR_PATH}"
        body = {"code": invited["code"], "voice": {"name": self._here(), "version": skew.version()},
                "vendors": self.hub._vendors()}
        try:
            async with aiohttp.ClientSession() as http, http.post(
                    url, json=body, ssl=aiohttp.Fingerprint(bytes.fromhex(invited["fp"])),
                    timeout=aiohttp.ClientTimeout(total=PAIR_SECS)) as response:
                raw = await response.content.read(MAX_ANSWER_BYTES)
                if response.status != 200:
                    said = " ".join(raw.decode(errors="replace").split())[:200]
                    return (response.status if 400 <= response.status < 500 else 502,
                            f"The machine refused: {said or response.status}.")
                got = json.loads(raw)
        except aiohttp.ServerFingerprintMismatch:
            return 409, CERTIFICATE_DIFFERS
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as e:
            return 502, (f"Cannot reach the machine at {invited['host']}:{invited['port']} ({type(e).__name__}). It "
                         f"must be on the same private network as this one (Tailscale, Twingate, the LAN).")
        except ValueError:
            return 502, NOT_A_PAIRING
        return (200, got) if _is_pairing(got) else (502, NOT_A_PAIRING)

    # ---- the one-time disclosure ----

    def disclosure(self) -> dict | None:
        """/voice/status `disclosure`: once after a machine is added, which services this voice sends that machine's
        transcripts to, until the person dismisses it."""
        self.hub.nodes.refresh()
        paired = next((n for n in self.hub.nodes.nodes.values() if n.get("disclose") and n.get("dial")), None)
        return {"machine": paired["name"], "vendors": self.hub._vendors()} if paired else None

    def seen(self, name: str) -> bool:
        paired = self.hub.nodes.by_name(str(name))
        if paired is None or not paired.get("dial"):
            return False
        self.hub.nodes.update(paired["id"], disclose=False)
        return True


def _is_pairing(got) -> bool:
    """A machine's pairing answer, every field in the form this voice will use it, before anything is stored."""
    if not isinstance(got, dict):
        return False
    person, host = got.get("person"), got.get("host")
    return (isinstance(person, dict) and isinstance(host, dict) and isinstance(got.get("key"), str)
            and bool(_HEX64.fullmatch(got["key"])) and isinstance(person.get("id"), str)
            and bool(_ID.fullmatch(person["id"])) and isinstance(person.get("name"), str)
            and person.get("grant") in nodelink.GRANTS and isinstance(host.get("id"), str)
            and bool(_ID.fullmatch(host["id"])) and isinstance(host.get("name"), str)
            and isinstance(host.get("os", ""), str) and isinstance(got.get("owner"), str))


def install(app, hub: hub_nodes.Hub) -> Dialer:
    """The route that adds a machine, and the dialer's life with the daemon's. In daemon.py, after hub_nodes.install:
        DIALER = machines.install(app, HUB)"""
    from contextlib import asynccontextmanager

    from fastapi import Request
    from fastapi.responses import PlainTextResponse

    from remote import Remote

    dialer = Dialer(hub)
    hub.host.disclosure = dialer.disclosure

    @app.post("/voice/machines/add")
    async def machine_add(request: Request):
        """{"line": "<invite>", "name"?: "<this voice's name for it>"} adds a machine; {"seen": "<name>"} dismisses
        the line that says where its transcripts go. For the owner only, as the /voice/hub routes."""
        if Remote.on_tls_listener(request.scope) and not request.scope.get("state", {}).get("pointe_phone"):
            return PlainTextResponse("forbidden", status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        if body.get("seen"):
            return {"ok": dialer.seen(body["seen"])}
        status, answer = await dialer.add(body.get("line"), body.get("name"))
        return answer if status == 200 else PlainTextResponse(answer, status_code=status)

    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(_app):
        dialer.start()
        try:
            async with previous(_app):
                yield
        finally:
            await dialer.close()

    app.router.lifespan_context = lifespan
    return dialer


# ---------- the command line: pointe machine ----------

def vendors_line(vendors: list) -> str:
    """Where a machine's transcripts go from this voice, as `pointe node join` says it."""
    return (f"Transcripts of its sessions (credentials masked) go to your voice and its vendors: "
            f"{', '.join(vendors or []) or 'none (fully local)'}.")


def _can(grant: str) -> str:
    return "you can watch its sessions" if grant == "watch" else "you can talk to its sessions"


def main(argv: list[str]) -> None:
    command = argv[0] if argv else "list"
    if command == "add" and len(argv) > 1 and not argv[1].startswith("--"):
        name = argv[argv.index("--name") + 1] if "--name" in argv[:-1] else None
        added = hub_nodes._daemon("POST", "/voice/machines/add", {"line": argv[1], **({"name": name} if name else {})},
                                  timeout=PAIR_SECS + 10)
        whose = f"It is {added['owner']}'s machine, and " if added.get("owner") else "On it, "
        print(f"Added {added['name']}. {whose}{_can(added.get('grant', 'send'))}.")
        print(vendors_line(added.get("vendors") or []))
        hub_nodes._daemon("POST", "/voice/machines/add", {"seen": added["name"]})  # said here: not again on a screen
    elif command in ("list", "ls"):
        machines = hub_nodes._daemon("GET", "/voice/hub/nodes")["nodes"]
        if not machines:
            return print("No machines besides this one. Add one you were invited to: pointe machine add '<line>'. "
                         "Pair one of your own: pointe hub invite")
        for m in machines:
            state = (f"online, {m['rtt_ms']} ms" if m["rtt_ms"] is not None else "online") if m["online"] else \
                f"offline since {time.strftime('%H:%M %b %d', time.localtime(m['since']))}"
            whose = f"{m['owner'] or 'somebody else'}'s, {_can(m.get('grant', ''))}" if "grant" in m else "yours"
            print(f"{m['name']}  {m['os']}  {state}  {m['sessions']} session(s)  {whose}"
                  + (f"\n  {m['notice']}" if m.get("notice") else ""))
    elif command in ("remove", "rm") and len(argv) > 1:
        hub_nodes._daemon("POST", "/voice/hub/revoke", {"name": " ".join(argv[1:])})
        print(f"{' '.join(argv[1:])} is no longer in your voice; its sessions left it.")
    else:
        print(__doc__.split("\n\n")[-1].rstrip())


if __name__ == "__main__":
    main(sys.argv[1:])
