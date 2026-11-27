# Parity matrix

Written by `python3 tools/parity.py` from the code of the four surfaces; do not edit by hand. The Linux hub
serves the page: its column is the page's unless a row or a Mac-only branch (at the end) says otherwise.
`tests/test_parity_matrix.py` fails when this file is stale, and when a feature is missing from a surface
without a reason. What the rows mean, how the scan works and the component spec: [parity.md](parity.md).

## Counts

| Surface | yes | partial | no | n/a (bound to another surface) |
|---|---|---|---|---|
| Page | 127 | 0 | 0 | 25 |
| iPhone | 136 | 0 | 0 | 16 |
| Mac | 142 | 0 | 0 | 10 |
| Linux hub | 127 | 0 | 0 | 25 |

Before this work (a pre-release build (2026-11-21)), by the same scan:

| Surface | yes | partial | no | n/a |
|---|---|---|---|---|
| Page | 73 | 0 | 1 | 14 |
| iPhone | 79 | 0 | 1 | 8 |
| Mac | 43 | 0 | 40 | 5 |
| Linux hub | not a surface then | | | |

## The call

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| Connect, Try again, Cancel and Hang up, with the reason a call did not start <br>`call.connect` | yes `ui.html:1807` | yes `apps/PointeKit/Sources/PointeUI/Connect.swift:138` | yes `apps/PointeKit/Sources/PointeUI/Connect.swift:138` | yes (the page) |
| A dropped call is redialled; a refused or idle-ended one is not, and says why <br>`call.redial` | yes `ui.html:2959` | yes `apps/PointeKit/Sources/PointeUI/Agents.swift:115` | yes `apps/PointeKit/Sources/PointeUI/Agents.swift:115` | yes (the page) |
| A dropped link comes back on the same call: its token in the hello, the copy while it does <br>`call.resume` | yes `ui.html:2931` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:170` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:170` | yes (the page) |
| The state line: listening, speaking, muted, holding, reconnecting <br>`call.state` | yes `ui.html:1772` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:2043` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:2043` | yes (the page) |
| Mute and unmute the microphone <br>`call.mute` | yes `ui.html:1897` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:190` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:190` | yes (the page) |
| An AirPods press talks or mutes <br>`ios.airpods` | n/a | yes `apps/PointeKit/Sources/PointeUI/AirPods.swift:11` | yes `apps/PointeKit/Sources/PointeUI/AirPods.swift:9` | n/a |
| The conversation, newest line followed <br>`call.transcript` | yes `ui.html:1219` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:479` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:479` | yes (the page) |
| A New pill when lines arrive while you read further up <br>`call.new-pill` | yes `ui.html:1814` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:502` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:502` | yes (the page) |
| Your words as you speak them <br>`call.hearing` | yes `ui.html:1874` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:153` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:153` | yes (the page) |
| Type instead of talking <br>`call.type` | yes `ui.html:1875` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:246` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:246` | yes (the page) |
| A new line in a typed message: Enter sends; Shift+Enter, Option+Enter, or New line on the iPhone <br>`call.newline` | yes `ui.html:3573` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:275` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:251` | yes (the page) |
| A typed line shows at once, Sending then Sent; one the Mac did not take can be sent again <br>`call.type-sending` | yes `ui.html:3532` | yes `apps/PointeKit/Sources/PointeUI/Outbox.swift:71` | yes `apps/PointeKit/Sources/PointeUI/Outbox.swift:71` | yes (the page) |
| Fix what was heard in a line of yours <br>`call.correct` | yes `ui.html:3523` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:217` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:217` | yes (the page) |
| Clean up my words <br>`call.polish` | yes `ui_quick.html:115` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:182` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:182` | yes (the page) |
| The daemon's last problem (a refused key, a vendor down) on screen <br>`call.problem` | yes `ui.html:1778` | yes `apps/PointeKit/Sources/PointeKit/NewSession.swift:168` | yes `apps/PointeKit/Sources/PointeKit/NewSession.swift:168` | yes (the page) |
| Hebrew lines read right to left <br>`call.rtl` | yes `ui.html:1262` | yes `apps/PointeKit/Sources/PointeUI/TextDirection.swift:6` | yes `apps/PointeKit/Sources/PointeUI/TextDirection.swift:6` | yes (the page) |
| How full the voice model's context is <br>`call.context` | yes `ui.html:1234` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:513` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:513` | yes (the page) |
| Recent requests and where each went <br>`call.recent` | yes `ui.html:1229` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:377` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:377` | yes (the page) |
| A line while the Mac keeps itself awake for a call from another device <br>`call.keep-awake` | n/a | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:588` | n/a | n/a |

## Push to talk and turn taking

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| Microphone: Always on or Push to talk <br>`talk.mode` | yes `ui.html:1561` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:119` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:119` | yes (the page) |
| The microphone at hand: the switch over the mic, or on the Mac a chip in the quick row <br>`talk.switch` | yes `ui.html:1894` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:128` | yes `apps/macos/PointeMac/Panels.swift:87` | yes (the page) |
| Talk button: Hold to talk or Tap to talk <br>`talk.style` | yes `ui.html:1563` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:128` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:128` | yes (the page) |
| The mic is the talk button: hold it, or tap it <br>`talk.ring` | yes `ui.html:1801` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:224` | yes `apps/macos/PointeMac/AppModel.swift:505` | yes (the page) |
| A draft of what a press has heard so far <br>`talk.draft` | yes `ui.html:1874` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:465` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:465` | yes (the page) |
| Why the Mac closed a press by itself (held too long, no audio) <br>`talk.closed-why` | yes `ui.html:5365` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:29` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:29` | yes (the page) |
| Talk without touching the screen: a key, a system-wide shortcut, or the Action button <br>`talk.key` | yes `ui.html:1564` | yes `apps/ios/PointeShared/TalkIntents.swift:13` | yes `apps/macos/PointeMac/HotKey.swift:5` | yes (the page) |
| Skip from any app: a system-wide shortcut, set in Settings <br>`skip.key` | n/a | n/a | yes `apps/macos/PointeMac/AppModel.swift:88` | n/a |
| Wait before answering: Quick, Normal or Patient <br>`talk.patience` | yes `ui.html:1584` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:134` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:134` | yes (the page) |
| Hold mode ("don't interrupt me"): quiet until you release it <br>`talk.hold` | yes `ui.html:2894` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:22` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:22` | yes (the page) |

## Quick settings

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| Reply length: Brief, Concise, Detailed or Thorough, a tap away, with a line on what each does <br>`quick.length` | yes `ui_quick.html:104` | yes `apps/PointeKit/Sources/PointeUI/QuickSettings.swift:234` | yes `apps/PointeKit/Sources/PointeUI/QuickSettings.swift:376` | yes (the page) |
| Speaking speed, 0.8× to 1.2×, this device's own; hidden on a voice with no speed number <br>`quick.speed` | yes `ui_quick.html:107` | yes `apps/PointeKit/Sources/PointeUI/QuickSettings.swift:244` | yes `apps/PointeKit/Sources/PointeUI/QuickSettings.swift:396` | yes (the page) |
| Clean up my words and Whisper as switches in the row, their state never colour alone <br>`quick.toggles` | yes `ui_quick.html:115` | yes `apps/PointeKit/Sources/PointeUI/QuickSettings.swift:254` | yes `apps/PointeKit/Sources/PointeUI/QuickSettings.swift:400` | yes (the page) |
| A change by voice glows on its chip <br>`quick.glow` | yes `ui_quick.html:173` | n/a | yes `apps/PointeKit/Sources/PointeUI/QuickSettings.swift:335` | yes (the page) |
| On a narrow screen the row keeps its values: the page moves it to More, the Mac drops the words <br>`quick.narrow` | yes `ui.html:5537` | n/a | yes `apps/macos/PointeMac/Bubble.swift:186` | yes (the page) |
| A Quick button in the iPhone's header, with a dot while a quick setting is off its default <br>`quick.button` | n/a | yes `apps/PointeKit/Sources/PointeUI/QuickSettings.swift:208` | n/a | n/a |
| The Voice menu: ⌘1 to ⌘4 reply length, ⌥⌘1 to ⌥⌘5 speed, ⇧⌘K clean up my words <br>`quick.keys` | n/a | n/a | yes `apps/macos/PointeMac/PointeMacApp.swift:76` | n/a |

## Sessions and machines

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| Sessions, grouped by machine, with each one's agent and state <br>`sessions.list` | yes `ui.html:1203` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:185` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:185` | yes (the page) |
| Focus on a session <br>`sessions.switch` | yes `ui.html:3370` | yes `apps/PointeKit/Sources/PointeUI/API.swift:636` | yes `apps/PointeKit/Sources/PointeUI/API.swift:636` | yes (the page) |
| Orchestrator or Session mode <br>`sessions.mode` | yes `ui.html:1210` | yes `apps/PointeKit/Sources/PointeUI/API.swift:674` | yes `apps/PointeKit/Sources/PointeUI/API.swift:674` | yes (the page) |
| Session mode holds the other sessions' news: a quiet count, the list, Tell me <br>`sessions.held` | yes `ui.html:1777` | yes `apps/PointeKit/Sources/PointeUI/Held.swift:62` | yes `apps/PointeKit/Sources/PointeUI/Held.swift:62` | yes (the page) |
| Rename a session <br>`sessions.rename` | yes `ui.html:3352` | yes `apps/PointeKit/Sources/PointeUI/API.swift:642` | yes `apps/PointeKit/Sources/PointeUI/API.swift:642` | yes (the page) |
| Disconnect a session from the voice <br>`sessions.disconnect` | yes `ui.html:3630` | yes `apps/PointeKit/Sources/PointeUI/API.swift:639` | yes `apps/PointeKit/Sources/PointeUI/API.swift:639` | yes (the page) |
| Show only one machine's sessions <br>`sessions.filter` | yes `ui.html:1218` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:717` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:717` | yes (the page) |
| Start a new session: agent, folder, machine, name, first prompt <br>`sessions.new` | yes `ui.html:1702` | yes `apps/PointeKit/Sources/PointeUI/NewSession.swift:78` | yes `apps/PointeKit/Sources/PointeUI/NewSession.swift:78` | yes (the page) |
| The read-back card of a session asked for by voice: Start or Cancel <br>`sessions.new.readback` | yes `ui.html:1866` | yes `apps/PointeKit/Sources/PointeUI/NewSession.swift:220` | yes `apps/PointeKit/Sources/PointeUI/NewSession.swift:220` | yes (the page) |
| Add sessions already open, or reopen one from this week: search, by machine and agent <br>`sessions.add` | yes `ui.html:1717` | yes `apps/PointeKit/Sources/PointeUI/AddSessions.swift:14` | yes `apps/PointeKit/Sources/PointeUI/AddSessions.swift:14` | yes (the page) |
| The read-back card of sessions asked for by voice: Join, Reopen or Cancel <br>`sessions.add.readback` | yes `ui.html:1867` | yes `apps/PointeKit/Sources/PointeUI/AddSessions.swift:130` | yes `apps/PointeKit/Sources/PointeUI/AddSessions.swift:130` | yes (the page) |
| Which folders a new session may start in <br>`sessions.new.folders` | yes `ui.html:1612` | n/a | yes `apps/macos/PointeMac/MacSettings.swift:95` | yes (the page) |
| Permissions for new sessions: Skip permission prompts (default) or Ask before actions <br>`sessions.new.permissions` | yes `ui.html:1608` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:204` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:204` | yes (the page) |
| The risk line under a start, the first time a session skips permission prompts <br>`sessions.new.notice` | yes `ui.html:2363` | yes `apps/PointeKit/Sources/PointeKit/NewSession.swift:153` | yes `apps/PointeKit/Sources/PointeKit/NewSession.swift:153` | yes (the page) |
| Machines on this voice: online, sessions, round trip, key fingerprint <br>`machines.list` | yes `ui.html:1379` | yes `apps/PointeKit/Sources/PointeUI/Settings.swift:10` | yes `apps/PointeKit/Sources/PointeUI/Settings.swift:10` | yes (the page) |
| Invite a machine with a one-time code, cancel it, revoke a machine <br>`machines.invite` | yes `ui.html:1391` | yes `apps/PointeKit/Sources/PointeUI/Settings.swift:187` | yes `apps/PointeKit/Sources/PointeUI/Settings.swift:187` | yes (the page) |
| Add a machine somebody invited you to, from its owner's line: paste it (the iPhone also scans it) <br>`machines.add` | yes `ui.html:1397` | yes `apps/PointeKit/Sources/PointeUI/AddMachine.swift:133` | yes `apps/PointeKit/Sources/PointeUI/AddMachine.swift:133` | yes (the page) |
| Once after a machine is added: which services your voice sends its transcripts to, until OK <br>`machines.disclosure` | yes `ui.html:1407` | yes `apps/PointeKit/Sources/PointeUI/AddMachine.swift:112` | yes `apps/PointeKit/Sources/PointeUI/AddMachine.swift:112` | yes (the page) |
| Agents built on agent frameworks on this voice: kind, address, whether each answers <br>`agents.list` | yes `ui.html:1452` | yes `apps/PointeKit/Sources/PointeUI/Agents.swift:169` | yes `apps/PointeKit/Sources/PointeUI/Agents.swift:169` | yes (the page) |
| Connect an agent: OpenClaw, Hermes, any A2A or OpenAI-compatible agent; its credential goes to the Keychain <br>`agents.add` | yes `ui.html:1456` | yes `apps/PointeKit/Sources/PointeUI/Agents.swift:293` | yes `apps/PointeKit/Sources/PointeUI/Agents.swift:293` | yes (the page) |
| Remove an agent and its saved credential, after a confirm <br>`agents.remove` | yes `ui.html:4649` | yes `apps/PointeKit/Sources/PointeUI/Agents.swift:226` | yes `apps/PointeKit/Sources/PointeUI/Agents.swift:226` | yes (the page) |
| Once after an agent is added: which services hear what it says, until OK <br>`agents.disclosure` | yes `ui.html:1465` | yes `apps/PointeKit/Sources/PointeUI/Agents.swift:188` | yes `apps/PointeKit/Sources/PointeUI/Agents.swift:188` | yes (the page) |
| Whose a machine and a session is, shown only where it is not yours <br>`machines.owner` | yes `ui.html:2118` | yes `apps/PointeKit/Sources/PointeUI/People.swift:383` | yes `apps/PointeKit/Sources/PointeUI/People.swift:383` | yes (the page) |
| Mine: show only your own sessions, while somebody else's are in your voice <br>`sessions.mine` | yes `ui.html:2079` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:725` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:725` | yes (the page) |
| Invite a person to this machine: a name, talk or watch only, a one-time line and its code; cancel it <br>`people.invite` | yes `ui.html:1431` | yes `apps/PointeKit/Sources/PointeUI/PeopleSheet.swift:155` | yes `apps/PointeKit/Sources/PointeUI/PeopleSheet.swift:155` | yes (the page) |
| Change what a person may do: talk to the sessions, or watch only <br>`people.grant` | yes `ui.html:5076` | yes `apps/PointeKit/Sources/PointeUI/People.swift:185` | yes `apps/PointeKit/Sources/PointeUI/People.swift:185` | yes (the page) |
| Remove a person from this machine, after a confirm <br>`people.remove` | yes `ui.html:5085` | yes `apps/PointeKit/Sources/PointeUI/People.swift:187` | yes `apps/PointeKit/Sources/PointeUI/People.swift:187` | yes (the page) |
| Private: keep a session of this machine to yourself, or share it with people again <br>`sessions.private` | yes `ui.html:1759` | yes `apps/PointeKit/Sources/PointeUI/People.swift:200` | yes `apps/PointeKit/Sources/PointeUI/People.swift:200` | yes (the page) |
| What people can do on this machine: approve requests, start sessions, how their sessions start <br>`people.settings` | yes `ui.html:1439` | yes `apps/PointeKit/Sources/PointeUI/People.swift:190` | yes `apps/PointeKit/Sources/PointeUI/People.swift:190` | yes (the page) |
| Start a session on a machine somebody invited you to: its folders, whose it is, how it starts sessions <br>`sessions.new.there` | yes `ui.html:2419` | yes `apps/PointeKit/Sources/PointeUI/API.swift:684` | yes `apps/PointeKit/Sources/PointeUI/API.swift:684` | yes (the page) |

## Approvals and alerts

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| A permission request as a card with the exact request, Deny and Approve <br>`approve.card` | yes `ui.html:1865` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:2059` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:2059` | yes (the page) |
| A request somebody else is asked first for: who and how long, Approve only once it is yours, and who answered <br>`approve.asked` | yes `ui.html:4814` | yes `apps/PointeKit/Sources/PointeUI/Drive.swift:149` | yes `apps/PointeKit/Sources/PointeUI/Drive.swift:149` | yes (the page) |
| Any request can be approved by a spoken yes: read out short or word for word; the card says which (a secret is never said: tap) <br>`approve.voice` | yes `ui.html:2792` | yes `apps/PointeKit/Sources/PointeUI/API.swift:504` | yes `apps/PointeKit/Sources/PointeUI/API.swift:504` | yes (the page) |
| Approve asks that it is you: Face ID on the phone, Touch ID or the password on the Mac <br>`approve.owner` | n/a | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1239` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1239` | n/a |
| How many more requests wait <br>`approve.more` | yes `ui.html:2778` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:758` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:758` | yes (the page) |
| A request whose machine went offline says it is back in its terminal <br>`approve.offline` | yes `ui.html:2081` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:2100` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:2100` | yes (the page) |
| A notification when a session needs you and you are not looking <br>`alerts.notify` | yes `ui.html:5574` | yes `apps/PointeKit/Sources/PointeUI/Alerts.swift:195` | yes `apps/PointeKit/Sources/PointeUI/Alerts.swift:195` | yes (the page) |
| Approve from notifications, as a setting <br>`alerts.approve` | yes `ui.html:1630` | yes `apps/PointeKit/Sources/PointeUI/API.swift:440` | yes `apps/PointeKit/Sources/PointeUI/API.swift:440` | yes (the page) |
| Deny and Approve on the notification itself <br>`alerts.actions` | n/a | yes `apps/PointeKit/Sources/PointeUI/Alerts.swift:258` | yes `apps/PointeKit/Sources/PointeUI/Alerts.swift:258` | n/a |
| An agent replied with no call up: one notification, and a tap opens its replies <br>`alerts.agent-reply` | yes `ui.html:5576` | yes `apps/PointeKit/Sources/PointeUI/Alerts.swift:376` | yes `apps/PointeKit/Sources/PointeUI/Alerts.swift:376` | yes (the page) |
| Alerts keep arriving while the app is in the background <br>`alerts.background` | n/a | yes `apps/ios/Pointe/PointeApp.swift:13` | yes `apps/macos/PointeMac/PointeMacApp.swift:16` | n/a |

## Brain dump and challenge

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| Brain dump: think aloud, the thoughts listed, Done or Discard <br>`dump.panel` | yes `ui.html:1845` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:127` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:127` | yes (the page) |
| Review the structured prompt: edit, pick who gets it, send <br>`dump.review` | yes `ui.html:1293` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:300` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:300` | yes (the page) |
| Add more, or have it read back, before sending <br>`dump.more` | yes `ui.html:1304` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:302` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:302` | yes (the page) |
| Challenge the plan from the review <br>`dump.challenge` | yes `ui.html:1306` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:304` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:304` | yes (the page) |
| Challenge (devil's advocate): the items, the plan, End <br>`challenge.panel` | yes `ui.html:1834` | yes `apps/PointeKit/Sources/PointeUI/Challenge.swift:76` | yes `apps/PointeKit/Sources/PointeUI/Challenge.swift:76` | yes (the page) |

## Meetings

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| Start a meeting: mode, context, sessions that may be asked, consent <br>`meeting.start` | yes `ui.html:1253` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:130` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:130` | yes (the page) |
| Listening or Participating, switched during the meeting <br>`meeting.mode` | yes `ui.html:1794` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:229` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:229` | yes (the page) |
| The notes feed, filtered by kind, and the transcript <br>`meeting.notes` | yes `ui.html:1831` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:417` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:417` | yes (the page) |
| A raised hand: let it speak, later, or type it <br>`meeting.hand` | yes `ui.html:1818` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:371` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:371` | yes (the page) |
| Name the speakers; "that was me" <br>`meeting.speakers` | yes `ui.html:1792` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:701` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:701` | yes (the page) |
| Ask or add context during the meeting, and look a note up <br>`meeting.ask` | yes `ui.html:1832` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:631` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:631` | yes (the page) |
| End: the summary, export notes (with the transcript), send the action items, discard <br>`meeting.end` | yes `ui.html:1278` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:749` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:749` | yes (the page) |
| Meeting settings: default mode, lookups, consent, notes language <br>`meeting.settings` | yes `ui.html:1529` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:872` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:872` | yes (the page) |

## Briefings, whisper, drive

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| Briefing: what happened since, play, stop, length <br>`briefing.sheet` | yes `ui.html:1669` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:187` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:187` | yes (the page) |
| A ready briefing offers itself; playing, it has its own bar <br>`briefing.ready` | yes `ui.html:1870` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:166` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:166` | yes (the page) |
| A scheduled briefing: days, time, length, skip when empty <br>`briefing.schedule` | yes `ui.html:1520` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:312` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:312` | yes (the page) |
| Night shift: tasks for the sessions, the hours and the message budget, Start <br>`night.start` | yes `ui.html:1728` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:16` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:16` | yes (the page) |
| The read-back card of a night shift asked for by voice: Start or Cancel <br>`night.readback` | yes `ui.html:1868` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:216` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:216` | yes (the page) |
| A running night shift: tasks done, the blocked count, Stop <br>`night.status` | yes `ui.html:1869` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:168` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:168` | yes (the page) |
| The night's ledger: decisions, questions, done, blocked with the exact request, in flight <br>`night.ledger` | yes `ui.html:1744` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:253` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:253` | yes (the page) |
| Alerts about a night shift's blockers: off unless asked for <br>`night.notify` | yes `ui.html:1739` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:116` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:116` | yes (the page) |
| Whisper: short quiet replies, with the notes it held back <br>`whisper` | yes `ui.html:1912` | yes `apps/PointeKit/Sources/PointeUI/Whisper.swift:61` | yes `apps/PointeKit/Sources/PointeUI/Whisper.swift:61` | yes (the page) |
| Mute Pointe: one button beside the status line, every reply as text, each device's own choice <br>`mute` | yes `ui.html:1772` | yes `apps/PointeKit/Sources/PointeUI/Mute.swift:71` | yes `apps/PointeKit/Sources/PointeUI/Mute.swift:71` | yes (the page) |
| Muted, the state line says Writing… where it would say Speaking… <br>`mute.writing` | yes `ui.html:3232` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:25` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:25` | yes (the page) |
| Muting mid-reply stops what the device still holds to play <br>`mute.cut` | yes `ui_mute.html:46` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:193` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:193` | yes (the page) |
| The status line says Thinking… from the end of the turn until the reply <br>`thinking` | yes `ui_thinking.html:20` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:27` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:27` | yes (the page) |
| The status line names the session that has the request: "billing is working…" <br>`thinking.working` | yes `ui_thinking.html:21` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:36` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:36` | yes (the page) |
| The call's own link says the turn was taken: Thinking… without waiting for a status <br>`thinking.link` | yes `ui.html:2944` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:565` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:565` | yes (the page) |
| The state's dot tells thinking, speaking and working apart by motion, and Reduce Motion stops it <br>`thinking.motion` | yes `ui_thinking.html:13` | yes `apps/PointeKit/Sources/PointeUI/Thinking.swift:60` | yes `apps/PointeKit/Sources/PointeUI/Thinking.swift:60` | yes (the page) |
| Session tones: a setting, off by default, and a session's row names its tone <br>`tones` | yes `ui.html:1598` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:160` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:160` | yes (the page) |
| Only when I say Pointe: the microphone setting between Always on and push to talk, and the state line says how to talk <br>`mic.addressed` | yes `ui.html:1893` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:121` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:121` | yes (the page) |
| The approvals record: each answer that went through Pointe, when, by voice or tap, the exact request, the voice lock's score <br>`approvals.record` | yes `ui.html:1639` | yes `apps/PointeKit/Sources/PointeUI/Approvals.swift:90` | yes `apps/PointeKit/Sources/PointeUI/Approvals.swift:90` | yes (the page) |
| Reduce Motion: no animation runs, no symbol pulses and no scroll glides <br>`a11y.motion` | yes `ui.html:1197` | yes `apps/PointeKit/Sources/PointeUI/Motion.swift:30` | yes `apps/PointeKit/Sources/PointeUI/Motion.swift:30` | yes (the page) |
| A screen reader hears the state line as one element, with the line under it <br>`a11y.state` | yes `ui.html:1775` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:2042` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:2042` | yes (the page) |
| A session's agent is its name in plain text, read as "runs on Codex" <br>`a11y.agent` | yes `ui.html:2254` | yes `apps/PointeKit/Sources/PointeUI/Brand.swift:181` | yes `apps/PointeKit/Sources/PointeUI/Brand.swift:181` | yes (the page) |
| The call bubble and the menu bar item show thinking <br>`thinking.bubble` | n/a | n/a | yes `apps/macos/PointeMac/Bubble.swift:276` | n/a |
| The waiting sound: a setting, on by default <br>`thinking.cue` | yes `ui.html:1590` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:144` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:144` | yes (the page) |
| Progress updates while a session works: a setting, off by default <br>`progress` | yes `ui.html:1594` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:152` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:152` | yes (the page) |
| Skip what Pointe is saying: one button beside the status line, after the mute button, only while it speaks <br>`skip` | yes `ui.html:1773` | yes `apps/PointeKit/Sources/PointeUI/Skip.swift:18` | yes `apps/PointeKit/Sources/PointeUI/Skip.swift:18` | yes (the page) |
| Skipping stops what the device still holds to play <br>`skip.cut` | yes `ui_skip.html:24` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1777` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1777` | yes (the page) |
| The conversation's text can be selected and copied <br>`talk.copy` | yes `ui.html:505` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:93` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:93` | yes (the page) |
| Drive mode on screen: the one line, the request, Stop <br>`drive.screen` | yes `ui.html:1859` | yes `apps/PointeKit/Sources/PointeUI/Drive.swift:87` | yes `apps/PointeKit/Sources/PointeUI/Drive.swift:87` | yes (the page) |
| Turn drive mode on from the screen <br>`drive.start` | n/a | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:547` | n/a | n/a |
| Offer drive mode when the phone is in a car <br>`drive.suggest` | n/a | yes `apps/PointeKit/Sources/PointeUI/Drive.swift:229` | n/a | n/a |

