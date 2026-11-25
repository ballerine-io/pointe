# A Linux hub

Pointe can run on a Linux machine as a **hub**: the machine that holds the voice. Its page, your phone and your other
machines connect to it. Or a Linux machine can be a **node** of another hub, Mac or Linux, and only its sessions join
that hub's voice ([Machines](multi-machine.md)).

**What was tested on Linux.** In Ubuntu 24.04 containers: the install as a hub and as a node, a key saved in a real
login keyring and read back by the hub with no key in its environment, the hub's page and status in headless
Chromium, a session that joins, a call from the browser whose microphone audio (Chromium's fake device) reaches the hub,
a Claude Code start in tmux, pairing over the local network with its QR, and a Linux node paired with the Linux hub.
**Not tested on Linux:** a whole spoken call with a vendor answering, a real Claude Code session started by Pointe, a
real phone, and Twingate end to end. The vendors' code is the same as on a Mac.

## Install

You need `curl`, and for the parts below `tmux` and `secret-tool`:

```
sudo apt install curl tmux libsecret-tools
curl -fsSLO https://eng.ballerine.com/pointe/install.sh && bash install.sh
```

The installer asks **1. hub** or **2. node**. Choose hub. (`bash install.sh --hub` or `--node` answers it.) Nothing
needs `sudo` past the packages above, and nothing starts at login. Then:

```
pointe setup
```

It asks one question, asks for your key, and starts Pointe.

## Keys

The hub needs a model key, the same as on a Mac ([Which keys](install.md#which-keys)). On Linux the key lives in your
**login keyring**, through the freedesktop Secret Service (libsecret's `secret-tool`), the Linux equivalent of the
Keychain:

```
pointe key gemini
```

It asks in the terminal with hidden typing, checks the key with one tiny call, and saves it in your login keyring. The
key goes to `secret-tool` on its standard input, never on a command line, and never into a file. Pointe reads it from
the keyring each time it starts. `pointe uninstall` removes it.

The login keyring is open while you are logged in to the desktop (GNOME, KDE and others run a Secret Service). Over SSH
it works while you are also logged in at the desktop. A locked keyring cannot be read, and Pointe does not wait for it.

**With no keyring** (a server with no desktop, CI), give the key in the environment of the one command that starts
Pointe, from your own secret store:

```
GOOGLE_API_KEY="$(<command that prints it>)" pointe restart
```

The environment wins over the keyring. Do not put a key in a file, in `~/.bashrc`, or in an `export` that every program
inherits. The variables are `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `SONIOX_API_KEY` and
`ELEVENLABS_API_KEY`. Pointe passes none of them to the programs it starts.

## Where you talk

The hub needs no microphone of its own. You talk from one of these:

- **The hub's own desktop:** `pointe open` opens the page in the browser. Use Chrome or Chromium.
- **Your phone:** the Pointe iPhone app, or the phone's browser. First make the hub reachable (below).
- **Another computer's browser:** after the hub is reachable, `pointe pair link` on the hub prints an address and a
  QR. Open it once in that browser. It holds a secret: send it only to yourself.

## Reach it from other devices

Pick one route ([Connect your phone](phone.md) has the details, the same on Linux):

| Route | On the hub | Notes |
|---|---|---|
| Tailscale | `pointe pair tailscale` | Tailscale on the hub and the phone, same account |
| Same network | `pointe pair wifi` | Listens on the hub's private address on its default route (wired or Wi-Fi). Pair again if it changes |
| Twingate | `pointe pair host <alias>` | See below |

Or on the hub's page: **Settings → Phone → Connect your phone**. It lists the routes it finds and shows the QR.

**Twingate.** A Twingate connector must reach the hub's listener (port 7443). Two ways:

- **Connector on the hub, sharing its network** (simplest). Copy the connector's `docker run` command from the Twingate
  console, then run Pointe's `bin/voice-connector`. It reads the command from the clipboard (`wl-paste`, `xclip` or
  `xsel`), or lets you paste it when there is no clipboard, and starts the container with `--network host`. Give the
  resource the address `127.0.0.1`, port TCP 7443, and an alias such as `pointe.example.internal`. Then
  `pointe pair host pointe.example.internal`.
- **Connector in Docker's default bridge network** (the console's own command). It reaches the hub at the bridge's
  address, usually `172.17.0.1`, not `127.0.0.1`. Run `pointe pair host pointe.example.internal --listen docker`, and
  give the resource the address `172.17.0.1`, port TCP 7443. `pointe pair host` says so when it finds such a
  connector. The listener then also answers other containers on that bridge; pairing still guards it.

## Your sessions

**Claude Code.** Install the current plugin, then run `/pointe:voice` in each session:

```
claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe
```

The plugin also reads permission prompts out loud and takes a spoken yes. Without the plugin, use **Add sessions** on
the page, or say "connect to all open Claude Code sessions": Pointe joins the Claude Code sessions that are open, and their permission prompts
stay in their terminals.

**An older plugin.** A Pointe plugin from an older marketplace (for example `pointe@ballerine`, a 0.1 release) next to a
newer Pointe breaks `/pointe:voice`. `pointe doctor` and `install.sh` name it and print the commands to remove it. In
short:

```
claude plugin uninstall pointe@ballerine
claude plugin marketplace add https://github.com/ballerine-io/pointe.git && claude plugin install pointe@pointe
```

Then restart your Claude Code sessions.

**OpenCode and Codex:** `pointe join opencode` or `pointe join codex` in the session's folder.

**New sessions from the voice.** "Start a session in shop" opens Claude Code in a **tmux** window on the hub, in the
tmux session `pointe`. See it with `tmux attach -t pointe`; each started session has its own window. tmux, not a
desktop terminal, because Pointe runs in the background, often with no screen (over SSH), and a tmux window stays when
a terminal closes. Without tmux, Pointe says so: start `claude` yourself and run `/pointe:voice` in it. A new Claude
Code session skips permission prompts by default ([New session](features/new-session.md)).

**Session names.** A session that joins with `/pointe:voice` is named after its folder, with the git branch when it
has one: a session in `~/alon-pointe` with no branch is `alon-pointe`. Rename it by voice ("rename it to shop").

## Other machines, and other people

Pointe is made for **one person's voice**. These shapes are supported:

| Shape | How | Limits |
|---|---|---|
| Your other machines' sessions in your call | Each runs as a node: `pointe hub invite` on the hub, `pointe node join '<line>'` on the machine | A node has one hub. The hub's owner approves the node's prompts |
| Several phones | Each pairs with its own key: Settings → Phone, again for each | One call at a time |
| Several browsers | `pointe pair link`, opened once in each | They share one pairing secret; `pointe pair rotate` signs all out |
| Taking turns | A second phone or browser that calls while a call is up is refused ("a call is already up") | Not at the same time |

**Not supported: two people talking to the same hub at once.** Everyone paired with a hub acts as its owner: they hear
every session's reports and can send to any session and approve its prompts. Pair only your own devices, and give each
person their own hub. A colleague's machine can be a node of your hub only if you are the one who voices it.

**What multi-person use would take.** The hub keeps one call: one conversation, one active session, one voice lock and
one set of vendor keys. Several people at once would need a call per person, each with its own conversation and state;
a person behind each phone, browser and node, with who may send to and approve which session; approvals recorded by
person; a voice lock per person; and reports sent only to the person who owns the session. That is a redesign of the
daemon's state, not a setting. One hub per person is the supported way.

## Limits on Linux

- **Local models.** `pointe local` and "Voice stays local" need an Apple-silicon Mac. On Linux, local roles can be set
  by hand ([Local](features/local.md)); not measured.
- **The page and the CLI say "Mac"** in many places. On a Linux hub they mean this machine.
- **No Mac app, and the iPhone app is built on a Mac.** The phone's browser needs nothing built.
- **Idle and power checks** (sleep, battery) are macOS only; on Linux they are off.
- **Nothing starts at login.** `pointe open` or `/pointe:voice` starts the hub when needed.
