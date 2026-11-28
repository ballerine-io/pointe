# Machines and people

Two things are on this page:

- **Your own other machines.** Sessions on another Mac, a Linux host or a VM of yours join your voice: you hear their
  reports, send to them, approve their prompts, and always see which machine each one is on.
- **A shared machine.** The owner of a machine invites other people to it. Each person adds the machine to their own
  voice, and talks to its sessions from their own call, with their own keys. The owner keeps their own voice too.

The designs and the reasons: [design/multi-machine.md](design/multi-machine.md) and
[design/people-and-machines.md](design/people-and-machines.md).

## Words

The docs and the screens say "your voice", "machines" and "people". The command line keeps its older words: every
`pointe hub ...` and `pointe node ...` command still works.

| The docs and the screens say | Meaning | Before, and still in the commands |
|---|---|---|
| **Your voice** | One person's Pointe: the call, the brain, the notes and the model keys. It runs on a Mac or a Linux machine | The hub (`pointe hub ...`) |
| **Machine** | A computer whose sessions a voice can reach: the one your voice runs on, another one of yours, or one somebody invited you to | A node (`pointe node ...`), or the hub itself |
| **Person** | Somebody the owner of a machine invited to it. A person reaches the machine from their own voice | Did not exist |
| **Owner** | Of a machine: the person whose Pointe runs on it. Of a session: the person who started it from their voice, else the owner of the machine it runs on | Implied |

## Your own other machines

Your sessions do not all run on the machine with your voice. Pair your other machines with it, and their sessions join
the same voice. Each other machine runs a small Pointe (`pointe node ...`) with no microphone, no speaker, no models and
no keys. It watches its own sessions, types your requests into them and holds their permission prompts.

### Set it up

1. **On the machine with your voice**, make it reachable, as for the phone: `pointe pair tailscale`, `pointe pair wifi`
   or `pointe pair host <name>`. The other machine reaches the same listener the phone does.
2. **Make a one-time code** there, in any of three places:
   - `pointe hub invite` in a terminal. It prints the whole line to paste.
   - The page: Settings → Machines → **Invite a machine**.
   - The iPhone app: Settings → Machines → **Invite a machine**. The app asks for Face ID before it shows the code, and
     shows the whole line to copy.

   The code works once and lasts 10 minutes. Cancel it from the same place.
3. **On the other machine**, paste the line:

   ```
   pointe node join 'pointe://hub?v=1&host=…&port=7443&fp=…&code=K7PQ-2MXD'
   ```

   The other machine checks your voice's certificate against the fingerprint in the line before it sends anything. It
   then says which vendors your voice uses, because its sessions' transcripts go there.
4. **Check the pairing.** Your voice shows the machine's name, address and key fingerprint, for example
   "devbox paired from 100.101.5.7 (Tailscale), key 3f2a…". `pointe node status` on the other machine shows the same
   fingerprint. If they differ, revoke it.
5. **Join sessions on the other machine** as you do on the first: `/pointe:voice` in Claude Code, `pointe join opencode`
   or `pointe join codex` in a folder.

A Linux machine needs `uv` and `ps` (procps): `pointe node join` checks and says what to install. A machine paired this way does not install the voice models: on Linux, `bash install.sh --node` installs it
without them.

### Use it

**On the screens.** With one machine, nothing changes. With more than one, on the page and in the app:

- The sessions are **grouped by machine**, this Mac first. Each group shows the machine's OS, its round trip ("23 ms")
  or "offline since 14:02", and how many sessions need you. On the page a click folds a group; in the app the Sessions
  sheet has a section per machine.
- **Filter chips** at the top: `All · studio · devbox · laptop`. One tap shows only that machine's sessions and narrows
  the "Orchestrating N sessions" line. A chip is a view only: it sends nothing and changes no mode.
- Each session carries a **machine tag** while more than one machine has sessions.
- An approval card, and its notification, say **"shop · devbox needs approval"**.
- In the app, hold a session chip and choose "Sessions on devbox" to open the Sessions sheet on that machine.

