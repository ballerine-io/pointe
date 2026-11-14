# Multi-machine Pointe: one voice over sessions on several machines

Status: design, not built; revised after an independent review. Line numbers are from `main` at `fbc0ca9`.

Owner decisions taken into this revision: one hub per node in v1; transcripts (credentials masked on the node) may
reach the hub's vendors; the machine is said aloud only when ambiguous, on a switch across machines, and in
"everywhere" answers; `bin/voice-remote` is deleted in its own small PR; the iPhone app keeps full parity with the page.

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

- **Connect a machine in one command on each side**: an invite on the hub, `pointe node join <invite>` on the other
  machine. After that, `/pointe:voice` and `pointe join opencode|codex` on that machine work unchanged.
- **One call over every machine.** Orchestrator mode routes across machines; session mode pins to one session anywhere;
  "go to devbox" and "what's going on everywhere" work by voice.
- **Always clear where a session runs**: in the brain's view, in the voice when it matters, and on the page and in the
  app always.
- **Approvals as strict as today, with a second check on the node for what the voice can approve.** The node re-checks
  voice and notification approvals against its own copy of the request: a hub bug cannot approve by voice what the
  node would not read out. A tap is trusted from the hub, as the hub's own page is trusted today; a node may opt to
  refuse remote taps on requests it cannot read out (`remote_taps: readable_only`).
- **No vendor key leaves the hub, and no credential leaves a node** except as masked text.
- **Degrades to today:** a node offline, a hub down, or a link dropping hands prompts back to the terminal, as a hung-up
  call does now (`_hand_prompts_back`, `daemon.py:4047-4051`).

## Non-goals

- A central server, an account, or any relay outside the user's own machines. Nodes dial the hub directly over the
  private network the phone already uses.
- Audio on nodes. A node has no ears, mouth, brain, reader or gate, and no key.
- Two calls at once. One hub holds the call, as today (`socket_call`, `daemon.py:5208-5213`).
- **A node paired with two hubs** (v1). `pointe node join` refuses while paired; `pointe node leave` first. A second
  Mac that wants the call runs the daemon on its own sessions and is simply not a node; a hub does not act as a node.
- Launch mode (`pointe start`, a Claude Code channel) on a node. Channels must be on the daemon's machine
  (`daemon.py:3986-3987`); on a node, `/pointe:voice` (inbox mode) and `pointe join` only.
- Side questions by a forked copy on the node (`claude -p --resume --fork-session`, `harnesses/claude_code.py:86-115`).
  Remote sessions declare `side_questions = False`, so "by the way" questions are answered by the transcript reader from
  the mirror, as for a harness without forking (`docs/harnesses.md`, "Side questions").
- Meeting mode, briefings, the conflict alarm and the voice lock change nothing: they run on the hub over whatever
  sessions it has, remote ones included, through the same notes.
- Windows nodes.

## Shape: a hub and nodes, evaluated

| Shape | Verdict |
|---|---|
| **Hub + lightweight nodes** (proposed): the Mac with the call runs the daemon; each other machine runs a small node that owns its sessions and talks to the hub over pinned TLS | **Chosen.** Everything machine-local stays on the machine; the hub keeps every rule it has. |
| Peer daemons, each a full Pointe, borrowing each other's sessions | The same as hub + node, but every node carries Pipecat, the model libraries and vendor keys for nothing. A node never needs a key. |
| The hub reaches into machines over SSH (tail the transcript, write the socket, catch the hook) | The hook must post to something on the session's machine, so the hub would need a long-lived listener there anyway; nothing on the far side can re-check an approval; file tailing over SSH on a dropped link loses lines silently. Rejected. |
| A central relay | Against the product (no server, no account). Rejected. |

One refinement: **the node is not a cut-down brain, it is a file shipper and a hand.** It ships the session's
transcript to the hub as the hub's own mirror file, delivers sends into the session, and holds and re-checks permission
prompts. The hub reads the mirror with the same follower, reader and brain it uses for local sessions. This is how
OpenCode and Codex already join: their adapters write a mirror transcript in Claude Code's JSONL shape under
`~/.claude-voice/harness/<harness>/` and the ordinary follower reads it (`harnesses/opencode.py:165-167`,
`harnesses/codex.py:210-212`). A remote session is one more mirror, written from a stream instead of a local service.

Direction of the link: **the node dials the hub.** VMs and Linux hosts are often behind NAT with outbound only; the hub
already has a reachable TLS listener for the phone (`remote.Remote.serve`, `remote.py:99-122`, port 7443 on the
address `pointe pair` chose). The hub never needs a node's address.

## Architecture

```
  hub: the Mac with the call                                   node: another Mac, or a Linux host or VM
  ──────────────────────────                                   ────────────────────────────────────────
  Chrome page ── iPhone app (paired, pinned)                   Claude Code ─ OpenCode ─ Codex (their terminals)
        \          /                                                 |  register, inbox socket, PermissionRequest hook
    daemon.py (brain, ears, mouth, approvals, notes, routing)        |  (bin/* unchanged: they talk to 127.0.0.1:7860)
        │                                                        node.py  (127.0.0.1:7860, same token file, no keys)
        │ harnesses/remote.py: one RemoteHarness per node          │ Registry (sessions.py), harness adapters (watch,
        │   alive from node state; send over the link              │ send, alive, probe), transcript tail (complete
        │   watch = follow_transcript on the mirror                 │ lines only), hold + re-check
        │   ~/.claude-voice/harness/remote/<node>/<id>.<gen>.jsonl  │
        │   + <id>.<gen>.offset (the node's next_offset)            │
   remote.py TLS listener :7443 ◄───── WebSocket /voice/node ───────┘   HMAC over a hub nonce; hub cert pinned by SHA-256
   (shared with the phone)             JSON frames, heartbeat (phone.Heartbeat)
```

What moves where:

| Concern | Today | Multi-machine |
|---|---|---|
| Registration | `/voice/register` on the daemon, `daemon.py:3980-4029` | On a node, the same route on `node.py`; the node announces the session to the hub (`session.joined`). The hub creates a `Session` with `machine` set, through `register_remote()` next to `register()` |
| Transcript | daemon tails the file every 0.3 s (`sessions.py:535`) | node tails it and ships complete JSONL lines with the node's byte offsets; hub appends them to a mirror file and persists the node's `next_offset` beside it; the hub's follower reads the mirror unchanged |
| Send | `harnesses.get(s.harness).send` → inbox socket, `daemon.py:2050-2052` | `RemoteHarness.send` → `send` frame → node runs the real adapter's `send` |
| Permission | hook → `/voice/permission-hook` → `hold_permission` → voice/tap → future (`daemon.py:4054-4129`) | hook → node's `/voice/permission-hook` → node holds the future and forwards the request → hub answers `permission.holding` at once and puts it to the user as a channel request is put today (`_put_permission`, `daemon.py:4142-4166`) → verdict frame → **node re-checks** → future |
| Liveness | pid check / adapter probe every 5 s (`_liveness`, `daemon.py:5014-5024`) | node runs the same loop and reports `session.left`; hub marks a node's sessions offline when the link drops; `Session.alive()` for a remote session reads node state, never a pid |
| Notes, reports, routing, side answers from the record | read the transcript file | read the mirror: unchanged, with time filters shifted by the node's clock offset |
| `git ls-files` for routing hints (`_tracked_files`, `daemon.py:3184-3190`) | run in `cwd` | node sends the first 40 names at join and on each repoint |
| Show while it says (`artifacts.render`) | reads files under `cwd` | phase 2 (below) |

### Why not run the node's logic inside `daemon.py`

