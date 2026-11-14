# Multi-machine Pointe: one voice over sessions on several machines

Status: design, not built. Line numbers are from `main` at `fbc0ca9`.

## The problem

Pointe today is one daemon on one Mac. A session joins it over loopback (`register-session` posts to
`http://127.0.0.1:7860/voice/register`, `bin/register-session:54-56`), its transcript is a local file the daemon tails
(`sessions.py:515-535`), a request reaches it over a local Unix socket (`sessions.post_inbox`, `sessions.py:454-470`),
and its permission prompts arrive from a local hook (`bin/voice-permission-hook` → `/voice/permission-hook`,
`daemon.py:4054-4068`). Every one of those is machine-local. The owner has sessions on other Macs and on Linux hosts
and VMs (Claude Code, OpenCode, Codex; no audio there), reachable over Tailscale, Twingate or the LAN, and wants one
voice over all of them: orchestrate everything at once, or move between machines and sessions, always knowing which
machine a session is on.

## Goals

- **Connect a machine in one command on each side**, like pairing the phone: an invite on the hub, `pointe node join
  <invite>` on the other machine. After that, `/pointe:voice` and `pointe join opencode|codex` on that machine work
  unchanged.
- **One call over every machine.** Orchestrator mode routes across machines; session mode pins to one session anywhere;
  "go to devbox" and "what's going on everywhere" work by voice.
- **Always clear where a session runs**: in the brain's view, in the voice when it matters, and on the page and in the
  app always.
- **Approvals as strict as today, with a second check on the node.** A hub bug, or a compromised hub, cannot approve
  what the node would not: the node binds the answer to its own copy of the request.
- **No vendor key leaves the hub, and no credential leaves a node** except as masked text.
- **Degrades to today:** a node offline, a hub down, or a link dropping hands prompts back to the terminal, as a hung-up
  call does now (`_hand_prompts_back`, `daemon.py:4047-4051`).

## Non-goals

- A central server, an account, or any relay outside the user's own machines. Nodes dial the hub directly over the
  private network the phone already uses.
- Audio on nodes. A node has no ears, mouth, brain, reader or gate, and no key.
- Two calls at once. One hub holds the call, as today (`socket_call`, `daemon.py:5208-5213`).
- Launch mode (`pointe start`, a Claude Code channel) on a node. Channels must be on the daemon's machine
  (`daemon.py:3986-3987`); on a node, `/pointe:voice` (inbox mode) and `pointe join` only.
- Meeting mode, briefings, the conflict alarm and the voice lock change nothing: they run on the hub over whatever
  sessions it has. Meeting lookups and briefings cover remote sessions through the same notes.
- Windows nodes.

## Shape: a hub and nodes, evaluated

Four shapes were weighed.

| Shape | Verdict |
|---|---|
| **Hub + lightweight nodes** (proposed): the Mac with the call runs the daemon; each other machine runs a small node that owns its sessions and talks to the hub over pinned TLS | **Chosen.** Everything machine-local stays on the machine; the hub keeps every rule it has. |
| Peer daemons, each a full Pointe, borrowing each other's sessions | The same as hub + node, but every node carries Pipecat, the model libraries and vendor keys for nothing. A node never needs a key. |
| The hub reaches into machines over SSH (tail the transcript, write the socket, catch the hook) | The hook must post to something on the session's machine, so the hub would need a long-lived SSH listener there anyway; nothing on the far side can re-check an approval; file tailing over SSH on a dropped link loses lines silently. Rejected. |
| A central relay | Against the product (no server, no account). Rejected. |

One refinement to the proposed shape: **the node is not a cut-down brain, it is a file shipper and a hand.** It ships
the session's transcript to the hub as the hub's own mirror file, delivers sends into the session, and holds and
re-checks permission prompts. The hub reads the mirror with the same follower, reader and brain it uses for local
sessions. This is exactly how OpenCode and Codex already join: their adapters write a mirror transcript in Claude
Code's JSONL shape under `~/.claude-voice/harness/<harness>/` and the ordinary follower reads it
(`harnesses/opencode.py:165-167`, `harnesses/codex.py:210-212`; `docs/harnesses.md`, "Watch"). A remote session is one
more mirror, written from a stream instead of a local service.

Direction of the link: **the node dials the hub.** VMs and Linux hosts are often behind NAT with outbound only; the hub
already has a reachable TLS listener for the phone (`remote.Remote.serve`, `remote.py:99-122`, port 7443 on the
address `pointe pair` chose). The hub never needs to know a node's address. A node that is also sometimes a hub (a
second Mac) is covered under "Two hubs".

## Architecture

```
  hub: the Mac with the call                                   node: another Mac, or a Linux host or VM
  ──────────────────────────                                   ────────────────────────────────────────
  Chrome page ── iPhone app (paired, pinned)                   Claude Code ─ OpenCode ─ Codex (their terminals)
        \          /                                                 |  register, inbox socket, PermissionRequest hook
    daemon.py (brain, ears, mouth, approvals, notes, routing)        |  (bin/* unchanged: they talk to 127.0.0.1:7860)
        │                                                        node.py  (127.0.0.1:7860, same token file, no keys)
        │ harnesses/remote.py: one RemoteHarness per node          │ Registry (sessions.py), harness adapters (watch,
        │   alive/send/side_question/title over the link           │ send, alive, probe), transcript tail, hold+re-check
        │   watch = follow_transcript on the mirror                 │
        │   ~/.claude-voice/harness/remote/<node>/<id>.<gen>.jsonl  │
        │                                                           │
   remote.py TLS listener :7443 ◄───── WebSocket /voice/node ───────┘   node key (Bearer), hub cert pinned by SHA-256
   (shared with the phone)             JSON frames, heartbeat (phone.Heartbeat)
```

What moves where:

| Concern | Today | Multi-machine |
|---|---|---|
| Registration | `/voice/register` on the daemon, `daemon.py:3980-4029` | On a node, the same route on `node.py`; the node announces the session to the hub (`session.joined`). The hub creates a `Session` with `machine` set, through `register_remote()` next to `register()` |
| Transcript | daemon tails the file every 0.3 s (`sessions.py:535`) | node tails it and ships raw JSONL entries; hub appends them to a mirror file; the hub's follower reads the mirror unchanged |
| Send | `harnesses.get(s.harness).send` → inbox socket, `daemon.py:2050-2052` | `RemoteHarness.send` → `send` frame → node runs the real adapter's `send` |
| Permission | hook → `/voice/permission-hook` → `hold_permission` → voice/tap → future (`daemon.py:4054-4129`) | hook → node's `/voice/permission-hook` → node holds the future and forwards the request → hub puts it to the user as a channel request is put today (`_put_permission`, `daemon.py:4142-4166`) → verdict frame → **node re-checks** → future |
| Liveness | pid check / adapter probe every 5 s (`_liveness`, `daemon.py:5014-5024`) | node runs the same loop and reports `session.left`; hub marks a node's sessions offline when the link drops |
| Notes, reports, routing, side answers from the record | read the transcript file | read the mirror: unchanged |
| `claude -p --resume --fork-session` side questions (`harnesses/claude_code.py:86-115`) | on the daemon | on the node, in the session's own account: `side_question` frame |
| Show while it says (`artifacts.render`) | reads files under `cwd` | node renders from its own record of the turn's artifacts (phase 2, below) |
| `git ls-files` for routing hints (`_tracked_files`, `daemon.py:3184-3190`) | run in `cwd` | node sends the first 40 names at join and on each repoint |

### Why not run the node's logic inside `daemon.py`

`daemon.py` is 5,400 lines around Pipecat, vendors and the call. A node is ~600 lines: `Registry` and `post_inbox`
from `sessions.py`, the harness adapters, `LocalAuth` from `guards.py`, `readable_request` and `readout.mask`, a hold
loop with the contract of `_hold_one` (`daemon.py:4104-4129`: a future, `gone()` polled each second, a deadline), and
the link. It imports nothing that loads a model or reads a key. The hub's local sessions keep their current code path;
remote sessions enter through one adapter, `harnesses/remote.py`, so the daemon's call sites change in one way: where
they do `harnesses.get(s.harness)`, they do `harnesses.of(s)`, which returns the wrapped adapter when `s.machine` is
set. `label`, `agent`, `noise`, `capabilities` and `permission_deadline` come from the inner adapter, so the badges,
the feed tags and `brief.for_agent` are untouched.

### Processes on a machine

Every machine runs exactly one thing on `127.0.0.1:7860`: `daemon.py` if it is the hub, `node.py` if it is a node.
Both write `$STATE/token` and `$STATE/daemon.pid`, so `bin/register-session`, `bin/voice-permission-hook`,
`bin/claude-voice-attach` and `harnesses/join.py` work on a node with no change (they check that the pid on the port is
ours, `bin/voice-permission-hook:7-10`). `bin/voice-daemon ensure` gains one branch: if `$STATE/node.json` lists a hub,
it execs `bin/voice-node ensure` instead, so `/pointe:voice` on a node starts the node, not a daemon.
`bin/voice-open` on a node prints "the call is on <hub>" instead of opening a page.

## Protocol

One WebSocket per node per hub, path `/voice/node`, on the hub's TLS listener (and on loopback for tests). Text frames,
one JSON object each: `{"t": "<type>", "seq": n, ...}`. `seq` is per connection and per direction; a frame out of order
closes the link (code 4400). Heartbeat reuses `phone.Heartbeat` (`phone.py:48-70`): a ping every 2 s, dead after 12 s
with no pong, close 4408; the node reconnects with backoff 1, 2, 4 … 30 s. Unknown frame types are ignored both ways,
as in the phone protocol (`phone.py:16-17`), so one side can move first.

Hello carries `protocol: 1`. The hub refuses a node below its minimum with 4426 and a reason the node prints.

### Node to hub

| Frame | Fields | Notes |
|---|---|---|
| `hello` | `protocol, node: {id, name, os, arch, version, harnesses: [names]}, resume: {hub_session_id: {gen, offset}}` | once, first. `resume` echoes what the hub sent in `welcome` so both agree where each mirror stands |
| `sessions` | `[{id, name, name_given, cwd, pid, harness, home, title, capabilities, files: [≤40], pending: permission?}]` | full snapshot, after `welcome` and whenever the set changes. Never `inbox_socket` or `inbox_token`: they stay on the node |
| `session.joined` / `session.left` | `id`; `left` adds `why: exited \| disconnected` | incremental |
| `transcript` | `id, gen, offset, entries: [raw JSONL lines]` | `offset` is the byte offset of the first entry in the node's file; the hub refuses a gap (asks `resume`). Every string field in an entry passed through `readout.mask` on the node |
| `transcript.repointed` | `id, gen` | the session moved to a new file (`/clear`, `/resume`: `claude_code.transcript_path`, `harnesses/claude_code.py:63-76`); the hub opens a new mirror `<id>.<gen>.jsonl` and re-points `session.transcript` |
| `title` | `id, title` | Claude Code's own title, followed as today (`_follow_titles`, `daemon.py:5027-5036`), decided on the hub |
| `files` | `id, names` | routing hints, after a repoint |
| `permission.request` | `id, request_id, tool, description, preview, readable, deadline_ms` | `preview` is `tool_input` JSON after `readout.mask`; `readable` is the node's own `guards.readable_request(tool, tool_input, cwd)` on the **unmasked** input, or null. `deadline_ms` is relative |
| `permission.resolved` | `id, request_id, how: terminal \| timeout \| left \| other_hub` | the prompt is no longer the hub's to answer |
| `permission.answered` | `request_id, ok, why?` | the node's reply to a verdict: `ok` false with `why` when the re-check refused it |
| `send.result` | `req, ok` | |
| `side_question.result` | `req, text?` | |
| `artifact.result` | `req, view?` | phase 2 |
| `pong` | `id` | |