**By voice.** Session names are unique across machines. If a second machine has a session with a name already in use,
it gets the machine's name added: "shop devbox". Then:

| Say | Does |
|---|---|
| "go to devbox" | switches to devbox's session; with several there, asks which one |
| "tell devbox to pull" | sends to devbox's session, or asks which one |
| "tell everyone on devbox to pull", "everyone except the laptop" | sends to that machine's sessions only |
| "what's going on everywhere", "what's on devbox" | answers grouped by machine |
| "where is shop running" | names the machine |

A machine's name counts only where it says who something is for ("tell devbox", "on devbox"). "Fix the devbox config"
names no session. The voice says the machine when the name alone is not enough, when you switch to another machine, and
in "everywhere" answers. It does not repeat it in every report.

### When a machine goes offline

A machine that sleeps, or whose network drops, is marked offline within about 12 seconds:

- Its sessions stay listed, dimmed, with "offline since 14:02". A send to one is refused ("devbox is offline").
- A prompt it held goes back to its own terminal. Its card says "offline: answer it in its terminal", with no Approve or
  Deny, and its notification has no actions.
- You can still focus an offline session and ask what its notes say.
- When the machine comes back it reconnects by itself and sends the lines you missed. After 10 minutes offline its
  sessions are closed, as an exited session is.

### Approvals

Your voice keeps every rule it has for the sessions on its own machine ([SECURITY.md](../SECURITY.md)). The other
machine checks again before it answers a prompt:

- A **spoken yes** counts only if your voice read out exactly the text the other machine computed from the real
  request, in short or word for word. A request it never reads out (one that holds a credential-like value) cannot be
  approved by voice.
- A **notification's Approve** counts only for a request that machine can read out.
- A **tap** on the page or in the app is trusted from your voice, as a tap on its own sessions is. What the card
  shows is the request with credentials masked; the exact request is in the session's own terminal.
- A **no** from anywhere denies.

To answer unreadable prompts only in that machine's terminal, set `"remote_taps": "readable_only"` in its
`~/.claude-voice/config.json`. Then a tap can approve only what could have been read out. `/pointe:doctor` on that
machine says which setting is on.

### What goes where

- **To your voice:** each session's transcript, with credentials masked on the machine it runs on; its name, folder
  path, process id and agent; up to 40 file names; permission requests in masked form and in read-out form. When you
  look for sessions to add ([features/add-sessions.md](features/add-sessions.md)): each listed session's name, folder,
  agent, age, title, keywords and first and last request, cut to 160 characters, and nothing of a session you do not
  add after that.
- **From your voice:** your requests to its sessions, and your answers to its prompts.
- **Never:** vendor keys (the other machine has none), your voiceprint, the journal, session notes, the dictionary, the
  page or phone keys, or the machine's own key (it proves the key with a fresh challenge each time).

Your voice treats the other machine's transcripts like its own: they go to its reader and brain vendors.
`pointe node join` and `pointe node status` name those vendors. A voice in fully local mode (`pointe local`) sends them
to none.

## Your own machines, each a full voice