`daemon.py` is 5,400 lines around Pipecat, vendors and the call. A node is ~600 lines: `Registry` and `post_inbox`
from `sessions.py`, the harness adapters, `LocalAuth` from `guards.py`, `readable_request` and `readout.mask`, a hold
loop with the contract of `_hold_one` (`daemon.py:4104-4129`: a future, `gone()` polled each second, a deadline), and
the link. It imports nothing that loads a model or reads a key. The hub's local sessions keep their current code path;
remote sessions enter through one adapter, `harnesses/remote.py`.

**Every place that picks an adapter goes through `harnesses.of(session)`**, which returns `RemoteHarness` wrapping the
inner adapter when `session.machine` is set, else `harnesses.get(session.harness)`. That includes the four sites in
`sessions.py` the review found, not only `daemon.py`: `Session.alive` (`sessions.py:78-81`), `current_transcript`
(`sessions.py:502-507`), `_follow_one` (`sessions.py:519`) and `ClaudeSessionWorker.start` (`sessions.py:781`).
`label`, `agent`, `noise`, `capabilities` and `permission_deadline` come from the inner adapter, so the badges, the feed
tags and `brief.for_agent` are untouched; `capabilities()` sets `side_questions: False`.

`RemoteHarness`:

| Method | Behaviour |
|---|---|
| `alive(session)` | true while the node is online and the session is in its last snapshot, or the node has been offline less than `OFFLINE_GRACE_SECS` (600). Never a pid check. After the grace, `_reap_dead` drops it as an exited session (`daemon.py:5066-5079`) |
| `transcript_path(session)` | the mirror with the highest `gen` for this session, so `current_transcript`'s five-second repoint check (`sessions.py:499-507`) sees a `/clear` or `/resume` and `_follow_one` returns and reopens, exactly as for a local Claude Code session |
| `watch(session, feed)` | `follow_transcript` on the mirror, as OpenCode does (`harnesses/opencode.py`, `watch`) |
| `send(session, text)` | `send` frame, awaits `send.result` with a 5 s timeout; false on timeout or offline |
| `probe`, `title`, `leave` | no-op; node pushes titles in its `sessions` snapshots; `leave` sends `leave` |
| `side_question` | `None`: the transcript reader answers |

On a hub restart, `Registry.load` (`sessions.py:115-143`) keeps remote sessions: `Session.machine` joins `PERSISTED`,
`alive()` goes through `RemoteHarness`, and the node is "offline since load" until it reconnects. The check at
`sessions.py:133-134` (a Claude Code session needs a pid and a transcript) is skipped when `machine` is set, since the
pid is the node's.

### Processes on a machine

Every machine runs exactly one thing on `127.0.0.1:7860`: `daemon.py` if it is the hub, `node.py` if it is a node.
Both write `$STATE/token` and `$STATE/daemon.pid`, so `bin/register-session`, `bin/voice-permission-hook`,
`bin/claude-voice-attach` and `harnesses/join.py` work on a node with no change. `bin/voice-daemon ensure` gains one
branch: if `$STATE/node.json` lists a hub, it execs `bin/voice-node ensure` instead, so `/pointe:voice` on a node starts
the node, not a daemon. `bin/voice-open` on a node prints "the call is on <hub>" instead of opening a page.

**Linux and `lsof`.** `bin/voice-permission-hook:7-10` checks that the pid listening on the port is ours with `lsof`,
and exits silently when `lsof` is missing, so on a Linux box without it the hook would never forward a prompt and the
user would not know. Two fixes: `pointe node join` preflights `lsof`, else `ss`, and refuses to pair with "install lsof
or iproute2" when neither is there; the hook (and `bin/voice-daemon`'s `ours()`) fall back to `ss -ltnp` and, failing
that, to reading `/proc/net/tcp` plus `/proc/<pid>/fd` for the listening socket's inode. The Docker test below runs the
real hook script, not a hand-made POST.

### Node install

A node must not pull Pipecat, sherpa-onnx or the model libraries (180 MB, `bin/voice-daemon`). Day-one work:

- `pyproject.toml` gets a `node` dependency group (`aiohttp`, `fastapi`, `uvicorn`, `cryptography`, `loguru`), and
  `bin/voice-node` runs `uv sync --locked --only-group node`.
- `ClaudeSessionWorker` moves from `sessions.py:767-788` to `daemon.py`: it is the one thing in `sessions.py` that
  imports Pipecat (`sessions.py:27`), and the node never uses it. `sessions.py` also imports `artifacts` and `brief`;
  both are pure text code with no vendor import at module load, and `tests/test_node.py` asserts the node's import set
  (a test fails if `pipecat`, `onnxruntime`, `anthropic` or `google` appear in `sys.modules` after `import node`).

## Protocol

One WebSocket per node, path `/voice/node`, on the hub's TLS listener (and on loopback for tests). Text frames, one
JSON object each: `{"t": "<type>", ...}`. Heartbeat reuses `phone.Heartbeat` (`phone.py:48-70`): a ping every 2 s, dead
after 12 s with no pong, close 4408; the node reconnects with backoff 1, 2, 4 … 30 s. Unknown frame types are ignored
both ways, as in the phone protocol (`phone.py:16-17`), so one side can move first. There is no sequence number: TLS
orders and protects the stream, and every request carries its own id.

Hello carries `protocol: 1`. The hub refuses a node below its minimum with 4426 and a reason the node prints.

### Authentication: HMAC over a hub nonce

On connect the hub sends `challenge {nonce}` (32 random bytes, hex). The node answers `hello` with
`auth: HMAC-SHA256(node_key, nonce || hub_id)`. The hub holds the node key (0600, `nodes.json`) and compares with
`hmac.compare_digest`; a wrong answer, or a node id it does not know, closes with 4401, and only on 4401 does the
node delete its key. No `hello` within 10 s, or a first frame that is not a valid `hello`, closes with 4400: the node
keeps its key and reconnects, so a laptop that stalls mid-handshake does not unpair itself. The key is never sent, so
a hub that logged a request, or a listener that was not the hub, learns nothing reusable. **One live connection per key:** a second connection that
authenticates with a key already connected is closed with 4409 `already connected`, and the first stays; a cloned VM or
a stale process cannot shadow the real node. Before refusing it, the hub pings the first link: if no frame comes from
it within 3 s (`STALE_PROBE_SECS`), that link is stale (the node crashed, slept or lost its network and is now
reconnecting), so the hub closes it 4408 and welcomes the new one, instead of refusing every reconnect until the
heartbeat gives up about 15 s later. A first link that answers stays, so the protection holds against any copy of the
key while the real node is connected.

### Node to hub

| Frame | Fields | Notes |
|---|---|---|
| `hello` | `protocol, auth, node: {id, name, os, arch, version, harnesses}, now` | once, first. `now` is the node's wall clock (epoch seconds): the hub records `skew = hub_now - now` (good to about half a round trip) |
| `sessions` | `[{id, name, name_given, cwd, pid, harness, home, title, capabilities, files: [≤40], pending: permission?}]` | full snapshot, after `welcome` and whenever the set, a title or the pending prompt changes. Never `inbox_socket` or `inbox_token`: they stay on the node |
| `session.joined` / `session.left` | `id`; `left` adds `why: exited \| disconnected` | incremental |
| `transcript` | `id, gen, offset, next_offset, entries: [raw JSONL lines]` | only complete lines (ending in `\n`); a partial tail waits for the next poll. `offset` is the node-file byte offset of the first entry, `next_offset` the offset after the last. The hub appends only if `offset == stored next_offset`, else drops the frame and sends `resume` |
| `transcript.repointed` | `id, gen, history?` | the session moved to a new file (`claude_code.transcript_path`, `harnesses/claude_code.py:63-76`); the hub opens `<id>.<gen>.jsonl` with offset 0. `history: true` when the node opened the gen from a resume (it re-ships a file from byte 0 that already happened), not a live move: the hub writes it as a backlog (`.part`, below), never as news |
| `files` | `id, names` | routing hints, after a repoint |
| `permission.request` | `id, request_id, tool, description, preview, readable, deadline_ms` | `preview` is `tool_input` JSON after the transcript masking rules; `readable` is the node's own `guards.readable_request(tool, tool_input, cwd)` on the **unmasked** input, or null. `deadline_ms` is relative |
| `permission.resolved` | `id, request_id, how: terminal \| timeout \| left` | the prompt is no longer the hub's to answer |
| `permission.answered` | `request_id, ok, why?` | the node's reply to a verdict: `ok` false with `why` when the re-check refused it |
| `send.result` | `req, ok` | |
| `artifact.result` | `req, view?` | phase 2 |
| `pong` | `id` | |

