# Parity matrix

Written by `python3 tools/parity.py` from the code of the three surfaces; do not edit by hand.
`tests/test_parity_matrix.py` fails when this file is stale, and when a feature is missing from a surface
without a reason. What the rows mean, how the scan works and the component spec: [parity.md](parity.md).

## Counts

| Surface | yes | partial | no | n/a (bound to another surface) |
|---|---|---|---|---|
| Page | 98 | 0 | 0 | 22 |
| iPhone | 108 | 0 | 0 | 12 |
| Mac | 110 | 0 | 0 | 10 |

Before this work (a pre-release build (2026-11-21)), by the same scan:

| Surface | yes | partial | no | n/a |
|---|---|---|---|---|
| Page | 73 | 0 | 1 | 14 |
| iPhone | 79 | 0 | 1 | 8 |
| Mac | 43 | 0 | 40 | 5 |

## The call

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Connect, Try again, Cancel and Hang up, with the reason a call did not start <br>`call.connect` | yes `ui.html:1660` | yes `apps/PointeKit/Sources/PointeUI/Connect.swift:138` | yes `apps/PointeKit/Sources/PointeUI/Connect.swift:138` |
| A dropped call is redialled; a refused or idle-ended one is not, and says why <br>`call.redial` | yes `ui.html:2708` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:647` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:647` |
| A dropped link comes back on the same call: its token in the hello, the copy while it does <br>`call.resume` | yes `ui.html:2680` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:142` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:142` |
| The state line: listening, speaking, muted, holding, reconnecting <br>`call.state` | yes `ui.html:1625` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1848` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1848` |
| Mute and unmute the microphone <br>`call.mute` | yes `ui.html:1747` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:162` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:162` |
| The conversation, newest line followed <br>`call.transcript` | yes `ui.html:1169` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:443` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:443` |
| A New pill when lines arrive while you read further up <br>`call.new-pill` | yes `ui.html:1667` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:466` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:466` |
| Your words as you speak them <br>`call.hearing` | yes `ui.html:1725` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:153` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:153` |
| Type instead of talking <br>`call.type` | yes `ui.html:1726` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:245` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:245` |
| A new line in a typed message: Enter sends; Shift+Enter, Option+Enter, or New line on the iPhone <br>`call.newline` | yes `ui.html:3318` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:274` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:250` |
| A typed line shows at once, Sending then Sent; one the Mac did not take can be sent again <br>`call.type-sending` | yes `ui.html:3277` | yes `apps/PointeKit/Sources/PointeUI/Outbox.swift:71` | yes `apps/PointeKit/Sources/PointeUI/Outbox.swift:71` |
| Fix what was heard in a line of yours <br>`call.correct` | yes `ui.html:3268` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:217` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:217` |
| Clean up my words <br>`call.polish` | yes `ui.html:1636` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:158` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:158` |
| The daemon's last problem (a refused key, a vendor down) on screen <br>`call.problem` | yes `ui.html:1631` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:433` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:433` |
| Hebrew lines read right to left <br>`call.rtl` | yes `ui.html:1212` | yes `apps/PointeKit/Sources/PointeUI/TextDirection.swift:6` | yes `apps/PointeKit/Sources/PointeUI/TextDirection.swift:6` |
| How full the voice model's context is <br>`call.context` | yes `ui.html:1184` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:409` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:409` |
| Recent requests and where each went <br>`call.recent` | yes `ui.html:1179` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:330` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:330` |
| A line while the Mac keeps itself awake for a call from another device <br>`call.keep-awake` | n/a | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:549` | n/a |

## Push to talk and turn taking

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Microphone: Always on or Push to talk <br>`talk.mode` | yes `ui.html:1439` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:107` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:107` |
| The Always on / Push to talk switch over the mic <br>`talk.switch` | yes `ui.html:1744` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:127` | yes `apps/PointeKit/Sources/PointeUI/BottomBar.swift:127` |
| Talk button: Hold to talk or Tap to talk <br>`talk.style` | yes `ui.html:1440` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:113` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:113` |
| The mic is the talk button: hold it, or tap it <br>`talk.ring` | yes `ui.html:1654` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:191` | yes `apps/macos/PointeMac/AppModel.swift:496` |
| A draft of what a press has heard so far <br>`talk.draft` | yes `ui.html:1725` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:429` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:429` |
| Why the Mac closed a press by itself (held too long, no audio) <br>`talk.closed-why` | yes `ui.html:4684` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:29` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:29` |
| Talk without touching the screen: a key, a system-wide shortcut, or the Action button <br>`talk.key` | yes `ui.html:1441` | yes `apps/ios/PointeShared/TalkIntents.swift:13` | yes `apps/macos/PointeMac/HotKey.swift:5` |
| Skip from any app: a system-wide shortcut, set in Settings <br>`skip.key` | n/a | n/a | yes `apps/macos/PointeMac/AppModel.swift:81` |
| Wait before answering: Quick, Normal or Patient <br>`talk.patience` | yes `ui.html:1461` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:119` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:119` |
| Hold mode ("don't interrupt me"): quiet until you release it <br>`talk.hold` | yes `ui.html:2643` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:22` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:22` |

## Sessions and machines

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Sessions, grouped by machine, with each one's agent and state <br>`sessions.list` | yes `ui.html:1153` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:161` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:161` |
| Focus on a session <br>`sessions.switch` | yes `ui.html:3115` | yes `apps/PointeKit/Sources/PointeUI/API.swift:549` | yes `apps/PointeKit/Sources/PointeUI/API.swift:549` |
| Orchestrator or Session mode <br>`sessions.mode` | yes `ui.html:1160` | yes `apps/PointeKit/Sources/PointeUI/API.swift:587` | yes `apps/PointeKit/Sources/PointeUI/API.swift:587` |
| Session mode holds the other sessions' news: a quiet count, the list, Tell me <br>`sessions.held` | yes `ui.html:1630` | yes `apps/PointeKit/Sources/PointeUI/Held.swift:62` | yes `apps/PointeKit/Sources/PointeUI/Held.swift:62` |
| Rename a session <br>`sessions.rename` | yes `ui.html:3099` | yes `apps/PointeKit/Sources/PointeUI/API.swift:555` | yes `apps/PointeKit/Sources/PointeUI/API.swift:555` |
| Disconnect a session from the voice <br>`sessions.disconnect` | yes `ui.html:3383` | yes `apps/PointeKit/Sources/PointeUI/API.swift:552` | yes `apps/PointeKit/Sources/PointeUI/API.swift:552` |
| Show only one machine's sessions <br>`sessions.filter` | yes `ui.html:1168` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:588` | yes `apps/PointeKit/Sources/PointeUI/Sessions.swift:588` |
| Start a new session: agent, folder, machine, name, first prompt <br>`sessions.new` | yes `ui.html:1556` | yes `apps/PointeKit/Sources/PointeUI/NewSession.swift:12` | yes `apps/PointeKit/Sources/PointeUI/NewSession.swift:12` |
| The read-back card of a session asked for by voice: Start or Cancel <br>`sessions.new.readback` | yes `ui.html:1719` | yes `apps/PointeKit/Sources/PointeUI/NewSession.swift:153` | yes `apps/PointeKit/Sources/PointeUI/NewSession.swift:153` |
| Add sessions already open, or reopen one from this week: search, by machine and agent <br>`sessions.add` | yes `ui.html:1570` | yes `apps/PointeKit/Sources/PointeUI/AddSessions.swift:14` | yes `apps/PointeKit/Sources/PointeUI/AddSessions.swift:14` |
| The read-back card of sessions asked for by voice: Join, Reopen or Cancel <br>`sessions.add.readback` | yes `ui.html:1720` | yes `apps/PointeKit/Sources/PointeUI/AddSessions.swift:130` | yes `apps/PointeKit/Sources/PointeUI/AddSessions.swift:130` |
| Which folders a new session may start in <br>`sessions.new.folders` | yes `ui.html:1481` | n/a | yes `apps/macos/PointeMac/MacSettings.swift:91` |
| Machines on this voice: online, sessions, round trip, key fingerprint <br>`machines.list` | yes `ui.html:1327` | yes `apps/PointeKit/Sources/PointeUI/Settings.swift:9` | yes `apps/PointeKit/Sources/PointeUI/Settings.swift:9` |
| Invite a machine with a one-time code, cancel it, revoke a machine <br>`machines.invite` | yes `ui.html:1339` | yes `apps/PointeKit/Sources/PointeUI/Settings.swift:131` | yes `apps/PointeKit/Sources/PointeUI/Settings.swift:131` |

