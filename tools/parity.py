"""Write docs/design/parity-matrix.md: which feature each surface has, read from the code of all three.

    python3 tools/parity.py            write docs/design/parity-matrix.md
    python3 tools/parity.py --check    exit 1 if the file is not what this would write
    python3 tools/parity.py --json     the matrix as JSON on stdout (tests/test_parity_matrix.py reads it)

The three surfaces are the page (ui.html), the iPhone app (ios/Pointe and the package it links) and the Mac app
(macos/PointeMac and the package it links). A feature is a row of FEATURES: per surface, the regular expressions that
must all be found in that surface's sources. All found is "yes", some is "partial", none is "no". A surface that cannot
have the feature carries the reason in `bound`, and is "n/a". The Swift the two apps share (apple/PointeKit) counts for
an app only when its project links that target, and is read with the other platform's `#if os(...)` branches blanked,
so a screen compiled out of the Mac app does not count for it. Standard library only.
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = "docs/design/parity-matrix.md"
BASELINE = "tools/parity_baseline.json"
SURFACES = ("web", "ios", "mac")
NAMES = {"web": "Page", "ios": "iPhone", "mac": "Mac"}

# ---------- sources ----------

_IF = re.compile(r"^\s*#(if|elseif|else|endif)\b(.*)$")


def _truth(condition: str, platform: str) -> bool | None:
    """True or False when the condition is decided by the platform alone; None when it is not (DEBUG, a mix)."""
    c = condition.split("//")[0].strip()  # a comment after the condition is not part of it
    facts = {"os(iOS)": platform == "ios", "os(macOS)": platform == "mac", "canImport(UIKit)": platform == "ios",
             "canImport(AppKit)": platform == "mac"}
    if c in facts:
        return facts[c]
    if c.startswith("!") and c[1:].strip() in facts:
        return not facts[c[1:].strip()]
    return None


def for_platform(text: str, platform: str) -> str:
    """The Swift source as one platform compiles it: lines in a branch the platform does not take are blanked, so
    line numbers stay. A condition that is not about the platform keeps every branch."""
    out, stack = [], []  # stack: [taken so far in this #if chain (None: undecided), this branch is live]
    for line in text.split("\n"):
        m = _IF.match(line)
        if m:
            word, rest = m.group(1), m.group(2)
            if word == "if":
                t = _truth(rest, platform)
                stack.append([t, t is not False])
            elif word in ("elseif", "else") and stack:
                taken = stack[-1][0]
                t = True if word == "else" else _truth(rest, platform)
                if taken is None or t is None:
                    stack[-1] = [None, True]
                else:
                    stack[-1] = [taken or t, (not taken) and t]
            elif word == "endif" and stack:
                stack.pop()
            out.append("")
            continue
        out.append(line if all(live for _, live in stack) else "")
    return "\n".join(out)


_DEPENDS = re.compile(r'\.target\(name: "(\w+)"(?:, dependencies: \[([^\]]*)\])?')


def linked(project: Path, root: Path) -> list[str]:
    """The package targets an app links: the products its project names, and the targets those depend on. A module the
    app does not link is not the app's code, whatever it holds."""
    depends = {name: re.findall(r'"(\w+)"', deps or "")
               for name, deps in _DEPENDS.findall((root / "apple" / "PointeKit" / "Package.swift").read_text())}
    todo = re.findall(r"isa = XCSwiftPackageProductDependency;[^}]*?productName = (\w+);", (project / "project.pbxproj").read_text())
    seen: list[str] = []
    while todo:
        target = todo.pop()
        if target in depends and target not in seen:
            seen.append(target)
            todo += depends[target]
    return sorted(seen)


def sources(surface: str, root: Path = ROOT) -> dict[str, str]:
    """Path (relative to the repository) to text, for one surface."""
    if surface == "web":
        return {path.name: path.read_text() for path in sorted(root.glob("ui*.html"))}  # the page and the parts daemon.py puts in it
    project, own = {"ios": ("ios/Pointe.xcodeproj", "ios/Pointe"), "mac": ("macos/PointeMac.xcodeproj", "macos/PointeMac")}[surface]
    folders = [own] + [f"apple/PointeKit/Sources/{target}" for target in linked(root / project, root)]
    found = {}
    for folder in folders:
        for path in sorted((root / folder).rglob("*.swift")):
            found[str(path.relative_to(root))] = for_platform(path.read_text(), surface)
    return found