### Hub to node

| Frame | Fields | Notes |
|---|---|---|
| `challenge` | `nonce, hub: {id, name}` | once, first |
| `welcome` | `protocol, call_up, approvals_terminal, vendors, resume: {hub_session_id: {gen, offset}}` | once, after a good `hello`. `resume` comes from the persisted `.offset` files. `vendors` is the hub's role list, for `pointe node status` |
| `resume` | `{id: {gen, offset}}` | after a gap: the node reseeks and resends from there |
| `call` | `up: bool, approvals_terminal: bool` | the node forwards prompts only while a call is up and the hub's `approvals` is not `terminal` (`vendors.config().get("approvals")`, `daemon.py:4075-4077`); otherwise its hook returns `{}` at once, as the daemon does with no call (`daemon.py:4061-4062`) |
| `send` | `req, id, text` | the node applies `voice_message` so the `#tag` is fresh (`sessions.py:449-451`) |
| `permission.holding` | `request_id` | sent **immediately on receipt**, before the read-out is scheduled. The node waits up to 10 s for it, then hands the prompt back to the terminal; the hub's `_read_out_when_quiet` can wait longer than that for the brain (`daemon.py:4245-4251`), which is why the ack must not wait for the read-out |
| `permission.answer` | `id, request_id, verdict: allow \| deny, how: voice \| tap \| notification, spoken?` | `spoken` is the exact line the hub read out, for `how: voice` |
| `artifact.render` | `req, id, artifact_id` | phase 2 |
| `leave` | `id` | the user took the session off the voice from the page or by voice (`disconnect`, `daemon.py:5054-5063`); the node removes it from its registry (it keeps running in its terminal) and calls `Harness.leave` |
| `unpaired` | | the hub revoked this node; the node deletes its key and stops reconnecting |
| `ping` | `id, rtt_ms` | |

### Ids and mirrors

Hub-side session id: `<node_short>-<session_id>` (`node_short` is 6 hex of the node id; the registry's id pattern
`[\w-]{1,128}` allows it, `daemon.py:3984`), with the real id in `harness_data["remote_id"]`. Everything the hub keys
by session id (notes in `briefs/<id>.json`, `_PERMISSION_LOCKS`, workers) stays unique across machines. The node keys by
the real id, so `pointe leave` and `claude-voice-attach off` there work as now.

Mirrors live in `$STATE/harness/remote/<node_id>/<id>.<gen>.jsonl`, 0600 in a 0700 directory (they hold session
content, like `daemon.log`). Beside each, `<id>.<gen>.offset` holds the node's `next_offset` after the last appended
frame, written with the same temp-and-replace the registry uses (`Registry.save`, `sessions.py:105-113`). On hub
restart `welcome.resume` is built from these files, never from mirror sizes: masking changes line lengths, so a mirror's
size says nothing about the node's file. Mirrors of a session that left are pruned 7 days after it departed, and
`<id>.<gen-1>` files once `gen` advanced, so `/clear`-heavy sessions do not accumulate. All of one node's mirrors together are
capped at 4 GB (`MAX_MIRROR_BYTES_PER_NODE`): past it the hub still counts each frame's offsets, so the link stays in
step, but writes no entries until a repoint or a prune frees space, and logs it once.

### Clock skew

Transcript entries carry the node's wall-clock `timestamp`, and the hub filters by time when it reads a record:
`recent_history`'s `since` (`_stamped_before`, `sessions.py:634-648`) and the briefing windows. So skew matters there.
The hub shifts every `since` it applies to a remote mirror by the node's `skew` from `hello` (re-measured on each
reconnect). Elsewhere nothing compares wall clocks across machines: the hold deadline travels as `deadline_ms`, the
invite's 10 minutes are counted on the hub's monotonic clock, and the certificate pin ignores dates.

## Pairing

Modeled on the phone (`pair.py`): the hub shows a secret once, the node proves it has it, and from then on both hold
a shared key.

### Hub

```
pointe hub invite [--name devbox]
```

Requires `pointe pair tailscale|wifi|host <name>` to have run (it refuses otherwise and says so): the node reaches the
same listener the phone does, and there is one place reachability is chosen. Prints one line, no QR code:

```
pointe://hub?v=1&host=studio.tail1234.ts.net&port=7443&fp=3b1c…&code=K7PQ-2MXD
```

- `host`, `port` and `fp` are what the phone's pairing link carries (`pair.pairing_link`, `pair.py:133-137`).
- `code` is 8 characters from a 32-letter alphabet (about 40 bits), single use, valid 10 minutes. The daemon keeps a
  SHA-256 of it in memory (`POST /voice/hub/invite`, token-protected, from the CLI), never on disk. `/voice/node/pair`
  answers only while an invite is outstanding, and at most 5 wrong codes a minute per source address and 10 a minute
  in all (429). The right code pairs even then: behind `bin/voice-connector` every attempt comes from 127.0.0.1, so a
  guesser would otherwise lock the real node out. What bounds the guesses is the invite itself: after 20 wrong codes
  (429s included, since each was checked) it is cancelled, and `GET /voice/hub/invite` says so (`ended`, with the last
  source address); while it is live, the status shows `wrong_codes` and `pointe hub invite` prints each new one.
- The page and the app show the same one-time code as text with a countdown (Settings → Machines → "Invite a
  machine"; the app asks for Face ID to show it).

When the code is used, the hub prints and shows **the node's name, source address and key fingerprint** (the first 16
hex of SHA-256 of the node key), so the owner can see that the machine that paired is the one they typed the code on:
"devbox paired from 100.101.5.7 (Tailscale), key 3f2a…". `pointe node status` on the node shows the same fingerprint.

### Node

```
pointe node join 'pointe://hub?…'   [--name devbox]
```

1. Refuses if `node.json` already names a hub ("leave studio first: pointe node leave").
2. Preflights `lsof`/`ss` (above) and `uv`.
3. **Pins in two steps.** Opens a TLS connection with certificate verification off, reads the peer certificate, and
   compares its DER SHA-256 to `fp`. Only if equal does it send anything. A mismatch prints: "the hub's certificate is
   not the one in the invite. If the hub re-paired or rotated its certificate (pointe pair rotate), ask for a new
   invite." This is the iOS app's check, so dates and issuer play no part.
4. `POST /voice/node/pair {code, name, os, arch, version}` → `{node_id, node_key, hub: {id, name}, vendors}`. Keys are
   256 bits (`secrets.token_bytes(32)`, hex). The hub refuses a name that is taken, that `sessions.speakable` would
   refuse (`sessions.py:214, 231`), or whose words appear in any current session's name words (a node called `shop`
   beside a session `shop/main` could never be told apart by voice).