## Approvals and alerts

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| A permission request as a card with the exact request, Deny and Approve <br>`approve.card` | yes `ui.html:1718` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1864` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1864` |
| Any request can be approved by a spoken yes: read out short or word for word; the card says which (a secret is never said: tap) <br>`approve.voice` | yes `ui.html:2550` | yes `apps/PointeKit/Sources/PointeUI/API.swift:469` | yes `apps/PointeKit/Sources/PointeUI/API.swift:469` |
| Approve asks that it is you: Face ID on the phone, Touch ID or the password on the Mac <br>`approve.owner` | n/a | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1184` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1184` |
| How many more requests wait <br>`approve.more` | yes `ui.html:2545` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:716` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:716` |
| A request whose machine went offline says it is back in its terminal <br>`approve.offline` | yes `ui.html:1928` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1902` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1902` |
| A notification when a session needs you and you are not looking <br>`alerts.notify` | yes `ui.html:4893` | yes `apps/PointeKit/Sources/PointeUI/Alerts.swift:167` | yes `apps/PointeKit/Sources/PointeUI/Alerts.swift:167` |
| Approve from notifications, as a setting <br>`alerts.approve` | yes `ui.html:1499` | yes `apps/PointeKit/Sources/PointeUI/API.swift:411` | yes `apps/PointeKit/Sources/PointeUI/API.swift:411` |
| Deny and Approve on the notification itself <br>`alerts.actions` | n/a | yes `apps/PointeKit/Sources/PointeUI/Alerts.swift:209` | yes `apps/PointeKit/Sources/PointeUI/Alerts.swift:209` |
| Alerts keep arriving while the app is in the background <br>`alerts.background` | n/a | yes `apps/ios/Pointe/PointeApp.swift:13` | yes `apps/macos/PointeMac/PointeMacApp.swift:16` |