### Hub to node

| Frame | Fields | Notes |
|---|---|---|
| `welcome` | `protocol, hub: {id, name}, lease: bool, call_up: bool, resume: {hub_session_id: {gen, offset}}` | once, after `hello` |
| `call` | `up: bool` | the node forwards prompts only while a call is up; otherwise its hook returns `{}` at once, as the daemon does with no call (`daemon.py:4061-4062`) |
| `lease` | `held: bool, by?: hub name` | see "Two hubs" |
| `send` | `req, id, text` | the text already wrapped as today (`voice_message` is applied on the node, so the `#tag` is fresh) |
| `permission.holding` | `request_id` | the hub has put it to the user. No `holding` within 2 s: the node hands the prompt back to the terminal |
| `permission.answer` | `id, request_id, verdict: allow \| deny, how: voice \| tap \| notification, spoken?` | `spoken` is the exact line the hub read out, for `how: voice` |
| `side_question` | `req, id, question` | |
| `artifact.render` | `req, id, artifact_id` | phase 2 |
| `leave` | `id` | the user took the session off the voice from the page or by voice (`disconnect`, `daemon.py:5054-5063`); the node removes it from its registry (it keeps running in its terminal) and tells the harness (`Harness.leave`) |
| `unpaired` | | the hub revoked this node; the node deletes its key and stops reconnecting |
| `ping` | `id, rtt_ms` | |

### Ids

Hub-side session id: `<node_short>-<session_id>` (`node_short` is 6 hex of the node id; the registry's id pattern
`[\w-]{1,128}` allows it, `daemon.py:3984`), with the real id in `harness_data["remote_id"]`. Everything the hub keys
by session id (notes in `briefs/<id>.json`, `_PERMISSION_LOCKS`, workers) stays unique across machines. The node keys by
the real id, so `pointe leave` and `claude-voice-attach off` there work as now.

## Pairing

Modeled on the phone (`pair.py`): the hub shows a secret once, the node proves it has it, and from then on the node
holds a key and the hub holds only a hash.

### Hub

```
pointe hub invite [tailscale | wifi | host <name>]    # default: the reachability already set by `pointe pair`
```

Prints one line and a QR code (for a Mac node you can scan it with the phone to copy it; on Linux you paste the line):

```
pointe://hub?v=1&host=studio.tail1234.ts.net&port=7443&fp=3b1c…&code=K7PQ-2MXD
```

- `host`, `port` and `fp` are what the phone's pairing link already carries (`pair.pairing_link`, `pair.py:133-137`).
  If `pointe pair` has not run, `invite` runs `pair.setup` for the chosen reachability first and says the daemon must
  restart once for the listener.
- `code` is 8 characters from a 32-letter alphabet (about 40 bits), single use, valid 10 minutes. The daemon keeps a
  SHA-256 of it in memory (`POST /voice/hub/invite`, token-protected, from the CLI), never on disk. The pair route
  answers at most 5 attempts a minute and only while an invite is outstanding. The attacker also has to be on the
  private network the listener is on.
- `--name <node name>` is optional; the node proposes its own.

While the invite is open the page shows "Waiting for <code> to be used … (9:40 left)" in Settings → Machines, and the
daemon says "<name> joined from <os>" when it is.

### Node

```
pointe node join 'pointe://hub?…'   [--name devbox]
```

1. Parses the invite. Connects to `host:port` with TLS verification turned off and compares the server certificate's
   DER SHA-256 to `fp`; anything else is refused before a byte is sent. This is the phone's check, so the hub's
   certificate dates and issuer play no part, and clock skew cannot break it.
2. `POST /voice/node/pair {code, name, os, arch, version}` → `{node_id, node_key, hub: {id, name}}`. The hub refuses a
   name that is taken (it suggests `-2`), or that `sessions.speakable` would refuse (a node called `dev` or `main` could
   never be picked by voice: `sessions.py:214, 231`).
3. Writes `$STATE/node.json` (`{name, hubs: [{id, name, host, port, fp}]}`) and `$STATE/node_keys/<hub id>` (0600) and
   starts `bin/voice-node ensure`. Prints: "Paired with studio. Sessions you join here reach its voice:
   /pointe:voice in Claude Code, pointe join opencode|codex in a folder."

On the hub, `$STATE/nodes.json` gets `{id, name, os, key_sha256, paired_at}`. The key itself is never on the hub's
disk, so a copied hub state dir cannot pose as a node.

### Everyday commands

| Where | Command | Does |
|---|---|---|
| hub | `pointe hub nodes` | each node: name, os, online or offline since, sessions, round trip |
| hub | `pointe hub revoke <name>` | deletes the entry; the link is closed with `unpaired`; its sessions go to `departed` |
| hub | `pointe hub invite …` | as above |
| node | `pointe node status` | hubs, which has the lease, link state, sessions here |
| node | `pointe node leave [<hub>]` | deletes the key, sends a best-effort `bye {unpair: true}` so the hub forgets it too |
| node | `pointe node join …` | pair with another hub as well |

Revocation from either side works offline: a revoked node that reconnects gets 4401 and deletes its key; a node that
left while the hub was down is dropped by the hub when it never comes back (its entry is listed as offline until
`pointe hub revoke`).

### Where the node's key lives on Linux

