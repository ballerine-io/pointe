# People and machines: several voices on one machine, several machines in one voice

Status: being built (phase 1 of the multi-machine plan). This file is the contract the daemon, the page, the iPhone
app and the Mac app build to. [multi-machine.md](multi-machine.md) is the first design (one voice, its own machines),
and everything there still holds.

## Words

| Word | Meaning | Before |
|---|---|---|
| **Your voice** | One person's Pointe: the call, the brain, the notes, the keys | The hub |
| **Machine** | A computer whose sessions a voice can reach | A node, or the hub itself |
| **Person** | Somebody whose voice the owner of a machine invited to it | Did not exist |
| **Owner** | Of a machine: the account its Pointe runs as. Of a session: the person who joined or started it | Implied |

The screens and the documents say "your voice", "machines" and "people". The command line keeps `pointe hub` and
`pointe node` as they are, and adds `pointe machine` and `pointe people`.

## The trust model, plainly

The owner's rule: **the people with access to a machine are legitimate.** A shared machine has one OS account. A
person invited to it can make its agents run commands as that account, and sessions Pointe starts skip permission
prompts by default. Pointe does not isolate people from each other on one account: the operating system cannot, so
Pointe cannot. What Pointe does add:

- **Identity.** Each person has their own key. Nobody shares a secret, and removing a person removes only their key.
- **Attribution.** The machine stamps every request with the person who sent it. The agent sees the name, the owner's
  voice notes it, and every other voice on that session is told. A voice cannot claim another person's name.
- **A record.** Every link, request, share and removal is in the machine's journal with the person's name.
- **A lower grant.** A person can be invited to watch only: they hear and see, and the machine refuses their requests.
- **Private sessions.** The owner can keep a session to themselves. Nothing about it crosses to anyone's voice.

## What a person does

**Avi invites Dana to his machine** (page, iPhone, Mac: Settings → Machines → People → Invite a person; or
`pointe people invite dana`). He gets one line and a QR code, valid once, for ten minutes:

    pointe://machine?v=1&host=avi-box.example&port=7443&fp=<64 hex>&code=K7PQ-2MXD&name=avi-box

**Dana adds the machine** (Settings → Machines → Add a machine: scan or paste; or `pointe machine add '<line>'`). Her
voice checks the certificate against `fp` before it sends anything, trades the code for her key, and links. She sees
the machine with its sessions in her one conversation. Nothing else to do: no follow step, no account.

The first time, her screen says once which services her voice sends that machine's transcripts to (the same sentence
`pointe node join` prints), and Avi's People list shows them next to her name.

## What is shared

- Every session on the machine is shared with every person invited to it, unless its owner marks it **private**
  (`pointe share shop --private`, the session's row menu, or "keep shop private").
- A person's grant is **send** (the default: they can talk to the sessions) or **watch** (they see and hear only).
- Sessions on the machine's own other machines (its nodes) are not passed on. Only its own sessions are shared.

## What the machine enforces

The machine (the host side, `pointe/guests.py`) decides, never the person's voice:

| Rule | How |
|---|---|
| Who is linked | An HMAC over a fresh nonce with the person's key, as a node proves itself today |
| Which sessions a link sees | Its snapshot, transcripts, files and prompts carry shared sessions only. A private session is in no frame to anyone |
| Who may send | `send` grant, checked on the machine. A `watch` link's send is refused: `send.result {ok: false, why: "watch"}` |
| Who sent | `by` is set from the link. A `by` in a frame from a voice is ignored |
| One request at a time | A send to a session that is working on another person's request is refused with `why: "busy"` and `busy: {by, since}`. The voice says "shop is working on Dana's request from 14:02". The same send with `anyway: true` is delivered |
| A claimed approval | A send that claims somebody's consent ("Avi said yes") is refused, with the daemon's own `guards` check, and so is a send while the session waits on a permission prompt |
| Approvals (phase 1) | A prompt is offered to the machine owner's own voice and terminal only. Phase 3 offers it to people |

## The link

A voice dials the machine it was invited to, on the machine's TLS listener (the phone's, port 7443), path
`/voice/host`. After the handshake the link is the node link of [multi-machine.md](multi-machine.md), with the
machine in the node's role: the same frames, heartbeat, offsets, resume and masking.

    machine -> voice   host.challenge  {nonce, now, protocol, protocol_min, features,
                                        host: {id, name, os, arch, version, harnesses}}
    voice -> machine   voice.hello     {auth: HMAC(key, nonce || host id), person, protocol, protocol_min, features,
                                        voice: {name, version}, vendors: [..]}
    machine -> voice   host.welcome    {protocol, features, you: {id, name, grant}, owner}
    voice -> machine   welcome         (as a hub sends a node: call_up, approvals_terminal, vendors, resume)
    ... then the node link's frames, both ways ...

Protocol 2 adds, besides the three frames above:

| Frame | Direction | Fields | Meaning |
|---|---|---|---|
| `sessions[].owner` | machine → voice | a person's name, or the machine owner's | Whose session it is |
| `send.anyway` | voice → machine | bool | Deliver although the session is busy with another person's request |
| `send.result.why`, `.busy` | machine → voice | `"watch"`, `"busy"`, `"private"`, `"consent"`, `"prompt"`; `{by, since}` | Why a send was refused |
| `sent` | machine → voice | `{id, by, text, at}` | Another person sent this to a session the voice sees. Never the voice's own send |
| `you` | machine → voice | `{grant}` | The owner changed this person's grant |

A machine that removes a person sends `unpaired` and closes with 4401. The voice deletes that key, keeps the machine
listed as "avi-box removed you", and stops dialing.

Version skew is the node link's ([../multi-machine.md](../multi-machine.md#versions-an-old-pointe-next-to-a-new-one)):
no protocol in common closes with 4426 and says which side to update.

## HTTP, on the machine that invites (the host side)

Owner only: the page on the machine, a script with its token, or the owner's phone. Never a browser over the TLS
listener, and never a person's key.

| Route | Body | Answer |
|---|---|---|
| `POST /voice/people/invite` | `{name, grant?: "send" \| "watch"}`, or `{cancel: true}` | `{code, link, expires_in, name, grant}`; 409 with a sentence when the name is taken or not sayable, or no address is paired |
| `GET /voice/people/invite` | | `{code, expires_in, link, name, paired, ended}` as `/voice/hub/invite` |
| `GET /voice/people` | | `{people: [{id, name, grant, online, since, address, key_fp, vendors, added}]}` |
| `POST /voice/people/grant` | `{name, grant}` | `{ok: true}` |
| `POST /voice/people/remove` | `{name}` | `{ok: true}`; 404 with a sentence |
| `POST /voice/share` | `{session: <name or id>, private: bool}` | `{ok: true, private}` |

For a person's voice, on the TLS listener, with no key (each proves itself in its handler, as `/voice/node` does):

| Route | Body | Answer |
|---|---|---|
| `POST /voice/host/pair` | `{code, voice: {name, version}, vendors: [..]}` | `{person: {id, name, grant}, key, host: {id, name, os}, owner}`; the same refusals and attempt limits as `/voice/node/pair` |
| `WS /voice/host` | | The link above |

## HTTP, on the voice that adds a machine

| Route | Body | Answer |
|---|---|---|
| `POST /voice/machines/add` | `{line, name?}` | `{name, owner, grant, vendors: [..]}` once paired and linking. Else one sentence: 409 only when the name is taken or cannot be said (the screens then ask for another name); 400 for a line that is not an invite, this voice's own machine, or one already added; 403 when the certificate differs or the machine refuses the code; 502 when the machine cannot be reached or its answer is not a pairing |
| `POST /voice/hub/revoke` | `{name}` | As today. For a machine this voice dialed: it says `bye`, deletes its key, forgets the machine |

`name` is this voice's own name for the machine (default: the machine's). It follows the machine-name rules of
[multi-machine.md](multi-machine.md), "Session names".

## The status, `/voice/status`

Added, all optional so an older app reads the rest:

| Field | Value |
|---|---|
| `machines[].owner` | The owner's name, on a machine that is not this person's own. Absent on their own |
| `machines[].grant` | `"send"` or `"watch"`, on a machine they were invited to |
| `machines[].removed` | `true` on a machine whose owner removed this person. It stays listed, with its `notice`, and is not dialed |
| `machines[].notice` | One line: "avi-box removed you", "avi-box runs an older Pointe (0.9.0). Update it there…" (exists) |
| `sessions[].owner` | The owner's name when the session is not this person's |
| `sessions[].private` | `true` on a session of this machine its owner keeps private |
| `sessions[].by` | `{name, since}` while the session works on another person's request |
| `people` | On a machine with people: `[{name, grant, online, since}]`. Absent with none |
| `people_invite` | As `invite`: the code that waits, for the owner's screens |
| `disclosure` | `{machine, vendors: [..]}` once after a machine is added, until the person dismisses it (`POST /voice/machines/add {seen: name}`) |

## What each person hears

- A person hears the report of a turn **they** started. A report of a turn somebody else started is held: it counts
  on the screen and is read at "anything from the others?" (`scope.py`, as session mode holds news).
- The owner of a session may choose to hear all its reports (Settings → People → "Read me everything on my sessions").
- "Dana asked shop to run the tests" goes into the notes of every voice on that session, from the `sent` frame.
- Names: a session I own keeps its plain name. One owned by somebody else never wins a tie against mine and never
  renames mine; it gets the machine's name added ("shop on avi-box").

## Files

| Where | File | Holds |
|---|---|---|
| Machine | `people.json` (0600) | `{people: {id: {id, name, key, grant, added, address, vendors}}}`, `private: [session ids]` |
| Voice | `nodes.json` (0600), as today | A dialed machine is an entry with `dial: {host, port, fp}`, `owner`, `grant` |
| Voice | `harness/remote/<machine id>/` | The mirror of each session's transcript, as for a node |

## Not in phase 1

A person approving a prompt or starting a session on the machine (phase 3). The context budget, tiers and quiet
sessions for a big fleet (phase 2). A machine that is only a node (no voice of its own) serving several people: it
still has one voice, its owner's.