## Brain dump and challenge

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Brain dump: think aloud, the thoughts listed, Done or Discard <br>`dump.panel` | yes `ui.html:1698` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:127` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:127` |
| Review the structured prompt: edit, pick who gets it, send <br>`dump.review` | yes `ui.html:1243` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:300` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:300` |
| Add more, or have it read back, before sending <br>`dump.more` | yes `ui.html:1254` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:302` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:302` |
| Challenge the plan from the review <br>`dump.challenge` | yes `ui.html:1256` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:304` | yes `apps/PointeKit/Sources/PointeUI/BrainDump.swift:304` |
| Challenge (devil's advocate): the items, the plan, End <br>`challenge.panel` | yes `ui.html:1687` | yes `apps/PointeKit/Sources/PointeUI/Challenge.swift:76` | yes `apps/PointeKit/Sources/PointeUI/Challenge.swift:76` |

## Meetings

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Start a meeting: mode, context, sessions that may be asked, consent <br>`meeting.start` | yes `ui.html:1203` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:130` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:130` |
| Listening or Participating, switched during the meeting <br>`meeting.mode` | yes `ui.html:1647` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:229` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:229` |
| The notes feed, filtered by kind, and the transcript <br>`meeting.notes` | yes `ui.html:1684` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:417` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:417` |
| A raised hand: let it speak, later, or type it <br>`meeting.hand` | yes `ui.html:1671` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:371` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:371` |
| Name the speakers; "that was me" <br>`meeting.speakers` | yes `ui.html:1645` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:701` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:701` |
| Ask or add context during the meeting, and look a note up <br>`meeting.ask` | yes `ui.html:1685` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:631` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:631` |
| End: the summary, export notes (with the transcript), send the action items, discard <br>`meeting.end` | yes `ui.html:1228` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:749` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:749` |
| Meeting settings: default mode, lookups, consent, notes language <br>`meeting.settings` | yes `ui.html:1407` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:872` | yes `apps/PointeKit/Sources/PointeUI/Meeting.swift:872` |