In `~/.claude-voice/node_keys/<hub id>`, 0600, inside the 0700 state dir. This is what Pointe already does for its own
secrets on the Mac too: the daemon token, the page key and the phone key are 0600 files, not Keychain items
(SECURITY.md, "Files"; `phone.phone_key`, `phone.py:105-112`). The Keychain holds vendor keys, and a node has none. The
threat this leaves is the same as today's "code running as you is trusted" (SECURITY.md, "Known limits"): another user
on a shared Linux box cannot read it; root, or a process running as you, can. The node has no vendor key, voiceprint,
journal or notes, so what the file protects is the ability to offer sessions to the hub and receive its sends.

## Security model

### What crosses the link

| Node → hub | Hub → node | Never crosses |
|---|---|---|
| transcript entries, every string through `readout.mask` | the user's requests (sends), which can quote hub-side conversation | vendor keys (none on a node), voiceprints, the journal, session notes (`briefs/`), the dictionary |
| names, `cwd` as a string, pid, harness, title, up to 40 tracked file names | permission verdicts, bound to a request id | page key, phone key, inbox sockets and tokens (stay on the node) |
| permission requests: masked preview + the node's read-out form | side questions, which can quote the conversation | the brain's context |
| side-question answers (produced on the node by that session's own account) | artifact ids to render (phase 2) | |

The hub treats a mirror as it treats a local transcript: 0700 state dir, sent to the reader and brain vendors under the
hub's keys. So **a node's session content reaches whatever vendors the hub uses.** `pointe node join` prints that
sentence; `pointe node status` names the hub's vendors (the hub sends them in `welcome`), the same list
`bin/voice-doctor` shows. A hub in fully local mode (`pointe local`) sends it to no vendor. The masking on the node is
defense in depth: it costs the reader a value it would never need, and a hub bug or a hub-side vendor leak cannot expose a
token that sat in a remote session's shell output.

### Approvals: the node's second check

The hub side keeps every rule in `SECURITY.md`: the read-out is built from what will run (`readable_request`,
`guards.py:95-116`), only a bound yes right after it approves (`_answer_permission`, `daemon.py:2897-2961`), a tap
approves the pending request id (`approve`, `daemon.py:4267-4283`), notification approvals need `alerts.approvable`
(`daemon.py:4279-4280`). The node adds a check the hub cannot bypass, in `node.py`, with its own tests:

| Verdict arrives with | Node releases the hook only if |
|---|---|
| any `request_id` | it equals the one request the node holds for that session right now. Else `permission.answered {ok: false, why: stale}`. The hub says "the answer did not reach it", as it does today on a failed delivery (`_apply_answer`, `daemon.py:2967-2971`) |
| `verdict: deny` | always. A no from anywhere denies |
| `how: voice`, `verdict: allow` | the node's own `readable` for this request is non-empty **and** `spoken == readable` byte for byte. The node computed `readable` from the unmasked input before the request left; a hub that read out anything else, or a request the node itself judged unreadable, cannot be approved by voice |
| `how: notification`, `verdict: allow` | the node's `readable` is non-empty (the rule `alerts.approvable` enforces on the hub, re-enforced here) |
| `how: tap`, `verdict: allow` | the id check, and the hub holds the lease. The node cannot see Face ID; the tap's binding is the id, as on the hub (`daemon.py:4276-4277`) |
| anything | the hub holds the lease (see "Two hubs"), and `approvals` is not `terminal` in the node's `$STATE/config.json` (then the node never forwards prompts at all, matching `daemon.py:4075-4077`) |

The hub also checks consistency on arrival: `guards.readable_request(tool, masked_input, cwd)` must equal the node's
`readable`, or the request is treated as unreadable (tap only). A request with a credential is unreadable on both sides
(`readout._hidden`, `guards.py:102-103`), so masking the preview changes nothing a yes could approve. What a tap approves
on the hub page is the masked text; the exact unmasked request is in the session's own terminal, as it is today for a
notification (`docs/features/alerts.md`, "Rules").

### Threats and mitigations

| Threat | Mitigation |
|---|---|
| A machine on the same tailnet or LAN pairs itself as a node | needs a live invite code: single use, 10 minutes, ~40 bits, stored hashed, 5 attempts a minute, route open only while an invite is outstanding |
| A machine in the middle between node and hub | the node pins the hub certificate's SHA-256 and refuses anything else; the hub authenticates the node by its key over that TLS |
| A stolen node key | the holder can offer fake sessions and fake transcript lines to the hub (prompt injection into the brain: no worse than a malicious local session, which `SECURITY.md` already treats as data, not instructions, behind the gate), and receive sends aimed at those sessions. It cannot read other sessions, the journal, notes or keys. `pointe hub revoke` ends it |
| A stolen hub TLS key plus control of the route to the hub's name | can impersonate the hub to a node: receive its transcripts, send into its sessions, and approve prompts the node holds. The 0600 key file is the control; re-pairing (`pointe pair`) rotates the certificate only when it is near its end (`pair._covers`, `pair.py:100-117`), so add `pointe pair rotate` to force a new one and re-invite nodes |
| A hub bug approves the wrong request, or wording | the node's second check above: id-bound, and a spoken yes only for the node's own read-out text |
| A compromised hub sends `leave` or junk sends | `leave` only takes the session off the voice; a send is typed into the session as a user message tagged as relayed by the voice assistant (`sessions.voice_message`, `sessions.py:449-451`), which Claude Code already treats with suspicion for approvals (`docs/how-it-works.md`, "Approvals, exactly"). Same exposure as a compromised local daemon |
| Replay | TLS, per-connection `seq`, random request ids, and a verdict for a request not pending is dropped |
| Version skew | `protocol` in `hello`; the hub refuses below its minimum; the read-out consistency check turns a mismatch in `readout.py` versions into tap-only, never a wrong read-out |
| Clock skew | nothing compares wall clocks across machines: deadlines travel as `deadline_ms` relative to the frame, the pin ignores certificate dates, the invite's 10 minutes are counted on the hub's monotonic clock |
| A huge or hostile transcript | the hub caps an entry at 256 kB and a `transcript` frame at 1 MB, drops the rest of that entry with a logged warning, and refuses a gap in offsets rather than guessing |
| A node floods permission requests | the node already serializes one prompt per session (as `_PERMISSION_LOCKS` does, `daemon.py:4087-4098`); the hub announces a non-active session's prompt in one line (`daemon.py:4162-4165`) |
| The page or phone shows a remote request | they show the masked preview; a credential in a remote command never reaches the hub, so it cannot reach a screen or a notification |

### Two hubs

A node may be paired with several hubs (a desk Mac and a laptop). Each link streams transcripts (read-only), so
either hub's notes stay warm. **Sends and approvals need the lease**, one per node: the first hub whose call comes up
takes it (`lease {held: true}` to it, `lease {held: false, by: "studio"}` to the others); it is released when that call
ends. A hub without the lease shows the node's sessions with "driven from studio" and refuses to send to them or
answer their prompts; the brain is told the same in `_needs_now`. The node enforces this: a `send` or `permission.answer`
from a hub without the lease is refused with `why: no_lease`. A Mac that runs its own daemon and is also a node of
another hub embeds the node client in the daemon (`hub_nodes.NodeClient`, the same class `node.py` uses); its local call
takes the lease on its own sessions.

### Failure modes

| Event | What happens | The user sees / hears |
|---|---|---|
| Link drops (VPN down, node asleep) | heartbeat dead after 12 s; the hub marks the node and its sessions **offline** (kept, not removed); workers keep following the mirror (nothing new arrives); node reconnects with backoff. After 10 minutes offline the sessions go to `departed`, as an exited session does (`Registry.remove`, `sessions.py:191-201`) | the group greys out with "offline since 14:02"; a send to one is refused and the voice says "devbox is offline"; a prompt it held is gone back to its terminal |
| Node offline mid-approval | the node released the hook with `None` when the link died, so the prompt is in the terminal; the hub's card changes to "offline: answer it in its terminal"; a late tap or yes gets `stale` | one line: "devbox dropped, shop's approval went back to its terminal" |
| Hub restart | `REGISTRY` reloads `sessions.json` including remote sessions (`Session.machine` joins `PERSISTED`, `sessions.py:84-86`); they start offline; the node reconnects, `welcome.resume` carries mirror offsets, the node ships what the hub missed and re-sends `pending` prompts with the same `request_id`, which the hub puts to the user again (as `_on_connect` re-asks local ones, `daemon.py:5105-5111`) | the call reconnects as today; a held prompt is read out again |
| Node restart | its `sessions.json` reloads and dead pids are dropped (`sessions.py:138`); it reconnects and sends a fresh `sessions` snapshot; the hub reconciles (joins, lefts) | a session that died meanwhile is announced as closed, in one line |
| Hub has no call up | the node's hook returns `{}` at once: the prompt stays in the terminal, as a local session's does with no call | nothing; as today |
| The user answers in the terminal first | the node's `gone()` sees it (the hook's connection closes); `permission.resolved {how: terminal}`; the hub clears the card | the card disappears |
| Two sessions named `shop` on two machines | the hub suffixes the later one with the machine, the way it suffixes a second harness (`daemon.py:4006-4014`): `shop devbox` | "shop devbox finished…" |
| Same session id on two nodes (a cloned VM) | impossible to confuse: hub ids are prefixed by node |
| A node is revoked while its session holds a prompt | the link closes; the node hands the prompt to the terminal | the group disappears; one line |
| Invite expires or is mistyped | `403 invite expired` / `403 wrong code`, counted toward the rate limit | `pointe node join` prints the hub's message |

