# People and machines: several voices on one machine, several machines in one voice

Status: phase 1 built (phase 1 of the multi-machine plan). This file is the contract the daemon, the page, the iPhone
app and the Mac app were built to, corrected where the code came out different; each such place says "As built". The
guide for people who use it: [../multi-machine.md](../multi-machine.md). The threat model:
[SECURITY.md](../../SECURITY.md#people-on-a-machine). [multi-machine.md](multi-machine.md) is the first design (one voice, its own machines),
and everything there still holds.

## Words

| Word | Meaning | Before |
|---|---|---|
| **Your voice** | One person's Pointe: the call, the brain, the notes, the keys | The hub |
| **Machine** | A computer whose sessions a voice can reach | A node, or the hub itself |
| **Person** | Somebody whose voice the owner of a machine invited to it | Did not exist |
| **Owner** | Of a machine: the account its Pointe runs as. Of a session: the person who joined or started it. As built, phase 1: every session on a machine is its machine owner's, because a person cannot join or start one there yet | Implied |

The screens and the documents say "your voice", "machines" and "people". The command line keeps `pointe hub` and
`pointe node` as they are, and adds `pointe machine add|list|remove`, `pointe machines`,
`pointe people [invite|grant|remove]` and `pointe share`.

**The owner's name** (as built) is `"owner"` in the machine's `config.json`, else the name of the OS account Pointe
runs as (`guests.owner_name`). It is what people's voices show, what the agents read, and what "busy" names.

## The trust model, plainly

The owner's rule: **the people with access to a machine are legitimate.** A shared machine has one OS account. A
person invited to it can make its agents run commands as that account, and sessions Pointe starts skip permission
prompts by default. Pointe does not isolate people from each other on one account: the operating system cannot, so
Pointe cannot. What Pointe does add:

- **Identity.** Each person has their own key. Nobody shares a secret, and removing a person removes only their key.
- **Attribution.** The machine stamps every request with the person who sent it. The agent sees the name, the owner's
  voice notes it, and every other voice on that session is told. A voice cannot claim another person's name. As built,
  the tag the agent reads starts "[Voice request from Dana, a person invited to this machine, relayed by Dana's voice
  assistant" (`sessions.person_prefix`); the owner's own requests keep "[Voice request from the user, relayed by their
  voice assistant".
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

The first time, her screen says once which services her voice sends that machine's transcripts to, and Avi's People
list shows them next to her name. As built, each surface has its own sentence for it (the page's `PEOPLE_SAYS.disclosure`,
the apps' `PeopleCopy.disclosure`, `machines.vendors_line` in the terminal), and the list is what her voice names: the
machine cannot check it.

## What is shared

- Every session on the machine is shared with every person invited to it, unless its owner marks it **private**
  (`pointe share shop --private`, or the session's row menu). As built there is no voice phrase for it.
- A person's grant is **send** (the default: they can talk to the sessions) or **watch** (they see and hear only).
- Sessions on the machine's own other machines (its nodes) are not passed on. Only its own sessions are shared.

## What the machine enforces

The machine (the host side, `pointe/guests.py`) decides, never the person's voice:

| Rule | How |
|---|---|
| Who is linked | An HMAC over a fresh nonce with the person's key, as a node proves itself today |
| Which sessions a link sees | Its snapshot, transcripts, files and prompts carry shared sessions only. A private session is in no frame to anyone |
| Who may send | `send` grant, checked on the machine. A `watch` link's send is refused: `send.result {ok: false, why: "watch"}`. As built, the first reason that holds is the one given, in this order: `private`, `watch`, `prompt`, `consent`, `busy` (`HostSide.refusal`) |
| Who sent | `by` is set from the link. A `by` in a frame from a voice is ignored |
| One request at a time | A send to a session that is working on another person's request is refused with `why: "busy"` and `busy: {by, since}`. The voice says "Not sent. shop is working on Dana's request from 14:02. Say send it anyway, and it goes." The same send with `anyway: true` is delivered. As built: a session that works on a turn no person asked for is busy with the owner's name (the owner typed it, or asked from their own call); a person's request counts as the session's work until its turn ends, with 15 seconds for the turn to show; and the voice sends `anyway` only for the person's own whole "send it anyway", once, within 120 seconds of the busy refusal (`daemon.ANYWAY_SECS`) |
| A claimed approval | A send that claims somebody's consent ("Avi said yes") is refused (`"consent"`), and so is a send while the session waits on a permission prompt or a sandbox request (`"prompt"`). As built the consent rule is `guards.claims_consent`, given the names of the owner and of the people on the machine |
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

As built, the other direction: a voice that removes a machine sends `bye`, deletes its key and forgets the machine.
The machine closes that link and keeps the person listed, not linked, with their key: taking a person off a machine is
its owner's to do (`pointe people remove`).

As built, a person's voice is offered no prompt, no session to add and no file: `permission.answer` is answered
`permission.answered {ok: false, why: "not_offered"}`, `discover` with an empty list, `attach` with a refusal and
`artifact.render` with an empty result. A session's entry carries `pending: null` and `capabilities.approvals: false`;
one that waits on a prompt says so in its wait state.

Version skew is the node link's ([../multi-machine.md](../multi-machine.md#versions-an-old-pointe-next-to-a-new-one)):
no protocol in common closes with 4426 and says which side to update.

## HTTP, on the machine that invites (the host side)

Owner only: the page on the machine, a script with its token, or the owner's phone. Never a browser over the TLS
listener, and never a person's key.

| Route | Body | Answer |
|---|---|---|
| `POST /voice/people/invite` | `{name, grant?: "send" \| "watch"}`, or `{cancel: true}` | `{code, link, svg, expires_in, name, grant}`; 409 with a sentence when the name is taken or not sayable, or no address is paired. As built, `svg` is the line as a QR code, drawn by the machine as the phone's is |
| `GET /voice/people/invite` | | `{code, expires_in, link, svg, name, grant, paired, ended}` as `/voice/hub/invite` |
| `GET /voice/people` | | `{people: [{id, name, grant, online, since, address, key_fp, vendors, added}]}`. As built, `since` is when the person's link dropped (or when this Pointe started), and `null` while they are linked |
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
| `POST /voice/machines/add` | `{line, name?}`, or `{seen: name}` | `{name, owner, grant, vendors: [..]}` once paired and linking. Else one sentence: 409 only when the name is taken or cannot be said (the screens then ask for another name); 400 for a line that is not an invite, this voice's own machine, or one already added; 403 when the certificate differs or the machine refuses the code; 502 when the machine cannot be reached or its answer is not a pairing |
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
| `sessions[].by` | `{name, since}` while the session works on a person's request. As built, it is in the status of the machine itself (the owner's screens), not in a person's voice |
| `people` | On a machine with people: `[{name, grant, online, since, vendors}]`. Absent with none. `since` as in `GET /voice/people` |
| `account` | As built: on a machine with people, the OS account a person's requests run as, for the owner's trust line. Absent with none |
| `people_invite` | As `invite`: the code that waits, for the owner's screens |
| `disclosure` | `{machine, vendors: [..]}` once after a machine is added, until the person dismisses it (`POST /voice/machines/add {seen: name}`) |

## What each person hears

- A person hears the report of a turn **they** started. A report of a turn somebody else started is held: it counts
  on the screen and is read at "anything from the others?" (`scope.py`, as session mode holds news). As built, this
  applies to sessions on a machine somebody invited the voice to (`daemon._others_machine`); a report is held only
  while a call is up, and with no call it goes to the session's notes alone.
- As built, the owner's voice is not changed: on its own machines every report is spoken as before, whoever started
  the turn. The setting "Read me everything on my sessions" was not needed and is not built.
- "Dana asked shop: run the tests" goes into the notes of every other voice on that session, from the `sent` frame.
  The owner's own voice gets it in its Recent requests ("sent by Dana") and, on a call, in the brain's context.
- Names: a session I own keeps its plain name. One owned by somebody else never wins a tie against mine and never
  renames mine; it gets the machine's name added ("shop avi-box").

## Files

| Where | File | Holds |
|---|---|---|
| Machine | `people.json` (0600) | `{people: {id: {id, name, key, grant, added, address, vendors}}}`, `private: [session ids]`. Unreadable, it is moved aside and nobody can link |
| Machine | `people_tails.json` (0600), as built | Per person, each session's transcript path and generation, so a voice resumes its mirror after the machine restarts |
| Voice | `nodes.json` (0600), as today | A dialed machine is an entry with `dial: {host, port, fp}`, `owner`, `grant`. As built it has this voice's own `id` for the machine, plus `host_id` (the machine's id, checked at each link), `person` (this person's id there), `person_name`, `disclose` (the disclosure is not dismissed yet) and `removed` (the machine removed this person: no key, not dialed) |
| Voice | `harness/remote/<machine id>/` | The mirror of each session's transcript, as for a node |

`pointe pair rotate` and `pointe pair off` (as built) sign out phones, browsers, nodes and every person: each
person's key is deleted from `people.json`, a live link is closed with 4401, and the command says who to invite
again. The private-sessions list stays. They keep the machines this voice dials
([SECURITY.md](../../SECURITY.md#people-on-a-machine)).

## A big fleet

The rules are in `pointe/scale.py` and the tests in `tests/test_fleet_scale.py`. `POINTE_FLEET=off` turns all of them
off, so one build can be measured with and without them.

**Tiers.** Every session is in one tier at a time. In focus: the active session, the thread, sessions that wait on the
user, urgent ones, sessions sent to with no report yet, and sessions named or asked about in the last ten minutes;
twelve at most. An event puts a session in focus, never a model's choice. Background: the rest. Quiet: a background
session the person marked ("keep tide quiet", lifted by "stop keeping tide quiet"), and by default every one past the
twenty most recent on its machine. Recent is by a session's activity when it joined and by the person's words since,
not by its own work.

**The budget.** "What needs me" is at most 1,800 tokens at any size, counted as characters over 3.5. Twelve sessions
or fewer: a line each, as before. More: a full line for each session in focus, then one line per machine ("avi-box
(Linux, 23 ms): 18 more, 15 working, 3 idle, none need you"), and "And 4 more need you: a, b, c, d" for sessions that
wait on the user and found no place in focus. A machine's latency is told again only when it moved a lot, so the
block is the same text from turn to turn when nothing changed.

**Routing.** With more than eight sessions the classifier sees eight at most: the thread, the active session, the
best matches of the request's words against each session's name, goal, title, keywords and file names, then the
sessions in focus. No match and no thread: Pointe asks. A tie of more than eight (a machine named, with many sessions
on it) is narrowed the same way. The same name on several machines is a tie unless the words name the machine; a
session of the user's own on this machine keeps the plain name.

**"Which session?"** Three options at most, grouped by machine when they span machines. More: the machine first
("Which machine? shop is on avi-box, kestrel and 8 more."), and the machine's name alone answers it.

**`list_sessions`** takes `machine`, `owner`, `state` and `query`, returns twenty rows at most, a count of the rest in
`more`, and the per-machine lines. "What's going on everywhere" with more than five sessions is said by the daemon
from its counts, machine by machine.

**Quiet sessions.** A quiet session's finished turn is not read by the reading model. It is read when its last words
end in a question, and its notes are read when it is next named, asked about or sent to.

**Speech.** Approvals first, then sessions that need the user, then the thread's reports, then the rest. More than two
background reports waiting become one line per machine ("Three on avi-box finished: tide, harbor and ferry; ferry has
a question."). Past four background lines in a minute the rest are held for the screen and for "anything from the
others?". A report with a question for the user is never held.

**For the benchmark.** `GET /voice/context` has `fleet`: the block and its token estimate, the count of sessions per
tier, the candidates of the last routing decision with how each was picked, and counters of reader calls made and
skipped, report lines spoken and reports held. The journal has a `fleet:` line for each of these events.

## Not in phase 1

A person approving a prompt or starting a session on the machine (phase 3). The context budget, tiers and quiet
sessions for a big fleet (phase 2). A machine that is only a node (no voice of its own) serving several people: it
still has one voice, its owner's. A voice phrase for Private, a grant, an invite or a removal. Any measurement of how
many machines or people work well together.