## Briefings, whisper, drive

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Briefing: what happened since, play, stop, length <br>`briefing.sheet` | yes `ui.html:1529` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:187` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:187` |
| A ready briefing offers itself; playing, it has its own bar <br>`briefing.ready` | yes `ui.html:1723` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:166` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:166` |
| A scheduled briefing: days, time, length, skip when empty <br>`briefing.schedule` | yes `ui.html:1398` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:312` | yes `apps/PointeKit/Sources/PointeUI/Briefing.swift:312` |
| Night shift: tasks for the sessions, the hours and the message budget, Start <br>`night.start` | yes `ui.html:1581` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:16` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:16` |
| The read-back card of a night shift asked for by voice: Start or Cancel <br>`night.readback` | yes `ui.html:1721` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:216` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:216` |
| A running night shift: tasks done, the blocked count, Stop <br>`night.status` | yes `ui.html:1722` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:168` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:168` |
| The night's ledger: decisions, questions, done, blocked with the exact request, in flight <br>`night.ledger` | yes `ui.html:1597` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:253` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:253` |
| Alerts about a night shift's blockers: off unless asked for <br>`night.notify` | yes `ui.html:1592` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:116` | yes `apps/PointeKit/Sources/PointeUI/NightShift.swift:116` |
| Whisper: short quiet replies, with the notes it held back <br>`whisper` | yes `ui.html:1762` | yes `apps/PointeKit/Sources/PointeUI/Whisper.swift:61` | yes `apps/PointeKit/Sources/PointeUI/Whisper.swift:61` |
| Mute Pointe: one button beside the status line, every reply as text, each device's own choice <br>`mute` | yes `ui.html:1625` | yes `apps/PointeKit/Sources/PointeUI/Mute.swift:71` | yes `apps/PointeKit/Sources/PointeUI/Mute.swift:71` |
| Muted, the state line says Writing… where it would say Speaking… <br>`mute.writing` | yes `ui.html:2981` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:25` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:25` |
| Muting mid-reply stops what the device still holds to play <br>`mute.cut` | yes `ui_mute.html:43` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:165` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:165` |
| The status line says Thinking… from the end of the turn until the reply <br>`thinking` | yes `ui_thinking.html:20` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:27` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:27` |
| The status line names the session that has the request: "billing is working…" <br>`thinking.working` | yes `ui_thinking.html:21` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:36` | yes `apps/PointeKit/Sources/PointeUI/CallTitle.swift:36` |
| The call's own link says the turn was taken: Thinking… without waiting for a status <br>`thinking.link` | yes `ui.html:2693` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:520` | yes `apps/PointeKit/Sources/PointeUI/Call.swift:520` |
| The state's dot tells thinking, speaking and working apart by motion, and Reduce Motion stops it <br>`thinking.motion` | yes `ui_thinking.html:13` | yes `apps/PointeKit/Sources/PointeUI/Thinking.swift:60` | yes `apps/PointeKit/Sources/PointeUI/Thinking.swift:60` |
| The call bubble and the menu bar item show thinking <br>`thinking.bubble` | n/a | n/a | yes `apps/macos/PointeMac/Bubble.swift:267` |
| The waiting sound: a setting, on by default <br>`thinking.cue` | yes `ui.html:1467` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:129` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:129` |
| Progress updates while a session works: a setting, off by default <br>`progress` | yes `ui.html:1471` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:137` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:137` |
| Skip what Pointe is saying: one button beside the status line, after the mute button, only while it speaks <br>`skip` | yes `ui.html:1626` | yes `apps/PointeKit/Sources/PointeUI/Skip.swift:18` | yes `apps/PointeKit/Sources/PointeUI/Skip.swift:18` |
| Skipping stops what the device still holds to play <br>`skip.cut` | yes `ui_skip.html:24` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1582` | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:1582` |
| The conversation's text can be selected and copied <br>`talk.copy` | yes `ui.html:457` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:93` | yes `apps/PointeKit/Sources/PointeUI/Conversation.swift:93` |
| Drive mode on screen: the one line, the request, Stop <br>`drive.screen` | yes `ui.html:1712` | yes `apps/PointeKit/Sources/PointeUI/Drive.swift:87` | yes `apps/PointeKit/Sources/PointeUI/Drive.swift:87` |
| Turn drive mode on from the screen <br>`drive.start` | n/a | yes `apps/PointeKit/Sources/PointeUI/CallView.swift:511` | n/a |
| Offer drive mode when the phone is in a car <br>`drive.suggest` | n/a | yes `apps/PointeKit/Sources/PointeUI/Drive.swift:227` | n/a |