### Latency budget

The link adds one round trip each way. Tailscale between two machines on the same LAN is usually under 10 ms; over
WireGuard across sites 20 to 60 ms; Twingate 30 to 100 ms. Measured against today's own timings:

| Path | Today | Added | Budget |
|---|---|---|---|
| Transcript line written → fed to the brain | up to 0.3 s (`sessions.py:535`) | node tail (0.3 s) + 1 RTT + hub tail (0.3 s) | a report from a remote session is spoken within 0.7 s of when a local one would be |
| Permission: hook fires → read-out starts | `_read_out_when_quiet` waits for the brain to go quiet (`daemon.py:4245-4251`) | 1 RTT | under 150 ms added |
| Yes → hook released | 1 s poll in `_hold_one` (`daemon.py:4112-4113`) | 1 RTT + node re-check | under 150 ms added; the 1 s poll on the node is the floor, as today |
| Send → typed into the session | inbox write | 1 RTT | under 150 ms added |

`pointe hub nodes` and the Machines group show each node's round trip (`Heartbeat.rtt_ms`, `phone.py:62-66`), so a
slow link is visible rather than felt.

## Routing and the brain

### Session names

- `Session.machine: str = ""` (`""` is this machine); persisted. The hub's own name defaults to its short host name and
  is editable in `config.json` (`"machine": "studio"`); a node's name is set at pairing.
- Collision across machines: when a session joins with a name another machine already uses (same rule as the harness
  suffix, `daemon.py:4006-4014`), it is named `<name> <machine>` if that is `valid_name` and passes `rename_check`; else
  the registry's `-2` fallback (`sessions.py:149-153`). The first to join keeps the plain name.
- `sessions._aliases` (`sessions.py:357-367`) adds `(machine, 0)` for a remote session, exactly as it adds the harness
  label, so "the devbox one" and "shop on devbox" pick by machine. The hub's own machine name is **not** an alias (every
  "on this Mac" would match), as `claude` is excluded today.
- `_spoken_names` (`daemon.py:733-740`) says the machine only when the name was suffixed with it; otherwise the plain
  name. The machine is said on a switch across machines ("Now on shop, on devbox"), in `list_sessions` summaries, and
  whenever the user asks where something runs.