## Voice lock, dictionary, conflicts, show

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| Voice lock: which actions only your voice may do <br>`lock.level` | yes `ui.html:1368` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:181` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:181` | yes (the page) |
| Enrol your voice, per device, and delete a voiceprint <br>`lock.enrol` | yes `ui.html:1360` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:122` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:122` | yes (the page) |
| What the lock ignored, and the note after three unsure yeses <br>`lock.ignored` | yes `ui.html:1689` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:219` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:219` | yes (the page) |
| Dictionary: the terms, add, edit, delete, suggestions, learn from fixes <br>`dictionary.sheet` | yes `ui.html:1514` | yes `apps/PointeKit/Sources/PointeUI/Vocabulary.swift:139` | yes `apps/PointeKit/Sources/PointeUI/Vocabulary.swift:139` | yes (the page) |
| A term learned during the call shows, with Undo <br>`dictionary.toast` | yes `ui_dictionary.html:29` | yes `apps/PointeKit/Sources/PointeUI/Vocabulary.swift:120` | yes `apps/PointeKit/Sources/PointeUI/Vocabulary.swift:120` | yes (the page) |
| Two sessions disagree: the card, ask either, dismiss <br>`conflicts.card` | yes `ui.html:1858` | yes `apps/PointeKit/Sources/PointeUI/Conflicts.swift:80` | yes `apps/PointeKit/Sources/PointeUI/Conflicts.swift:80` | yes (the page) |
| Conflict alarm settings: on, spoken <br>`conflicts.settings` | yes `ui.html:1619` | yes `apps/PointeKit/Sources/PointeUI/Conflicts.swift:169` | yes `apps/PointeKit/Sources/PointeUI/Conflicts.swift:169` | yes (the page) |
| Show while it says: the file, the diff or the test the voice is talking about <br>`show.card` | yes `ui.html:1924` | yes `apps/PointeKit/Sources/PointeUI/Show.swift:86` | yes `apps/PointeKit/Sources/PointeUI/Show.swift:86` | yes (the page) |
| Also show on the phone, as a setting <br>`show.setting` | yes `ui.html:1554` | yes `apps/PointeKit/Sources/PointeUI/Show.swift:325` | yes `apps/PointeKit/Sources/PointeUI/Show.swift:325` | yes (the page) |