# ---------- the features ----------

@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    web: tuple[str, ...] = ()
    ios: tuple[str, ...] = ()
    mac: tuple[str, ...] = ()
    bound: dict = field(default_factory=dict)  # surface -> why it cannot have the feature

    def needs(self, surface: str) -> tuple[str, ...]:
        return getattr(self, surface)


def F(id: str, title: str, web=(), swift=(), ios=None, mac=None) -> Feature:
    """`swift` is what both apps must show; `ios` or `mac` replaces it for one. A list is patterns; a plain sentence
    in place of a list is the reason that surface cannot have the feature."""
    given = {"web": web, "ios": swift if ios is None else ios, "mac": swift if mac is None else mac}
    reasons = {s: v for s, v in given.items() if isinstance(v, str)}
    needs = {s: () if s in reasons else tuple(v) for s, v in given.items()}
    return Feature(id, title, needs["web"], needs["ios"], needs["mac"], reasons)


def ident(*names: str) -> str:
    """An accessibility identifier, any of these."""
    return r'accessibilityIdentifier\("(?:' + "|".join(re.escape(n) for n in names) + r')"\)'


PAGE_IS_THE_MAC = "the page is served by the daemon on the Mac: it is the side that shows the code"
NO_DAEMON_NO_PAGE = "the page exists only while the daemon runs, so there is nothing to start, find or demo from it"
MAC_SHELL = "a Mac shell feature: AppKit only (docs/design/macos-app.md)"
DRIVE_IS_THE_PHONES = "drive mode is for a phone in a car: it starts there or by voice, and the Mac only shows it and stops it"
PHONE_ONLY_HARDWARE = "needs the phone's own hardware or system service"