### What the brain sees

- `list_sessions` (`daemon.py:3593-3600`) adds `machine` and `online` per session. The tool description says sessions
  may be on several machines and that "everywhere" questions are answered grouped by machine.
- `_brain_context` (`daemon.py:669-694`) adds one line: `Machines: studio (this Mac, 3 sessions), devbox (Linux, 2
  sessions, 23 ms), laptop (offline since 14:02, 1 session).` `_needs_now` (`daemon.py:2994-3018`) names the machine
  after the agent in each line (`shop (Claude on devbox, working)`), and marks offline sessions `OFFLINE: cannot be
  sent to`.
- `_classify_target` (`daemon.py:3201-3228`) lists the machine next to the folder, so "the one on the VM" resolves.
- `send_to_claude_code`, `switch_session`, `ask_about_session` take session names, which are unique across machines, so
  no tool schema changes.

### Voice intents

| Said | Decided in code |
|---|---|
| "go to devbox", "switch to the devbox one" | `switch_intent` + `name_groups` with the machine alias: one session there → switch; several → a tie → "which on devbox: shop or api?" (the existing tie path, `daemon.py:3633-3637`) |
| "tell devbox to pull" | `_route` names → one session or a tie, as above |
| "tell everyone on devbox to pull", "everyone except the laptop" | `broadcast_intent` and `excluded_sessions` (`guards.py:254-266`, `sessions.py:439-444`) learn `on <machine>` / `except <machine>` through the same alias, so the broadcast is scoped to the machine's sessions |
| "what's going on everywhere", "what's on devbox" | the brain calls `list_sessions`; `status_intent` (`guards.py:287-294`) also injects `_needs_now`, which is grouped by machine when more than one machine has sessions |
| "where is shop running" | answered from `list_sessions`; the brain is told machine names are facts from the list, never from memory |
| a yes to a remote prompt | identical to today on the hub; the node re-checks |

Session mode pins to a session on any machine. There is no "machine mode": the UI's machine filter is a view, and
routing stays orchestrator or session, so the rules in `_route` (`daemon.py:3084-3127`) gain no third branch.

## UI

Status (`/voice/status`, `daemon.py:4581-4626`) adds:

```
"machines": [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true, "sessions": 3, "need": 1},
             {"id": "n3f2a1", "name": "devbox", "here": false, "os": "linux", "online": false, "since": 1731590520.0,
              "sessions": 2, "need": 0, "rtt_ms": 23, "lease": true}],
"sessions": [..., {"name": "shop devbox", "machine": "devbox", "online": false, ...}]
```

With one machine, `machines` has one entry with `here: true` and both clients render as today.

### Page (`ui.html`)

- **Sessions column grouped by machine** when `machines.length > 1`: a header row per machine (name, OS glyph,
  "offline since 14:02" or "23 ms", "N need you"), collapsible, state in `localStorage`. Within a group the existing sort
  (urgency, then name; `ui.html:868`) holds. This Mac's group is first.
- **Filter chips** above the list: `All · studio · devbox · laptop`. A chip filters the list and the "Orchestrating N
  sessions · M need you" line (`ui.html:1057-1060`) to that machine. Client-side only; it sends nothing and changes no
  mode.
- **Machine tag** on each session row when more than one machine has sessions and the filter is All, next to the agent
  badge, with the same rule the agent badge follows (`agentBadges`, `ui.html:855-856`): shown only when it tells
  something apart.
- **Approval card** (`approvalCard`, `ui.html:857-862`) shows `shop · devbox` and, if the node is offline, replaces
  Approve and Deny with "offline: answer it in its terminal".
- **Offline group**: greyed rows, no Approve/Deny, click still focuses (so you can ask about it from the notes), the
  row's title says "offline since …; sends are refused".
- **Settings → Machines**: the paired nodes with `pointe hub nodes` data, "Invite a machine" (shows the code and QR,
  the 10-minute countdown), Revoke with a confirm, and the "Approve from notifications" and "Show on phone" prefs
  unchanged.

### iPhone app (`ios/Pointe`)

- `API.Session` (`API.swift:356-385`) gains `machine: String?` and `online: Bool?`; `API.Status` gains `machines`.
- `SessionChips` (`Sessions.swift:14-80`): a machine badge on a chip when `sessions.mixesMachines`, like `AgentBadge`;
  an offline session's chip is dimmed with "offline"; the context menu adds "Sessions on <machine>" which opens the
  Sessions sheet filtered.
- Sessions sheet: sections per machine with the header data; an offline section shows "since …". A tap focuses as
  today.
- Approval card: `shop · devbox`; no Approve when offline.
- Alerts: `title` becomes `shop (devbox) needs approval` (`alerts.permission_alert`, `alerts.py:40-47`); nothing else
  changes, since the body is the read-out form, which is already the node's.
- Pairing a node is a Mac-side task; the app shows machines, it does not add them.

## Migration from `bin/voice-remote`

What it is: a 56-line script from the first commit (`git log -- bin/voice-remote`: only `558414b`) for reaching the
**browser page** from a phone over Twingate. `setup <host>` makes a CA constrained to one name, a leaf certificate, a
`remote_token` and `remote.json` (`bin/voice-remote:10-49`); `link` prints `https://<host>:7443/voice?pair=<token>`
(`:50-53`); `off` deletes the lot (`:54`). `remote.py` still honours that flow: `Remote.guard` turns `?pair=` into the
`pointe_pair` cookie (`remote.py:78-85`) and its 403 text points at `bin/voice-remote link` (`remote.py:95`).

What replaced it: `pair.py` writes the same `remote.json` and `remote_token` (`pair.setup`, `pair.py:120-130`) with a
self-signed certificate the app pins by fingerprint, and the iPhone app replaced the browser page as the phone client
(`docs/phone.md`, "The browser page (older way)").