5. Writes `$STATE/node.json` (`{name, hub: {id, name, host, port, fp}}`) and `$STATE/node_keys/<hub id>` (0600), starts
   `bin/voice-node ensure`, and prints: "Paired with studio. Sessions you join here reach its voice: /pointe:voice in
   Claude Code, pointe join opencode|codex in a folder. Their transcripts (credentials masked) go to studio and its
   vendors: Anthropic, Soniox, ElevenLabs, Gemini."

On the hub, `$STATE/nodes.json` (0600) gets `{id, name, os, key, paired_at}`. A `nodes.json` that does not parse is never saved over:
it is moved to `nodes.json.broken-<time>` (still 0600, it holds the keys) for repair by hand, and the hub keeps its
`hub_id` if that is legible in it, so the paired nodes are not told "another hub answers" once the file is restored.

### Everyday commands

| Where | Command | Does |
|---|---|---|
| hub | `pointe hub nodes` | each node: name, os, online or offline since, sessions, round trip, key fingerprint |
| hub | `pointe hub revoke <name>` | deletes the entry; the link is closed with `unpaired`; its sessions go to `departed`; mirrors pruned on the 7-day schedule |
| hub | `pointe hub invite` | as above |
| node | `pointe node status` | the hub, link state, round trip, the hub's vendors, sessions here, key fingerprint |
| node | `pointe node leave` | deletes the key, sends a best-effort `bye` so the hub forgets it too |

Revocation from either side works offline: a revoked node that reconnects gets 4401 and deletes its key; a node that
left while the hub was down stays listed offline until `pointe hub revoke`.

### Where the node's key lives on Linux

In `~/.claude-voice/node_keys/<hub id>`, 0600, inside the 0700 state dir. This is what Pointe already does for its own
secrets on the Mac too: the daemon token, the page key and the phone key are 0600 files, not Keychain items
(SECURITY.md, "Files"; `phone.phone_key`, `phone.py:105-112`). The Keychain holds vendor keys, and a node has none. The
threat this leaves is today's "code running as you is trusted" (SECURITY.md, "Known limits"): another user on a shared
Linux box cannot read it; root, or a process running as you, can. What the file protects is the ability to offer
sessions to the hub and receive its sends.

## Security model

### What crosses the link

| Node → hub | Hub → node | Never crosses |
|---|---|---|
| transcript entries, string fields through the transcript masking rules | the user's requests (sends), which can quote hub-side conversation | vendor keys (none on a node), voiceprints, the journal, session notes (`briefs/`), the dictionary |
| names, `cwd` as a string, pid, harness, title, up to 40 tracked file names, the node's wall clock | permission verdicts, bound to a request id | page key, phone key, inbox sockets and tokens (stay on the node) |
| permission requests: masked preview + the node's read-out form | artifact ids to render (phase 2) | the brain's context; the node key (only an HMAC over a nonce) |

The hub treats a mirror as it treats a local transcript: 0700 state dir, sent to the reader and brain vendors under the
hub's keys. **A node's session content reaches whatever vendors the hub uses** (owner decision). `pointe node join`
prints that sentence with the vendor list; `pointe node status` repeats it. A hub in fully local mode (`pointe local`)
sends it to no vendor.

**Masking on the node** uses only `readout.mask`'s high-precision rules: known token shapes, private-key blocks, URL
passwords, and quoted or env-style values of secret-like names. The broader rules (this machine's own key variables'
values, which the node has none of; bare `name: value` guesses) stay off for transcript fields, so the reader is not
handed a record with ordinary values blanked. The same subset masks the permission preview. A request with a
credential is unreadable on both sides (`readout._hidden`, `guards.py:102-103`), so masking changes nothing a yes could
approve.

### Approvals: what the node re-checks, and what it trusts

The hub keeps every rule in `SECURITY.md`: the read-out is built from what will run (`readable_request`,
`guards.py:95-116`), only a bound yes right after it approves (`_answer_permission`, `daemon.py:2897-2961`), a tap
approves the pending request id (`approve`, `daemon.py:4267-4283`), notification approvals need `alerts.approvable`
(`daemon.py:4279-4280`). The hub does **not** recompute the read-out from the masked preview: it uses the node's
`readable` after cheap local checks (a string under 25 words, `readout.redact` not `None`, no consent word in it: the
checks `readable_request` ends with, `guards.py:111-116`), and treats a failure as unreadable, tap only.

The node adds, in `node.py`, with its own tests:

| Verdict arrives with | Node releases the hook only if |
|---|---|
| any `request_id` | it equals the one request the node holds for that session right now. Else `permission.answered {ok: false, why: stale}`; the hub says "the answer did not reach it", as on a failed delivery today (`_apply_answer`, `daemon.py:2967-2971`) |
| `verdict: deny` | always. A no from anywhere denies |
| `how: voice`, `verdict: allow` | the node's own `readable` for this request is non-empty **and** `spoken == readable` byte for byte. The node computed `readable` from the unmasked input before the request left; a hub that read out anything else, or a request the node itself judged unreadable, cannot be approved by voice |
| `how: notification`, `verdict: allow` | the node's `readable` is non-empty (the rule `alerts.approvable` enforces on the hub, re-enforced here) |
| `how: tap`, `verdict: allow` | the id check. **A tap is trusted from the hub**, as the hub's own page and app are trusted today: the node cannot see the page cookie or Face ID, and the exact request a tap approves may have no read-out form. A node that wants less exposure sets `remote_taps: readable_only` in its `$STATE/config.json` (default off): then a remote tap is refused (`why: unreadable`) for a request with no readable form, and such prompts are answered only in the node's terminal. `/pointe:doctor` on the node says which it is |
| anything | the node's `approvals` is not `terminal` in its `$STATE/config.json` (then the node never forwards prompts, matching `daemon.py:4075-4077`) |

A verdict the re-check refuses does not end the hold: the node answers `permission.answered {ok: false, why}`
(`stale`, `unreadable`, `mismatch` or `terminal`) and keeps the prompt held, so the user can still answer it by a
verdict that passes, in the terminal, or by letting it time out. Only an accepted verdict, a terminal answer, the
deadline, or a hand-back releases the hook.

Honest summary for `SECURITY.md`: the node re-checks voice and notification approvals; a tap is trusted from the hub,
as the hub's own page is trusted. What a tap approves on the hub's screens is the masked preview; the exact unmasked
request is in the session's own terminal.

### Threats and mitigations

