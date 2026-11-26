# Machines: one voice over sessions on several machines

Your sessions do not all run on the machine with the call. Some run on another Mac, a Linux host or a VM. Pair those
machines with the machine that holds the call, and their sessions join the same voice: you hear their reports, send to
them, approve their prompts, and always see which machine each one is on.

The machine with the call is the **hub**: a Mac, or a Linux machine ([Linux](linux.md)). Each other machine runs a small
Pointe called a **node**. A node has no
microphone, no speaker, no models and no keys. It watches its own sessions, types your requests into them and holds
their permission prompts. The design and the reasons: [design/multi-machine.md](design/multi-machine.md).

## Set it up

1. **On the hub**, make it reachable, as for the phone: `pointe pair tailscale`, `pointe pair wifi` or
   `pointe pair host <name>`. A node reaches the same listener the phone does.
2. **Make a one-time code** on the hub, in any of three places:
   - `pointe hub invite` in a terminal. It prints the whole line to paste.
   - The page: Settings → Machines → **Invite a machine**.
   - The iPhone app: menu → Machines → **Invite a machine**. The app asks for Face ID before it shows the code, and
     shows the whole line to copy.

   The code works once and lasts 10 minutes. Cancel it from the same place.
3. **On the other machine**, paste the line:

   ```
   pointe node join 'pointe://hub?v=1&host=…&port=7443&fp=…&code=K7PQ-2MXD'
   ```

   The node checks the hub's certificate against the fingerprint in the line before it sends anything. It then says
   which vendors the hub uses, because your sessions' transcripts go there.
4. **Check the pairing.** The hub shows the node's name, address and key fingerprint, for example
   "devbox paired from 100.101.5.7 (Tailscale), key 3f2a…". `pointe node status` on the node shows the same
   fingerprint. If they differ, revoke it.
5. **Join sessions on the node** as you do on the hub: `/pointe:voice` in Claude Code, `pointe join opencode` or
   `pointe join codex` in a folder.

A Linux node needs `uv` and either `lsof` or `ss` (from iproute2): `pointe node join` checks and says what to install.
A node does not install the voice models: on Linux, `bash install.sh --node` installs it without them.

## Use it

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

## When a machine goes offline

A node that sleeps, or whose network drops, is marked offline within about 12 seconds:

- Its sessions stay listed, dimmed, with "offline since 14:02". A send to one is refused ("devbox is offline").
- A prompt it held goes back to its own terminal. Its card says "offline: answer it in its terminal", with no Approve or
  Deny, and its notification has no actions.
- You can still focus an offline session and ask what its notes say.
- When the node comes back it reconnects by itself and sends the lines you missed. After 10 minutes offline its
  sessions are closed, as an exited session is.

## Approvals

The hub keeps every rule it has for its own sessions ([SECURITY.md](../SECURITY.md)). The node checks again before it
answers a prompt:

- A **spoken yes** counts only if the hub read out exactly the text the node computed from the real request. A request
  the node cannot read out cannot be approved by voice.
- A **notification's Approve** counts only for a request the node can read out.
- A **tap** on the page or in the app is trusted from the hub, as a tap on the hub's own sessions is. What the card
  shows is the request with credentials masked; the exact request is in the session's own terminal.
- A **no** from anywhere denies.

To answer unreadable prompts only in the node's terminal, set `"remote_taps": "readable_only"` in that node's
`~/.claude-voice/config.json`. Then a tap can approve only what could have been read out. `/pointe:doctor` on the node
says which setting is on.

## What goes where

- **To the hub:** each session's transcript, with credentials masked on the node; its name, folder path, process id and
  agent; up to 40 file names; permission requests in masked form and in read-out form. When you look for sessions to
  add ([features/add-sessions.md](features/add-sessions.md)): each listed session's name, folder, agent, age, title,
  keywords and first and last request, cut to 160 characters, and nothing of a session you do not add after that.
- **From the hub:** your requests to its sessions, and your answers to its prompts.
- **Never:** vendor keys (a node has none), your voiceprint, the journal, session notes, the dictionary, the page or
  phone keys, or the node's own key (the node proves it with a fresh challenge each time).

The hub treats a node's transcripts like its own: they go to the hub's reader and brain vendors. `pointe node join` and
`pointe node status` name those vendors. A hub in fully local mode (`pointe local`) sends them to none.

## Everyday commands