Decision: **absorb, then delete.**

1. `pointe pair link` prints the browser pairing URL (what `voice-remote link` did) from `remote_token`, and
   `pointe pair off` removes `tls/`, `remote.json`, `remote_token`, so the two remaining uses have a home. A phone browser
   trusts the self-signed leaf directly (Settings → Certificate Trust) instead of the nameConstrained CA; the scope is
   the same one name.
2. The node link reuses the listener `pair.py` configures. There is nothing of `voice-remote` to build on: it has no
   pairing exchange, no per-client key, and a lasting URL secret `SECURITY.md` already calls a password.
3. Delete `bin/voice-remote`; update the four mentions: `docs/phone.md:45-50`, `SECURITY.md:192-194` (the "Phone
   access (experimental…)" paragraph, which also describes `bin/voice-connector`, which stays), `remote.py:95`, and the
   mobile plan's "Twingate | the existing bin/voice-remote path" row (`docs/design/2026-11-mobile-plan.md:56`).
4. `voice-remote off` left the connector and its tokens in place (SECURITY.md notes this); `pointe pair off` does the
   same and says so, since the connector is `bin/voice-connector`'s.

Anyone who ran `voice-remote setup` keeps working: `remote.json` and `remote_token` are the files `pair.py` reads, and
`pair._covers` keeps a certificate that still names the host (`pair.py:100-117`).

## Test plan

### Offline (no keys, in `tests/`, run by CI on Ubuntu)

- `tests/test_nodelink.py`: frame encode/decode, `seq` enforcement, unknown types ignored, heartbeat death, resume
  offsets, the 1 MB / 256 kB caps.
- `tests/test_node.py`: `node.py` against a fake hub (`fastapi.testclient` WebSocket): registration from
  `register-session`'s body shape; transcript shipping with masking (a line holding `ANTHROPIC_API_KEY=sk-…` arrives
  masked); repoint; the hook path: a request forwarded with the node's `readable`, hub `holding` within 2 s or back to
  the terminal; **the re-check table above, one test per row**, including `spoken` off by one character, a stale id,
  `approvals: terminal`, no lease; `gone()` → `permission.resolved`; link drop mid-hold releases `None`.
- `tests/test_hub_nodes.py`: `daemon.py` against a fake node: a remote session appears in `/voice/status` with
  `machine`; its mirror is followed and a `finished its turn` line produces a report (reuse `tests/test_orchestrator.py`'s
  fake model); a send goes out as a `send` frame and the result is honoured; `/voice/approve` on a remote request
  becomes `permission.answer` and a `permission.answered {ok: false}` turns into the existing "did not reach" line;
  name collision → `shop devbox`; offline marking after heartbeat death, `departed` after 10 minutes (clock injected);
  hub restart reload with `machine` persisted; lease refusal; "go to devbox" with one and with two sessions;
  "everyone on devbox"; `_needs_now` grouping.
- `tests/test_security.py` (append a section): `/voice/node` refuses without the key, with the phone key, with the page
  cookie, and on the loopback listener from a non-local `Host`; `/voice/node/pair` refuses without an outstanding
  invite, a wrong code, a sixth attempt in a minute, a reused code; the hub stores only the hash; a revoked key gets
  4401.
- `tests/test_pair.py`: the invite URL round trip and `speakable` on node names.
- `tests/test_mixed_harnesses.py`: a remote OpenCode session beside a local Claude Code one, each with its own prompt.

### Two simulated machines on one Mac

Both from the same checkout, isolated by state dir and ports (the pattern `docs/how-it-works.md` "Tests" and
`tests/e2e/rig.py:31-33` use):

```
# hub
CLAUDE_VOICE_STATE=/tmp/cv-hub CLAUDE_VOICE_DAEMON_PORT=7861 CLAUDE_VOICE_TLS_PORT=7444 \
  bin/pointe pair host 127.0.0.1 && bin/voice-daemon ensure && bin/pointe hub invite --name devbox-sim
# node (a second shell; the invite from above)
CLAUDE_VOICE_STATE=/tmp/cv-node CLAUDE_VOICE_DAEMON_PORT=7862 bin/pointe node join 'pointe://hub?…'
# a real Claude Code session on the "node": rig.ClaudeSession with the node's env
```