## Pairing, appearance, about, help

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| Show the code that pairs a phone, list the paired phones, unpair <br>`pair.show` | yes `ui.html:1471` | n/a | yes `apps/PointeKit/Sources/PointeUI/PhoneSheet.swift:235` | yes (the page) |
| Pair with the Mac: scan or paste the code in the app, then confirm; unpair this phone <br>`pair.read` | n/a | yes `apps/PointeKit/Sources/PointeUI/PairView.swift:6` | n/a | n/a |
| Appearance: System, Light or Dark <br>`appearance` | yes `ui.html:1648` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:247` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:247` | yes (the page) |
| About: what Pointe is, the version, the repository <br>`about` | yes `ui.html:1655` | yes `apps/PointeKit/Sources/PointeUI/About.swift:54` | yes `apps/PointeKit/Sources/PointeUI/About.swift:54` | yes (the page) |
| The app's version beside the daemon's when they differ <br>`about.version` | yes `ui.html:1204` | yes `apps/PointeKit/Sources/PointeUI/Brand.swift:564` | yes `apps/macos/PointeMac/AppModel.swift:258` | yes (the page) |
| Local mode, as one read-only line <br>`local-mode` | yes `ui.html:1539` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:58` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:58` | yes (the page) |
| The voice knows where this surface keeps each control (product_help.json) <br>`help` | yes `product_help.json (51 topics)` | yes `product_help.json (51 topics)` | yes `product_help.json (48 topics)` | yes (the page) |
| A demo with invented sessions, no Mac needed <br>`demo` | n/a | yes `apps/PointeKit/Sources/PointeUI/Demo.swift:7` | yes `apps/PointeKit/Sources/PointeUI/Demo.swift:7` | n/a |
| Keyboard: a key for every main action <br>`keys` | yes `ui.html:3570` | n/a | yes `apps/macos/PointeMac/Panels.swift:202` | yes (the page) |