| Where | Command | Does |
|---|---|---|
| hub | `pointe hub nodes` | each node: name, OS, online or offline since, sessions, round trip, key fingerprint |
| hub | `pointe hub invite [--name devbox]` | a one-time code, as above |
| hub | `pointe hub revoke <name>` | unpairs it: its sessions leave the voice, and it needs a new code to come back. Also on the page (Settings → Machines, two clicks) and in the app (Face ID, then a confirm) |
| hub | `pointe pair rotate` | a new certificate, and every machine, phone and browser paired with this Mac signed out: each needs a new code. `pointe pair off` signs out the same and stops listening |
| node | `pointe node status` | the hub, the link, round trip, the hub's vendors, sessions here, key fingerprint |
| node | `pointe node leave` | unpairs this machine from its side |

**Names.** The hub's name is `"machine"` in its `~/.claude-voice/config.json` (else its short host name). Rename the hub
there and restart it: each node takes the new name at its next link. A node's name is set when it pairs
(`pointe hub invite --name devbox`); to change it, pair again.

## Versions: an old Pointe next to a new one

Two machines, or a plugin and the Pointe it calls, are often on different versions. Each pair says what it speaks when
it connects, and a pair with nothing in common fails in one sentence that names the side to update and the command.

| Pair | What each side says | No common version |
|---|---|---|
| A node and its hub | The hub's challenge and the node's hello each carry the oldest and newest link protocol they speak, and a list of features. The link uses the newest protocol both speak and the features both list | The link closes with code 4426. `pointe node status` on the node says which side is old: "studio runs an older Pointe (0.9.0) than this machine: update it there with pointe update", or "studio needs a newer Pointe on this machine". On the hub the machine stays in Settings → Machines, offline, with "devbox runs an older Pointe (0.9.0). Update it there to see its sessions: pointe update". Nobody's key is deleted, and the node reconnects by itself after the update |
| A script, hook or command and the Pointe on the same machine | `X-Pointe-Client: <part>/<version> api=<n>` on every request | The answer is `426` with `{"error", "need", "have", "how"}`. The script prints the sentence in `error`; `how` is the command. A permission hook that is refused leaves the prompt in the terminal: it never blocks Claude Code |
| The iPhone app and the Mac | The call protocol and the oldest one served, in the status ([phone.md](phone.md)) | The app says which of the two to update |

Every script prints one sentence for any answer that is not what it expects: a refusal, a Pointe that does not know
the request, something that is not Pointe. A script from a release before 0.10 sends no header and is served as
before; one so old that it fails by itself (the 0.1.6 plugin) is named by `pointe doctor`, with the commands that
update or remove it.

**What is tested.** A node as 0.9.0 sends its hello (one protocol, no range, no features) links with this hub. The
requests the scripts of 0.1.6, 0.8.0, 0.8.7 and 0.9.0 send are replayed against this daemon on every push
(`tests/fixtures/skew_requests.json`): each gets a 200 or a refusal with a sentence. A pair further apart than that
is not tested.

## Limits

- **One hub per node.** To move a node to another hub, `pointe node leave`, then join the new one.
- **No call on a node.** The call, its page and the app are on the hub. `/pointe:open` on a node says where the call is.
- **No launch mode on a node.** `pointe start` (a Claude Code channel) works only on the hub. On a node, use
  `/pointe:voice` or `pointe join`.
- **Adding sessions on a node** works by voice and on screen: "connect to the pentest session on devbox". A closed
  Claude Code session there is not reopened from the hub (it needs a terminal on that machine); Codex and OpenCode ones
  are. The read-back says when a node session's approvals stay in its terminal; after it joins, its approvals capability
  shows as the node's adapter reports it.
- **No new session on a node from the hub.** Pointe starts sessions only on the hub itself: in a terminal window on a
  Mac, in tmux on Linux ([features/new-session.md](features/new-session.md)). On a node, start the agent there and join
  it.
- **One owner.** A node's sessions are voiced, and its prompts approved, by the hub's owner. Pair machines you own, not
  a colleague's: each person runs their own hub ([Linux](linux.md#other-machines-and-other-people)).
- **"By the way" questions** about a session on a node are answered from its transcript, not from a forked copy.
- **Show while it says** does not show files from a node yet, and **Challenge me** leaves a node's diffs out of its
  evidence and says so.
- **Wi-Fi only (`pointe pair wifi`):** when the hub's address changes, pair again and make a new code, as for the phone.
- **Windows** cannot be a node.