| Threat | Mitigation |
|---|---|
| A machine on the same tailnet or LAN pairs itself as a node | needs a live invite code: single use, 10 minutes, ~40 bits, stored hashed, at most 20 wrong codes before the invite is cancelled, route open only while an invite is outstanding; the owner sees the count of wrong codes, and the source address and key fingerprint of whatever paired |
| A machine in the middle between node and hub | the node pins the hub certificate's SHA-256 before sending a byte; the hub authenticates the node by HMAC over its nonce, so the key never crosses |
| A stolen node key | the holder can offer fake sessions and fake transcript lines (prompt injection into the brain: no worse than a malicious local session, which `SECURITY.md` treats as data behind the gate), receive sends aimed at those sessions, and approve prompts it itself forwards. It cannot read other sessions, the journal, notes or keys, and cannot connect while the real node is connected (one connection per key). `pointe hub revoke` ends it |
| A stolen hub state dir (`nodes.json` holds node keys) | the holder can pose as any node to this hub, with the same reach as a stolen node key. Posing as the hub to a node also needs the TLS key and the route. Revoke and re-invite; `pointe pair rotate` forces a new certificate |
| A stolen hub TLS key plus control of the route to the hub's name | can impersonate the hub to a node: receive its transcripts, send into its sessions, and tap-approve prompts the node holds (voice approvals still need the node's own read-out text, which the impersonator also sees, so they are not protected against this case). The 0600 key file is the control; `remote_taps: readable_only` limits taps to what could have been read out |
| A hub bug approves by voice what should not be | the node's check: id-bound, and a spoken yes only for the node's own read-out text |
| A hub bug approves by tap what should not be | not caught by the node, by design (above); same exposure as a bug in the hub's own page path today |
| A compromised hub sends `leave` or junk sends | `leave` only takes the session off the voice; a send is typed as a user message tagged as relayed by the voice assistant (`sessions.voice_message`), which Claude Code treats with suspicion for approvals (`docs/how-it-works.md`, "Approvals, exactly"). Same exposure as a compromised local daemon |
| Replay | TLS, a fresh nonce per connection, random request ids, and a verdict for a request not pending is dropped |
| Version skew | `protocol` in `hello`; the hub refuses below its minimum; the node's `readable` is the only read-out text, so a newer `readout.py` on one side cannot produce two forms |
| Clock skew | time filters on remote mirrors are shifted by the measured skew; nothing else compares wall clocks |
| A huge or hostile transcript | the hub caps an entry at 256 kB and a frame at 1 MB, drops the rest of that entry with a logged warning, and refuses a gap in offsets rather than guessing. Every other string a node sends is cut before the daemon sees it (`hub_nodes.MAX_*_CHARS`: a folder or file name 4096, a name, title or tool 200, a description 2000, a preview 20 000); a read-out over 1000 characters is dropped (tap only), never cut |
| A node names its session after one on the hub, so the hub's requests go to the node | a session on the hub always keeps its plain name: a remote session holding it is renamed `<name> <machine>` when the local one joins (`_tell_apart`) |
| A node names its session `yes` or `no`, so the user's answer to a prompt goes nowhere | a name, title or folder alias with a yes or no word is refused, on every machine (`sessions.answers_a_prompt`) |
| A node titles its session to extend one on the hub (`shop deploy` beside `shop`), so requests for it go to the node | a name or title sharing a distinctive word with a session on another machine is refused (`Registry.cross_machine_problem`), except the machine suffix |
| A node floods permission requests | the node serializes one prompt per session (as `_PERMISSION_LOCKS` does, `daemon.py:4087-4098`); the hub announces a non-active session's prompt in one line (`daemon.py:4162-4165`) |
| A credential in a remote command reaches a screen or notification | it does not: masked on the node, and an unreadable request shows only its tool in a notification (`alerts.py:40-47`) |

### Failure modes

| Event | What happens | The user sees / hears |
|---|---|---|
| Link drops (VPN down, node asleep) | heartbeat dead after 12 s; the hub marks the node and its sessions **offline** (kept, not removed); workers keep following the mirror (nothing new arrives); node reconnects with backoff. After 10 minutes offline `RemoteHarness.alive` turns false and `_reap_dead` moves them to `departed` | the group greys out with "offline since 14:02"; a send to one is refused and the voice says "devbox is offline"; a prompt it held went back to its terminal |
| Node offline mid-approval | the node keeps the hook held for a grace window of 20 s (`GRACE_SECS`, `node.py`), so a hub restart or a short network drop does not lose it; if the hub is back within it, the node re-offers the prompt (below); else it releases the hook with `None` and the prompt is in the terminal. The hub's card says "offline: answer it in its terminal"; a late tap or yes gets `stale`. A link back with `approvals: terminal` hands it back at once; a link back with no call up yet (a restarted hub, before its page reconnects) keeps it for the rest of the grace window and re-offers it when `call` says the call is up | one line: "devbox dropped; shop's approval waits up to 20 seconds for it, then goes to its terminal" |
| Hub restart | `REGISTRY` reloads remote sessions offline; the node reconnects; `welcome.resume` carries the persisted `next_offset` per mirror; the node ships what the hub missed and, for prompts still held in the 20 s grace window, lists them as `pending` in its `sessions` snapshot and re-sends `permission.request` with the same `request_id` (and the remaining `deadline_ms`; `holding` is due again within 10 s), which the hub puts to the user again (as `_on_connect` re-asks local ones, `daemon.py:5105-5111`) | the call reconnects as today; a held prompt is read out again |
| Node restart | its `sessions.json` reloads and dead pids are dropped (`sessions.py:138`); it reconnects and sends a fresh `sessions` snapshot; the hub reconciles (joins, lefts) | a session that died meanwhile is announced as closed, in one line |
| Hub has no call up, or `approvals: terminal` on the hub | the node's hook returns `{}` at once: the prompt stays in the terminal, as a local session's does | nothing; as today |
| The hub does not answer `holding` within 10 s | the node hands the prompt to the terminal and sends `permission.resolved {how: timeout}`; a later verdict is `stale` | the card disappears |
| The user answers in the terminal first | the node's `gone()` sees it; `permission.resolved {how: terminal}`; the hub clears the card | the card disappears |
| Two sessions named `shop` on two machines | the hub suffixes the later one with the machine, the way it suffixes a second harness (`daemon.py:4006-4014`): `shop devbox`. A session on the hub always keeps the plain name: a remote `shop` that joined first becomes `shop devbox` when a local `shop` joins | "shop devbox finished…" |
| Same session id on two nodes (a cloned VM) | hub ids are prefixed by node; and a clone with the same node key cannot connect while the original is connected | |
| A node is revoked while its session holds a prompt | the link closes; the node hands the prompt to the terminal | the group disappears; one line |
| Invite expires, is mistyped, or the address is rate-limited | `403 invite expired` / `403 wrong code` / `429` | `pointe node join` prints the hub's message |

### Latency budget

The link adds one round trip each way. Tailscale between two machines on the same LAN is usually under 10 ms; over
WireGuard across sites 20 to 60 ms; Twingate 30 to 100 ms.

| Path | Today | Added | Budget |
|---|---|---|---|
| Transcript line written → fed to the brain | up to 0.3 s (`sessions.py:535`) | node tail (0.3 s) + 1 RTT + hub tail (0.3 s) | a report from a remote session is spoken within 0.7 s of when a local one would be |
| Permission: hook fires → read-out starts | `_read_out_when_quiet` waits for the brain to go quiet (`daemon.py:4245-4251`) | 1 RTT (`holding` is sent before that wait) | under 150 ms added |
| Yes → hook released | 1 s poll in `_hold_one` (`daemon.py:4112-4113`) | 1 RTT + node re-check | under 150 ms added; the 1 s poll on the node is the floor, as today |
| Send → typed into the session | inbox write | 1 RTT | under 150 ms added |

`pointe hub nodes` and the Machines section show each node's round trip (`Heartbeat.rtt_ms`, `phone.py:62-66`).

## Routing and the brain

### Session names

- `Session.machine: str = ""` (`""` is this machine); persisted. The hub's own name defaults to its short host name and
  is editable in `config.json` (`"machine": "studio"`); a node's name is set at pairing.
- Collision across machines: when a session joins with a name another machine already uses (same rule as the harness
  suffix, `daemon.py:4006-4014`), it is named `<name> <machine>` if that is `valid_name` and passes `rename_check`; else
  the registry's `-2` fallback (`sessions.py:149-153`). Between two remote sessions, the first to join keeps the plain
  name. A session on the hub always keeps it: a remote one that holds it is renamed `<name> <machine>` when the local one
  joins (`_tell_apart`), so "tell shop" never goes to another machine because that session joined first. The hub's own
  name is never a suffix (that would make it an alias of one session).
- A session may not be named, or renamed to, a machine's name (`rename_check` and `_session_name` refuse it), and a node
  may not take a name whose words are in a session's name (pairing refuses it).