## The Mac shell

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| A menu bar item with the state and who needs you <br>`mac.menubar` | n/a | n/a | yes `apps/macos/PointeMac/PointeMacApp.swift:16` | n/a |
| A small call bubble that floats over other apps while a call is up: click to open, drag, small or full, × <br>`mac.bubble` | n/a | n/a | yes `apps/macos/PointeMac/Bubble.swift:144` | n/a |
| The talk mode and the talk shortcut ("Hold ⌃⌥Space"), in the window and the bubble <br>`mac.talkmode` | n/a | n/a | yes `apps/macos/PointeMac/AppModel.swift:154` | n/a |
| Play/pause in a call: Mute Pointe, Skip or Nothing, set in Settings; taken only during a call; the window and bubble say what an AirPods press does <br>`mac.airpods` | n/a | n/a | yes `apps/PointeKit/Sources/PointeUI/MacShell.swift:218` | n/a |
| Open at login <br>`mac.login` | n/a | n/a | yes `apps/macos/PointeMac/Platform.swift:4` | n/a |
| Find, start and restart Pointe on this Mac; say when versions differ <br>`mac.daemon` | n/a | n/a | yes `apps/macos/PointeMac/AppModel.swift:215` | n/a |
| Which roles the keys fill: a key no role needs is Optional, an empty role names the one key to add <br>`keys.status` | yes `ui.html:1543` | n/a | yes `apps/macos/PointeMac/AppModel.swift:401` | yes (the page) |
| Which vendor keys are in the Keychain, and Add… <br>`mac.keys` | n/a | n/a | yes `apps/macos/PointeMac/AppModel.swift:395` | n/a |

