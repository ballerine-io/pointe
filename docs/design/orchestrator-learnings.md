# What Pointe takes from the coding-agent orchestrators

Decided 2026-11-15, against Pointe 1.9.1. Input: a research report on orchestrators (herdr, cmux, Conductor, Paseo,
Moshi and others) and the vendors' own surfaces, which listed 20 things Pointe could borrow. The report was written
without knowing what Pointe has. Each item below was checked twice: the claim against a primary source (vendor docs,
the vendor's repository, the installed CLI), and the gap against Pointe's code.

Verdicts: **ADOPT** (build it in Pointe), **INTEGRATE** (connect to someone else's surface), **ALREADY HAVE**,
**REJECT**. Effort: S is up to a day, M is days to two weeks, L is longer. Impact is judged for four things: conversation
quality, reliable session state and approvals, the phone, and the open-source launch.

## The short answer

Most of the list is already built, and a few items are rejected because they would weaken the approval rules. The one
real hole the report exposed was session state: a Claude Code session stopped at a prompt in its own terminal was
reported as working. That is fixed in 1.10.0 and 1.11.0. The largest gap left is not on the list as such: the phone
learns of a request only while the app is alive, because Pointe has no push server.

## What was verified

| Claim | Source checked | Result |
|---|---|---|
| `claude agents --json` is the supported way to read session state | Claude Code agent view docs; changelog; the CLI at 2.1.325 | True. Added in 2.1.145, `waitingFor` in 2.1.162. It lists interactive sessions with `pid`, `status` (`busy`, `waiting`, `idle`) and `waitingFor`. One call takes about half a second. `CLAUDE_CONFIG_DIR` scopes it to one account. |
| A `PermissionRequest` hook can return no decision and leave the prompt to the terminal | Claude Code hooks reference | True, and documented: exit 0 with no output is "no decision". Pointe's hook relies on it. |
| Claude Code emits OSC 7501 | Claude Code changelog, 2.1.295 | True, only to a terminal that implements the protocol. |
| `CLAUDE_CLIENT_PRESENCE_FILE` suppresses pushes | Remote Control docs; changelog, 2.1.181 | True, for Remote Control's own mobile pushes. The user sets it, per Claude Code process. |
| An inbox message to a session that bypasses permission prompts is held | Cross-session messaging docs | True: held for approval in that terminal unless the sender also bypasses. |
| herdr-core: JSON-RPC, 32 methods, one `events.subscribe`, "the API only grows", status only from OSC 7501, no API password | herdr-core repository: schema README, OpenRPC file, `status.rs`, `docs/security.md`, `AGENTS.md` | True. Version 0.1.21, marked preview, repository created 2026-10-16. Apache-2.0. |
| herdr's TUI reads agent state from the screen, and warns that idle is not safe | herdr agents docs | True. |
| cmux alert classes and suppression when the workspace is in view | cmux notifications docs | True. |
| ACP v2 is a draft with stdio as its transport | ACP v2 migration page | True. |

## Verdicts

| # | Item | Verdict | Reason | Effort | Risk | Impact |
|---|---|---|---|---|---|---|
| 1 | Spoken approval through a `PermissionRequest` hook; `Notification` and `Stop` hooks | ALREADY HAVE | `bin/voice-permission-hook` posts to `/voice/permission-hook`, which goes through `hold_permission`. The final message comes from the transcript. A `Stop` hook would start a process on every turn of every user for nothing new. | - | - | - |
| 2 | One event model across vendors | ALREADY HAVE, one piece adopted | The harness contract (`harnesses/base.py`): feed lines, `finished_tag`, `hold_permission`, `capabilities`. The missing state, "stopped at a prompt", is `blocked_on` since 1.10.0. Renaming to ACP's words changes nothing a user sees. `allow_always` is left out on purpose: a yes approves one request. | - | - | - |
| 3 | Voice rules for approvals: read back the session and the command, never trust "idle" | ALREADY HAVE | Stricter than proposed: the read-out names the session and is built from what will run (`guards.readable_request`), the yes is bound to that line and to 120 seconds, typed words never approve. Pointe never types into a dialog, so a wrong "idle" cannot approve anything. | - | - | - |
| 4 | Session state from `claude agents --json` | ADOPT, done in 1.10.0 | The transcript cannot tell a tool that runs from one that waits in the terminal; the feed line itself said "perhaps still waiting for approval". | S | Low | State: high |
| 5 | Presence-aware routing | Partly ALREADY HAVE; one piece done in 1.11.0; one INTEGRATE | Alerts already fire only when the tab is hidden or the app is off screen, and only the active session is read out. Added: a prompt answered at the keyboard within 15 seconds never alerts. Left: the Mac's idle time as a signal for the phone (plan, item 3). The presence file is rejected: Pointe cannot set it for a running session and sends no push. | S | Low | Phone: medium |
| 6 | Send through the Claude Code inbox socket | ALREADY HAVE | `sessions.post_inbox`. The report's caveat is real and not handled: see the plan, item 2. | - | - | - |
| 7 | Briefings from structured summaries | ALREADY HAVE | Session notes, `briefing.py`, and forked copies for side questions on all three harnesses. | - | - | - |
| 8 | herdr-core adapter | INTEGRATE, later | See "herdr" below. | M | Medium | Launch: low now |
| 9 | OpenCode adapter | ALREADY HAVE | `harnesses/opencode.py`, on the v2 API. | - | - | - |
| 10 | Codex app-server adapter | ALREADY HAVE | `harnesses/codex.py`. `acceptForSession` is left out on purpose. | - | - | - |
| 11 | Draft protection; clearing stale state | Stale state ALREADY HAVE; drafts REJECT | `alive`, `probe` and the reaper drop dead and zombie sessions. No harness reports that a person is mid-draft, and Pointe sends through APIs, not keystrokes. | - | - | - |
| 12 | Pairing and reliability basics | ALREADY HAVE; one candidate | QR pairing, pinned TLS, call health. No relay by design. Keeping the Mac awake during a call from the phone is the one piece missing (plan, item 6). | S | Low | Phone: medium |
| 13 | A phone inbox in Moshi's style | ALREADY HAVE | Sessions sorted by who needs you, approvals first, alerts only for what needs you. | - | - | - |
| 14 | Lock-screen Approve and Deny; a Siri intent; Live Activity | Approve and Deny ALREADY HAVE; Siri approve REJECT; Live Activity INTEGRATE | `alerts.py` and `Alerts.swift`: opt-in, only for a request that can be read out, Deny first. A Siri "approve" is a yes with no read-out before it, which the bound-yes rule forbids. Live Activity is plan item 4. | M | Medium | Phone: medium |
| 15 | herdr TUI adapter | REJECT | Its state is read from the screen, and its own docs say idle is not safe. An approval there is keystrokes into a dialog Pointe did not read. | - | - | - |
| 16 | Answer the OSC 7501 probe | REJECT for now | Pointe owns no terminal. It matters only once Pointe starts agents itself. | - | - | - |
| 17 | Deep links for diff review | REJECT | "Show while it says" already puts the diff on screen. Terminals share no link scheme. | - | - | - |
| 18 | ACP to start new agents | INTEGRATE, later | The right seam for "start an agent by voice", which needs a `start(cwd)` capability first (`docs/harnesses.md`). v2 is a draft. | L | Medium | Launch: low now |
| 19 | End-to-end-encrypted relay; speech on the device | Relay REJECT; local speech ALREADY HAVE | There is no relay to encrypt: the phone reaches the Mac directly over pinned TLS. `pointe local voice` keeps ears and mouth on the Mac. | - | - | - |
| 20 | Claude Channels permission relay | ALREADY HAVE | Launch mode (`bin/claude-voice`, `channel/voice-channel.mjs`). It stays second while it needs the development flag. | - | - | - |

## The decisions asked for

**herdr.** Not the TUI socket, and not now for herdr-core. For Claude Code, OpenCode and Codex, Pointe's own seams
are better than anything herdr can give: herdr-core's status says `blocked`, kind `permission`, and nothing about
what will run, so a read-out could only come from the screen, and its answer is `terminal.keys` into a dialog. That
breaks the rule that a yes approves only what the daemon read out from the request itself. What herdr-core could add
is narrow: state and send for agents that have no API of their own (they would join with `approvals = False`), and
its SSH machines as a second way to reach remote terminals. When it is built, it is `events.subscribe` for state and
`terminal.send` for sends, never `terminal.attach` and never `terminal.keys` on a blocked terminal. Wait until
herdr-core leaves 0.x or users ask: its audience today is small (the 51,000 stars are the TUI's, which does not share
sessions with it).

**`claude agents --json` for session state.** Yes, as a second source beside the transcript, and done. Not for
finding sessions: a session joins the voice by its own `/pointe:voice`, which is the user's consent to voice control.
The cost is bounded: one read per account at most every 15 seconds, only while a session could be at a prompt.

**OSC 7501.** No. It is a terminal's protocol and Pointe is not a terminal.

**Presence-aware routing.** The voice already goes where the call is, and alerts already go only where nobody is
looking. A full "speak on the Mac, push to the phone" needs a push channel, which Pointe does not have. The useful
part without one is the Mac's idle time (plan, item 3).

**cmux-style alert classes; no alert for the session in view.** Pointe's attention kinds are the classes
(`permission`, `terminal`, `question`, `hand`, `conflict`, `briefing`); the phone already gives a permission the
time-sensitive level. A "turn complete" alert with nothing to answer is left out on purpose: it is noise on a wrist.
Subagent activity never reaches the feed (`isSidechain`). Suppression for what is in view exists per client.

**Lock-screen Approve and Deny; Live Activity.** The first exists. Live Activity is worth building for a call with
the phone locked (plan, item 4), and can be driven by the app itself while the call keeps it alive.

**ACP for new agents.** Later, with the `start(cwd)` capability, once v2 is final.

**Voice safety rules.** Nothing to add. Pointe's rules are stricter than the report's, and they are in code with
tests.

## Built now

1. **1.10.0: a Claude Code session stopped at a prompt in its terminal is no longer called working.** The adapter
   reads `claude agents --json`. The status gives the session `working: false`, `needs` and `blocked_on`, so the page
   and the iPhone app both show "needs you" with no client change, and the voice is told that a yes does not reach
   that prompt. Fixed words only; a prompt the voice holds stays a permission. `tests/test_terminal_prompt.py`.
2. **1.11.0: that session alerts the phone and the desktop, and is nudged on a call.** A new attention kind,
   `terminal`, with no actions. A prompt answered at the keyboard within 15 seconds never alerts; an open dialog is
   state only. The nudge sends the user to the terminal and offers no words to say.

## Plan for the rest, ranked

| # | Item | Verdict | Effort | Risk | Why this rank |
|---|---|---|---|---|---|
| 1 | The same state for sessions on other machines: the node ships `blocked_on` | ADOPT | S | Low to medium (link protocol) | Finishes 1.10.0; a remote session is the one the user cannot glance at. |
| 2 | A send held by the terminal: Claude Code holds an inbox message to a session that bypasses permission prompts, and Pointe reports it sent | ADOPT | S, after one live check | Low | The voice says "docs is on it" when it is not. The roster's `dialog open` right after a send is the likely signal; it needs a run against a real session first. |
| 3 | The Mac's idle time in the status, so the phone stays quiet while the user is at the Mac | ADOPT | S to M (daemon and iOS) | Low | Stops the desk and the wrist alerting together. |
| 4 | Live Activity and Dynamic Island during a call: the active session, how many need you, the pending request's read-out form | INTEGRATE | M (a widget extension target) | Medium (signing, entitlements) | The phone's lock screen during a call is blank today. |
| 5 | A push channel, so the phone hears of a request with the app suspended | Owner decision | L | High (it is a server, or a user-run relay) | The largest phone gap, and it conflicts with "no server, no account". |
| 6 | Keep the Mac awake while a call from the phone is up | ADOPT | S | Low; costs battery | Needs the owner's yes and a check on real hardware. |
| 7 | One `state` field per session in the status, so the page and the app stop deriving the label separately | ADOPT | S | Low | Parity by construction; nothing a user sees. |
| 8 | herdr-core adapter for agents with no API of their own | INTEGRATE | M | Medium (0.x API, no socket auth) | After the launch, on demand. |
| 9 | ACP to start agents by voice | INTEGRATE | L | Medium | After `start(cwd)`, when v2 is final. |

## Where the report was wrong or out of date

- **Its links into herdr-core are dead.** The repository's branch is `master`; every `blob/main` link returns 404. The
  content it cites is there.
- **"Voice layer for herdr-core gains herdr's users"** does not follow from its own facts: the users are on the TUI,
  which shares no sessions with herdr-core and reads state from the screen.
- **The roster's fields.** It lists `state` for the roster. `state` exists only for background sessions; a session in a
  terminal carries `status` and `waitingFor`. Code keyed on `state` sees nothing for the sessions Pointe cares about.
- **The roster's risk.** It rates `claude agents --json` a research preview. The agent view screen is; the JSON output
  is documented as the supported interface, and has carried `waitingFor` since 2.1.162.
- **"Unverified: can a hook return no decision".** It is documented, and it is how Pointe's hook hands a prompt back.
- **The presence file.** It proposes that Pointe set `CLAUDE_CLIENT_PRESENCE_FILE`. The variable belongs to the Claude
  Code process and to Remote Control's pushes; Pointe can do nothing with it.
- **"Nobody ships lock-screen Approve and Deny."** Pointe does, and the report's own Moshi section describes a watch app
  that approves.
- **Not checked here:** Paseo's voice, Moshi's feature list, the star counts other than herdr's, and the user quotes.
  No verdict above rests on them.
