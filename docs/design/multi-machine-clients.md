# Several machines from every client: each machine a full voice, the client holds the list

Status: design; phase 1's iPhone part is built behind a Labs flag (see "As built" at the end) (2026-11). Line numbers are from `main` at `1b6e55b2`. This revises one property
of [multi-machine.md](multi-machine.md) and [people-and-machines.md](people-and-machines.md): a client no longer pairs
with one voice. Everything else in those two documents still holds, and this design reuses their link, pairing and
people machinery.

## The plan, for the owner

**What you'll be able to do.** Your iPhone, Mac app and browser each keep a list of machines: your Mac, `kite` and
`ledger` (the two servers), and Avi's box. Tap one, or say "call kite", and you talk to that machine directly, on its
own keys. Each machine is reached its own way (Twingate, Tailscale, Wi-Fi, a public
address, an SSH tunnel), and the list shows which way and whether it answers. Alerts come from every machine, each
once. From phase 2, any machine you call reaches the others.

**Phases** (working time):
1. **About 1 week.** The phone holds several machines; tap or voice to switch; alerts from all; Avi's box and the
   servers over Twingate.
2. **About 2 weeks.** Your machines link each other; the Mac app and the page get the list; figures on screen only
   for the finance agent.
3. **About 1 week.** Servers see your Mac's sessions; what you heard on one machine is not repeated on another.
4. **About 3 weeks, only if wanted.** A call on Avi's box limited to what Avi shares with you.

**Decided.** Each machine uses its own keys: a call on Avi's box runs on Avi's keys. Notes and history stay per
machine for now. In phase 1 your phone pairs with Avi's box as Avi's own phone does.

**Questions.** Does Avi accept that, or do you need phase 4? After a server reboot, do you unlock its keys over SSH,
or should they open by themselves?

## What changes, and what stays

Before: a client pairs with **one** voice; that voice links the person's other machines (nodes) and shared machines
(people links). If that voice is down, the client reaches nothing.

After: a client pairs with **several** machines. Each runs its own full Pointe voice and works alone. A call goes to
one machine at a time, directly. Orchestration stays: a machine still links other machines, and from phase 2 the
owner's own machines link each other in both directions, so whichever he calls reaches the rest.

What stays exactly as it is:

- The node link and the people link: frames, heartbeat, HMAC over a nonce, mirrors, masking, the host's re-check of
  every approval (`node.recheck`, `guests.HostSide`).
- A link never passes on another machine's sessions (`guests.py:424-435`, `_shared` drops any session with
  `machine` set). This is what keeps several voices from seeing one session twice through each other.
- Pairing by a one-time code, the certificate pinned by its SHA-256 before anything is sent (`Pairing.swift:156-196`,
  `pair.py`, `phone_pairing.py:203-219`), a key per device.
- One call at a time per voice (`daemon.py:12460`, "a call is already up").

The research plan rejected "the client fans out to N brains" because N brains means N conversations. That cost is
real and this design accepts it: conversation, notes and heard markers are per machine (section 4). The owner chose
independence over one shared conversation; phase 3 removes the most visible repeat.

## Words

| Word | Meaning |
|---|---|
| **Machine** | A computer that runs a full Pointe voice the client can call |
| **Pairing** | What a client holds for one machine: its identity, its pinned certificate, this device's key there, and its routes |
| **Route** | One way to reach a machine: a method (Twingate, Tailscale, Wi-Fi, public host, SSH tunnel) and an address |
| **Own machine** | A machine whose Pointe runs as the client's owner (his Mac, his servers) |
| **Shared machine** | Somebody else's machine he may call (Avi's box) |
| **Origin** | Where a session really runs: `<machine id>/<session id there>`. The same on every voice that sees it |

## 1. The client model

### 1.1 A list of pairings

Each pairing is one Keychain item (iPhone and Mac app), generic password, service `io.ballerine.pointe.pairing`,
account = the machine's id, accessible `AfterFirstUnlockThisDeviceOnly` as today (`Pairing.swift:141-149`):

```json
{"id": "a3f9c2…", "name": "kite", "fingerprint": "<64 hex>", "key": "<phone key>",
 "routes": [{"kind": "twingate", "host": "kite.example.internal", "port": 7443}],
 "mine": true, "added": 1795000000}
```

- `id` is the machine's own id (`HUB.nodes.hub_id`), returned by the pairing answer. Two pairings with one id are the
  same machine: a second scan adds its route to the existing pairing instead of a second entry.
- `fingerprint` and `key` are per machine, never per route. Every route ends at the same listener certificate.
- The order of the list, the current machine and per-machine alert mutes are not secret: `UserDefaults`.
- **Migration.** The item an older app saved has no account. At first launch it is read, its `id` taken from the
  first answer of that machine (`/voice/phone/pair` answers it now; an older machine is asked for its status), saved
  under that account, read back, and only then is the old item deleted. A machine that never answers keeps its old
  item and is listed under its host name.

