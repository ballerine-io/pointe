# Parity matrix

Written by `python3 tools/parity.py` from the code of the three surfaces; do not edit by hand.
`tests/test_parity_matrix.py` fails when this file is stale, and when a feature is missing from a surface
without a reason. What the rows mean, how the scan works and the component spec: [parity.md](parity.md).

## Counts

| Surface | yes | partial | no | n/a (bound to another surface) |
|---|---|---|---|---|
| Page | 73 | 0 | 0 | 15 |
| iPhone | 80 | 0 | 0 | 8 |
| Mac | 82 | 0 | 0 | 6 |

Before this work (1.16.0, a9ddfea), by the same scan:

| Surface | yes | partial | no | n/a |
|---|---|---|---|---|
| Page | 73 | 0 | 1 | 14 |
| iPhone | 79 | 0 | 1 | 8 |
| Mac | 43 | 0 | 40 | 5 |

## The call

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Connect, Try again, Cancel and Hang up, with the reason a call did not start <br>`call.connect` | yes `ui.html:1421` | yes `apple/PointeKit/Sources/PointeUI/Connect.swift:110` | yes `apple/PointeKit/Sources/PointeUI/Connect.swift:110` |
| A dropped call is redialled; a refused or idle-ended one is not, and says why <br>`call.redial` | yes `ui.html:2070` | yes `apple/PointeKit/Sources/PointeUI/Call.swift:542` | yes `apple/PointeKit/Sources/PointeUI/Call.swift:542` |
| The state line: listening, speaking, muted, holding, reconnecting <br>`call.state` | yes `ui.html:1393` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:1547` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:1547` |
| Mute and unmute <br>`call.mute` | yes `ui.html:1504` | yes `apple/PointeKit/Sources/PointeUI/Call.swift:124` | yes `apple/PointeKit/Sources/PointeUI/Call.swift:124` |
| The conversation, newest line followed <br>`call.transcript` | yes `ui.html:1004` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:411` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:411` |
| A New pill when lines arrive while you read further up <br>`call.new-pill` | yes `ui.html:1428` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:433` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:433` |
| Your words as you speak them <br>`call.hearing` | yes `ui.html:1483` | yes `apple/PointeKit/Sources/PointeUI/Conversation.swift:111` | yes `apple/PointeKit/Sources/PointeUI/Conversation.swift:111` |
| Type instead of talking <br>`call.type` | yes `ui.html:1484` | yes `apple/PointeKit/Sources/PointeUI/BottomBar.swift:168` | yes `apple/PointeKit/Sources/PointeUI/BottomBar.swift:168` |
| Fix what was heard in a line of yours <br>`call.correct` | yes `ui.html:2561` | yes `apple/PointeKit/Sources/PointeUI/Conversation.swift:172` | yes `apple/PointeKit/Sources/PointeUI/Conversation.swift:172` |
| Clean up my words <br>`call.polish` | yes `ui.html:1399` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:109` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:109` |
| The daemon's last problem (a refused key, a vendor down) on screen <br>`call.problem` | yes `ui.html:1395` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:402` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:402` |
| Hebrew lines read right to left <br>`call.rtl` | yes `ui.html:1043` | yes `apple/PointeKit/Sources/PointeUI/TextDirection.swift:6` | yes `apple/PointeKit/Sources/PointeUI/TextDirection.swift:6` |
| How full the voice model's context is <br>`call.context` | yes `ui.html:1016` | yes `apple/PointeKit/Sources/PointeUI/Sessions.swift:336` | yes `apple/PointeKit/Sources/PointeUI/Sessions.swift:336` |
| Recent requests and where each went <br>`call.recent` | yes `ui.html:1011` | yes `apple/PointeKit/Sources/PointeUI/Sessions.swift:277` | yes `apple/PointeKit/Sources/PointeUI/Sessions.swift:277` |
| A line while the Mac keeps itself awake for a call from another device <br>`call.keep-awake` | n/a | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:507` | n/a |

## Push to talk and turn taking

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Microphone: Always on or Push to talk <br>`talk.mode` | yes `ui.html:1256` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:93` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:93` |
| The Always on / Push to talk switch over the mic <br>`talk.switch` | yes `ui.html:1501` | yes `apple/PointeKit/Sources/PointeUI/BottomBar.swift:124` | yes `apple/PointeKit/Sources/PointeUI/BottomBar.swift:124` |
| Talk button: Hold to talk or Tap to talk <br>`talk.style` | yes `ui.html:1257` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:99` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:99` |
| The mic is the talk button: hold it, or tap it <br>`talk.ring` | yes `ui.html:1415` | yes `apple/PointeKit/Sources/PointeUI/Call.swift:147` | yes `macos/PointeMac/AppModel.swift:259` |
| A draft of what a press has heard so far <br>`talk.draft` | yes `ui.html:1483` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:399` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:399` |
| Why the Mac closed a press by itself (held too long, no audio) <br>`talk.closed-why` | yes `ui.html:3762` | yes `apple/PointeKit/Sources/PointeUI/CallTitle.swift:21` | yes `apple/PointeKit/Sources/PointeUI/CallTitle.swift:21` |
| Talk without touching the screen: a key, a system-wide shortcut, or the Action button <br>`talk.key` | yes `ui.html:1258` | yes `ios/Pointe/TalkIntent.swift:7` | yes `macos/PointeMac/HotKey.swift:5` |
| Wait before answering: Quick, Normal or Patient <br>`talk.patience` | yes `ui.html:1278` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:105` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:105` |
| Hold mode ("don't interrupt me"): quiet until you release it <br>`talk.hold` | yes `ui.html:2011` | yes `apple/PointeKit/Sources/PointeUI/CallTitle.swift:16` | yes `apple/PointeKit/Sources/PointeUI/CallTitle.swift:16` |

## Sessions and machines

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Sessions, grouped by machine, with each one's agent and state <br>`sessions.list` | yes `ui.html:988` | yes `apple/PointeKit/Sources/PointeUI/Sessions.swift:142` | yes `apple/PointeKit/Sources/PointeUI/Sessions.swift:142` |
| Focus on a session <br>`sessions.switch` | yes `ui.html:2420` | yes `apple/PointeKit/Sources/PointeUI/API.swift:516` | yes `apple/PointeKit/Sources/PointeUI/API.swift:516` |
| Orchestrator or Session mode <br>`sessions.mode` | yes `ui.html:995` | yes `apple/PointeKit/Sources/PointeUI/API.swift:534` | yes `apple/PointeKit/Sources/PointeUI/API.swift:534` |
| Rename a session <br>`sessions.rename` | yes `ui.html:2404` | yes `apple/PointeKit/Sources/PointeUI/API.swift:522` | yes `apple/PointeKit/Sources/PointeUI/API.swift:522` |
| Disconnect a session from the voice <br>`sessions.disconnect` | yes `ui.html:2616` | yes `apple/PointeKit/Sources/PointeUI/API.swift:519` | yes `apple/PointeKit/Sources/PointeUI/API.swift:519` |
| Show only one machine's sessions <br>`sessions.filter` | yes `ui.html:1003` | yes `apple/PointeKit/Sources/PointeUI/Sessions.swift:511` | yes `apple/PointeKit/Sources/PointeUI/Sessions.swift:511` |
| Start a new session: agent, folder, machine, name, first prompt <br>`sessions.new` | yes `ui.html:1362` | yes `apple/PointeKit/Sources/PointeUI/NewSession.swift:12` | yes `apple/PointeKit/Sources/PointeUI/NewSession.swift:12` |
| The read-back card of a session asked for by voice: Start or Cancel <br>`sessions.new.readback` | yes `ui.html:1480` | yes `apple/PointeKit/Sources/PointeUI/NewSession.swift:154` | yes `apple/PointeKit/Sources/PointeUI/NewSession.swift:154` |
| Which folders a new session may start in <br>`sessions.new.folders` | yes `ui.html:1287` | n/a | yes `macos/PointeMac/MacSettings.swift:79` |
| Machines on this voice: online, sessions, round trip, key fingerprint <br>`machines.list` | yes `ui.html:1157` | yes `apple/PointeKit/Sources/PointeUI/Settings.swift:9` | yes `apple/PointeKit/Sources/PointeUI/Settings.swift:9` |
| Invite a machine with a one-time code, cancel it, revoke a machine <br>`machines.invite` | yes `ui.html:1168` | yes `apple/PointeKit/Sources/PointeUI/Settings.swift:131` | yes `apple/PointeKit/Sources/PointeUI/Settings.swift:131` |

## Approvals and alerts

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| A permission request as a card with the exact request, Deny and Approve <br>`approve.card` | yes `ui.html:1479` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:1551` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:1551` |
| Approve asks that it is you: Face ID on the phone, Touch ID or the password on the Mac <br>`approve.owner` | n/a | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:1078` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:1078` |
| How many more requests wait <br>`approve.more` | yes `ui.html:1934` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:636` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:636` |
| A request whose machine went offline says it is back in its terminal <br>`approve.offline` | yes `ui.html:1670` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:1582` | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:1582` |
| A notification when a session needs you and you are not looking <br>`alerts.notify` | yes `ui.html:3956` | yes `apple/PointeKit/Sources/PointeUI/Alerts.swift:167` | yes `apple/PointeKit/Sources/PointeUI/Alerts.swift:167` |
| Approve from notifications, as a setting <br>`alerts.approve` | yes `ui.html:1305` | yes `apple/PointeKit/Sources/PointeUI/API.swift:383` | yes `apple/PointeKit/Sources/PointeUI/API.swift:383` |
| Deny and Approve on the notification itself <br>`alerts.actions` | n/a | yes `apple/PointeKit/Sources/PointeUI/Alerts.swift:209` | yes `apple/PointeKit/Sources/PointeUI/Alerts.swift:209` |
| Alerts keep arriving while the app is in the background <br>`alerts.background` | n/a | yes `ios/Pointe/PointeApp.swift:13` | yes `macos/PointeMac/PointeMacApp.swift:16` |

## Brain dump and challenge

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Brain dump: think aloud, the thoughts listed, Done or Discard <br>`dump.panel` | yes `ui.html:1459` | yes `apple/PointeKit/Sources/PointeUI/BrainDump.swift:126` | yes `apple/PointeKit/Sources/PointeUI/BrainDump.swift:126` |
| Review the structured prompt: edit, pick who gets it, send <br>`dump.review` | yes `ui.html:1074` | yes `apple/PointeKit/Sources/PointeUI/BrainDump.swift:289` | yes `apple/PointeKit/Sources/PointeUI/BrainDump.swift:289` |
| Add more, or have it read back, before sending <br>`dump.more` | yes `ui.html:1085` | yes `apple/PointeKit/Sources/PointeUI/BrainDump.swift:291` | yes `apple/PointeKit/Sources/PointeUI/BrainDump.swift:291` |
| Challenge the plan from the review <br>`dump.challenge` | yes `ui.html:1087` | yes `apple/PointeKit/Sources/PointeUI/BrainDump.swift:293` | yes `apple/PointeKit/Sources/PointeUI/BrainDump.swift:293` |
| Challenge (devil's advocate): the items, the plan, End <br>`challenge.panel` | yes `ui.html:1448` | yes `apple/PointeKit/Sources/PointeUI/Challenge.swift:76` | yes `apple/PointeKit/Sources/PointeUI/Challenge.swift:76` |

## Meetings

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Start a meeting: mode, context, sessions that may be asked, consent <br>`meeting.start` | yes `ui.html:1034` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:119` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:119` |
| Listening or Participating, switched during the meeting <br>`meeting.mode` | yes `ui.html:1408` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:218` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:218` |
| The notes feed, filtered by kind, and the transcript <br>`meeting.notes` | yes `ui.html:1445` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:406` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:406` |
| A raised hand: let it speak, later, or type it <br>`meeting.hand` | yes `ui.html:1432` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:360` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:360` |
| Name the speakers; "that was me" <br>`meeting.speakers` | yes `ui.html:1406` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:689` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:689` |
| Ask or add context during the meeting, and look a note up <br>`meeting.ask` | yes `ui.html:1446` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:619` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:619` |
| End: the summary, export notes (with the transcript), send the action items, discard <br>`meeting.end` | yes `ui.html:1059` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:737` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:737` |
| Meeting settings: default mode, lookups, consent, notes language <br>`meeting.settings` | yes `ui.html:1233` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:855` | yes `apple/PointeKit/Sources/PointeUI/Meeting.swift:855` |