GROUPS: list[tuple[str, list[Feature]]] = [
    ("The call", [
        F("call.connect", "Connect, Try again, Cancel and Hang up, with the reason a call did not start",
          web=['id="connectbtn"', 'id="hangup"', "CONNECT_COPY"], swift=[ident("connectButton"), r"ConnectCopy\.|MacCopy\.tryAgain"]),
        F("call.redial", "A dropped call is redialled; a refused or idle-ended one is not, and says why",
          web=["e.code === 4409", "idleHangup"], swift=[r"func refusal\(|static func refusal", "idleHangup"]),
        F("call.state", "The state line: listening, speaking, muted, holding, reconnecting",
          web=['id="state"', "'Reconnecting…'|reconnecting"], swift=[ident("statusLine", "state"), r"TurnsCopy\.holding"]),
        F("call.mute", "Mute and unmute",
          web=['id="mic"', "Unmute|toggleMute|setMuted"], swift=[r"func toggleMute\("]),
        F("call.transcript", "The conversation, newest line followed",
          web=['id="list"'], swift=[ident("conversation")]),
        F("call.new-pill", "A New pill when lines arrive while you read further up",
          web=['id="newpill"'], swift=[r"pillShown"]),
        F("call.hearing", "Your words as you speak them",
          web=['id="caption-text"'], swift=[r"struct (?:LiveBubble|HearingBubble)\b"]),
        F("call.type", "Type instead of talking",
          web=['id="typed"', "/voice/say"], swift=[ident("typeField"), r'"voice/say"']),
        F("call.correct", "Fix what was heard in a line of yours",
          web=["/voice/correct"], swift=[ident("fixField"), r'"voice/correct"']),
        F("call.polish", "Clean up my words",
          web=['id="polish"', "/voice/polish"], swift=[r'"Clean up my words"', r'"voice/polish"']),
        F("call.problem", "The daemon's last problem (a refused key, a vendor down) on screen",
          web=['id="problem"'], swift=[r"shownProblem|store\.notice|\.notice\b"]),
        F("call.rtl", "Hebrew lines read right to left",
          web=['dir="auto"'], swift=[r"enum TextDirection\b"]),
        F("call.context", "How full the voice model's context is",
          web=['id="ctx"'], swift=[ident("contextTokens")]),
        F("call.recent", "Recent requests and where each went",
          web=['id="recent"'], swift=[r"recentAndContext|struct RecentRequests\b"]),
        F("call.keep-awake", "A line while the Mac keeps itself awake for a call from another device",
          swift=[ident("keepAwake")], web="the rule runs only for a call from another device; on the Mac there is nothing to say",
          mac="the rule runs only for a call from another device; on the Mac there is nothing to say"),
    ]),
    ("Push to talk and turn taking", [
        F("talk.mode", "Microphone: Always on or Push to talk",
          web=['id="pref-mic"'], swift=[ident("microphoneSetting", "settings.microphone")]),
        F("talk.switch", "The Always on / Push to talk switch over the mic",
          web=['id="micmode-ptt"'], swift=[ident("micMode", "micModeSwitch", "micmode")]),
        F("talk.style", "Talk button: Hold to talk or Tap to talk",
          web=['id="pref-style"'], swift=[ident("talkStyleSetting", "settings.talkStyle")]),
        F("talk.ring", "The mic is the talk button: hold it, or tap it",
          web=['id="talk"|id="mic"', "pttHold"], swift=[r"talkPress\(|talkDown\("]),
        F("talk.draft", "A draft of what a press has heard so far",
          web=['id="caption-draft"'], swift=[r"TalkDraft\.line"]),
        F("talk.closed-why", "Why the Mac closed a press by itself (held too long, no audio)",
          web=["closed_why|closedWhy"], swift=[r"closedLine\("]),
        F("talk.key", "Talk without touching the screen: a key, a system-wide shortcut, or the Action button",
          web=['id="pref-key"', 'id="pref-talk"'], ios=[r"struct TalkIntent\b"], mac=[r"RegisterEventHotKey", ident("settings.shortcut", "shortcutRecorder")]),
        F("talk.patience", "Wait before answering: Quick, Normal or Patient",
          web=['id="pref-patience"'], swift=[ident("patienceSetting", "settings.patience")]),
        F("talk.hold", "Hold mode (\"don't interrupt me\"): quiet until you release it",
          web=["holding: 'Holding'"], swift=[r"TurnsCopy\.holdingHow|TurnsCopy\.holding\b"]),
    ]),
    ("Sessions and machines", [
        F("sessions.list", "Sessions, grouped by machine, with each one's agent and state",
          web=['id="side"', "harnessMark"], swift=[r"struct (?:SessionsSheet|SessionSidebar)\b", r"struct MachineView\b"]),
        F("sessions.switch", "Focus on a session",
          web=["/voice/switch"], swift=[r'"voice/switch"']),
        F("sessions.mode", "Orchestrator or Session mode",
          web=['id="m-orchestrator"', "/voice/mode"], swift=[r'"voice/mode"', r"SessionsCopy\.|setMode\("]),
        F("sessions.rename", "Rename a session",
          web=["/voice/rename"], swift=[r'"voice/rename"']),
        F("sessions.disconnect", "Disconnect a session from the voice",
          web=["/voice/disconnect"], swift=[r'"voice/disconnect"']),
        F("sessions.filter", "Show only one machine's sessions",
          web=['id="mchips"'], swift=[r"struct MachineFilter\b"]),
        F("sessions.new", "Start a new session: agent, folder, machine, name, first prompt",
          web=['id="newsheet"', "/voice/new-session"], swift=[r"struct NewSessionSheet\b", r'"voice/new-session"']),
        F("sessions.new.readback", "The read-back card of a session asked for by voice: Start or Cancel",
          web=['id="startask"'], swift=[r"struct StartCard\b|\"startCard\""]),
        F("sessions.add", "Add sessions already open, or reopen one from this week: search, by machine and agent",
          web=['id="addsheet"', "/voice/add-sessions"], swift=[r"struct AddSessionsSheet\b", r'"voice/add-sessions"']),
        F("sessions.add.readback", "The read-back card of sessions asked for by voice: Join, Reopen or Cancel",
          web=['id="attachask"'], swift=[r"struct AttachCard\b"]),
        F("sessions.new.folders", "Which folders a new session may start in",
          web=['id="pref-folders"'], mac=[ident("settings.folders.add")],
          ios="the daemon takes this setting at the Mac only (daemon.py: voice/prefs refuses sessions.folders off the Mac)"),
        F("machines.list", "Machines on this voice: online, sessions, round trip, key fingerprint",
          web=['id="machines"', 'id="mach-list"'], swift=[r"struct MachinesSheet\b"]),
        F("machines.invite", "Invite a machine with a one-time code, cancel it, revoke a machine",
          web=['id="mach-invitebtn"', "hub/revoke|mach-cancel"], swift=[ident("inviteMachine"), r'"voice/hub/revoke"']),
    ]),
    ("Approvals and alerts", [
        F("approve.card", "A permission request as a card with the exact request, Deny and Approve",
          web=['id="attention"', "/voice/approve"], swift=[r"struct (?:RequestCard|ApprovalCard)\b", r'"voice/approve"']),
        F("approve.owner", "Approve asks that it is you: Face ID on the phone, Touch ID or the password on the Mac",
          swift=[r"deviceOwnerAuthentication"],
          web="a browser page cannot ask for Touch ID without WebAuthn enrolment; the page is on the unlocked Mac beside the terminal"),
        F("approve.more", "How many more requests wait",
          web=["more waiting"], swift=[r"more waiting|MacCopy\.moreWaiting"]),
        F("approve.offline", "A request whose machine went offline says it is back in its terminal",
          web=["offline"], swift=[ident("requestOffline") + r"|MacCopy\.offlineCard"]),
        F("alerts.notify", "A notification when a session needs you and you are not looking",
          web=["new Notification\\(", 'id="pref-desktop"'], swift=[r"UNUserNotificationCenter", r"struct AlertsSheet\b|" + ident("settings.alerts")]),
        F("alerts.approve", "Approve from notifications, as a setting",
          web=['id="pref-watch"'], swift=[r"watchApprove"]),
        F("alerts.actions", "Deny and Approve on the notification itself",
          swift=[r"UNNotificationAction\("], web="a web notification has no authenticated action; the click opens the page"),
        F("alerts.background", "Alerts keep arriving while the app is in the background",
          ios=[r"BGAppRefreshTask|backgroundTask\(\.appRefresh"], mac=[r"MenuBarExtra"],
          web="a background tab keeps its timer; there is nothing to schedule"),
    ]),
    ("Brain dump and challenge", [
        F("dump.panel", "Brain dump: think aloud, the thoughts listed, Done or Discard",
          web=['id="dump"', "/voice/dump"], swift=[r"struct BrainDumpPanel\b", r'"voice/dump"']),
        F("dump.review", "Review the structured prompt: edit, pick who gets it, send",
          web=['id="dumpsheet"', 'id="dump-send"', 'id="dump-to"'], swift=[ident("dump.send"), ident("dump.text"), r"DumpTarget"]),
        F("dump.more", "Add more, or have it read back, before sending",
          web=['id="dump-more"', 'id="dump-read"'], swift=[r"BrainDumpCopy\.addMore", r"BrainDumpCopy\.readBack"]),
        F("dump.challenge", "Challenge the plan from the review",
          web=['id="dump-challenge"'], swift=[r"ChallengeCopy\.fromDump"]),
        F("challenge.panel", "Challenge (devil's advocate): the items, the plan, End",
          web=['id="challenge"', "/voice/challenge"], swift=[r"struct ChallengePanel\b", r'"voice/challenge"']),
    ]),
    ("Meetings", [
        F("meeting.start", "Start a meeting: mode, context, sessions that may be asked, consent",
          web=['id="meetsheet"', 'id="meetconsent"', 'id="meetbrief"'], swift=[r"struct MeetingStartSheet\b", ident("meetingConsent"), ident("meetingBrief")]),
        F("meeting.mode", "Listening or Participating, switched during the meeting",
          web=['id="mm-listening"', 'id="mm-participating"'], swift=[r"meetingMode-"]),
        F("meeting.notes", "The notes feed, filtered by kind, and the transcript",
          web=['id="notelist"', "/voice/meeting/transcript"], swift=[r"struct NotesFeed\b", r'"voice/meeting/transcript"']),
        F("meeting.hand", "A raised hand: let it speak, later, or type it",
          web=['id="hand"', 'id="handspeak"'], swift=[r"struct HandCard\b", ident("handSpeak")]),
        F("meeting.speakers", "Name the speakers; \"that was me\"",
          web=['id="speakers"', "renameSpeaker"], swift=[r"struct SpeakersSheet\b"]),
        F("meeting.ask", "Ask or add context during the meeting, and look a note up",
          web=['id="meetsay"'], swift=[r"struct MeetingBar\b", ident("lookUp")]),
        F("meeting.end", "End: the summary, export notes (with the transcript), send the action items, discard",
          web=['id="endsheet"', "exportMeeting", 'id="endsend"', 'id="enddiscard"'],
          swift=[r"struct MeetingEndSheet\b", ident("exportTranscript"), ident("meetingSend"), ident("meetingDiscard")]),
        F("meeting.settings", "Meeting settings: default mode, lookups, consent, notes language",
          web=['id="g-meetings"', 'id="pref-lang"', 'id="pref-lookups"'], swift=[r"struct MeetingSettingsSheet\b"]),
    ]),
    ("Briefings, whisper, drive", [
        F("briefing.sheet", "Briefing: what happened since, play, stop, length",
          web=['id="briefsheet"', 'id="brf-go"'], swift=[r"struct BriefingSheet\b"]),
        F("briefing.ready", "A ready briefing offers itself; playing, it has its own bar",
          web=['id="briefalert"'], swift=[r"struct BriefingReadyCard\b", r"struct BriefingNowBar\b"]),
        F("briefing.schedule", "A scheduled briefing: days, time, length, skip when empty",
          web=['id="brf-sched"', 'id="brf-days"'], swift=[r"struct BriefingSettingsSheet\b"]),
        F("night.start", "Night shift: tasks for the sessions, the hours and the message budget, Start",
          web=['id="nightsheet"', 'id="night-start"', "/voice/night-shift"], swift=[r"struct NightShiftSheet\b", r'"voice/night-shift"']),
        F("night.readback", "The read-back card of a night shift asked for by voice: Start or Cancel",
          web=['id="shiftask"'], swift=[r"struct ShiftCard\b|\"shiftCard\""]),
        F("night.status", "A running night shift: tasks done, the blocked count, Stop",
          web=['id="nightstrip"', "stopShift"], swift=[r"struct NightShiftStrip\b", ident("nightShiftStop")]),
        F("night.ledger", "The night's ledger: decisions, questions, done, blocked with the exact request, in flight",
          web=['id="night-ledger"', "NIGHT_ORDER"], swift=[r"struct NightShiftLedger\b"]),
        F("night.notify", "Alerts about a night shift's blockers: off unless asked for",
          web=['id="night-notify"'], swift=[r"NightShiftCopy\.notify"]),
        F("whisper", "Whisper: short quiet replies, with the notes it held back",
          web=['id="whisperbtn"', 'id="whispercard"'], swift=[r"struct WhisperCard\b", ident("whisperItem")]),
        F("drive.screen", "Drive mode on screen: the one line, the request, Stop",
          web=['id="drivebar"', 'id="drive-stop"'], swift=[r"struct DriveScreen\b", ident("driveStop")]),
        F("drive.start", "Turn drive mode on from the screen",
          ios=[ident("driveButton")], web=DRIVE_IS_THE_PHONES, mac=DRIVE_IS_THE_PHONES),
        F("drive.suggest", "Offer drive mode when the phone is in a car",
          ios=[r"CMMotionActivityManager", r"struct DriveSuggestion\b"],
          web="no motion sensor and no car audio route on a Mac", mac="no motion sensor and no car audio route on a Mac"),
    ]),
    ("Voice lock, dictionary, conflicts, show", [
        F("lock.level", "Voice lock: which actions only your voice may do",
          web=['id="vl-levels"'], swift=[r"voiceLevel-|" + ident("settings.voiceLock")]),
        F("lock.enrol", "Enrol your voice, per device, and delete a voiceprint",
          web=['id="vl-enrolbtn"', 'id="vl-deleteall"'], swift=[ident("enrolLine"), r"deleteVoiceprint-"]),
        F("lock.ignored", "What the lock ignored, and the note after three unsure yeses",
          web=['id="ignoredsheet"', "unsure_streak"], swift=[r"struct IgnoredSheet\b", ident("voiceUnsure")]),
        F("dictionary.sheet", "Dictionary: the terms, add, edit, delete, suggestions, learn from fixes",
          web=['id="dict-open"', "/voice/dictionary|dictionary"], swift=[r"struct VocabularySheet\b", ident("dictionaryLearn")]),
        F("dictionary.toast", "A term learned during the call shows, with Undo",
          web=['id="dicttoast"'], swift=[r"struct LearnedToast\b"]),
        F("conflicts.card", "Two sessions disagree: the card, ask either, dismiss",
          web=['id="conflicts"', "/voice/conflicts"], swift=[r"struct ConflictCard\b", r'"voice/conflicts"']),
        F("conflicts.settings", "Conflict alarm settings: on, spoken",
          web=['id="pref-conflicts"', 'id="pref-conflicts-spoken"'], swift=[r"struct ConflictSettingsSheet\b"]),
        F("show.card", "Show while it says: the file, the diff or the test the voice is talking about",
          web=['id="show"', "/voice/artifact"], swift=[r"struct ShowSheet\b", r'"voice/artifact"']),
        F("show.setting", "Also show on the phone, as a setting",
          web=['id="pref-showphone"'], swift=[r"struct ShowSettingsSheet\b"]),
    ]),
    ("Pairing, appearance, about, help", [
        F("pair.show", "Show the code that pairs a phone, list the paired phones, unpair",
          web=['id="phone"', 'id="ph-qr"', 'id="ph-unpair"'], mac=[r"struct PhoneSheet\b", r'"voice/phone/invite"'],
          ios="the phone is the device being paired: it reads the code the Mac shows"),
        F("pair.read", "Pair with the Mac: scan or paste the code in the app, then confirm; unpair this phone",
          ios=[r"struct PairView\b", r"Unpair this phone"], web=PAGE_IS_THE_MAC, mac="the Mac app talks to its own daemon on loopback: nothing to pair"),
        F("appearance", "Appearance: System, Light or Dark",
          web=['id="theme-system"', 'id="theme-dark"'], swift=[ident("appearanceSetting", "settings.theme")]),
        F("about", "About: what Pointe is, the version, the repository",
          web=['id="g-about"', 'id="about-ver"'], swift=[r"struct AboutSheet\b"]),
        F("about.version", "The app's version beside the daemon's when they differ",
          web=['id="ver"'], swift=[ident("versionLine") + r"|versionNote"]),
        F("local-mode", "Local mode, as one read-only line",
          web=['id="g-local"'], swift=[r"local\??\.short"]),
        F("help", "The voice knows where this surface keeps each control (product_help.json)",
          web=[], ios=[], mac=[]),  # filled from product_help.json below
        F("demo", "A demo with invented sessions, no Mac needed",
          swift=[r"struct Demo\b", ident("tryDemo")], web=NO_DAEMON_NO_PAGE),
        F("keys", "Keyboard: a key for every main action",
          web=["addEventListener\\('keydown'", "Space mutes"], mac=[r"\.keyboardShortcut\("],
          ios="an iPhone has no keyboard by default; VoiceOver and Switch Control reach every control by its label"),
    ]),
    ("The Mac shell", [
        F("mac.menubar", "A menu bar item with the state and who needs you",
          mac=[r"MenuBarExtra"], web=MAC_SHELL, ios=MAC_SHELL),
        F("mac.bubble", "A small call bubble that floats over other apps while a call is up: click to open, drag, small or full, ×",
          mac=[r"struct BubbleView\b", r"func acceptsFirstMouse\b", r"\"bubble\.close\"", r"func resetBubblePosition\("],
          web=MAC_SHELL, ios=MAC_SHELL),
        F("mac.talkmode", "The talk mode and the talk shortcut (\"Hold ⌥Space\"), in the window and the bubble",
          mac=[r"BubbleRule\.talkMode\(", ident("talkMode"), ident("bubble.mode")], web=MAC_SHELL, ios=MAC_SHELL),
        F("mac.login", "Open at login",
          mac=[r"SMAppService"], web=MAC_SHELL, ios=MAC_SHELL),
        F("mac.daemon", "Find, start and restart Pointe on this Mac; say when versions differ",
          mac=[r"func startDaemon\(", r"func restartDaemon\("], web=NO_DAEMON_NO_PAGE, ios="the phone reaches a Mac that already runs Pointe"),
        F("keys.status", "Which roles the keys fill: a key no role needs is Optional, an empty role names the one key to add",
          web=['id="g-keys"', "KEYS_COPY"], mac=[r"KeyPlan\(present:", r"KeyCopy\.whatYouNeed"],
          ios="the keys live in the Mac's Keychain, and the iPhone app shows none of them"),
        F("mac.keys", "Which vendor keys are in the Keychain, and Add…",
          mac=[r"KeychainPresence"], web="keys are added with `pointe key`, never through a page", ios="the keys live in the Mac's Keychain"),
    ]),
    ("The phone alone", [
        F("ios.airpods", "An AirPods press talks or mutes",
          ios=[r"MPRemoteCommandCenter"], web=PHONE_ONLY_HARDWARE + " (macOS gives the press to the media-key owner)",
          mac=PHONE_ONLY_HARDWARE + " (macOS gives the press to the media-key owner)"),
        F("ios.nowplaying", "Drive mode on the lock screen",
          ios=[r"MPNowPlayingInfoCenter"], web=PHONE_ONLY_HARDWARE, mac=PHONE_ONLY_HARDWARE),
    ]),
]