### 1.2 Routes: how each machine is reached

The connection method is a property of each pairing, chosen per machine, with several routes per machine in order.
Pinning and the key do not depend on the route: TLS runs end to end from the client to Pointe's own listener on every
route, and the client compares the leaf certificate's SHA-256 to the pairing's `fingerprint` (`PinnedDelegate`,
`Pairing.swift:174-195`). A route only says where to open the TCP connection.

| Method (`kind`) | Address | Set up on the machine | Client support | How the client tells it is down |
|---|---|---|---|---|
| `twingate` | a resource alias, `kite.example.internal:7443` | `pointe pair host <alias>` + a connector (`docs/phone/twingate.md`) | iPhone, Mac app, page | name not found: "Twingate is off on this phone, or the resource is not yours" |
| `tailscale` | a MagicDNS name or `100.x` address | `pointe pair tailscale` | iPhone, Mac app, page | timeout to a `100.64/10` address: "Tailscale is off on this phone" |
| `wifi` | a private LAN address | `pointe pair wifi` | iPhone, Mac app, page | "not on the same network as kite" (`LocalNetwork.contains`, already used) |
| `host` | any name the user routes himself (another VPN, a hosts entry) | `pointe pair host <name>` | iPhone, Mac app, page | the generic cause from `ConnectionProblem` |
| `public` | a public name or address whose port 7443 passes TLS through untouched | `pointe pair host <name> --public` (new: says the port is on the internet, and that pairing and the pin are what guard it) | iPhone, Mac app, page | as `host` |
| `ssh` | `user@server` (the client's own `~/.ssh/config` and agent decide keys), forwarded to the machine's `127.0.0.1:7443` | nothing: only SSH is open | Mac app and machine-to-machine links (system `ssh -N -L`); **not the iPhone in phase 1** (it would need an SSH library, a new dependency for the owner to approve) | "ssh to server failed" with ssh's own first line |

A front door that ends TLS itself (Cloudflare Tunnel, an HTTPS reverse proxy) shows its own certificate, so the pin
fails and the client refuses it. That stays the browser-only route it is today (`docs/phone/cloudflare.md`). This is
deliberate: the pin is the only thing that makes a route untrusted by design.

**Order and fallback.** A pairing's routes are tried in order: the one that worked last first, then the rest, each
with a 3 s connect limit, until one opens. The pin is checked on every one. A refusal (pin mismatch, 401, 403, 4409)
stops the attempt at once and is shown: it is never "try the next route".

**The machine tells the client its other routes.** The status adds `routes: [{kind, host, port}]` from `remote.json`.
A client connected by any route stores the ones it lacks: they end at the same pinned certificate, so learning them
needs no secret. `pointe pair <method>` on a machine therefore **adds** a route (it keeps the certificate and the
listeners of the others); `pointe pair off` removes all. `remote.json` becomes `{"routes": [{kind, host, listen}]}`;
the old `{host, listen}` reads as one route of kind `host`.

**What the user sees.** Each machine in the list shows its method and state: "kite · Twingate · answering",
"ledger · Twingate · not reachable since 14:02: Twingate is off on this phone", "Mac · Wi-Fi, Tailscale · answering
by Tailscale".

### 1.3 Which machine a call goes to

- **The current machine** is the one of the last call the user started, else the first in the list.
- Every Talk path dials it: the call screen, the Lock Screen and Control Center control, the AirPods press, the Siri
  intent and the widget (`PhoneTalk.swift:67-72`).
- **Fallback, hands-free only.** When the current machine cannot be reached on any route (no answer, not a refusal),
  a Talk from outside the app dials the next **own** machine in the list that answered a status check in the last
  minute, and the screen says "Your Mac did not answer. You are on kite." Never a shared machine, never after a
  refusal. In the app the user picks.
- **The voice names itself** when the client holds more than one pairing: the call's hello adds
  `machines: [{id, name}]` (names only, no keys or addresses; `phone.py:242`), and the greeting starts with the
  machine's name.

### 1.4 Switching

**By tap.** The call screen's title is the machine's name with a chevron; it opens the list. A tap on another machine
hangs up with code 1000 (the call ends at once, no `calllink.GRACE_SECS` hold, `calllink.py:26`) and dials it.

**By voice.** Two meanings, decided in code, never by the model:

| Said | When | Does |
|---|---|---|
| "go to kite", "switch to kite" | this voice links kite and kite has sessions | today's meaning: the active session moves to kite's session, or "which on kite" |
| "call kite", "move the call to kite", "hand me to kite" | the client listed kite in its hello | "Moving you to kite." Then a `{"type": "handoff", "machine": {"id", "name"}}` message on the call socket; the client hangs up with 1000 and dials kite |
| "switch to kite" | this voice does not link kite, the client listed it | the same handoff |
| any of these | the client did not list kite | "This phone is not paired with kite. Add it in Settings, Machines." |

An older client sends no `machines`, so it is never offered a handoff.

### 1.5 When a machine is down

| State | Seen from | The list shows | A tap |
|---|---|---|---|
| answering | the last status check worked | sessions and how many need you | calls it |
| not reachable | every route failed to connect | grey, the route's own cause and since when | the cause, How to fix, "Call kite instead" |
| keys locked | status `key_refused` or a keys problem | "kite cannot use its keys: unlock them on kite" | calls it; the voice says the same |
| no longer paired | 401 or 403 with the key | "kite no longer knows this phone" | pair again |
| certificate changed | pin mismatch | "kite's certificate changed. Pair again only if it was rotated there" | pair again |
| version | the existing version checks (`DaemonLink.swift:133-138`) | "update kite" or "update the app" | |

Polling: the current machine at today's call cadence; the others every 15 s while the app is in front, in parallel,
8 s limit each; Background App Refresh checks all of them (`Alerts.swift:289-295`).

### 1.6 Notifications from every machine

- `AlertCenter` takes the attention of every pairing (`Alerts.swift:199-205` reads one pairing today).
- **One notification per thing, wherever it comes from.** The status adds `origin` to each session and each attention
  item (`daemon.py:11653`, `daemon.py:11719-11758`): `<machine id>/<session id there>`. On the machine that runs the
  session it is its own id and the session's id; on a voice that sees it through a link it is the host's id and
  `harness_data["remote_id"]`. The notification id is the kind, the origin and the request id. Two machines listing
  the same prompt post one notification.
- A notification is withdrawn only when every pairing whose last check worked has dropped it. A failed check
  withdraws nothing, as today ("a failed poll changes nothing", `Alerts.swift:241`).
- **Approve and Deny** go to the pairing whose id is the origin's machine when it answered last, else to the pairing
  that listed it. The machine that runs the session re-checks and takes the first valid verdict
  (`guests.py:1131-1147`); a second answer comes back 409 and the phone says "Already answered".
- Each machine's row has "Alerts from kite: on or off".

### 1.7 Pairing on each client

| Client | Own machine | Shared machine (Avi's box) |
|---|---|---|
| iPhone | Settings, Machines, **Add a machine**: scan the QR of `pointe pair <method>` on that machine (or its page's Settings, Phone) or paste the line. Face ID before a second machine is added (it opens a microphone into more sessions). The first pairing needs none, as today | the same, with the code Avi's machine shows (phase 1); a `pointe://machine?` people line keeps today's meaning: it adds the machine to a voice, not to the phone |
| Mac app | Settings, Machines, **Add a machine**: paste or drop the line; Touch ID. Its own Mac is always the first entry and is not a pairing | the same |
| Page | each machine serves its own page; the list is links (section 1.8) | `pointe pair link` on that machine, opened once in the browser |

From phase 3, a client paired with one own machine adds the others in one tap: that machine asks each machine it
links (a `phone.invite` frame over an own-machine link) for a one-time code and its routes and fingerprint, and the
client redeems the code directly, pinned to that fingerprint.

### 1.8 The Mac app and the page

**The Mac app** reaches its own daemon on loopback only: `DaemonEndpoint.host` is the constant `127.0.0.1`
(`DaemonClient.swift:42-57`) and `MacSession` holds one `DaemonLink(local:)` (`MacShell.swift:33-40`,
`AppModel.swift:98`). That stays: the loopback client keeps refusing any other host. A remote machine uses the
other kind `DaemonLink` already has, `.phone(Pairing)` (`DaemonLink.swift:24-43`), with the pinned delegate and
`/voice/phone`; `Pairing`, `PinnedDelegate` and `PairingFlow` carry no `#if os(iOS)` and build for macOS now. So
`MacSession` holds the local link plus the pairings, and a current one; the menu bar shows the current machine's
name; the switcher is in the menu and the window. With no local daemon and at least one pairing the app runs as a
client only. The `ssh` route is the Mac app's: it starts `/usr/bin/ssh -N -L <free port>:127.0.0.1:7443 <target>`
with the user's own SSH configuration and agent, nothing secret on the command line, and dials the forwarded port.

**The page** stays one machine per origin: `connect-src 'self'` (`guards.py:1121`) and the exact-origin rule
(`remote.py:92`) are protections `SECURITY.md` relies on, and lifting them to let one page talk to many machines is
not worth it. The page gains a Machines menu: the owner's machines this voice knows (its own links' names and
`routes`), each a link to that machine's page. A browser is paired with each machine once, with `pointe pair link`.

## 2. Orchestration among the owner's own machines (phase 2)

Today the owner's Mac could add `kite` as a shared machine (`pointe people invite alon` on kite,
`pointe machine add` on the Mac). It would work, but as a guest: requests stamped "a person invited to this machine",
agents invisible (an agent is private until shared, `agent_routes.py:44`), reports held as "the others'"
(`daemon.py:3220`, `_others_machine` at `daemon.py:3540-3543`). The fix is one more grant.

### 2.1 The `mine` grant

`GRANTS` becomes `("send", "watch", "mine")` (`nodelink.py:34`), offered only to a voice that lists the feature
`mine` (`FEATURES`, `nodelink.py:26`). A `mine` link is the machine's owner reaching it from another of his voices:

| Rule | A person (`send`) | A `mine` link |
|---|---|---|
| Which sessions cross (`guests.py:424-435`) | shared ones | all of this machine's own, private ones and agents included. Never another machine's: no transitivity |
| Tag the agent reads (`guests.py:903-905`, `sessions.SENDER`) | "a person invited to this machine" | none: "[Voice request from the user, relayed by their voice assistant", as a local send |
| Busy refusal (`guests.py:858-888`) | yes | no: it is the same person. `prompt` and `consent` stay |
| Prompts (`guests.py:967-1001`) | after the owner-first time | offered at once; a `mine` link with a call up counts as the owner hearing (`_owner_hears`, `guests.py:346`), so people still wait for it |
| `approve: "off"` (`guests.py:936-938`) | refused | not affected: it is the owner |
| Starting sessions | the people rules | the owner's own start path and default |
| Where listed | People | "Your machines", not in People and not in the trust line |
| On the voice that dialed | reports held, owner tag | reports spoken as for own sessions (`_others_machine` is false), no owner tag |

### 2.2 One invite, both directions

`pointe machines link [--name kite]` on machine A prints a `pointe://machine?…&mine=1` line (a people invite with the
grant `mine`, single use, 10 minutes, as today). On B, `pointe machine add '<line>'` (unchanged command) pins A and
redeems the code, and in the same request sends `back: {routes, fp, code, name}`: a one-time `mine` invite of B's
own. A then pairs with B using that code, pinned to that `fp`. A learns B's fingerprint inside a TLS connection to
its own listener, from a party that just proved the one-time code, so it is as trusted as a scanned QR. Result: one
paste links both machines both ways. When A cannot reach B (B is a laptop behind NAT), A records B as **reverse**:
from phase 3, B opens `/voice/host/reverse` to A, proves its key on A, and then the roles swap on that socket (A is
the voice, B the host). Nothing has to listen on the laptop for the servers.

Server to server: when both servers are on one private network, `pointe machine add '<line>' --via 10.0.0.3` adds
a `wifi`-kind route at that address (the pin, not the name, is checked); else a Twingate route.

### 2.3 One session, reported once

- **Inside one voice** a session arrives once: links do not pass on (`guests.py:427-428`), and a second link to a
  machine id already in the voice is refused (`machines.py:360`).
- **Across voices** the same session is seen by every voice that links its machine. Only the voice with the call
  speaks; voices with no call follow nothing (`daemon.py:4423`). The client dedupes alerts by `origin` (1.6).
- **One person, several voices on a shared machine.** If the owner's Mac and kite both link Avi's box, today they are
  two people there ("alon" and "alon-kite"), so a turn the Mac started is "somebody else's" to kite. A person
  becomes `keys: [{voice, key, added}]` (`guests.py:236-246`): `pointe people invite alon --another-voice` adds a key
  to the existing person. Busy, "the turn you started", owner-first and attribution then treat them as one person.

### 2.4 An approval answered once

The machine that runs the session is the one authority, as today: it holds the hook, offers the prompt to each
eligible link, takes the first valid verdict, and tells every other link `permission.resolved {how: "answered"}`
(`guests.py:1099-1123`). A `mine` link adds no new path, only a new eligible link. When two of the owner's voices both
have a call up, both read the prompt; the first answer wins and the other screen shows "Answered on kite."

### 2.5 Agents across links

An agent is a session with a mirror (`harnesses/agent.py:85-135`); a send goes through its harness on its machine
(`guests.py:905`). A `mine` link sees it. Whether a framework's approvals and unheard-reply alerts cross the link is
not proven: `_agent_unheard` (`daemon.py:11712-11716`) skips another machine's copy. Phase 2 tests it; until then the
owner calls the agent's machine directly.

## 3. A shared machine (Avi's box)

**Decided: each machine uses its own keys.** A call on Avi's box runs on Avi's vendor keys. Avi pays; the owner's
voice is transcribed under Avi's vendor accounts, and those accounts' logs hold what the owner says there. The
sessions' content already reaches Avi's vendors, so session content gains no new exposure. Recorded alternatives:
sending the caller's keys for the call would put vendor keys on the phone (none are there today) and into Avi's
process memory, readable by Avi's account; reaching Avi's box through one of the owner's own machines uses the
owner's keys and exists today (`pointe machine add` on that machine).

**Phase 1: a phone pairing that Avi grants.** Avi shows the phone code of his machine (`pointe pair host <alias>`,
or his page's Settings, Phone) and the owner's phone pairs with it like any machine, with `mine: false`. Under
today's rule that phone **acts as Avi's owner on that voice** (`docs/linux.md`, "A phone or a browser paired with a
voice acts as its owner"): it sees every session, private ones included, Avi's notes and settings, and its sends are
stamped as Avi's. Under the owner's rule that people with access are legitimate this is usable, but it is Avi's
decision, and the client says so when the pairing is added: "You will act as Avi on avi-box."

**Phase 4: a call scoped to a person.** `pointe people invite alon --phone` makes a phone code bound to the person.
A call with that key is a guest call: the status, `list_sessions`, the brain's context, notes and "what needs me"
cover the sessions shared with that person; sends carry the person's tag and the people refusals; prompts follow the
people rules; the conversation, journal, dictionary, settings, voiceprint, private sessions and Avi's own agents are
out of reach. Avi's daemon still holds one call: Avi's own call takes the line from a guest, who hears "Avi took the
call on avi-box." The daemon's state is global (one `state`, one `REGISTRY` view); threading a person through every
status field, tool and record is the size of this phase, and a leak there is a privacy bug, so it gets its own review.

## 4. State per machine

Each machine's voice keeps its own record. Nothing below is shared between machines in phases 1 and 2.

| What | Where | What the owner sees as a result |
|---|---|---|
| The conversation (what he said, what it answered) | each voice | Calling kite after the Mac, kite does not know what he just told the Mac |
| Session notes (`briefs/<id>.json`) | each voice that followed the session during a call | Two voices' notes on one session can differ in wording; both come from the same transcript |
| Heard markers: reports heard, alerts dismissed, agent replies heard | each voice | kite may report again a turn the Mac already reported. Phone alerts are deduped from phase 1; the spoken repeat goes in phase 3 |
| Recent requests, journal | each voice; the host's journal also notes sends from links | Each machine's record lists what was asked through it |
| Dictionary, voiceprint and voice lock, settings, mode, active session | each voice | Set each machine once; the voice lock needs enrolling on each |
| Night shift, briefings, meetings | the voice that ran them | A briefing covers what that voice reaches |
| Vendor keys | each machine | Entered on each machine; a rotated key is changed on each |
| Approvals record | the machine the session runs on | One record per prompt, whoever answered |

**Phase 3, heard markers only.** A voice that spoke or showed a report of a session on a `mine` link sends
`heard {id, upto}` to that machine, which keeps per session the last offset its owner heard from any of his voices.
Calling that machine later starts from there. Shared notes are a later phase.

## 5. Security

- **Each pairing is pinned and revocable on its own.** One fingerprint and one key per machine. Remove on the client
  deletes that item and tells the machine (`/voice/phone/unpair` for this key, best effort). On the machine, the
  Phones list unpairs one phone (`phone_pairing.py:139`). Machine links: `pointe machine remove`,
  `pointe people remove`, per pair.
- **Keys live on each machine.** The Mac in its Keychain; a Linux server in its login keyring through `secret-tool`
  (`keys.py:13-16`). A server with no desktop needs a Secret Service in the user's session: `gnome-keyring` with a
  password, unlocked after each boot (`pointe unlock`, new: hidden typing, then a restart). An empty-password keyring
  opens by itself but keeps the key in a file anyone with the account's files can read: not the default. No vendor key
  is on a phone or crosses a link or a route.
- **Agents stay on loopback.** An agent's address is `http://127.0.0.1:<port>` (plain http is allowed only to this
  machine or a private network, `agents.py:135-145`). Pointe's listener is on `127.0.0.1:7443` for a `host` route
  (`pair.py:5`), reached through the Twingate connector on the host network. Only SSH is public. A Docker port
  published as `-p 18789:18789` binds every address and passes around `ufw`: publish it as `127.0.0.1:18789:18789`.
- **The route is not trusted.** Every method ends in the same pinned TLS and the same key. A route that ends TLS on
  the way is refused. An SSH tunnel's keys are the user's own SSH keys, managed by `ssh`.
- **A lost phone.** It holds a key for each paired machine, after first unlock. With the phone unlocked and its
  Twingate signed in, the finder can call each machine, send to its sessions (commands run as that machine's
  account; sessions Pointe starts skip prompts by default), approve prompts by tap, and talk to its agents, the
  finance agent included. No vendor key is on the phone. The fastest stop is **removing the device in Twingate's
  admin console**: every Twingate route closes at once. Then unpair the phone on each machine; from phase 2, one
  command on any own machine does it for all of them over the `mine` links (`phones.unpair`). New in phase 1: with
  more than one machine paired, the app asks for Face ID when it opens (on by default, a setting).
- **The finance agent.** What the owner says reaches the speech-to-text vendor; the agent's replies reach the brain
  and the reader; what is spoken reaches the voice vendor. Hermes's own model provider already sees everything.
  Phase 2 adds **figures on screen only** per agent (`pointe agent set hermes --figures screen`): amounts, account
  and card numbers in its replies are masked before the reader, the brain and the voice get them, and also before the
  mirror leaves the machine on a link; the voice says "Hermes answered; the figures are on your screen", and the
  screen shows the reply as the agent wrote it, sent only over the pinned TLS to the client. What he says aloud still
  reaches speech-to-text.

## 6. What changes in code

Sizes: S under a day, M one to three days, L three to seven, XL more.

| # | Change | Where | Size | Phase |
|---|---|---|---|---|
| 1 | The pairing answer names the machine: `id`, `name`; the status adds `id` on its own entry and `host_id` on each linked one | `phone_pairing.py:219`, `daemon.py:1459-1470` | S | 1 |
| 2 | `origin` on each session and attention item | `daemon.py:11653`, `daemon.py:11719-11758`, `alerts.py:48` | S | 1 |
| 3 | The call's hello lists the client's machines; the greeting names the machine; `handoff` intent and message | `phone.py:242`, `guards.py:306` (beside `switch_intent`), daemon call loop | M | 1 |
| 4 | Pairing list: `Pairing` gains `id`, `name`, `routes`, `mine`; one Keychain item per machine; migration | `Pairing.swift:6-60`, `Pairing.swift:129-154` | M | 1 |
| 5 | Adding instead of replacing; Face ID for a second machine; the route learnt from a scan | `PairingFlow.swift:18-37` and the flow's single `pairing` | M | 1 |
| 6 | Machines list and switcher; the call follows the current machine; the down states | `PointeRoot.swift:46-60`, new `Machines.swift` | L | 1 |
| 7 | Talk paths dial the current machine, fallback to an own machine | `PhoneTalk.swift:20-72`, `PhoneTalk.swift:245-257` | M | 1 |
| 8 | Alerts from every pairing, deduped by origin, actions routed to the origin | `Alerts.swift:199-205`, `Alerts.swift:241-260`, `Alerts.swift:289-295`, `AlertPlan` | M | 1 |
| 9 | Routes on the machine: `pointe pair <method>` adds a route; status `routes`; `--public` | `pair.py:186-200`, `remote.py` listeners | M | 1 |
| 10 | Route order and fallback in the client; per-route cause | `DaemonLink.swift:53-58`, `ConnectionProblem.swift` | M | 1 |
| 11 | Linux start at boot and key unlock: `pointe service install`, `pointe unlock` | new `pointe/service.py`, `bin/pointe` | S | 1 |
| 12 | The `mine` grant | `nodelink.py:26,34,157-158`; `guests.py:346,424-435,858-938,967-1001`; `machines.py:343-380`; `daemon.py:3540-3543` | L | 2 |
| 13 | One invite both ways (`back`), `--via` | `guests.py:568-594`, `machines.py:343` | M | 2 |
| 14 | One person, several voices | `guests.py:236-246`, `guests.py:678-705` | M | 2 |
| 15 | Mac app: local link plus pairings, client-only mode, `ssh` route | `MacShell.swift:33-40`, `AppModel.swift:98`, new route runner in PointeMacKit | L | 2 |
| 16 | Page Machines menu | `ui.html` | S | 2 |
| 17 | Figures on screen only | `agents.py`, `harnesses/agent.py`, `readout.py` | M | 2 |
| 18 | Unpair a phone everywhere | `guests.py` frame, `phone_pairing.py:139` | S | 2 |
| 19 | Agents across `mine` links, proven or fixed | `daemon.py:11712-11716`, `harnesses/agent.py` | M | 2 |
| 20 | Reverse links | `guests.py:661` serve over a dialed socket, `machines.py:199` accept | L | 3 |
| 21 | Heard markers | `guests.py`, `daemon.py` call start | M | 3 |
| 22 | One-tap add of the other own machines | `guests.py`, `PairingFlow.swift` | M | 3 |
| 23 | A call scoped to a person on a shared machine | `daemon.py` throughout, `guests.py`, `phone_pairing.py` | XL | 4 |

## 7. Phases

**Phase 1: the client holds several machines.** Rows 1 to 11. Behind a flag on the iPhone (Settings, Labs,
"Several machines", off) until CI's iPhone UI tests prove the list, switching and an unreachable machine.
- Bar: with the Mac off, the phone calls kite and Avi's box over Twingate, one full spoken call each; a tap and "call
  kite" switch; an approval on each machine arrives as one notification and is answered from it; a machine with
  Twingate off shows "not reachable … Twingate" and the other still calls.
- Tests: `tests/test_machine_identity.py` (the pairing answer and the status carry the id; a node session's `origin`
  is the same on the hub and on the node's own status); `tests/test_handoff.py` ("call kite" with kite listed gives
  the handoff, unlisted gives the sentence, "go to kite" with kite linked keeps today's switch); `tests/test_routes.py`
  (adding a route keeps the certificate and the other listeners; an old `remote.json` reads as one route; `--public`
  says so; status `routes`); `tests/test_service.py` (the unit has no key in its environment). PointeKit unit tests:
  `PairingStoreTests` (two items, the legacy item migrated only after the new one reads back, removing one keeps the
  other), `RouteTests` (order, last-good first, a pin refusal never tries the next route, fallback only to own
  machines), `AlertMergeTests` (one origin from two pairings posts once; a failed check withdraws nothing; Approve
  goes to the origin's pairing). CI `ui` workflow: `MachinesUITests` with two demo machines and one unreachable.
- Test path per method: `wifi` and `host` in CI with two daemons on loopback addresses; `public` in CI through a
  TCP pass-through proxy (the pin holds) and through a TLS-ending proxy (the client refuses); `ssh` in CI against
  `sshd` in the Linux Docker image (`tests/e2e/linux_node/`); `tailscale` and `twingate` on the real-hardware
  checklist (`tailscale ping`; the Twingate check in `docs/phone/twingate.md`), with the cause words unit-tested.

**Phase 2: the owner's machines link each other.** Rows 12 to 19.
- Bar: on a call with the Mac, "ask openclaw on kite…" and "what needs me" cover kite and ledger; a ledger prompt
  approved by voice on the Mac passes ledger's re-check and its card leaves every client; Hermes's figures never
  reach a vendor.
- Tests: `tests/test_mine_grant.py` (one test per row of the table in 2.1); `tests/test_link_both_ways.py` (one code
  makes two entries; the back code is single use; a back fingerprint without the code is refused);
  `tests/test_person_voices.py`; `tests/test_agent_figures.py` (a synthetic reply's amounts are masked in the feed and
  the mirror, intact in the status); `tests/e2e/three_voices.py` (three daemons on one Mac, each linking the others:
  no session twice in any status, a report spoken once in the calling voice's journal, one verdict per prompt).

**Phase 3: polish.** Rows 20 to 22. Bar: kite reports the Mac's sessions with nothing listening on the Mac; a report
heard on the Mac is not repeated when calling kite; one tap adds ledger to a phone that has kite.

**Phase 4: a person-scoped call.** Row 23, only if the owner still wants it after phase 2. Bar: a guest call on a
fixture with private sessions shows none of them in any field of the status, any tool result or the brain's input
(a test walks every key).

Order: 1, then 2, then 3. The server rollout (section 8) runs alongside phase 1.

## 8. Rollout: two Linux servers over Twingate

The servers here are `kite` (OpenClaw) and `ledger` (Hermes Agent, a finance agent); only SSH is open on them. The
owner keeps his own copy with the real names and addresses outside the repository.

**What needs the owner:** the SSH survey (step 0), the Twingate admin console (step 5), typing the keys on each server
(step 3), scanning the codes (step 6), and the two open questions at the top.

0. **Survey, read-only, on each server** (the owner runs it and pastes the output; it prints no secret):

   ```
   id; uname -sr; . /etc/os-release; echo "$PRETTY_NAME"; loginctl show-user "$USER" -p Linger
   ss -ltnp
   docker ps --format '{{.Names}}  {{.Ports}}' 2>/dev/null
   systemctl list-units --type=service --no-pager | grep -i -e openclaw -e hermes
   command -v secret-tool gnome-keyring-daemon tmux uv docker lsof ss
   sudo ufw status 2>/dev/null
   ```

   It answers: which account runs the agent (Pointe runs as that one), the agent's port and whether it listens on
   `127.0.0.1` only, and whether Docker published a port on every address. The Hetzner Cloud Firewall is checked in
   its console: inbound TCP 22 only.
1. **Packages and linger:** `sudo apt install curl tmux libsecret-tools gnome-keyring dbus-user-session` and
   `sudo loginctl enable-linger "$USER"`.
2. **Pointe as a voice:** `curl -fsSLO https://eng.ballerine.com/pointe/install.sh && bash install.sh --hub`.
3. **Keys:** `pointe unlock` (sets the keyring password the first time, hidden), then `pointe setup`, which asks for
   the vendor keys with hidden typing into the keyring. Until `pointe unlock` ships, the same by hand in the SSH
   session: `export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`, then
   `read -rs P; printf %s "$P" | gnome-keyring-daemon --unlock --components=secrets; unset P`.
4. **The agent:** `POINTE_AGENTS=on pointe restart`, then on kite
   `pointe agent add openclaw http://127.0.0.1:18789 --name openclaw`, on ledger
   `pointe agent add hermes http://127.0.0.1:8642 --name hermes` (the port from the survey); each asks for the
   agent's token, hidden.
5. **Twingate, per server** (`docs/phone/twingate.md`, steps 3 and 4): its own Remote Network named after it, a Docker
   connector started with Pointe's `voice-connector` helper (paste the console's command over SSH, then Ctrl-D; it
   runs with `--network host`), a resource at `127.0.0.1`, TCP 7443 only, alias `kite.<network>.internal`, access for
   a group with only the owner. One Remote Network per server: two connectors in one network share its resources,
   and `127.0.0.1` would land on either server.
6. **Pair:** `pointe pair host kite.<network>.internal` prints a QR; in the app, Settings, Machines, Add a machine.
7. **At boot:** `pointe service install` (a user unit, with `POINTE_AGENTS=on` and no key). After a reboot, `pointe
   unlock` over SSH; until then the phone shows "kite cannot use its keys".
8. **Check:** `pointe doctor` on the server (its Phone section checks the route); on the phone, with Twingate on,
   `https://kite.<network>.internal:7443/voice/status` in Safari; a call; "ask openclaw what is on my calendar
   tomorrow"; on ledger a Hermes question; `sudo reboot`, `pointe unlock`, call again.
9. **Phase 2, linking:** `pointe machines link` on kite, `pointe machine add '<line>'` on the Mac and on ledger
   (`--via <private address>` when the servers share a Hetzner network).

Avi's box follows steps 5 and 6 on Avi's side with Avi's keys: Avi shows the phone code, the owner scans it.

## 9. Decisions and open questions

Decided:

- The client pairs with several machines; each is a full voice; the owner's own machines link each other (owner,
  2026-11-27).
- Each machine uses its own keys; a call on Avi's box runs on Avi's keys (owner).
- The connection method is per machine and pluggable; pin and key are the same on every route (owner).
- Phase 1 reaches a shared machine with a phone pairing its owner grants, acting as that owner; a person-scoped call
  is phase 4. Taken because a person key authenticates a voice link, not a call, and scoping a call is the largest
  item here.
- Notes, history and heard markers stay per machine; heard markers sync in phase 3; shared notes later.
- Hands-free fallback goes only to the owner's own machines and never after a refusal.
- An SSH route is not on the iPhone in phase 1: it needs an SSH library, a new dependency.
- Server keys: a password-locked keyring, unlocked over SSH after a reboot.

Open:

1. Is a phase 1 phone pairing on Avi's box, acting as Avi there, acceptable to Avi, or is phase 4 needed first?
2. Server keys after a reboot: unlock over SSH (default), or a keyring that opens by itself?
3. Figures on screen only for Hermes: on by default for that agent?

## As built: phase 1

- **Routes:** the line names its route (`via=tailscale|wifi|host`), the pairing keeps it, and the list shows it. One
  route per machine for now: pairing the same machine again replaces its route. The machine still keeps one route in
  `remote.json` (now with its `kind`); `routes` in the status, `--public` and the `ssh` route are not built.
- **iPhone:** one Keychain item per machine (account `id:<machine id>`, else `fp:<fingerprint>`), the older
  account-less item replaced once its machine is saved again; the bar over the call, the list with each machine's
  route and state (checked every 15 s), tap to move the call, Remove, Face ID to add a second machine.
- **By voice:** `handoff.py`; the hello's `machines`, the `handoff` message, and the same words typed.
- **Alerts:** `origin` on each session and alert; merged by it on the phone; an action goes to the machine that runs
  the session, and another machine's own "Approve from notifications" setting decides whether its alerts carry Approve.
- **Not yet:** the hands-free fallback to another machine, Face ID when the app opens with several machines, the Mac
  app's list, the page's menu, `pointe service install` and `pointe unlock` on Linux.