`tests/e2e/two_machines.py` drives it with the fake browser (`rig.Browser`) on the hub and `rig.ClaudeSession` started
with the node's `CLAUDE_VOICE_STATE`/port: join and greeting names the machine; a request routed by name; a report heard
within the 0.7 s budget (compare timestamps in both `daemon.log`s); a voice approval end to end (the hook's reply is in
the node's log); a tap approval through `/voice/approve`; `kill -STOP` the node mid-prompt → the prompt is in the
terminal within 15 s and the card says offline; `kill -CONT` → resume with no duplicated feed lines (count
`finished its turn` in the hub journal); `voice-daemon stop` + `ensure` on the hub → the node re-sends a pending prompt
and it is read out once; two sessions called `shop`; "go to devbox-sim"; "what's going on everywhere".

### A Linux node in Docker

`tests/e2e/linux_node/Dockerfile`: `python:3.12-slim`, `uv`, the checkout mounted read-only, `uv sync --locked`
(the same install CI does on Ubuntu, `CONTRIBUTING.md`). Reaches the hub on the Mac through `host.docker.internal:7444`
(the hub paired with `host 127.0.0.1`; the node pins the fingerprint, so the name does not matter). Two runs:

1. **Synthetic session**: register a session with `pid` of a `sleep infinity` and a transcript the test appends to, as
   `tests/e2e/page_show.py` does for Show; checks the mirror arrives masked, a report is spoken, and a synthetic
   `/voice/permission-hook` POST from inside the container is answered by a tap on the hub and refused when the id is
   stale. No model key in the container.
2. **Real Claude Code** in the container with `ANTHROPIC_API_KEY` injected at `docker run -e` from the Keychain (never
   in the image or a file): `/pointe:voice`, one request, one voice approval of `git status`.

### Real hardware checklist

- Mac Studio hub, MacBook node over Tailscale: pair, join two sessions, orchestrate across both, switch by machine,
  approve by voice and by tap, close the MacBook lid (offline within 15 s, back within 30 s of waking, no lost lines).
- Linux VM over Twingate: pair with `host <alias>`, Claude Code and Codex (`codex --remote unix://`) on the node, one
  prompt each at once.
- LAN only (`pointe pair wifi`), Wi-Fi address change: the node reconnects after `pointe pair wifi` + `pointe hub
  invite` again (documented as the Wi-Fi limit, as for the phone).
- iPhone app and a node at once on the TLS listener; approve a remote prompt from the watch (notification approve), and
  confirm the node refused a forged `how: notification` for an unreadable request in its log.
- Hub asleep: node backoff visible in `pointe node status`; wake → resume.
- Round trips shown in `pointe hub nodes` match `tailscale ping`.

## Build plan

Four tracks that can run in parallel. The contract between them is this document: the frame tables, the status fields,
and the `Session.machine` field. The first commit of Track A lands `nodelink.py` (the frame schema and heartbeat) and the
two-line `guards.py` change on day one, before anything else, so B, C and D build on files that exist. After that, no
two tracks edit the same file.

| Track | Owns | Delivers |
|---|---|---|
| **A. Link, pairing, hub side** | `nodelink.py` (new), `hub_nodes.py` (new: `NodesRegistry`, invite and pair routes, the `/voice/node` WebSocket handler, mirror writer, `NodeClient` for hub-as-node), `harnesses/remote.py` (new), `pair.py` (`invite`, `link`, `off`, `rotate`), `remote.py` (nothing beyond the 403 text), `guards.py` lines for `_NODE_PATHS` only (day one), `bin/pointe` (`hub` subcommands), `tests/test_nodelink.py`, `tests/test_hub_nodes.py`, `tests/test_security.py` node section, `tests/test_pair.py` | a hub that accepts nodes and shows their sessions, with a fake node in tests |
| **B. Node** | `node.py` (new), `bin/voice-node` (new), `bin/voice-daemon` (node-mode branch), `bin/voice-open` (node message), `harnesses/join.py` (nothing: it posts to `127.0.0.1:7860`), `tests/test_node.py`, `tests/e2e/linux_node/` | a node that ships a transcript, delivers sends and holds and re-checks prompts, against a fake hub |
| **C. Brain, routing, status** | `sessions.py` (`machine`, `PERSISTED`, `_aliases`, broadcast exclusion), `daemon.py` (`harnesses.of` at call sites, `register_remote`, `status` fields, `list_sessions`, `_brain_context`, `_needs_now`, `_classify_target`, `_spoken_names`, `_tracked_files`, `_deliver_verdict` and `_drop` for remote, offline handling), `harnesses/__init__.py` (`of()`), `guards.py` intent functions (after A's day-one lines), `brain.py` if a prompt line is needed, `tests/test_orchestrator.py`, `tests/test_units.py`, `tests/test_mixed_harnesses.py`, `bench/` cases for the new intents | a daemon that treats a `Session` with `machine` set correctly everywhere, against a fake `RemoteHarness` until A lands |
| **D. UI and docs** | `ui.html`, `ios/Pointe/{API,Sessions,CallView,Alerts}.swift`, `ios/PointeUITests/ParityUITests.swift`, `tests/e2e/page_parity.py`, `docs/multi-machine.md` (user doc), `README.md` (one feature row, Architecture block), `SECURITY.md` (a "Machines" section; remove the `voice-remote` paragraph), `docs/phone.md` (remove the older way), `docs/harnesses.md` (one paragraph: adapters run on the session's machine), `plugin/commands/` (`/pointe:voice` output on a node) | both clients rendering `machines` and `machine` from a recorded status fixture, then live |

Integration, after the tracks: `tests/e2e/two_machines.py`, the Docker run, the hardware checklist, and the deletion
of `bin/voice-remote` (Track A's `pointe pair link|off` must be in first).

Phase 2, not in the tracks above: Show while it says for remote sessions (`artifact.render` frames; the node keeps its
own last ten sets so it never takes a path from the hub, matching `docs/features/show-while-it-says.md`, "What it will
not show"); challenge evidence from remote diffs (`_challenge_diffs`, `daemon.py:2071-2087`, currently runs `git` in
`cwd`: skip remote sessions until then, and say so in the challenge's evidence line); trimming the node's install
(`sessions.py:27` imports Pipecat's `BaseWorker` for `ClaudeSessionWorker`, which the node never uses: move the worker to
`daemon.py` so a node needs only aiohttp, FastAPI, uvicorn and the cryptography package).

## Open questions for the owner

1. **Transcripts cross to the hub.** Every remote session's transcript (credentials masked on the node) reaches the hub
   and so the hub's reader and brain vendors. This is what makes a node keyless and the hub's rules unchanged. The
   alternative, notes written on the node by its own reader with its own key, breaks "no keys on nodes" and splits the
   rules. Accept the proposed design?
2. **Two hubs.** Proposed: a node may pair with several hubs; the first hub whose call comes up holds the lease on that
   node's sends and approvals until it hangs up; the others see "driven from studio". Simpler alternative for v1:
   refuse a second pairing. Which?
3. **How often is the machine said aloud?** Proposed: only when a name was suffixed with it, on a switch across
   machines, in "everywhere" summaries, and when asked. The alternative is to name the machine in every report about a
   remote session.
4. **`bin/voice-remote`**: delete in the same release that adds `pointe pair link|off`, or keep it one release with a
   message pointing at the new commands?