FEATURES = [f for _, group in GROUPS for f in group]


# ---------- the scan ----------

@dataclass
class Cell:
    state: str            # yes, partial, no, n/a
    refs: list[str]       # file:line for each pattern found
    missing: list[str]    # patterns not found
    why: str = ""         # for n/a


def _find(pattern: str, files: dict[str, str]) -> str | None:
    rx = re.compile(pattern)
    for path, text in files.items():
        m = rx.search(text)
        if m:
            return f"{path}:{text.count(chr(10), 0, m.start()) + 1}"
    return None


def _help_cell(surface: str, root: Path) -> Cell:
    """The product help names this surface, and at least one topic has a path on it."""
    key = {"web": "page", "ios": "iphone", "mac": "mac"}[surface]
    data = json.loads((root / "product_help.json").read_text())
    with_path = sum(1 for e in data["entries"] if e.get(key))
    if key in data["surfaces"] and with_path:
        return Cell("yes", [f"product_help.json ({with_path} topics)"], [])
    return Cell("no", [], [f"product_help.json has no '{key}' surface"])


def scan(root: Path = ROOT) -> dict[str, dict[str, Cell]]:
    files = {s: sources(s, root) for s in SURFACES}
    matrix = {}
    for f in FEATURES:
        row = {}
        for s in SURFACES:
            if s in f.bound:
                row[s] = Cell("n/a", [], [], f.bound[s])
            elif f.id == "help":
                row[s] = _help_cell(s, root)
            else:
                needs = f.needs(s)
                assert needs, f"{f.id}: no pattern and no reason for {s}"
                found = [(p, _find(p, files[s])) for p in needs]
                refs = [r for _, r in found if r]
                state = "yes" if len(refs) == len(needs) else "partial" if refs else "no"
                row[s] = Cell(state, refs, [p for p, r in found if not r])
        matrix[f.id] = row
    return matrix