## Briefings, whisper, drive

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Briefing: what happened since, play, stop, length <br>`briefing.sheet` | yes `ui.html:1335` | yes `apple/PointeKit/Sources/PointeUI/Briefing.swift:186` | yes `apple/PointeKit/Sources/PointeUI/Briefing.swift:186` |
| A ready briefing offers itself; playing, it has its own bar <br>`briefing.ready` | yes `ui.html:1481` | yes `apple/PointeKit/Sources/PointeUI/Briefing.swift:165` | yes `apple/PointeKit/Sources/PointeUI/Briefing.swift:165` |
| A scheduled briefing: days, time, length, skip when empty <br>`briefing.schedule` | yes `ui.html:1224` | yes `apple/PointeKit/Sources/PointeUI/Briefing.swift:308` | yes `apple/PointeKit/Sources/PointeUI/Briefing.swift:308` |
| Whisper: short quiet replies, with the notes it held back <br>`whisper` | yes `ui.html:1519` | yes `apple/PointeKit/Sources/PointeUI/Whisper.swift:61` | yes `apple/PointeKit/Sources/PointeUI/Whisper.swift:61` |
| Drive mode on screen: the one line, the request, Stop <br>`drive.screen` | yes `ui.html:1473` | yes `apple/PointeKit/Sources/PointeUI/Drive.swift:87` | yes `apple/PointeKit/Sources/PointeUI/Drive.swift:87` |
| Turn drive mode on from the screen <br>`drive.start` | n/a | yes `apple/PointeKit/Sources/PointeUI/CallView.swift:473` | n/a |
| Offer drive mode when the phone is in a car <br>`drive.suggest` | n/a | yes `apple/PointeKit/Sources/PointeUI/Drive.swift:215` | n/a |

