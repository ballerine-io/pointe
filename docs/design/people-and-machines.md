# People and machines: several voices on one machine, several machines in one voice

Status: phases 1, 2 and 3 built. Phase 3 (people approve prompts and start sessions on a machine) is the section
"Phase 3" below, and it changes what phase 1 said about approvals. This file is the contract the daemon, the page, the iPhone
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
| **Owner** | Of a machine: the account its Pointe runs as. Of a session: the person who joined or started it. A session a person started from their voice is theirs (phase 3); every other session on a machine is its machine owner's | Implied |

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
| Approvals | Phase 3, below: a prompt is put to its session's owner first, then to every person who may send. The machine re-checks every verdict. With `approve: "off"` it is phase 1 again: the machine owner's own voice and terminal only |

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

As built, a person's voice is offered no session to add and no file: `discover` is answered with an empty list,
`attach` with a refusal and `artifact.render` with an empty result. Prompts are phase 3, below. A voice that may not
answer a session's prompt (a watch grant, `approve: "off"`, or a voice from before phase 3) gets `pending: null` and
`capabilities.approvals: false`, and a session that waits on a prompt says so in its wait state, as in phase 1.

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

The rules are in `pointe/scale.py` and the tests in `tests/test_fleet_scale.py`. They are off unless the daemon
starts with `POINTE_FLEET=on`, until the fleet benchmark has measured them: one build is measured with and without them.

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

## Phase 3

People invited to a machine answer its sessions' permission prompts and start sessions there. The owner's rule
decides the shape: the people with access to a machine are legitimate, so the best experience wins, and every
answer carries a name. The code is `pointe/guests.py` (the machine), `pointe/hub_nodes.py` and `pointe/machines.py`
(the voice), and the seams in `pointe/daemon.py`. The tests are `tests/test_people_approve.py`.

### Who answers a prompt

1. A session on the machine asks for permission. Its **owner** is asked first: the person who started it from
   their voice, else the machine's owner. The owner's voice reads it out as it reads any prompt.
2. At the same moment every other person with the send grant who sees the session gets the request, marked "for
   the owner first". Their screens show it with who is asked and until when. Their voices read nothing out yet.