- A session's name, local or remote, may not hold a yes or no word (`guards._YES`, `_WEAK_YES`, `_NO`;
  `sessions.answers_a_prompt`): a session called `yes` would take the user's yes to a prompt as aimed at it. A folder
  with such a word is not an alias either.
- A session may not take a name, or a title, that shares a distinctive word with a session on another machine
  or is one letter off one (`shops`; `Registry.cross_machine_problem`): a node titling its session `shop deploy` beside the hub's `shop` would take
  "what is shop doing with the deploy". The machine suffix (`shop devbox` beside `shop`) is the one exception. A node's
  session whose name is refused at join is called `session <id>`.
- `sessions._aliases` (`sessions.py:357-367`) adds `(machine, 0)` for a remote session, as it adds the harness label.
  **The machine alias is scored only against address slots**: the positions `_address` marks (`sessions.py:312-355`,
  used at `sessions.py:407`), where the words say who something is for ("tell X", "on X", "the X one"). A machine word
  inside a request ("fix the devbox config") names nothing. The hub's own machine name is not an alias (every "on this
  Mac" would match), as `claude` is excluded today.
- `_spoken_names` (`daemon.py:733-740`) says the machine only when the name was suffixed with it. The machine is said
  on a switch across machines ("Now on shop, on devbox"), in "everywhere" answers, and when asked where something runs.
  Not in every report (owner decision).

### What the brain sees

- `list_sessions` (`daemon.py:3593-3600`) adds `machine` and `online` per session. The tool description says sessions
  may be on several machines and that "everywhere" questions are answered grouped by machine.
- `_brain_context` (`daemon.py:669-694`) adds one line when more than one machine has sessions: `Machines: studio (this
  Mac, 3 sessions), devbox (Linux, 2 sessions, 23 ms), laptop (offline since 14:02, 1 session).` `_needs_now`
  (`daemon.py:2994-3018`) names the machine after the agent in each line (`shop (Claude on devbox, working)`), and marks
  offline sessions `OFFLINE: cannot be sent to`.
- `_classify_target` (`daemon.py:3201-3228`) lists the machine next to the folder, so "the one on the VM" resolves.
- `send_to_claude_code`, `switch_session`, `ask_about_session` take session names, which are unique across machines, so
  no tool schema changes.

### Voice intents

| Said | Decided in code |
|---|---|
| "go to devbox", "switch to the devbox one" | `switch_intent` + `name_groups` with the machine alias in an address slot: one session there → switch; several → a tie → "which on devbox: shop or api?" (the existing tie path, `daemon.py:3633-3637`) |
| "tell devbox to pull" | `_route` names → one session or a tie, as above |
| "tell everyone on devbox to pull", "everyone except the laptop" | `broadcast_intent` and `excluded_sessions` (`guards.py:254-266`, `sessions.py:439-444`) learn `on <machine>` / `except <machine>` through the same alias, so the broadcast is scoped to the machine's sessions |
| "what's going on everywhere", "what's on devbox" | the brain calls `list_sessions`; `status_intent` (`guards.py:287-294`) also injects `_needs_now`, grouped by machine when more than one machine has sessions |
| "where is shop running" | answered from `list_sessions`; the brain is told machine names are facts from the list, never from memory |
| a yes to a remote prompt | identical to today on the hub; the node re-checks |

Session mode pins to a session on any machine. There is no "machine mode": the machine filter on the screens is a view,
and routing stays orchestrator or session, so `_route` (`daemon.py:3084-3127`) gains no third branch.

## UI

Status (`/voice/status`, `daemon.py:4581-4626`) adds:

```
"machines": [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true, "sessions": 3, "need": 1},
             {"id": "n3f2a1", "name": "devbox", "here": false, "os": "linux", "online": false, "since": 1731590520.0,
              "sessions": 2, "need": 0, "rtt_ms": 23, "key_fp": "3f2a9c…"}],
"sessions": [..., {"name": "shop devbox", "machine": "devbox", "online": false, ...}],
"invite": null | {"code": "K7PQ-2MXD", "expires_in": 540}
```

With one machine, `machines` has one entry with `here: true` and both clients render as today. `invite` is sent only to
the page cookie and the phone key, never to a page over the TLS listener. New routes, both page and phone key:
`POST /voice/hub/invite` (make or cancel a code), `GET /voice/hub/nodes`, `POST /voice/hub/revoke {name}`.

### Page (`ui.html`)

- **Sessions column grouped by machine** when `machines.length > 1`: a header row per machine (name, OS glyph,
  "offline since 14:02" or "23 ms", "N need you"), collapsible, state in `localStorage`. Within a group the existing sort
  (urgency, then name; `ui.html:868`) holds. This Mac's group is first.
- **Filter chips** above the list: `All · studio · devbox · laptop`. A chip filters the list and the "Orchestrating N
  sessions · M need you" line (`ui.html:1057-1060`) to that machine. Client-side only; it sends nothing and changes no
  mode.
- **Machine tag** on each session row when more than one machine has sessions and the filter is All, next to the agent
  badge, with the rule the agent badge follows (`agentBadges`, `ui.html:855-856`): shown only when it tells something
  apart.
- **Approval card** (`approvalCard`, `ui.html:857-862`) shows `shop · devbox` and, if the node is offline, replaces
  Approve and Deny with "offline: answer it in its terminal".
- **Offline group**: greyed rows, no Approve/Deny, click still focuses (so you can ask about it from the notes), the
  row's title says "offline since …; sends are refused".
- **Settings → Machines**: the paired nodes (name, OS, online or offline since, round trip, key fingerprint), "Invite a
  machine" (shows the one-time code as text with the 10-minute countdown and a Cancel), Revoke with a confirm.

### iPhone app (`ios/Pointe`): full parity

- `API.Session` (`API.swift:356-385`) gains `machine: String?` and `online: Bool?`; `API.Status` gains `machines` and
  `invite`.
- `SessionChips` (`Sessions.swift:14-80`): **machine filter chips at the top of the strip** (`All · studio · devbox`),
  a **machine badge** on a session chip when `sessions.mixesMachines`, like `AgentBadge`; an offline session's chip is
  **dimmed** with "offline"; the context menu adds "Sessions on <machine>", which opens the Sessions sheet on that section.
- Sessions sheet: **a section per machine** with the header data (OS, online or since, round trip); an offline section
  shows "since …". A tap focuses as today.
- **Approval card and notifications** show `shop · devbox` (`alerts.permission_alert` title, `alerts.py:40-47`); no
  Approve when offline. The body stays the read-out form, which is the node's.
- **Settings → Machines**: the list with online state and round trip; **"Invite a machine" behind Face ID**, showing
  the one-time code as text with the countdown (the user types it into `pointe node join` on the other machine; the
  invite line's host, port and fingerprint are the ones the app itself paired with, so the app shows the full
  `pointe://hub?…` line to copy); **Revoke behind Face ID and a confirm**.

## Migration from `bin/voice-remote`

What it is: a 56-line script from the first commit (`git log -- bin/voice-remote`: only `558414b`) for reaching the
**browser page** from a phone over Twingate. `setup <host>` makes a CA constrained to one name, a leaf certificate, a
`remote_token` and `remote.json` (`bin/voice-remote:10-49`); `link` prints `https://<host>:7443/voice?pair=<token>`
(`:50-53`); `off` deletes the lot (`:54`). `remote.py` still honours that flow: `Remote.guard` turns `?pair=` into the
`pointe_pair` cookie (`remote.py:78-85`) and its 403 text points at `bin/voice-remote link` (`remote.py:95`).