## Voice lock, dictionary, conflicts, show

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Voice lock: which actions only your voice may do <br>`lock.level` | yes `ui.html:1146` | yes `apple/PointeKit/Sources/PointeUI/VoiceLock.swift:181` | yes `apple/PointeKit/Sources/PointeUI/VoiceLock.swift:181` |
| Enrol your voice, per device, and delete a voiceprint <br>`lock.enrol` | yes `ui.html:1138` | yes `apple/PointeKit/Sources/PointeUI/VoiceLock.swift:122` | yes `apple/PointeKit/Sources/PointeUI/VoiceLock.swift:122` |
| What the lock ignored, and the note after three unsure yeses <br>`lock.ignored` | yes `ui.html:1355` | yes `apple/PointeKit/Sources/PointeUI/VoiceLock.swift:212` | yes `apple/PointeKit/Sources/PointeUI/VoiceLock.swift:212` |
| Dictionary: the terms, add, edit, delete, suggestions, learn from fixes <br>`dictionary.sheet` | yes `ui.html:1218` | yes `apple/PointeKit/Sources/PointeUI/Vocabulary.swift:139` | yes `apple/PointeKit/Sources/PointeUI/Vocabulary.swift:139` |
| A term learned during the call shows, with Undo <br>`dictionary.toast` | yes `ui_dictionary.html:29` | yes `apple/PointeKit/Sources/PointeUI/Vocabulary.swift:120` | yes `apple/PointeKit/Sources/PointeUI/Vocabulary.swift:120` |
| Two sessions disagree: the card, ask either, dismiss <br>`conflicts.card` | yes `ui.html:1472` | yes `apple/PointeKit/Sources/PointeUI/Conflicts.swift:80` | yes `apple/PointeKit/Sources/PointeUI/Conflicts.swift:80` |
| Conflict alarm settings: on, spoken <br>`conflicts.settings` | yes `ui.html:1294` | yes `apple/PointeKit/Sources/PointeUI/Conflicts.swift:169` | yes `apple/PointeKit/Sources/PointeUI/Conflicts.swift:169` |
| Show while it says: the file, the diff or the test the voice is talking about <br>`show.card` | yes `ui.html:1534` | yes `apple/PointeKit/Sources/PointeUI/Show.swift:86` | yes `apple/PointeKit/Sources/PointeUI/Show.swift:86` |
| Also show on the phone, as a setting <br>`show.setting` | yes `ui.html:1249` | yes `apple/PointeKit/Sources/PointeUI/Show.swift:325` | yes `apple/PointeKit/Sources/PointeUI/Show.swift:325` |