3. The owner-first time is 20 seconds (`owner_first_secs`, 0 to 120, the machine owner's setting). When it ends, or
   at once when the owner cannot hear the prompt (no call, or their link is down), the prompt opens: the other
   voices read it out as their own prompts are read, and their screens offer Approve and Deny.
4. The first valid verdict wins, from anybody. The owner can still answer after the prompt opened. The terminal can
   always answer. A second verdict is refused with `why: "answered"` and `by`.
5. A watch-only person is sent no request and can answer none.

On the machine itself, the machine owner's tap always counts, also during a person's owner-first time: they are at
their own machine. Their voice reads a person's session's prompt out only when it opens.

A prompt is held with no call of the machine owner's when a person who may answer is linked with a call up. While
it is held, the terminal does not show it, and the owner may be sitting there. So such a hold is bounded: with no
call of the machine owner's and no answer, the prompt goes to its terminal after 45 seconds (`people_hold_secs`, 10
to 280, the machine owner's setting; `PEOPLE_HOLD_SECS`). Every voice that was offered it gets
`permission.resolved {how: "terminal"}`, and a later answer is refused as `stale`. The time counts from the moment
the prompt is held with the owner on no call; while the owner is on a call nothing changes, and their own deadline
applies. When nobody can answer any more (every such link dropped or ended its call, and the machine's owner has no call), the
prompt goes to its terminal within `HOLD_GRACE_SECS` (20 s). A person whose link drops loses the offer; a verdict
that arrives late is refused as `stale`.

### The machine's re-check

The machine takes a person's verdict only after its own checks, in this order. The first reason that holds is the
one given in `permission.answered {ok: false, why}`.

| `why` | When |
|---|---|
| `not_offered` | The person is no longer on the machine, or the owner set `approve: "off"` |
| `watch` | The person's grant is watch |
| `private` | The person does not see that session (it is private, not theirs, or not this machine's own) |
| `answered` (with `by`) | That request was answered already. `by` is who answered |
| `stale` | No such request is pending for that session: another request id, a request of another session, resolved in the terminal, past its deadline, or held for people only past `people_hold_secs` |
| `not_offered` | The link cannot be offered it now: no call up there, approvals in terminals there, or a voice without the `approve` feature |
| `not_yet` | Somebody else is asked first, and the owner-first time is not over |
| `terminal`, `unreadable`, `mismatch`, `unknown` | The node's re-check table, the same function (`node.recheck`): a deny always passes; an approve is refused when this machine's `approvals` is `terminal`; a spoken yes counts only when `spoken` is exactly the read-out the machine computed from the unmasked request; a notification's approve only for a request with a short readable form; a tap is trusted unless `remote_taps` is `readable_only` and the request has no short form |

A verdict that passes is delivered to the session as the machine owner's own is. The agent sees an approval or a
denial, nothing else.

### Attribution and the record

- The approvals record (`GET /voice/approvals` on the machine) has `person` and `link` on an answer a person gave:
  `{"session": "shop", "request_id": "9f2c41aa", "decision": "allow", "by": "tap", "person": "Dana",
  "link": "100.64.0.7", "request": "Bash\n{\"command\": \"npm test\"}", "lock": "off", "score": null, "at": "..."}`.
  Both are absent on the machine owner's own answers.
- The journal has a `people:` line: `Dana approved shop's request by tap, from 100.64.0.7: Bash: {"command": "npm test"}`.
  A refused verdict has one too: `Dana's yes by voice was refused: mismatch`.
- The machine owner's voice says it ("Dana approved shop's request to run: npm test."), and it is in their notes.
- Every other voice that was offered the prompt gets `permission.resolved {how: "answered", by, verdict}`. It goes
  into that voice's notes, and its screens show `resolved_by` for 30 seconds.

### A person starts a session

"Start a session on avi-box in the shop folder", or the New session sheet with the machine picked.

1. The voice asks the machine for its folder list (`folders`). The list is the machine owner's own: the folders
   their New session sheet shows. A folder that is not on it cannot be said or picked.
2. The read-back names the machine and whose it is: "Start a Claude Code session on avi-box, Avi's machine, in
   shop?" The first time for each machine it adds how that machine starts sessions: "avi-box starts sessions that
   skip permission prompts: it can edit files and run commands as avi without asking." or "avi-box starts sessions
   that ask before actions."
3. A yes (or Start on the sheet) sends `start`. The machine checks the grant and its owner's settings, then runs the
   owner's own start path: the same checks of the folder, the agent and the name, the same launcher, and the
   owner's setting for permission prompts. A consent Claude Code still needs once is the owner's to give: until
   they gave it, such a session asks before actions. `sessions_ask: "ask"` makes every session people start ask.
4. The new session's **owner** is that person. It is shared like every session. The person may mark their own
   session private (`share`): then they and the machine's owner see it, and nobody else. The machine's owner sees
   every session on the machine, always.
5. A first prompt is delivered by the machine as that person's request, under the rules of any send.

Refusals, as the voice says them (`machines.start_refusal`, from `start.result.why`):

| `why` | Sentence |
|---|---|
| `watch` | "Not started. Avi lets you watch avi-box, not start sessions there." |
| `off` | "Not started. Avi turned off starting sessions on avi-box for the people invited to it." |
| `folder` | "Not started. That folder is not on avi-box's list: a session starts there only in a folder Avi works in." |
| `harness` | "Not started. avi-box cannot start that agent: it is not set up there." |
| `busy` | "Not started. avi-box is starting other sessions now. Try again in a minute." (more than 3 in flight) |
| `failed` (with `detail`) | "Not started. avi-box says: ..." with the machine's own sentence, plain words only |
| no answer | "Not started. avi-box did not answer." |

### The machine owner's settings

One set for everybody on the machine, in `people.json` under `settings` (only what differs from the default).

| Setting | Values | Default | Meaning |
|---|---|---|---|
| `approve` | `"anyone"`, `"off"` | `"anyone"` | People with the send grant may answer prompts, or nobody but the machine's owner may |
| `start` | `"on"`, `"off"` | `"on"` | People with the send grant may start sessions here |
| `sessions_ask` | `"default"`, `"ask"` | `"default"` | Sessions people start follow the owner's "Permissions for new sessions", or always ask before actions |
| `owner_first_secs` | 0 to 120 | 20 | How long a prompt waits for its session's owner before the others may answer |
| `people_hold_secs` | 10 to 280 | 45 | With no call of the machine owner's, how long a prompt waits for people before it goes to its terminal |

Set from `pointe people approvals on|off`, `pointe people starts on|off`, `pointe people sessions default|ask`,
`pointe people window <seconds>`, `pointe people hold <seconds>`, or the route below.

### Frames

Protocol stays 2. Two features are added to `FEATURES`: `approve` and `start`. A machine offers a prompt only to a
link that listed `approve`. A voice asks to start only on a link whose machine listed `start`; otherwise it says
"avi-box runs an older Pointe. Its owner updates it there, and then you can start sessions on it."

| Frame | Direction | Fields | Meaning |
|---|---|---|---|
| `permission.request` | machine → voice | as a node's, plus optional `first: {name}` and `yours_in_ms` | With `first`: somebody else is asked first, and this voice may answer in `yours_in_ms`. Without: this voice may answer now. The machine sends the same `request_id` again, without `first`, when the prompt opens |
| `sessions[].pending` | machine → voice | the request this link was last sent, or `null` | A voice that links again gets the prompt it may answer |
| `sessions[].started_by` | machine → voice | a person's name | The person who started the session. `owner` is the same name |
| `sessions[].capabilities.approvals` | machine → voice | bool | This link's person may answer this machine's prompts |
| `permission.answer` | voice → machine | as to a node: `{id, request_id, verdict, how, spoken?}` | A person's verdict. Who sent it is the link's person, never a field |
| `permission.answered` | machine → voice | `{request_id, ok, why?, by?}` | `by`: who answered first, with `why: "answered"` |
| `permission.resolved` | machine → voice | `{id, request_id, how, by?, verdict?}` | `how`: `"answered"` (with `by` and `verdict`), `"terminal"`, `"timeout"`, or `"left"` (this voice may no longer answer: its grant, its call, the setting, or the session went) |
| `call` | voice → machine | `{up, approvals_terminal}` | As to a node: with no call there, that voice is offered no prompt |
| `folders` | voice → machine | `{req}` | Where may a session start there |
| `folders.result` | machine → voice | `{req, folders: [{path, name}], harnesses: [{name, title, available, why}], permissions: "skip" \| "ask", account, why?}` | The machine owner's own list, how new sessions start there, and the account they run as. With `why` (`"watch"`, `"off"`) the rest is empty |
| `start` | voice → machine | `{req, harness, folder, name?, prompt?}` | Start a session |
| `start.result` | machine → voice | `{req, ok, id?, name?, why?, detail?}` | Sent once the session joined there, or with why not |
| `share` | voice → machine | `{req, id, private}` | Keep a session this person started private, or share it again |
| `share.result` | machine → voice | `{req, ok, why?}` | `why`: `"not_yours"`, `"private"` (a session this person does not see) |

A request a person is asked first for, and the same request opened to another person:

    {"t": "permission.request", "id": "s1", "request_id": "9f2c41aa", "tool": "Bash", "description": "Run the tests",
     "preview": "{\"command\": \"npm test\"}", "readable": "run: npm test", "deadline_ms": 279000,
     "first": {"name": "Avi"}, "yours_in_ms": 20000}
    {"t": "permission.request", "id": "s1", "request_id": "9f2c41aa", "tool": "Bash", "description": "Run the tests",
     "preview": "{\"command\": \"npm test\"}", "readable": "run: npm test", "deadline_ms": 259000}
    {"t": "permission.answer", "id": "s1", "request_id": "9f2c41aa", "verdict": "allow", "how": "voice",
     "spoken": "run: npm test"}
    {"t": "permission.answered", "request_id": "9f2c41aa", "ok": true}
    {"t": "permission.resolved", "id": "s1", "request_id": "9f2c41aa", "how": "answered", "by": "Dana", "verdict": "allow"}

### HTTP

On the machine, for its owner only (as the other `/voice/people` routes):

| Route | Body | Answer |
|---|---|---|
| `GET /voice/people/settings` | | `{"approve": "anyone", "start": "on", "sessions_ask": "default", "owner_first_secs": 20.0, "people_hold_secs": 45.0}` |
| `POST /voice/people/settings` | any of those five keys | The settings now; 409 with one sentence for a value a setting does not take |
| `GET /voice/approvals` | | As before. An answer a person gave has `person` and `link` |
| `POST /voice/approve` | as before | As before. The machine owner's tap counts at any time |

On a voice:

| Route | Body | Answer |
|---|---|---|
| `GET /voice/new-session?machine=avi-box` | | `{harnesses, machines, folders: [{path, name, source: "machine"}], max_prompt, machine: {name, owner, permissions, account}}`: that machine's own list. 409 with one sentence when this voice cannot start there now, 403 when the machine refuses, 502 when it does not answer |
| `GET /voice/new-session` | | As before. `machines[]` has `available: true` for a machine this voice may start on, else `why`; and `owner` on a machine somebody invited this voice to |
| `POST /voice/new-session` | `{machine: "avi-box", harness, folder, name?, prompt?}` | `{id, name, machine, notice}`. `notice` is the line about how that machine starts sessions, the first time, else `""`. `permissions` in the body is ignored: the machine's owner decides |
| `POST /voice/approve` | as before | 409 "Avi is asked first. You can answer in a moment." while somebody else is asked first |
| `POST /voice/share` | `{session, private}` | Also for a session this person started on a machine they were invited to. 403 with a sentence for a session that is not theirs |

### The status, `/voice/status`

All optional and absent when they do not apply, so an older app reads the rest.

| Field | Where | Value |
|---|---|---|
| `people_settings` | On a machine with people | `{approve, start, sessions_ask, owner_first_secs, people_hold_secs}` |
| `sessions[].asked` | Machine and voices, while the owner-first time runs | `{name, until}`: who is asked first, and until when (epoch seconds, this side's clock) |
| `sessions[].can_answer` | Machine and voices, on a session whose prompt people may answer | `true` when this side may answer now. On a voice it is `false` while `asked` is there. On the machine it is `true` |
| `sessions[].resolved_by` | Machine and voices, for 30 s after a person answered | `{name, verdict, at}`. `verdict` is absent when this voice only learned who from a refused answer of its own |
| `sessions[].owner` | Machine and voices | May now be a person's name, on the machine too |
| `sessions[].started_by` | Machine and voices | The person who started the session from their voice |
| `machines[].can_start` | On a voice, for a machine somebody invited it to | `true` when this voice may ask to start a session there now (online, send grant, the machine has `start`). The machine's `start` setting is checked there |
| `starting[].machine`, `starting[].by` | Voice; machine | The machine a start runs on; the person who asked for it |
| `start_pending.machine` | Voice | The machine a read-back would start on |

On the machine, while Avi is asked first for shop's request, and after Dana answered tide's:

    "people_settings": {"approve": "anyone", "start": "on", "sessions_ask": "default", "owner_first_secs": 20.0,
                        "people_hold_secs": 45.0},
    "sessions": [
      {"name": "shop", "waiting": true, "request_id": "9f2c41aa", "request": "Bash\n{\"command\": \"npm test\"}",
       "asked": {"name": "Avi", "until": 1790000020.0}, "can_answer": true},
      {"name": "tide", "owner": "Dana", "started_by": "Dana", "waiting": false,
       "resolved_by": {"name": "Dana", "verdict": "allow", "at": 1790000003.5}}]

On Dana's voice at the same moment:

    "machines": [{"name": "avi-box", "owner": "Avi", "grant": "send", "can_start": true, "online": true}],
    "sessions": [
      {"name": "shop", "machine": "avi-box", "owner": "Avi", "waiting": true, "request_id": "9f2c41aa",
       "asked": {"name": "Avi", "until": 1790000020.4}, "can_answer": false},
      {"name": "tide", "machine": "avi-box", "started_by": "Dana", "waiting": false}]

### As built: where it differs from the plan

- A watch-only person is sent no request at all, so their screens show "waits on a permission prompt", not the
  request's text.
- On the machine, the machine owner's tap counts during a person's owner-first time. A person's tap does not count
  during somebody else's: `not_yet`.
- A no from a person is held to the same turn as a yes (`not_yet` before the prompt opens). The node's table lets
  a no through at any time; here the owner asked first keeps that time for both answers.
- A person's voice must have a call up to be offered a prompt, as a hub must for a node's. With no call, their
  screens show no card.
- A voice says how a machine starts sessions once per machine, from what the machine said at that moment. If its
  owner changes the setting later, the voice does not say it again; the sheet's `machine.permissions` is current.
- `start.result` is sent when the session joined on the machine or failed, up to 150 seconds after `start`.
- The machine owner marking a person's session private leaves it visible to that person.
- There is no setting "owner first only": `approve` is `anyone` or `off`.

## Limits that remain

A machine that is only a node (no voice of its own) serving several people: it still has one voice, its owner's. A
person joining a session that already runs on the machine (they start one, or the owner joins it). A person's stop
or interrupt of a session there. A voice phrase for Private, a grant, an invite, a removal or these settings. A
setting per person: these settings are for everybody on the machine. Isolation between people on one account:
there is none, as phase 1 says. Any measurement of how many machines or people work well together.