Each of your machines can run its own full Pointe, with its own keys, and your phone, Mac app and page can call any of
them directly ([iPhone app, Several machines](iphone-app.md#several-machines-on-this-phone-labs),
[design](design/multi-machine-clients.md)). They can also link each other, so the one you call reaches the rest:

1. On one machine: `pointe machines link kite` prints a one-time line (`kite` is the name the other machine gets here).
2. On the other machine: `pointe machine add '<line>'`. Do the same the other way round for the second direction.

A machine linked this way is yours, not a person's: it sees every session there, private ones and agents included (never
another machine's: links do not pass sessions on), what it sends carries your own tag and is never refused as busy
against you, a permission prompt is offered to it at once, and its reports are spoken as your own. An approval is taken
once, on the machine the session runs on, whichever of your voices answered it; the others are told it was answered.

**Two of your voices on somebody else's machine.** If Avi invited you and you add `avi-box` to a second voice of
yours too, ask Avi for `pointe people invite <your name> --another-voice`: that voice gets its own key under your one
name, so the two never count as two people (busy, "the turn you started", who answered).

## A shared machine

One machine, one OS account, several people. The owner's Pointe runs there and is the owner's voice. Each other person
runs their own Pointe on their own Mac or Linux machine, and adds the shared machine to it. Nobody shares a key or a
call.

**Read this first.** A person you invite can make the machine's agents run commands as the account Pointe runs as, and
a session Pointe starts skips permission prompts by default ([New session](features/new-session.md)). Pointe does not
isolate people from each other on one account. Invite only people you would give a shell on that account. The whole
trust model: [SECURITY.md](../SECURITY.md#people-on-a-machine).

The examples use Avi, who owns the machine `avi-box`, and Dana, whom he invites.

### The owner invites a person

The machine must be reachable first, as for a phone (`pointe pair tailscale`, `pointe pair wifi` or
`pointe pair host <name>`): a person's voice connects to the same listener, port 7443. Without an address the invite
says how to set one up.

Avi makes an invite in any of four places:

| Where | How |
|---|---|
| A terminal | `pointe people invite dana`, or `pointe people invite dana --watch` for watch only. It prints the line, waits, and says who paired |
| The page, on the machine itself | Settings → Machines → **Invite a person**: a name, then **Can talk to the sessions** or **Can only watch**, then **Show the invite** |
| The iPhone app | Settings → Machines → **People** → **Invite a person**. The app asks for Face ID first |
| The Mac app | The same screen as the iPhone's. It asks for Touch ID or the password first |

The invite is one line and, on the screens, a QR code of the same line:

    pointe://machine?v=1&host=avi-box.example&port=7443&fp=<64 hex>&code=K7PQ-2MXD&name=avi-box

It works once and lasts ten minutes. One invite is out at a time: a new one replaces it. **Cancel the invite** ends it
early. The page shows People only on the machine itself: a page opened in a phone's browser does not.

A person's name is said aloud and stamped on what they send. It may hold letters, digits, spaces, dots and dashes, it
must be a name the voice can tell apart, and it cannot be the owner's name or a name already on the machine.

When Dana's voice pairs, the terminal prints two lines, and the apps say "Dana can reach this machine now.":

    dana paired from 100.101.5.9 (Tailscale), key 3f2a…
    dana's voice sends this machine's transcripts to: Deepgram, Gemini.

### The person adds the machine

Dana needs her own Pointe with her own model keys, on the same private network as `avi-box` (Tailscale, Twingate or
the LAN). She adds the machine in any of four places:

| Where | How |
|---|---|
| A terminal | `pointe machine add '<line>'`, with `--name NAME` to call the machine something else in her voice |
| The page, on her machine | Settings → Machines → "Paste the line the machine's owner sent you" → **Add**. A pasted line is added at once |
| The iPhone app | Settings → Machines → **Add a machine**. The camera opens to scan the code on the owner's screen; **Paste instead** takes the line. The app asks for Face ID before it adds |
| The Mac app | Settings → Machines → **Add a machine**: paste the line or drop it on the field, then **Add**. The app asks for Touch ID or the password before it adds |

Her voice checks the machine's certificate against the fingerprint in the line before it sends anything, trades the
code for her own key on that machine, and connects. There is no account and no second step.

What a refusal says, each in one sentence:

- The line is not a machine invite, or is cut short.
- The certificate is not the one in the invite: "ask them for a new invite".
- The code is wrong, expired or already used.
- The machine cannot be reached: it must be on the same private network.
- The machine is her own, or is already in her voice.
- The machine's name is taken in her voice. The screens then ask for another name under **Call it**; the command takes
  `--name`. A refused name does not use up the invite.

**The disclosure, once.** After the add, Dana's screens say one time where her voice sends that machine's
transcripts, until she presses **OK**. The page says "Your voice sends the transcripts of the sessions on avi-box,
with credentials masked, to: Deepgram, Gemini. avi sees this list next to your name." `pointe machine add` prints the
same fact and the screens then do not repeat it. Avi sees the same list next to Dana's name.

### What the person sees and hears

- `avi-box` is in Settings → Machines, marked as Avi's, with its state and round trip, like a machine of her own.
  `pointe machine list` (or `pointe machines`) prints every machine in her voice and whose each one is.
- Its shared sessions are in her one conversation, grouped under `avi-box`. Each one that is not hers carries its
  owner's name ("avi's"). A session of her own never carries a name.
- A **Mine** chip joins the filter chips while any session in her voice is somebody else's. It shows only her own
  sessions.
- She talks to those sessions as to her own: "tell shop to run the tests". The agent on `avi-box` reads the request
  with her name on it: "[Voice request from dana, a person invited to this machine, relayed by dana's voice assistant".
- If a session on `avi-box` has the same name as one of hers, hers keeps the plain name and the other gets the
  machine's name added: "shop avi-box".
- A session that waits on a permission prompt shows that it waits. If she may send, she can answer it once its owner
  had 20 seconds: see [Approving a prompt](#approving-a-prompt-on-a-shared-machine).

### Send or watch

Each person has one grant on a machine:

| Grant | The person can | Set with |
|---|---|---|
| **send** (the default) | See the shared sessions and their transcripts, and send requests to them | `pointe people invite dana`, **Can talk to the sessions** |
| **watch** | See the shared sessions and their transcripts. The machine refuses every request from them | `pointe people invite dana --watch`, **Can only watch** |

The owner changes it at any time: `pointe people grant dana watch` or `pointe people grant dana send`; on the page, one
click on the person's **Can talk** or **Watch only** button; in the apps, the menu on the person's row. It applies from
that moment, and the person's screens show "watch only" on the machine.

The machine enforces the grant, not the person's voice. A request from a person who may only watch is answered "Not
sent. avi lets you watch avi-box, not talk to its sessions."

### Private sessions

Every session on the shared machine is shared with every person invited to it, unless its owner makes it private.

- `pointe share shop --private` keeps `shop` to the owner. `pointe share shop --shared` shares it again. With no flag,
  `pointe share shop` makes it private.
- On the page: the lock mark on the session's row, or **Private** in its ⋯ sheet. In the apps: long-press the session
  (right-click on the Mac) and choose **Private**; **Shared with people** shares it again.
- The choice is offered on a session the owner owns, on the machine itself, once the machine has people.

A private session leaves every person's voice at once: its name, its transcript and its file names stop crossing, and
lines already read for a person are not sent. Shared again, it continues where it stopped. A private session stays
private across a restart. There is no voice command for Private yet.

Sessions on the owner's other machines (the ones paired with `pointe hub invite`) are never passed on to people. Only
the shared machine's own sessions are.

### Who hears which report

- **You hear the report of a turn you started.** Dana asks `shop` to run the tests; when the turn ends, her voice
  reads the report, as for a session of her own.
- **A report of a turn somebody else started on somebody else's machine is held.** It is not spoken. While a call is
  up it counts on the screen, and "anything from the others?" reads it. With no call up it is not held: it goes to
  the session's notes only.
- **The owner's voice is not changed.** On the owner's own machine, reports are spoken as before, whoever started the
  turn.
- **A request another person sent is noted, never taken for yours.** When Omer sends `shop` a request, Dana's voice
  adds "omer asked shop: …" to the session's notes, and the voice never reports it as her own. The owner's voice shows
  it in Recent requests as "sent by omer".

### A session that is busy

A session takes one request at a time from people. If Dana sends to `shop` while it works on somebody else's request,
the machine refuses it and her voice says, word for word:

> Not sent. shop is working on omer's request from 14:02. Say send it anyway, and it goes.

- A session that works on a turn no invited person asked for (the owner typed it in the terminal, or asked from
  their own call) is busy with the owner's name.
- "**Send it anyway**" delivers the same request once, if she says it within 120 seconds of the refusal. Her voice
  then says "Sent to shop." It must be her own whole utterance; the model cannot say it for her.
- "Send it anyway" does not pass the other refusals:

| The machine refuses when | Her voice says |
|---|---|
| She may only watch | "Not sent. avi lets you watch avi-box, not talk to its sessions." |
| The session waits on a permission prompt | "Not sent. shop waits on a permission prompt on avi-box. It takes a request once that is answered." If you may send, you may answer it: see below |
| The request says somebody approved something ("Avi said yes") | "Not sent. avi-box takes no message that says somebody approved something: an approval comes from the person who gives it." |
| The session went private | "Not sent. avi keeps shop private now." |

### Approving a prompt on a shared machine

If you may send, you may also answer a session's permission prompt there.

- The session's owner is asked first: the person who started it, else the machine's owner. You see the request at
  once, with "avi is asked first", and your voice says nothing yet.
- After 20 seconds, or at once when the owner is not on a call, your voice reads the request out and your screens
  offer Approve and Deny. Say yes or no, or tap.
- The first answer wins. If somebody answered before you, your voice says who.
- The machine checks your answer itself. A spoken yes counts only if your voice read out exactly what the machine
  will run.
- Everybody is told who answered, and the machine keeps a record with your name.

The machine's owner can turn this off: `pointe people approvals off`. They change the 20 seconds with
`pointe people window <seconds>`.

When the machine's owner is not on a call, a prompt waits 45 seconds for you. Then it goes to its terminal, and
your answer no longer counts. The owner changes that with `pointe people hold <seconds>`.

### Starting a session on a shared machine

If you may send, you can start a session there: "start a session on avi-box in the shop folder", or the New session
sheet with the machine picked.

- The folders are the ones the machine's owner works in. Your voice asks the machine for the list.
- Your voice reads it back with the machine and whose it is: "Start a Claude Code session on avi-box, avi's machine,
  in shop?" The first time, it also says how that machine starts sessions: "avi-box starts sessions that skip
  permission prompts: it can edit files and run commands as avi without asking."
- How the session starts is the owner's choice, not yours.
- The session is yours. You are asked first for its prompts. You can keep it private with
  `pointe share <session> --private`: then you and the machine's owner see it.

The machine's owner can turn this off with `pointe people starts off`, or make these sessions always ask before
actions with `pointe people sessions ask`.

### What the owner sees

- **The People list**: Settings → Machines on the page of the machine itself, **People** in the apps, or
  `pointe people`. Each person has a name, a grant, whether their voice is linked now or when it was last here, and
  the services their voice sends this machine's transcripts to ("Their voice uses: Deepgram, Gemini"). `pointe people`
  also prints each person's key fingerprint.
- **The trust line** above the list: "People you invite can make these agents run commands as avi. Keep a session to
  yourself with Private."
- **On a session**: "dana is using it" while it works on a person's request, and a lock on a private session.
- **Recent requests** on the page lists each person's request as "sent by dana".
- **The journal** (`~/.claude-voice/journal.jsonl`) has a line, with the person's name, for each pairing, link, link
  that ended, request, refused request, change of grant, change of Private and removal.
- The owner's name, as people's voices and the agents read it, is `"owner"` in `~/.claude-voice/config.json`, else the
  name of the OS account.

### Remove a person, or a machine

**The owner removes a person:** `pointe people remove dana`; on the page, **Remove** and then **Remove dana?**; in the
apps, **Remove** in the person's menu, a confirm, then Face ID (Touch ID or the password on the Mac). Only that
person's key is deleted and their link closes at once. Nobody else is touched. To come back they need a new invite.

On the person's side the machine stays listed, offline, with "avi-box removed you". Its sessions leave their voice, the
voice deletes its key and stops connecting. **Remove** takes the line off.

**A person removes the machine from their voice:** `pointe machine remove avi-box`, or **Remove** next to the machine
in Settings → Machines. Its sessions leave the voice and the voice deletes its key. On the machine the person stays in
the People list, not linked, and their key stays valid there until the owner removes them. If the invited person will
not come back, the owner should run `pointe people remove`.

`pointe pair rotate` and `pointe pair off` on the shared machine remove every person, and say who to invite again:
see [SECURITY.md](../SECURITY.md#people-on-a-machine).

### What crosses to whom

- **From the shared machine to each linked person's voice:** for each shared session, its transcript with
  credentials masked on the machine, its name, folder path, agent, title, owner, up to 40 file names, and whether it
  works or waits. Requests other people sent to it, masked, with the sender's name. Its permission prompts, if the
  person may send and the owner has not turned people's approvals off. Not its process id, not a private session, not
  a session on another machine.
- **From a person's voice to the shared machine:** the person's requests, their answers to prompts, their requests to
  start a session, the name of the machine their voice runs on, its Pointe version, and the names of the services their voice uses.
- **From each person's voice to that person's vendors:** the shared sessions' transcripts, as for their own sessions.
  Each person's voice uses its own keys. A voice in fully local mode sends them to no outside service.
- **Never:** anybody's vendor keys, voiceprint, journal, session notes or dictionary, and no person's key after
  pairing (each link proves it with a fresh challenge).

## Everyday commands

| Where | Command | Does |
|---|---|---|
| your voice | `pointe machines`, `pointe machine list` | every machine in your voice: name, OS, online or offline since, sessions, and whose it is |
| your voice | `pointe hub nodes` | each machine of your own: name, OS, online or offline since, sessions, round trip, key fingerprint |
| your voice | `pointe hub invite [--name devbox]` | a one-time code for a machine of your own |
| your voice | `pointe hub revoke <name>` | unpairs it: its sessions leave your voice, and it needs a new code to come back. Also on the page (Settings → Machines, two clicks) and in the app (Face ID, then a confirm) |
| your voice | `pointe machine add '<line>' [--name NAME]` | adds a machine somebody invited you to |
| your voice | `pointe machine remove <name>` | takes a machine out of your voice |
| your voice | `pointe pair rotate` | a new certificate, and every phone, browser, machine of your own and invited person paired with this one signed out: each needs a new code. `pointe pair off` signs out the same and stops listening |
| a machine of your own | `pointe node status` | the voice it is paired with, the link, round trip, that voice's vendors, sessions here, key fingerprint |
| a machine of your own | `pointe node leave` | unpairs this machine from its side |
| a shared machine | `pointe people` | the people invited to this machine |
| a shared machine | `pointe people invite <name> [--watch]` | a one-time line for that person's voice |
| a shared machine | `pointe people grant <name> send\|watch` | changes what a person may do |
| a shared machine | `pointe people remove <name>` | deletes the person's key and closes their link |
| a shared machine | `pointe people approvals on\|off` | people who may send can answer a session's prompt, or not (on by default) |
| a shared machine | `pointe people starts on\|off` | people who may send can start a session here, or not (on by default) |
| a shared machine | `pointe people sessions default\|ask` | sessions people start follow your default, or always ask before actions |
| a shared machine | `pointe people window <seconds>` | how long a prompt waits for its session's owner before the others get it (20; 0 to 120) |
| a shared machine | `pointe people hold <seconds>` | with no call of yours, how long a prompt waits for people before your terminal gets it (45; 10 to 280) |
| a shared machine | `pointe share <session> [--private\|--shared]` | keeps a session to yourself, or shares it again |

**Names.** Your voice's machine is named by `"machine"` in its `~/.claude-voice/config.json` (else its short host
name). Rename it there and restart Pointe: each machine of your own takes the new name at its next link. A machine of
your own gets its name when it pairs (`pointe hub invite --name devbox`); to change it, pair again. A machine somebody
invited you to gets its own name, or the one you give with `--name`.

## Versions: an old Pointe next to a new one

Two machines, or a plugin and the Pointe it calls, are often on different versions. Each pair says what it speaks when
it connects, and a pair with nothing in common fails in one sentence that names the side to update and the command.

| Pair | What each side says | No common version |
|---|---|---|
| A node and its hub | The hub's challenge and the node's hello each carry the oldest and newest link protocol they speak. The node's hello and the hub's welcome list the features. The link uses the newest protocol both speak and the features both list | The link closes with code 4426. `pointe node status` on the node says which side is old: "studio runs an older Pointe (0.9.0) than this machine: update it there with pointe update", or "studio needs a newer Pointe on this machine". On the hub the machine stays in Settings → Machines, offline, with "devbox runs an older Pointe (0.9.0). Update it there to see its sessions: pointe update". Nobody's key is deleted, and the node reconnects by itself after the update |
| A script, hook or command and the Pointe on the same machine | `X-Pointe-Client: <part>/<version> api=<n>` on every request | The answer is `426` with `{"error", "need", "have", "how"}`. The script prints the sentence in `error`; `how` is the command. A permission hook that is refused leaves the prompt in the terminal: it never blocks Claude Code |
| The iPhone app and the Mac | The call protocol and the oldest one served, in the status ([phone.md](phone.md)) | The app says which of the two to update |

Every script prints one sentence for any answer that is not what it expects: a refusal, a Pointe that does not know
the request, something that is not Pointe. A script from a release before 0.10 sends no header and is served as
before; one so old that it fails by itself (the 0.1.6 plugin) is named by `pointe doctor`, with the commands that
update or remove it.

**What is tested.** A node as 0.9.0 sends its hello (one protocol, no range, no features) links with this hub. The
requests the scripts of 0.1.6, 0.8.0, 0.8.7, 0.9.0, 0.10.0, 0.10.1 and 0.10.2 send are replayed against this daemon on every push
(`tests/fixtures/skew_requests.json`): each gets a 200 or a refusal with a sentence. A pair further apart than that
is not tested.

## Limits

- **A watch-only person cannot answer a prompt or start a session.** They see that the session waits.
- **No adding a session that already runs on somebody else's machine.** You start a new one there, or its owner
  joins it.
- **No starting a session on a machine of your own that is a node.** Start it there and join it.
- **A request while a prompt waits is refused**, and so is a request that says somebody approved something.
- **The settings for people are for everybody on the machine**, not one per person.
- **No voice command for Private, a grant, an invite or a removal.** Use the screens or the commands.
- **A machine that is only a node serves one voice.** A machine paired with `pointe node join` has no voice of its
  own and cannot invite people. To share a machine, run Pointe on it as its owner's voice.
- **One voice per machine, one call per voice.** Each person's voice needs its own Mac or Linux machine, awake for
  their call, with their own model keys. A phone or a browser paired with a voice acts as that voice's owner; a
  second call to the same voice is refused while one is up.
- **One link per person.** A person's key links one voice at a time to the machine.
- **No fleet size is claimed.** How many machines one voice holds well, and how many people one machine serves well,
  is not measured yet.
- **Not isolation.** People on a shared machine act as one OS account ([SECURITY.md](../SECURITY.md#people-on-a-machine)).
- **Held reports need a call.** A report of a turn somebody else started is held for "anything from the others?"
  only while a call is up.
- **One voice per machine of your own.** To move a machine paired with `pointe node join` to another voice,
  `pointe node leave`, then join the new one.
- **No call on a machine paired with `pointe node join`.** The call, its page and the app are on the machine with
  your voice. `/pointe:open` on the other machine says where the call is.
- **No launch mode there.** `pointe start` (a Claude Code channel) works only on the machine with your voice. On
  another machine, use `/pointe:voice` or `pointe join`.
- **Adding sessions on a machine of your own** works by voice and on screen: "connect to the pentest session on
  devbox". A closed Claude Code session there is not reopened from your voice (it needs a terminal on that machine);
  Codex and OpenCode ones are. The read-back says when such a session's approvals stay in its terminal; after it
  joins, its approvals capability shows as that machine's adapter reports it.
- **"By the way" questions** about a session on another machine are answered from its transcript, not from a forked
  copy.
- **Show while it says** does not show files from another machine yet, and **Challenge me** leaves another machine's
  diffs out of its evidence and says so.
- **Wi-Fi only (`pointe pair wifi`):** when the address of the machine with your voice changes, pair again and make a
  new code, as for the phone.
- **Windows** cannot be a machine in a voice.