def counts(matrix: dict[str, dict]) -> dict[str, dict[str, int]]:
    out = {s: {"yes": 0, "partial": 0, "no": 0, "n/a": 0} for s in SURFACES}
    for row in matrix.values():
        for s in SURFACES:
            cell = row[s]
            out[s][cell.state if isinstance(cell, Cell) else cell] += 1
    return out


# ---------- the document ----------

MARK = {"yes": "yes", "partial": "partial", "no": "**no**", "n/a": "n/a"}


def render(matrix: dict[str, dict[str, Cell]], baseline: dict | None) -> str:
    lines = ["# Parity matrix",
             "",
             "Written by `python3 tools/parity.py` from the code of the three surfaces; do not edit by hand.",
             "`tests/test_parity_matrix.py` fails when this file is stale, and when a feature is missing from a surface",
             "without a reason. What the rows mean, how the scan works and the component spec: [parity.md](parity.md).",
             ""]
    now = counts(matrix)
    lines += ["## Counts", "", "| Surface | yes | partial | no | n/a (bound to another surface) |", "|---|---|---|---|---|"]
    for s in SURFACES:
        c = now[s]
        lines.append(f"| {NAMES[s]} | {c['yes']} | {c['partial']} | {c['no']} | {c['n/a']} |")
    if baseline:
        lines += ["", f"Before this work ({baseline['at']}), by the same scan:", "",
                  "| Surface | yes | partial | no | n/a |", "|---|---|---|---|---|"]
        for s in SURFACES:
            c = baseline["counts"][s]
            lines.append(f"| {NAMES[s]} | {c['yes']} | {c['partial']} | {c['no']} | {c['n/a']} |")
    for title, group in GROUPS:
        lines += ["", f"## {title}", "", "| Feature | Page | iPhone | Mac |", "|---|---|---|---|"]
        for f in group:
            cells = []
            for s in SURFACES:
                cell = matrix[f.id][s]
                text = MARK[cell.state]
                if cell.refs:
                    text += " `" + cell.refs[0] + "`"
                cells.append(text)
            lines.append(f"| {f.title} <br>`{f.id}` | " + " | ".join(cells) + " |")
    bound = [(f, s) for f in FEATURES for s in SURFACES if s in f.bound]
    lines += ["", "## Bound to a platform", "", "A feature a surface cannot have, and why. Everything else is on all three.", "",
              "| Feature | Not on | Why |", "|---|---|---|"]
    for f, s in bound:
        lines.append(f"| {f.title} | {NAMES[s]} | {f.bound[s]} |")
    gaps = [(f, s, matrix[f.id][s]) for f in FEATURES for s in SURFACES if matrix[f.id][s].state in ("no", "partial")]
    lines += ["", "## Gaps", ""]
    if not gaps:
        lines.append("None: every feature is on every surface that can have it.")
    else:
        lines += ["| Feature | Surface | State | Not found |", "|---|---|---|---|"]
        for f, s, cell in gaps:
            lines.append(f"| {f.title} | {NAMES[s]} | {cell.state} | " + "; ".join(f"`{p}`" for p in cell.missing).replace("|", "\\|") + " |")
    return "\n".join(lines) + "\n"