## The phone alone

| Feature | Page | iPhone | Mac | Linux hub |
|---|---|---|---|---|
| Drive mode on the lock screen <br>`ios.nowplaying` | n/a | yes `apps/PointeKit/Sources/PointeUI/Drive.swift:279` | n/a | n/a |
| Talk to Pointe from Control Center, the Lock Screen or the Action button: one press opens Pointe talking to the orchestrator, the next sends <br>`ios.control` | n/a | yes `apps/ios/PointeWidget/TalkControl.swift:8` | n/a | n/a |
| The call on the Lock Screen and in the Dynamic Island, with Send, Cancel, Talk and Hang up <br>`ios.live-activity` | n/a | yes `apps/ios/PointeWidget/TalkLiveActivity.swift:12` | n/a | n/a |
| A Home Screen tile: Talk to Pointe, with the Mac's status where the app group allows <br>`ios.widget` | n/a | yes `apps/ios/PointeWidget/TalkWidget.swift:8` | n/a | n/a |
| Turn Talk from outside the app on or off <br>`ios.outside-setting` | n/a | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:174` | n/a | n/a |

## Bound to a platform

A feature a surface cannot have, and why. Everything else is on all four.

| Feature | Not on | Why |
|---|---|---|
| An AirPods press talks or mutes | Page | a browser tab gets no AirPods mute gesture; the page has a headset's play/pause only while it has the focus |
| An AirPods press talks or mutes | Linux hub | a browser tab gets no AirPods mute gesture; the page has a headset's play/pause only while it has the focus |
| A line while the Mac keeps itself awake for a call from another device | Page | the rule runs only for a call from another device; on the Mac there is nothing to say |
| A line while the Mac keeps itself awake for a call from another device | Mac | the rule runs only for a call from another device; on the Mac there is nothing to say |
| A line while the Mac keeps itself awake for a call from another device | Linux hub | holding off sleep for a call, and the idle and power checks, are macOS only (pointe/mac.py: caffeinate, ioreg, pmset); on a Linux hub they are off (docs/linux.md, Limits on Linux) |
| Skip from any app: a system-wide shortcut, set in Settings | Page | A page hears keys only while its tab has the focus: it has the button, and no key from another app. |
| Skip from any app: a system-wide shortcut, set in Settings | iPhone | An iPhone has no system-wide key: it has the button. |
| Skip from any app: a system-wide shortcut, set in Settings | Linux hub | A page hears keys only while its tab has the focus: it has the button, and no key from another app. |
| A change by voice glows on its chip | iPhone | the iPhone's quick settings are in a sheet, closed while you talk; the dot on its button and the sheet show the new value |
| On a narrow screen the row keeps its values: the page moves it to More, the Mac drops the words | iPhone | the iPhone shows quick settings in a sheet of its own, the width of the screen |
| A Quick button in the iPhone's header, with a dot while a quick setting is off its default | Page | the page shows the chips themselves in its top bar |
| A Quick button in the iPhone's header, with a dot while a quick setting is off its default | Mac | the Mac shows the chips themselves in its title strip |
| A Quick button in the iPhone's header, with a dot while a quick setting is off its default | Linux hub | the page shows the chips themselves in its top bar |
| The Voice menu: ⌘1 to ⌘4 reply length, ⌥⌘1 to ⌥⌘5 speed, ⇧⌘K clean up my words | Page | a browser keeps ⌘1 to ⌘9 for its own tabs |
| The Voice menu: ⌘1 to ⌘4 reply length, ⌥⌘1 to ⌥⌘5 speed, ⇧⌘K clean up my words | iPhone | an iPhone has no menu bar; a hardware keyboard is rare on it |
| The Voice menu: ⌘1 to ⌘4 reply length, ⌥⌘1 to ⌥⌘5 speed, ⇧⌘K clean up my words | Linux hub | a browser keeps ⌘1 to ⌘9 for its own tabs |
| Which folders a new session may start in | iPhone | the daemon takes this setting at the Mac only (daemon.py: voice/prefs refuses sessions.folders off the Mac) |
| Approve asks that it is you: Face ID on the phone, Touch ID or the password on the Mac | Page | a browser page cannot ask for Touch ID without WebAuthn enrolment; the page is on the unlocked Mac beside the terminal |
| Approve asks that it is you: Face ID on the phone, Touch ID or the password on the Mac | Linux hub | a browser page cannot ask for Touch ID without WebAuthn enrolment; the page is on the unlocked Mac beside the terminal |
| Deny and Approve on the notification itself | Page | a web notification has no authenticated action; the click opens the page |
| Deny and Approve on the notification itself | Linux hub | a web notification has no authenticated action; the click opens the page |
| Alerts keep arriving while the app is in the background | Page | a background tab keeps its timer; there is nothing to schedule |
| Alerts keep arriving while the app is in the background | Linux hub | a background tab keeps its timer; there is nothing to schedule |
| The call bubble and the menu bar item show thinking | Page | The page has no bubble and no menu bar item: its state line is always on screen. |
| The call bubble and the menu bar item show thinking | iPhone | The iPhone has no bubble: its state line is the call screen's. |
| The call bubble and the menu bar item show thinking | Linux hub | The page has no bubble and no menu bar item: its state line is always on screen. |
| Turn drive mode on from the screen | Page | drive mode is for a phone in a car: it starts there or by voice, and the Mac only shows it and stops it |
| Turn drive mode on from the screen | Mac | drive mode is for a phone in a car: it starts there or by voice, and the Mac only shows it and stops it |
| Turn drive mode on from the screen | Linux hub | drive mode is for a phone in a car: it starts there or by voice, and the Mac only shows it and stops it |
| Offer drive mode when the phone is in a car | Page | no motion sensor and no car audio route on a Mac |
| Offer drive mode when the phone is in a car | Mac | no motion sensor and no car audio route on a Mac |
| Offer drive mode when the phone is in a car | Linux hub | no motion sensor and no car audio route on a Mac |
| Show the code that pairs a phone, list the paired phones, unpair | iPhone | the phone is the device being paired: it reads the code the Mac shows |
| Pair with the Mac: scan or paste the code in the app, then confirm; unpair this phone | Page | the page is served by the daemon on the Mac: it is the side that shows the code |
| Pair with the Mac: scan or paste the code in the app, then confirm; unpair this phone | Mac | the Mac app talks to its own daemon on loopback: nothing to pair |
| Pair with the Mac: scan or paste the code in the app, then confirm; unpair this phone | Linux hub | the page is served by the daemon on the Mac: it is the side that shows the code |
| A demo with invented sessions, no Mac needed | Page | the page exists only while the daemon runs, so there is nothing to start, find or demo from it |
| A demo with invented sessions, no Mac needed | Linux hub | the page exists only while the daemon runs, so there is nothing to start, find or demo from it |
| Keyboard: a key for every main action | iPhone | an iPhone has no keyboard by default; VoiceOver and Switch Control reach every control by its label |
| A menu bar item with the state and who needs you | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A menu bar item with the state and who needs you | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A menu bar item with the state and who needs you | Linux hub | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A small call bubble that floats over other apps while a call is up: click to open, drag, small or full, × | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A small call bubble that floats over other apps while a call is up: click to open, drag, small or full, × | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A small call bubble that floats over other apps while a call is up: click to open, drag, small or full, × | Linux hub | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| The talk mode and the talk shortcut ("Hold ⌃⌥Space"), in the window and the bubble | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| The talk mode and the talk shortcut ("Hold ⌃⌥Space"), in the window and the bubble | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| The talk mode and the talk shortcut ("Hold ⌃⌥Space"), in the window and the bubble | Linux hub | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| Play/pause in a call: Mute Pointe, Skip or Nothing, set in Settings; taken only during a call; the window and bubble say what an AirPods press does | Page | a browser tab gets no AirPods mute gesture and no media keys from other apps; the page has Space and a headset's play/pause while it has the focus |
| Play/pause in a call: Mute Pointe, Skip or Nothing, set in Settings; taken only during a call; the window and bubble say what an AirPods press does | iPhone | iOS mutes the input itself on the press, and the iPhone's play/pause is the talk button or drive mode's mute (ios.airpods) |
| Play/pause in a call: Mute Pointe, Skip or Nothing, set in Settings; taken only during a call; the window and bubble say what an AirPods press does | Linux hub | a browser tab gets no AirPods mute gesture and no media keys from other apps; the page has Space and a headset's play/pause while it has the focus |
| Open at login | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| Open at login | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| Open at login | Linux hub | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| Find, start and restart Pointe on this Mac; say when versions differ | Page | the page exists only while the daemon runs, so there is nothing to start, find or demo from it |
| Find, start and restart Pointe on this Mac; say when versions differ | iPhone | the phone reaches a Mac that already runs Pointe |
| Find, start and restart Pointe on this Mac; say when versions differ | Linux hub | the page exists only while the daemon runs, so there is nothing to start, find or demo from it |
| Which roles the keys fill: a key no role needs is Optional, an empty role names the one key to add | iPhone | the keys live in the Mac's Keychain, and the iPhone app shows none of them |
| Which vendor keys are in the Keychain, and Add… | Page | keys are added with `pointe key`, never through a page |
| Which vendor keys are in the Keychain, and Add… | iPhone | the keys live in the Mac's Keychain |
| Which vendor keys are in the Keychain, and Add… | Linux hub | keys are added with `pointe key`, never through a page |
| Drive mode on the lock screen | Page | needs the phone's own hardware or system service |
| Drive mode on the lock screen | Mac | needs the phone's own hardware or system service |
| Drive mode on the lock screen | Linux hub | needs the phone's own hardware or system service |
| Talk to Pointe from Control Center, the Lock Screen or the Action button: one press opens Pointe talking to the orchestrator, the next sends | Page | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18); the page's from-any-app is a system-wide shortcut running `pointe talk` |
| Talk to Pointe from Control Center, the Lock Screen or the Action button: one press opens Pointe talking to the orchestrator, the next sends | Mac | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18); the Mac app's is its talk shortcut (talk.key) |
| Talk to Pointe from Control Center, the Lock Screen or the Action button: one press opens Pointe talking to the orchestrator, the next sends | Linux hub | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18); the page's from-any-app is a system-wide shortcut running `pointe talk` |
| The call on the Lock Screen and in the Dynamic Island, with Send, Cancel, Talk and Hang up | Page | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |
| The call on the Lock Screen and in the Dynamic Island, with Send, Cancel, Talk and Hang up | Mac | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18); the Mac app's call bubble does the same (mac.bubble) |
| The call on the Lock Screen and in the Dynamic Island, with Send, Cancel, Talk and Hang up | Linux hub | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |
| A Home Screen tile: Talk to Pointe, with the Mac's status where the app group allows | Page | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |
| A Home Screen tile: Talk to Pointe, with the Mac's status where the app group allows | Mac | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18); the Mac app's menu bar item shows the same (mac.menubar) |
| A Home Screen tile: Talk to Pointe, with the Mac's status where the app group allows | Linux hub | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |
| Turn Talk from outside the app on or off | Page | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |
| Turn Talk from outside the app on or off | Mac | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |
| Turn Talk from outside the app on or off | Linux hub | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |

## Gaps

None: every feature is on every surface that can have it.

## The Linux hub: what the daemon does differently off a Mac

Each function in `pointe/` that asks which system it runs on (`LINUX_BRANCHES`). A path does the same another
way; a limit leaves part of the features out on Linux; a bound feature carries its Linux reason above.

| Branch | Kind | Features | On a Linux hub |
|---|---|---|---|
| `agents.py:_ask_secret` | path | `agents.add` | `pointe agent add` asks for the agent's credential in the terminal with hidden typing, not in a Mac dialog |
| `agents.py:delete_secret` | path | `agents.remove` | removing an agent deletes its credential from the Secret Service (secret-tool), not the Keychain |
| `daemon.py:_start_harnesses` | path | `sessions.new` | the agent list says Claude Code opens in a tmux window on this machine |
| `daemon.py:_status_machines` | path | `machines.list` | the hub names its own system, linux, in the machines list |
| `daemon.py:add_key` | path | `keys.status` | the page's Add answers with the terminal command (pointe key <vendor>, hidden typing) instead of opening a key window |
| `daemon.py:add_sessions_options` | limit | `sessions.add` | a Linux hub joins its open sessions and its machines' sessions, and does not offer to reopen its own recent ones (reopen_here is false) |
| `harnesses/claude_code.py:<module>` | path | none | Claude Code's managed settings are read from /etc/claude-code |
| `harnesses/claude_code.py:ClaudeCode.can_start` | path | `sessions.new` | starting Claude Code needs tmux; without it the start says how to install it |
| `harnesses/claude_code.py:could_not_open` | path | `sessions.new`, `sessions.add` | a failed start names tmux |
| `harnesses/claude_code.py:open_window` | path | `sessions.new`, `sessions.add` | a started or reopened session runs in a tmux window, not a Terminal window |
| `harnesses/claude_code.py:opens_where` | path | `sessions.new`, `sessions.add` | a started session opens in a tmux window (tmux attach -t pointe) |
| `keys.py:on_a_mac` | path | `keys.status` | `pointe key` asks in the terminal with hidden typing and saves the key in the login keyring (Secret Service), not the Keychain |
| `local.py:supported` | limit | `local-mode` | the one-step local mode needs an Apple-silicon Mac; on Linux each role is set to local by hand (docs/features/local.md), and the page's line shows it |
| `local.py:supported_voice` | limit | `local-mode` | Voice stays local needs an Apple-silicon Mac (MLX); on Linux ears and mouth are set to local by hand |
| `node.py:_os` | path | `machines.list` | a node tells the hub its system, linux, for the machines list |
| `pair.py:_open_picture` | path | `pair.show` | the pairing QR is printed in the terminal; no picture opens |
| `pair.py:_wifi` | path | `pair.show` | Same network listens on the private address of the default route (wired or Wi-Fi) |
| `pair.py:main` | path | `pair.show` | Twingate through a Docker-bridged connector gets the --listen docker hint |
| `terminal_setup.py:chrome` | path | none | not a feature row: the terminal setup and uninstall, run once; Chrome or Chromium is looked up on the PATH |
| `terminal_setup.py:desktop` | path | none | not a feature row: the terminal setup and uninstall, run once; a screen exists only in a desktop session (DISPLAY, WAYLAND_DISPLAY) |
| `terminal_setup.py:first_setup` | path | none | not a feature row: the terminal setup and uninstall, run once; it says "this machine" and does not require Chrome first |
| `uninstall.py:_in_keychain` | path | none | not a feature row: the terminal setup and uninstall, run once; keys are looked up in the login keyring |
| `uninstall.py:plan` | path | none | not a feature row: the terminal setup and uninstall, run once; keyring items are listed, and no pre-release Keychain names |
| `uninstall.py:remove` | path | none | not a feature row: the terminal setup and uninstall, run once; keyring items are removed with secret-tool |
| `vendors.py:_local_ears` | path | `local-mode` | local ears are faster-whisper instead of MLX Whisper |
| `vendors.py:_stored` | path | `keys.status` | only Pointe's own key names are read: the pre-release names are a Mac Keychain history |
| `vendors.py:from_store` | path | `keys.status` | keys are read from the Secret Service (secret-tool), not the Keychain |