## Voice lock, dictionary, conflicts, show

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Voice lock: which actions only your voice may do <br>`lock.level` | yes `ui.html:1316` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:181` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:181` |
| Enrol your voice, per device, and delete a voiceprint <br>`lock.enrol` | yes `ui.html:1308` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:122` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:122` |
| What the lock ignored, and the note after three unsure yeses <br>`lock.ignored` | yes `ui.html:1549` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:219` | yes `apps/PointeKit/Sources/PointeUI/VoiceLock.swift:219` |
| Dictionary: the terms, add, edit, delete, suggestions, learn from fixes <br>`dictionary.sheet` | yes `ui.html:1392` | yes `apps/PointeKit/Sources/PointeUI/Vocabulary.swift:139` | yes `apps/PointeKit/Sources/PointeUI/Vocabulary.swift:139` |
| A term learned during the call shows, with Undo <br>`dictionary.toast` | yes `ui_dictionary.html:29` | yes `apps/PointeKit/Sources/PointeUI/Vocabulary.swift:120` | yes `apps/PointeKit/Sources/PointeUI/Vocabulary.swift:120` |
| Two sessions disagree: the card, ask either, dismiss <br>`conflicts.card` | yes `ui.html:1711` | yes `apps/PointeKit/Sources/PointeUI/Conflicts.swift:80` | yes `apps/PointeKit/Sources/PointeUI/Conflicts.swift:80` |
| Conflict alarm settings: on, spoken <br>`conflicts.settings` | yes `ui.html:1488` | yes `apps/PointeKit/Sources/PointeUI/Conflicts.swift:169` | yes `apps/PointeKit/Sources/PointeUI/Conflicts.swift:169` |
| Show while it says: the file, the diff or the test the voice is talking about <br>`show.card` | yes `ui.html:1774` | yes `apps/PointeKit/Sources/PointeUI/Show.swift:86` | yes `apps/PointeKit/Sources/PointeUI/Show.swift:86` |
| Also show on the phone, as a setting <br>`show.setting` | yes `ui.html:1432` | yes `apps/PointeKit/Sources/PointeUI/Show.swift:325` | yes `apps/PointeKit/Sources/PointeUI/Show.swift:325` |

## Pairing, appearance, about, help

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Show the code that pairs a phone, list the paired phones, unpair <br>`pair.show` | yes `ui.html:1349` | n/a | yes `apps/PointeKit/Sources/PointeUI/PhoneSheet.swift:235` |
| Pair with the Mac: scan or paste the code in the app, then confirm; unpair this phone <br>`pair.read` | n/a | yes `apps/PointeKit/Sources/PointeUI/PairView.swift:6` | n/a |
| Appearance: System, Light or Dark <br>`appearance` | yes `ui.html:1509` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:206` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:206` |
| About: what Pointe is, the version, the repository <br>`about` | yes `ui.html:1516` | yes `apps/PointeKit/Sources/PointeUI/About.swift:51` | yes `apps/PointeKit/Sources/PointeUI/About.swift:51` |
| The app's version beside the daemon's when they differ <br>`about.version` | yes `ui.html:1154` | yes `apps/PointeKit/Sources/PointeUI/Brand.swift:562` | yes `apps/macos/PointeMac/AppModel.swift:249` |
| Local mode, as one read-only line <br>`local-mode` | yes `ui.html:1417` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:52` | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:52` |
| The voice knows where this surface keeps each control (product_help.json) <br>`help` | yes `product_help.json (40 topics)` | yes `product_help.json (40 topics)` | yes `product_help.json (39 topics)` |
| A demo with invented sessions, no Mac needed <br>`demo` | n/a | yes `apps/PointeKit/Sources/PointeUI/Demo.swift:7` | yes `apps/PointeKit/Sources/PointeUI/Demo.swift:7` |
| Keyboard: a key for every main action <br>`keys` | yes `ui.html:3315` | n/a | yes `apps/macos/PointeMac/Panels.swift:169` |

## The Mac shell

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| A menu bar item with the state and who needs you <br>`mac.menubar` | n/a | n/a | yes `apps/macos/PointeMac/PointeMacApp.swift:16` |
| A small call bubble that floats over other apps while a call is up: click to open, drag, small or full, × <br>`mac.bubble` | n/a | n/a | yes `apps/macos/PointeMac/Bubble.swift:144` |
| The talk mode and the talk shortcut ("Hold ⌃⌥Space"), in the window and the bubble <br>`mac.talkmode` | n/a | n/a | yes `apps/macos/PointeMac/AppModel.swift:146` |
| Open at login <br>`mac.login` | n/a | n/a | yes `apps/macos/PointeMac/Platform.swift:4` |
| Find, start and restart Pointe on this Mac; say when versions differ <br>`mac.daemon` | n/a | n/a | yes `apps/macos/PointeMac/AppModel.swift:206` |
| Which roles the keys fill: a key no role needs is Optional, an empty role names the one key to add <br>`keys.status` | yes `ui.html:1421` | n/a | yes `apps/macos/PointeMac/AppModel.swift:392` |
| Which vendor keys are in the Keychain, and Add… <br>`mac.keys` | n/a | n/a | yes `apps/macos/PointeMac/AppModel.swift:386` |

## The phone alone

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| An AirPods press talks or mutes <br>`ios.airpods` | n/a | yes `apps/PointeKit/Sources/PointeUI/Call.swift:290` | n/a |
| Drive mode on the lock screen <br>`ios.nowplaying` | n/a | yes `apps/PointeKit/Sources/PointeUI/Drive.swift:277` | n/a |
| Talk to Pointe from Control Center, the Lock Screen or the Action button: one press opens Pointe talking to the orchestrator, the next sends <br>`ios.control` | n/a | yes `apps/ios/PointeWidget/TalkControl.swift:8` | n/a |
| The call on the Lock Screen and in the Dynamic Island, with Send, Cancel, Talk and Hang up <br>`ios.live-activity` | n/a | yes `apps/ios/PointeWidget/TalkLiveActivity.swift:12` | n/a |
| A Home Screen tile: Talk to Pointe, with the Mac's status where the app group allows <br>`ios.widget` | n/a | yes `apps/ios/PointeWidget/TalkWidget.swift:8` | n/a |
| Turn Talk from outside the app on or off <br>`ios.outside-setting` | n/a | yes `apps/PointeKit/Sources/PointeUI/CallSettings.swift:150` | n/a |

## Bound to a platform

A feature a surface cannot have, and why. Everything else is on all three.

| Feature | Not on | Why |
|---|---|---|
| A line while the Mac keeps itself awake for a call from another device | Page | the rule runs only for a call from another device; on the Mac there is nothing to say |
| A line while the Mac keeps itself awake for a call from another device | Mac | the rule runs only for a call from another device; on the Mac there is nothing to say |
| Skip from any app: a system-wide shortcut, set in Settings | Page | A page hears keys only while its tab has the focus: it has the button, and no key from another app. |
| Skip from any app: a system-wide shortcut, set in Settings | iPhone | An iPhone has no system-wide key: it has the button. |
| Which folders a new session may start in | iPhone | the daemon takes this setting at the Mac only (daemon.py: voice/prefs refuses sessions.folders off the Mac) |
| Approve asks that it is you: Face ID on the phone, Touch ID or the password on the Mac | Page | a browser page cannot ask for Touch ID without WebAuthn enrolment; the page is on the unlocked Mac beside the terminal |
| Deny and Approve on the notification itself | Page | a web notification has no authenticated action; the click opens the page |
| Alerts keep arriving while the app is in the background | Page | a background tab keeps its timer; there is nothing to schedule |
| The call bubble and the menu bar item show thinking | Page | The page has no bubble and no menu bar item: its state line is always on screen. |
| The call bubble and the menu bar item show thinking | iPhone | The iPhone has no bubble: its state line is the call screen's. |
| Turn drive mode on from the screen | Page | drive mode is for a phone in a car: it starts there or by voice, and the Mac only shows it and stops it |
| Turn drive mode on from the screen | Mac | drive mode is for a phone in a car: it starts there or by voice, and the Mac only shows it and stops it |
| Offer drive mode when the phone is in a car | Page | no motion sensor and no car audio route on a Mac |
| Offer drive mode when the phone is in a car | Mac | no motion sensor and no car audio route on a Mac |
| Show the code that pairs a phone, list the paired phones, unpair | iPhone | the phone is the device being paired: it reads the code the Mac shows |
| Pair with the Mac: scan or paste the code in the app, then confirm; unpair this phone | Page | the page is served by the daemon on the Mac: it is the side that shows the code |
| Pair with the Mac: scan or paste the code in the app, then confirm; unpair this phone | Mac | the Mac app talks to its own daemon on loopback: nothing to pair |
| A demo with invented sessions, no Mac needed | Page | the page exists only while the daemon runs, so there is nothing to start, find or demo from it |
| Keyboard: a key for every main action | iPhone | an iPhone has no keyboard by default; VoiceOver and Switch Control reach every control by its label |
| A menu bar item with the state and who needs you | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A menu bar item with the state and who needs you | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A small call bubble that floats over other apps while a call is up: click to open, drag, small or full, × | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A small call bubble that floats over other apps while a call is up: click to open, drag, small or full, × | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| The talk mode and the talk shortcut ("Hold ⌃⌥Space"), in the window and the bubble | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| The talk mode and the talk shortcut ("Hold ⌃⌥Space"), in the window and the bubble | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| Open at login | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| Open at login | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| Find, start and restart Pointe on this Mac; say when versions differ | Page | the page exists only while the daemon runs, so there is nothing to start, find or demo from it |
| Find, start and restart Pointe on this Mac; say when versions differ | iPhone | the phone reaches a Mac that already runs Pointe |
| Which roles the keys fill: a key no role needs is Optional, an empty role names the one key to add | iPhone | the keys live in the Mac's Keychain, and the iPhone app shows none of them |
| Which vendor keys are in the Keychain, and Add… | Page | keys are added with `pointe key`, never through a page |
| Which vendor keys are in the Keychain, and Add… | iPhone | the keys live in the Mac's Keychain |
| An AirPods press talks or mutes | Page | needs the phone's own hardware or system service (macOS gives the press to the media-key owner) |
| An AirPods press talks or mutes | Mac | needs the phone's own hardware or system service (macOS gives the press to the media-key owner) |
| Drive mode on the lock screen | Page | needs the phone's own hardware or system service |
| Drive mode on the lock screen | Mac | needs the phone's own hardware or system service |
| Talk to Pointe from Control Center, the Lock Screen or the Action button: one press opens Pointe talking to the orchestrator, the next sends | Page | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18); the page's from-any-app is a system-wide shortcut running `pointe talk` |
| Talk to Pointe from Control Center, the Lock Screen or the Action button: one press opens Pointe talking to the orchestrator, the next sends | Mac | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18); the Mac app's is its talk shortcut (talk.key) |
| The call on the Lock Screen and in the Dynamic Island, with Send, Cancel, Talk and Hang up | Page | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |
| The call on the Lock Screen and in the Dynamic Island, with Send, Cancel, Talk and Hang up | Mac | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18); the Mac app's call bubble does the same (mac.bubble) |
| A Home Screen tile: Talk to Pointe, with the Mac's status where the app group allows | Page | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |
| A Home Screen tile: Talk to Pointe, with the Mac's status where the app group allows | Mac | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18); the Mac app's menu bar item shows the same (mac.menubar) |
| Turn Talk from outside the app on or off | Page | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |
| Turn Talk from outside the app on or off | Mac | an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18) |

## Gaps

None: every feature is on every surface that can have it.