What replaced it: `pair.py` writes the same `remote.json` and `remote_token` (`pair.setup`, `pair.py:120-130`) with a
self-signed certificate the app pins by fingerprint, and the iPhone app replaced the browser page as the phone client
(`docs/phone.md`, "The browser page (older way)").

Decision: **absorb, then delete in a separate small PR** (owner decision).

1. In this work: `pointe pair link` prints the browser pairing URL (what `voice-remote link` did) from `remote_token`,
   and `pointe pair off` removes `tls/`, `remote.json`, `remote_token`. `pointe pair rotate` forces a new certificate
   (today `pair._covers` keeps one that still names the host, `pair.py:100-117`) and says that the phone and every node
   must pair again. A phone browser trusts the self-signed leaf directly (Settings → Certificate Trust) instead of the
   nameConstrained CA; the scope is the same one name.
2. The node link reuses the listener `pair.py` configures. Nothing of `voice-remote` is built on: it has no pairing
   exchange, no per-client key, and a lasting URL secret `SECURITY.md` already calls a password.
3. **Separate PR, after `pointe pair link|off` ships**: delete `bin/voice-remote`; update the four mentions:
   `docs/phone.md:45-50`, `SECURITY.md:192-194` (the "Phone access (experimental…)" paragraph, which also describes
   `bin/voice-connector`, which stays), `remote.py:95`, and `docs/design/2026-11-mobile-plan.md:56`.
4. `voice-remote off` left the connector and its tokens in place (SECURITY.md notes this); `pointe pair off` does the
   same and says so, since the connector is `bin/voice-connector`'s.

Anyone who ran `voice-remote setup` keeps working: `remote.json` and `remote_token` are the files `pair.py` reads.

## Test plan

### Offline (no keys, in `tests/`, run by CI on Ubuntu)

- `tests/test_nodelink.py`: frame encode/decode, unknown types ignored, heartbeat death, the nonce challenge (right
  key, wrong key, replayed `hello` on a new connection fails), one connection per key (4409), the 1 MB / 256 kB caps,
  complete-lines-only shipping (a partial tail is held back).
- `tests/test_node.py`: `node.py` against a fake hub (`fastapi.testclient` WebSocket): registration from
  `register-session`'s body shape; transcript shipping with offsets (`offset`/`next_offset` match the node file's
  bytes) and masking (a line holding `ANTHROPIC_API_KEY=sk-…` arrives masked, an ordinary `port: 7860` does not);
  repoint; the hook path: a request forwarded with the node's `readable`, hub `holding` within 10 s or back to the
  terminal; **the re-check table above, one test per row**, including `spoken` off by one character, a stale id,
  `approvals: terminal`, `remote_taps: readable_only` refusing a tap on an unreadable request and allowing one on a
  readable one; `gone()` → `permission.resolved`; link drop mid-hold releases `None` after the grace window, and a hub back within it is re-offered the same
  `request_id`; the import-set assertion (no
  Pipecat, onnxruntime or vendor SDK in `sys.modules`); `lsof` absent → `ss` fallback → `/proc` fallback in the hook
  (run the real script with `PATH` trimmed).
- `tests/test_hub_nodes.py`: `daemon.py` against a fake node: a remote session appears in `/voice/status` with
  `machine`; its mirror is followed and a `finished its turn` line produces a report (reuse `tests/test_orchestrator.py`'s
  fake model); **hub restart with masked entries**: entries whose masked length differs from the source are appended,
  the `.offset` file holds the node's `next_offset`, the daemon is re-created on the same state dir, `welcome.resume`
  carries that offset, and a gap frame is refused with `resume`; `transcript.repointed` → `RemoteHarness.transcript_path`
  returns the new mirror and `_follow_one` reopens; a send goes out as a `send` frame and the result is honoured;
  `/voice/approve` on a remote request becomes `permission.answer` and a `permission.answered {ok: false}` turns into the
  existing "did not reach" line; the node's `readable` is used after the cheap checks and a `readable` holding a consent
  word is treated as unreadable; `call {approvals_terminal: true}` when the hub's config says so; name collision →
  `shop devbox`; a session renamed to a machine's name is refused; offline marking after heartbeat death, `departed`
  after 10 minutes (clock injected); `Registry.load` keeps remote sessions offline; `since` shifted by `skew` in
  `recent_history`; "go to devbox" with one and with two sessions; "fix the devbox config" names nothing; "everyone on
  devbox"; `_needs_now` grouping; mirror pruning.
- `tests/test_security.py` (append a section): `/voice/node` refuses without a good HMAC, with the phone key, with the
  page cookie, and on the loopback listener from a non-local `Host`; `/voice/node/pair` refuses without an outstanding
  invite, a wrong code, a sixth attempt in a minute from one address, a reused code; a revoked key gets 4401; `invite`
  is absent from status over the TLS listener; mirrors are 0600.
- `tests/test_pair.py`: the invite URL round trip, `speakable` and the session-word rule on node names, the fingerprint
  and source address in the pairing result.
- `tests/test_mixed_harnesses.py`: a remote OpenCode session beside a local Claude Code one, each with its own prompt;
  a remote session's `capabilities.side_questions` is false and `ask_about_session` falls back to the reader.

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
`finished its turn` in the hub journal); `voice-daemon stop` + `ensure` on the hub → the node resends from the persisted
offset and a pending prompt is read out once; two sessions called `shop`; "go to devbox-sim"; "what's going on
everywhere"; a second `node join` while paired is refused.

### A Linux node in Docker

`tests/e2e/linux_node/Dockerfile`: `python:3.12-slim`, `uv`, the checkout mounted read-only, `uv sync --locked
--only-group node`. Reaches the hub on the Mac through `host.docker.internal:7444` (the hub paired with `host 127.0.0.1`;
the node pins the fingerprint, so the name does not matter). Two runs:

1. **Synthetic session, real scripts**: register a session with `pid` of a `sleep infinity` and a transcript the test
   appends to, as `tests/e2e/page_show.py` does for Show; the permission is raised by running the real
   `bin/voice-permission-hook` with a hook JSON on stdin, inside the container, once with `lsof` installed and once
   without it; checks the mirror arrives masked, a report is spoken, the hook's stdout carries the hub's decision after
   a tap, and a stale id is refused. No model key in the container.
2. **Real Claude Code** in the container with `ANTHROPIC_API_KEY` injected at `docker run -e` from the Keychain (never
   in the image or a file): `/pointe:voice`, one request, one voice approval of `git status`.

### Real hardware checklist

- Mac Studio hub, MacBook node over Tailscale: pair (check the source address and fingerprint shown), join two sessions,
  orchestrate across both, switch by machine, approve by voice and by tap, close the MacBook lid (offline within 15 s,
  back within 30 s of waking, no lost or duplicated lines).
- Linux VM over Twingate: pair with the hub paired by `host <alias>`, Claude Code and Codex (`codex --remote unix://`) on
  the node, one prompt each at once; a VM without `lsof`.
- LAN only (`pointe pair wifi`), Wi-Fi address change: the node reconnects after `pointe pair wifi` + a new invite
  (documented as the Wi-Fi limit, as for the phone).
- iPhone app and a node at once on the TLS listener; invite from the app (Face ID), revoke from the app; approve a remote
  prompt from the watch (notification approve), and confirm the node refused a forged `how: notification` for an
  unreadable request in its log.
- Hub asleep: node backoff visible in `pointe node status`; wake → resume from the persisted offset.
- Round trips shown in `pointe hub nodes` match `tailscale ping`.

## Build plan

Four tracks that can run in parallel. The contract between them is this document: the frame tables, the status fields,
and the `Session.machine` field. **Day one** has three small commits, each in files no other track touches, and they
land before anything else:

1. Track A: `nodelink.py` (frame schema, HMAC challenge, heartbeat) and the `_NODE_PATHS` lines in `guards.py`.
2. Track C: move `ClaudeSessionWorker` from `sessions.py` to `daemon.py`; add `harnesses.of(session)` in
   `harnesses/__init__.py` and switch the four `sessions.py` call sites and `daemon.py`'s to it (a mechanical change
   with `tests/test_orchestrator.py` as the check).
3. Track B: the `node` dependency group in `pyproject.toml` and `uv.lock`.

After that, no two tracks edit the same file.

| Track | Owns | Delivers |
|---|---|---|
| **A. Link, pairing, hub side** | `nodelink.py` (new), `hub_nodes.py` (new: `NodesRegistry` with 0600 keys, invite and pair routes with per-address rate limit, the `/voice/node` WebSocket handler with the nonce challenge and one-connection-per-key, mirror writer with `.offset` files and pruning, skew), `harnesses/remote.py` (new), `pair.py` (`invite`, `link`, `off`, `rotate`), `remote.py` (nothing beyond the 403 text), `guards.py` `_NODE_PATHS` lines only (day one), `bin/pointe` (`hub` subcommands), `tests/test_nodelink.py`, `tests/test_hub_nodes.py`, `tests/test_security.py` node section, `tests/test_pair.py` | a hub that accepts nodes and shows their sessions, with a fake node in tests |
| **B. Node** | `node.py` (new), `bin/voice-node` (new), `bin/voice-daemon` (node-mode branch, `ours()` fallback), `bin/voice-permission-hook` (`ss` and `/proc` fallbacks), `bin/voice-open` (node message), `pyproject.toml` `node` group (day one), `tests/test_node.py`, `tests/e2e/linux_node/` | a node that ships a transcript with offsets, delivers sends and holds and re-checks prompts, against a fake hub; runs on Linux without `lsof` |
| **C. Brain, routing, status** | `sessions.py` (`machine`, `PERSISTED`, address-slot machine alias, machine-name refusals, `harnesses.of` at its four sites, `since` skew hook; day one: the worker move), `harnesses/__init__.py` (`of()`, day one), `daemon.py` (`ClaudeSessionWorker` lands here; `register_remote`, `status` fields including `machines` and `invite`, `list_sessions`, `_brain_context`, `_needs_now`, `_classify_target`, `_spoken_names`, `_tracked_files`, `_deliver_verdict` and `_drop` for remote, offline handling, `call {approvals_terminal}`), `guards.py` intent functions (after A's day-one lines), `brain.py` if a prompt line is needed, `tests/test_orchestrator.py`, `tests/test_units.py`, `tests/test_mixed_harnesses.py`, `bench/` cases for the new intents | a daemon that treats a `Session` with `machine` set correctly everywhere, against a fake `RemoteHarness` until A lands |
| **D. UI and docs** | `ui.html` (groups, filter chips, tags, offline, Settings → Machines with invite and revoke), `ios/Pointe/{API,Sessions,CallView,Alerts,Settings}.swift` (parity list above, Face ID gates), `ios/PointeUITests/ParityUITests.swift`, `tests/e2e/page_parity.py`, `docs/multi-machine.md` (user doc), `README.md` (one feature row, Architecture block), `SECURITY.md` (a "Machines" section with the honest tap sentence), `docs/harnesses.md` (one paragraph: adapters run on the session's machine; remote sessions have no forked side questions), `plugin/commands/` (`/pointe:voice` and `/pointe:doctor` output on a node) | both clients rendering `machines`, `machine` and `invite` from a recorded status fixture, then live |

### Track A as built: the seam with Track C

`hub_nodes.py` is the hub side; `harnesses/remote.py` is `RemoteHarness`. It uses the seam Track C defined in
`harnesses/__init__.py`: it calls `HOST.register_remote(node_id, machine, entry)` for every entry of every snapshot,
`HOST.remote_permission(...)` (and sends `permission.holding` only when it returns True), `HOST.remote_resolved(...)` and
`HOST.call_state()`; it sets `HOST.on_call` (sends `call` to every node) and `HOST.invite` (the outstanding code); it keeps
`sessions.MACHINES[name]` current (online, since, rtt_ms, skew, os, key_fp, id). `RemoteHarness.answer(...) -> bool` and
`leave(session)` go over the link. A session the node no longer lists, or a revoked node's, is no longer `alive()`, so
`_reap_dead` takes it off; an offline node's sessions stay alive for `OFFLINE_GRACE_SECS`.

The one call site daemon.py needs, after `app.router.lifespan_context = _with_housekeeping` (install wraps the lifespan):

```python
hub_nodes.install(app, hub_nodes.Hub(STATE_DIR, REGISTRY))
```

Optional: `HOST.vendors = lambda: [...]`, the hub's vendor names for `welcome` and the pairing reply (empty without it).
The phone app needs `/voice/hub/invite`, `/voice/hub/nodes` and `/voice/hub/revoke` in `guards._PHONE_PATHS`; the page
and the daemon token reach them already, a browser over the TLS listener never does.

Deviations from the text above, decided while building:

- `welcome.resume` and `resume` are keyed by the **node's** session id (the `id` every frame carries), not the hub's.
- The invite code is compared by its SHA-256, but the plain code is also kept in memory (never on disk) while valid,
  because status `invite.code` must show it.
- `permission.holding` is sent once the daemon's `remote_permission` returns True: it returns before the read-out is
  spoken, so the ack still never waits for the brain. False sends nothing; the node hands the prompt back in 10 s.
- A session the hub has no mirror of arrives from offset 0: that backlog goes to `<id>.<gen>.jsonl.part`, which the
  follower cannot see, and becomes the mirror after `HISTORY_QUIET_SECS` (1.5 s) without a frame. The follower opens it
  at its end, so history is in the record but not fed as news. A live line in the second after that can be missed (the
  follower polls for the file once a second), as for a local session's first lines.
  A `.part` left by a hub restart mid-backlog gets the same quiet timer when its node reconnects: the rest of the
  backlog (resumed from the `.offset` file) still goes to it, and if nothing more comes it becomes the mirror.
- `pointe hub invite --name X` wins over the name the node offers.
- A departed session's mirrors go 7 days after the hub first sees it off the voice (a `<id>.left` mark).
- `pointe pair link|off|rotate`; `pointe hub invite|nodes|revoke` (daemon token); `pointe node ...` runs `node.py` in
  `$STATE/node-env` with only the `node` group.

Integration, after the tracks: `tests/e2e/two_machines.py`, the Docker run, the hardware checklist. Then the separate
small PR that deletes `bin/voice-remote` (needs Track A's `pointe pair link|off`).

Phase 2, not in the tracks above: Show while it says for remote sessions (`artifact.render` frames; the node keeps its
own last ten sets so it never takes a path from the hub, matching `docs/features/show-while-it-says.md`, "What it will
not show"); challenge evidence from remote diffs (`_challenge_diffs`, `daemon.py:2071-2087`, runs `git` in `cwd`: skip
remote sessions until then, and say so in the challenge's evidence line); forked side questions on the node.

## Open questions for the owner

The four questions in the first revision are decided (one hub per node; masked transcripts may reach the hub's vendors;
the machine is said only when ambiguous, on cross-machine switches and in "everywhere" answers; `voice-remote` goes in
its own PR). One remains:

1. **`remote_taps: readable_only` default.** Proposed off, so a remote tap approves what a local tap approves today and
   nothing changes for the user. Turning it on by default would make every unreadable prompt on a node (about 87% of
   shell commands, by the measure in `SECURITY.md`) answerable only in that node's terminal. Keep the default off?