def as_json(matrix: dict[str, dict[str, Cell]]) -> dict:
    return {"counts": counts(matrix),
            "features": {fid: {s: {"state": c.state, "refs": c.refs, "missing": c.missing, "why": c.why} for s, c in row.items()}
                         for fid, row in matrix.items()}}


def main(argv: list[str]) -> int:
    matrix = scan()
    if "--json" in argv:
        print(json.dumps(as_json(matrix), indent=1))
        return 0
    if "--baseline" in argv:  # once, at the commit the work starts from
        at = argv[argv.index("--baseline") + 1]
        (ROOT / BASELINE).write_text(json.dumps({"at": at, "counts": counts(matrix),
                                                 "states": {fid: {s: c.state for s, c in row.items()} for fid, row in matrix.items()}},
                                                indent=1) + "\n")
        return 0
    path = ROOT / BASELINE
    text = render(matrix, json.loads(path.read_text()) if path.exists() else None)
    if "--check" in argv:
        if (ROOT / OUT).read_text() != text:
            print(f"{OUT} is stale: run python3 tools/parity.py", file=sys.stderr)
            return 1
        return 0
    (ROOT / OUT).write_text(text)
    c = counts(matrix)
    print(f"{OUT}: " + ", ".join(f"{NAMES[s]} {c[s]['yes']} yes / {c[s]['partial']} partial / {c[s]['no']} no" for s in SURFACES))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