## Pairing, appearance, about, help

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| Show the code that pairs a phone, list the paired phones, unpair <br>`pair.show` | yes `ui.html:1177` | n/a | yes `apple/PointeKit/Sources/PointeUI/PhoneSheet.swift:198` |
| Pair with the Mac: scan, paste or open the code; unpair this phone <br>`pair.read` | n/a | yes `apple/PointeKit/Sources/PointeUI/PairView.swift:6` | n/a |
| Appearance: System, Light or Dark <br>`appearance` | yes `ui.html:1315` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:155` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:155` |
| About: what Pointe is, the version, the repository <br>`about` | yes `ui.html:1322` | yes `apple/PointeKit/Sources/PointeUI/About.swift:14` | yes `apple/PointeKit/Sources/PointeUI/About.swift:14` |
| The app's version beside the daemon's when they differ <br>`about.version` | yes `ui.html:989` | yes `apple/PointeKit/Sources/PointeUI/Brand.swift:449` | yes `macos/PointeMac/AppModel.swift:179` |
| Local mode, as one read-only line <br>`local-mode` | yes `ui.html:1243` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:46` | yes `apple/PointeKit/Sources/PointeUI/CallSettings.swift:46` |
| The voice knows where this surface keeps each control (product_help.json) <br>`help` | yes `product_help.json (34 topics)` | yes `product_help.json (35 topics)` | yes `product_help.json (35 topics)` |
| A demo with invented sessions, no Mac needed <br>`demo` | n/a | yes `apple/PointeKit/Sources/PointeUI/Demo.swift:6` | yes `apple/PointeKit/Sources/PointeUI/Demo.swift:6` |
| Keyboard: a key for every main action <br>`keys` | yes `ui.html:2835` | n/a | yes `macos/PointeMac/PointeMacApp.swift:35` |

## The Mac shell

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| A menu bar item with the state and who needs you <br>`mac.menubar` | n/a | n/a | yes `macos/PointeMac/PointeMacApp.swift:16` |
| A small call bubble that floats over other apps <br>`mac.bubble` | n/a | n/a | yes `macos/PointeMac/Panels.swift:111` |
| Open at login <br>`mac.login` | n/a | n/a | yes `macos/PointeMac/Platform.swift:4` |
| Find, start and restart Pointe on this Mac; say when versions differ <br>`mac.daemon` | n/a | n/a | yes `macos/PointeMac/AppModel.swift:138` |
| Which vendor keys are in the Keychain, and Add… <br>`mac.keys` | n/a | n/a | yes `macos/PointeMac/AppModel.swift:198` |

## The phone alone

| Feature | Page | iPhone | Mac |
|---|---|---|---|
| An AirPods press talks or mutes <br>`ios.airpods` | n/a | yes `apple/PointeKit/Sources/PointeUI/Call.swift:247` | n/a |
| Drive mode on the lock screen <br>`ios.nowplaying` | n/a | yes `apple/PointeKit/Sources/PointeUI/Drive.swift:265` | n/a |

## Bound to a platform

A feature a surface cannot have, and why. Everything else is on all three.

| Feature | Not on | Why |
|---|---|---|
| A line while the Mac keeps itself awake for a call from another device | Page | the rule runs only for a call from another device; on the Mac there is nothing to say |
| A line while the Mac keeps itself awake for a call from another device | Mac | the rule runs only for a call from another device; on the Mac there is nothing to say |
| Which folders a new session may start in | iPhone | the daemon takes this setting at the Mac only (daemon.py: voice/prefs refuses sessions.folders off the Mac) |
| Approve asks that it is you: Face ID on the phone, Touch ID or the password on the Mac | Page | a browser page cannot ask for Touch ID without WebAuthn enrolment; the page is on the unlocked Mac beside the terminal |
| Deny and Approve on the notification itself | Page | a web notification has no authenticated action; the click opens the page |
| Alerts keep arriving while the app is in the background | Page | a background tab keeps its timer; there is nothing to schedule |
| Turn drive mode on from the screen | Page | drive mode is for a phone in a car: it starts there or by voice, and the Mac only shows it and stops it |
| Turn drive mode on from the screen | Mac | drive mode is for a phone in a car: it starts there or by voice, and the Mac only shows it and stops it |
| Offer drive mode when the phone is in a car | Page | no motion sensor and no car audio route on a Mac |
| Offer drive mode when the phone is in a car | Mac | no motion sensor and no car audio route on a Mac |
| Show the code that pairs a phone, list the paired phones, unpair | iPhone | the phone is the device being paired: it reads the code the Mac shows |
| Pair with the Mac: scan, paste or open the code; unpair this phone | Page | the page is served by the daemon on the Mac: it is the side that shows the code |
| Pair with the Mac: scan, paste or open the code; unpair this phone | Mac | the Mac app talks to its own daemon on loopback: nothing to pair |
| A demo with invented sessions, no Mac needed | Page | the page exists only while the daemon runs, so there is nothing to start, find or demo from it |
| Keyboard: a key for every main action | iPhone | an iPhone has no keyboard by default; VoiceOver and Switch Control reach every control by its label |
| A menu bar item with the state and who needs you | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A menu bar item with the state and who needs you | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A small call bubble that floats over other apps | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| A small call bubble that floats over other apps | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| Open at login | Page | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| Open at login | iPhone | a Mac shell feature: AppKit only (docs/design/macos-app.md) |
| Find, start and restart Pointe on this Mac; say when versions differ | Page | the page exists only while the daemon runs, so there is nothing to start, find or demo from it |
| Find, start and restart Pointe on this Mac; say when versions differ | iPhone | the phone reaches a Mac that already runs Pointe |
| Which vendor keys are in the Keychain, and Add… | Page | keys are added with `pointe key`, never through a page |
| Which vendor keys are in the Keychain, and Add… | iPhone | the keys live in the Mac's Keychain |
| An AirPods press talks or mutes | Page | needs the phone's own hardware or system service (macOS gives the press to the media-key owner) |
| An AirPods press talks or mutes | Mac | needs the phone's own hardware or system service (macOS gives the press to the media-key owner) |
| Drive mode on the lock screen | Page | needs the phone's own hardware or system service |
| Drive mode on the lock screen | Mac | needs the phone's own hardware or system service |

## Gaps

None: every feature is on every surface that can have it.
