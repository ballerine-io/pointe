"""Write docs/design/parity-matrix.md: which feature each surface has, read from the code of all three.

    python3 tools/parity.py            write docs/design/parity-matrix.md
    python3 tools/parity.py --check    exit 1 if the file is not what this would write
    python3 tools/parity.py --json     the matrix as JSON on stdout (tests/test_parity_matrix.py reads it)

The four surfaces are the page (ui.html), the iPhone app (apps/ios/Pointe and the package it links), the Mac app
(apps/macos/PointeMac and the package it links) and the Linux hub: the same page, served by a daemon on Linux
(docs/linux.md). The Linux column reads the page's sources with the page's patterns unless a row says otherwise; what
the daemon does differently off a Mac is LINUX_BRANCHES, one entry per Mac-only branch in pointe/ (mac_only_branches). A feature is a row of FEATURES: per surface, the regular expressions that
must all be found in that surface's sources. All found is "yes", some is "partial", none is "no". A surface that cannot
have the feature carries the reason in `bound`, and is "n/a". The Swift the two apps share (apps/PointeKit) counts for
an app only when its project links that target, and is read with the other platform's `#if os(...)` branches blanked,
so a screen compiled out of the Mac app does not count for it. Standard library only.
"""

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = "docs/design/parity-matrix.md"
BASELINE = "tools/parity_baseline.json"
SURFACES = ("web", "ios", "mac", "linux")
NAMES = {"web": "Page", "ios": "iPhone", "mac": "Mac", "linux": "Linux hub"}

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
               for name, deps in _DEPENDS.findall((root / "apps" / "PointeKit" / "Package.swift").read_text())}
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
    if surface in ("web", "linux"):  # a Linux hub serves the same page
        return {path.name: path.read_text() for path in sorted((root / "pointe").glob("ui*.html"))}  # the page and the parts daemon.py puts in it
    # the iPhone app's own folders: the app, the intents it shares with its widget extension, and the extension
    project, own = {"ios": ("apps/ios/Pointe.xcodeproj", ["apps/ios/Pointe", "apps/ios/PointeShared", "apps/ios/PointeWidget"]),
                    "mac": ("apps/macos/PointeMac.xcodeproj", ["apps/macos/PointeMac"])}[surface]
    folders = own + [f"apps/PointeKit/Sources/{target}" for target in linked(root / project, root)]
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
    linux: tuple[str, ...] = ()
    bound: dict = field(default_factory=dict)  # surface -> why it cannot have the feature

    def needs(self, surface: str) -> tuple[str, ...]:
        return getattr(self, surface)


def F(id: str, title: str, web=(), swift=(), ios=None, mac=None, linux=None) -> Feature:
    """`swift` is what both apps must show; `ios` or `mac` replaces it for one. `linux` is the page's (patterns or
    reason) unless given: a Linux hub serves the same page. A list is patterns; a plain sentence in place of a list is
    the reason that surface cannot have the feature."""
    given = {"web": web, "ios": swift if ios is None else ios, "mac": swift if mac is None else mac,
             "linux": web if linux is None else linux}
    reasons = {s: v for s, v in given.items() if isinstance(v, str)}
    needs = {s: () if s in reasons else tuple(v) for s, v in given.items()}
    return Feature(id, title, needs["web"], needs["ios"], needs["mac"], needs["linux"], reasons)


def ident(*names: str) -> str:
    """An accessibility identifier, any of these."""
    return r'accessibilityIdentifier\("(?:' + "|".join(re.escape(n) for n in names) + r')"\)'


PAGE_IS_THE_MAC = "the page is served by the daemon on the Mac: it is the side that shows the code"
NO_DAEMON_NO_PAGE = "the page exists only while the daemon runs, so there is nothing to start, find or demo from it"
MAC_SHELL = "a Mac shell feature: AppKit only (docs/design/macos-app.md)"
DRIVE_IS_THE_PHONES = "drive mode is for a phone in a car: it starts there or by voice, and the Mac only shows it and stops it"
PHONE_ONLY_HARDWARE = "needs the phone's own hardware or system service"
LINUX_POWER = ("holding off sleep for a call, and the idle and power checks, are macOS only (pointe/mac.py: caffeinate, "
               "ioreg, pmset); on a Linux hub they are off (docs/linux.md, Limits on Linux)")
IPHONE_SYSTEM = "an iPhone system surface (Controls, Live Activities, Home Screen widgets: WidgetKit and App Intents on iOS 18)"

GROUPS: list[tuple[str, list[Feature]]] = [
    ("The call", [
        F("call.connect", "Connect, Try again, Cancel and Hang up, with the reason a call did not start",
          web=['id="connectbtn"', 'id="hangup"', "CONNECT_COPY"], swift=[ident("connectButton"), r"ConnectCopy\.|MacCopy\.tryAgain"]),
        F("call.redial", "A dropped call is redialled; a refused or idle-ended one is not, and says why",
          web=["e.code === 4409", "idleHangup"], swift=[r"func refusal\(|static func refusal", "idleHangup"]),
        F("call.resume", "A dropped link comes back on the same call: its token in the hello, the copy while it does",
          web=["resume: call.token", "CONNECT_COPY.redialling"], swift=[r"Wire\.hello\(device: link\.device, resume:", r"ConnectCopy\.redialling"]),
        F("call.state", "The state line: listening, speaking, muted, holding, reconnecting",
          web=['id="state"', "'Reconnecting…'|reconnecting"], swift=[ident("statusLine", "state"), r"TurnsCopy\.holding"]),
        F("call.mute", "Mute and unmute the microphone",
          web=['id="mic"', "Unmute|toggleMute|setMuted"], swift=[r"func toggleMute\("]),
        F("ios.airpods", "An AirPods press talks or mutes",
          ios=[r"MPRemoteCommandCenter"], mac=[r"setInputMuteStateChangeHandler", r"MacRemoteCommands\("],
          web="a browser tab gets no AirPods mute gesture; the page has a headset's play/pause only while it has the focus"),
        F("call.transcript", "The conversation, newest line followed",
          web=['id="list"'], swift=[ident("conversation")]),
        F("call.new-pill", "A New pill when lines arrive while you read further up",
          web=['id="newpill"'], swift=[r"pillShown"]),
        F("call.hearing", "Your words as you speak them",
          web=['id="caption-text"'], swift=[r"struct (?:LiveBubble|HearingBubble)\b"]),
        F("call.type", "Type instead of talking",
          web=['id="typed"', "/voice/say"], swift=[ident("typeField"), r'"voice/say"']),
        F("call.newline", "A new line in a typed message: Enter sends; Shift+Enter, Option+Enter, or New line on the iPhone",
          web=[r"ev\.shiftKey \|\| ev\.altKey", r"ev\.isComposing"], ios=[ident("composerNewLine")],
          mac=[r"Composer\.returnKey\(shift:"]),
        F("call.type-sending", "A typed line shows at once, Sending then Sent; one the Mac did not take can be sent again",
          web=["TYPED_COPY", "outgoing.set"], swift=[r"struct OutgoingBubble\b", r'"client_id"']),
        F("call.correct", "Fix what was heard in a line of yours",
          web=["/voice/correct"], swift=[ident("fixField"), r'"voice/correct"']),
        F("call.polish", "Clean up my words",
          web=[r"toggle\('qs-polish'", r"key === 'polish'"], swift=[r'"Clean up my words"', r'"voice/polish"']),
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
          mac="the rule runs only for a call from another device; on the Mac there is nothing to say",
          linux=LINUX_POWER),
    ]),
    ("Push to talk and turn taking", [
        F("talk.mode", "Microphone: Always on or Push to talk",
          web=['id="pref-mic"'], swift=[ident("microphoneSetting", "settings.microphone")]),
        F("talk.switch", "The microphone at hand: the switch over the mic, or on the Mac a chip in the quick row",
          web=['id="micmode-ptt"'], swift=[ident("micMode", "micModeSwitch", "micmode")],
          mac=[r"QuickRow\(session:", r"session\.setQuick\(\.microphone\(", ident("talkMode")]),
        F("talk.style", "Talk button: Hold to talk or Tap to talk",
          web=['id="pref-style"'], swift=[ident("talkStyleSetting", "settings.talkStyle")]),
        F("talk.ring", "The mic is the talk button: hold it, or tap it",
          web=['id="talk"|id="mic"', "pttHold"], swift=[r"talkPress\(|talkDown\("]),
        F("talk.draft", "A draft of what a press has heard so far",
          web=['id="caption-draft"'], swift=[r"TalkDraft\.line"]),
        F("talk.closed-why", "Why the Mac closed a press by itself (held too long, no audio)",
          web=["closed_why|closedWhy"], swift=[r"closedLine\("]),
        F("talk.key", "Talk without touching the screen: a key, a system-wide shortcut, or the Action button",
          web=['id="pref-key"', 'id="pref-talk"'], ios=[r"struct TalkIntent\b"], mac=[r"RegisterEventHotKey", r'"settings\.shortcut"']),
        F("skip.key", "Skip from any app: a system-wide shortcut, set in Settings",
          web="A page hears keys only while its tab has the focus: it has the button, and no key from another app.",
          ios="An iPhone has no system-wide key: it has the button.",
          mac=[r"HotKey\(id: 2\)", r'"settings\.skipShortcut"', r"skipHint"]),
        F("talk.patience", "Wait before answering: Quick, Normal or Patient",
          web=['id="pref-patience"'], swift=[ident("patienceSetting", "settings.patience")]),
        F("talk.hold", "Hold mode (\"don't interrupt me\"): quiet until you release it",
          web=["holding: 'Holding'"], swift=[r"TurnsCopy\.holdingHow|TurnsCopy\.holding\b"]),
    ]),
    ("Quick settings", [
        F("quick.length", "Reply length: Brief, Concise, Detailed or Thorough, a tap away, with a line on what each does",
          web=[r"chip\('qs-length'", r"QUICK_COPY\[level \+ 'Hint'\]", "'replies.length'"],
          swift=[ident("quickLength"), r"QuickRule\.level\(", r"\.length\("]),
        F("quick.speed", "Speaking speed, 0.8× to 1.2×, this device's own; hidden on a voice with no speed number",
          web=[r"chip\('qs-speed'", r"\.page\b", "speed_shown"], swift=[ident("quickSpeed"), r"QuickRule\.surface", r"speedShown"]),
        F("quick.toggles", "Clean up my words and Whisper as switches in the row, their state never colour alone",
          web=[r"toggle\('qs-polish'", r"toggle\('qs-whisper'", "'aria-checked'"],
          swift=[r'"quickPolish"', r'"quickWhisper"']),
        F("quick.glow", "A change by voice glows on its chip",
          web=[r"classList\.add\('glow'\)"], swift=[r"QuickRule\.glow\("],
          ios="the iPhone's quick settings are in a sheet, closed while you talk; the dot on its button and the sheet show the new value"),
        F("quick.narrow", "On a narrow screen the row keeps its values: the page moves it to More, the Mac drops the words",
          web=[r"row\.parentElement !== \$\('more-list'\)", r"\.qhead"], mac=[r"ViewThatFits\(in: \.horizontal\)", r"strip\(\.tight\)", r"fit != \.full"],
          ios="the iPhone shows quick settings in a sheet of its own, the width of the screen"),
        F("quick.button", "A Quick button in the iPhone's header, with a dot while a quick setting is off its default",
          ios=[ident("quickButton"), r"QuickRule\.offDefault\("], mac="the Mac shows the chips themselves in its title strip",
          web="the page shows the chips themselves in its top bar"),
        F("quick.keys", "The Voice menu: ⌘1 to ⌘4 reply length, ⌥⌘1 to ⌥⌘5 speed, ⇧⌘K clean up my words",
          mac=[r"CommandMenu\(MacMenu\.voice\)", r'keyboardShortcut\("k", modifiers: \[\.command, \.shift\]\)'],
          ios="an iPhone has no menu bar; a hardware keyboard is rare on it",
          web="a browser keeps ⌘1 to ⌘9 for its own tabs"),
    ]),
    ("Sessions and machines", [
        F("sessions.list", "Sessions, grouped by machine, with each one's agent and state",
          web=['id="side"', "harnessMark"], swift=[r"struct (?:SessionsSheet|SessionSidebar)\b", r"struct MachineView\b"]),
        F("sessions.switch", "Focus on a session",
          web=["/voice/switch"], swift=[r'"voice/switch"']),
        F("sessions.mode", "Orchestrator or Session mode",
          web=['id="m-orchestrator"', "/voice/mode"], swift=[r'"voice/mode"', r"SessionsCopy\.|setMode\("]),
        F("sessions.held", "Session mode holds the other sessions' news: a quiet count, the list, Tell me",
          web=['id="heldnews"', "/voice/held"], swift=[ident("heldBadge"), ident("heldTell"), r'"voice/held"']),
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
        F("sessions.new.permissions", "Permissions for new sessions: Skip permission prompts (default) or Ask before actions",
          web=['id="pref-permissions"', "'sessions.permissions'"],
          swift=[ident("newSessionPermissionsSetting"), r'"sessions\.permissions"']),
        F("sessions.new.notice", "The risk line under a start, the first time a session skips permission prompts",
          web=[r"x\.notice"], swift=[r"public let notice: String\?", r"failed \? detail : notice"]),
        F("machines.list", "Machines on this voice: online, sessions, round trip, key fingerprint",
          web=['id="machines"', 'id="mach-list"'], swift=[r"struct MachinesSheet\b"]),
        F("machines.invite", "Invite a machine with a one-time code, cancel it, revoke a machine",
          web=['id="mach-invitebtn"', "hub/revoke|mach-cancel"], swift=[ident("inviteMachine"), r'"voice/hub/revoke"']),
        F("machines.add", "Add a machine somebody invited you to, from its owner's line: paste it (the iPhone also scans it)",
          web=['id="mach-add"', "/voice/machines/add"], swift=[r"struct AddMachineSheet\b", r'"voice/machines/add"']),
        F("machines.disclosure", "Once after a machine is added: which services your voice sends its transcripts to, until OK",
          web=['id="mach-disclosure"', r"PEOPLE_COPY\.disclosure\("],
          swift=[r"struct DisclosureCard\b", r"PeopleCopy\.disclosure\(", ident("disclosureOK")]),
        F("agents.list", "Agents built on agent frameworks on this voice: kind, address, whether each answers",
          web=['id="agents-list"', r"fetch\('/voice/agents'\)"], swift=[r"struct AgentsSheet\b", r'"voice/agents"', ident("agentsItem")]),
        F("agents.add", "Connect an agent: OpenClaw, Hermes, any A2A or OpenAI-compatible agent; its credential goes to the Keychain",
          web=['id="agent-add"', r"function addAgent\("], swift=[r"struct AddAgentSheet\b", ident("agentConnect")]),
        F("agents.remove", "Remove an agent and its saved credential, after a confirm",
          web=[r"function removeAgent\(", r"'/voice/agents/' \+ encodeURIComponent"],
          swift=[ident("agentRemoveConfirm"), r"func removeAgent\("]),
        F("agents.disclosure", "Once after an agent is added: which services hear what it says, until OK",
          web=['id="agent-disclosure"', "/voice/agents/seen"], swift=[ident("agentDisclosureOK"), r'"voice/agents/seen"']),
        F("machines.owner", "Whose a machine and a session is, shown only where it is not yours",
          web=[r"PEOPLE_COPY\.whose\(x\.owner\)", r"PEOPLE_COPY\.whose\(m\.owner\)"],
          swift=[r"func ownerTag\(_ s: API\.Session\)", r"func ownerTag\(machine name: String\)", r"machines\.ownerTag\("]),
        F("sessions.mine", "Mine: show only your own sessions, while somebody else's are in your voice",
          web=[r"PEOPLE_COPY\.mine\b", r"mv\.others \? \[MINE\]"],
          swift=[r"MachineView\.mineFilter, PeopleCopy\.mine"]),
        F("people.invite", "Invite a person to this machine: a name, talk or watch only, a one-time line and its code; cancel it",
          web=['id="people-invitebtn"', 'id="people-qr"', "/voice/people/invite"],
          swift=[r"struct PeopleSheet\b", ident("personInviteQR"), r'"voice/people/invite"']),
        F("people.grant", "Change what a person may do: talk to the sessions, or watch only",
          web=["/voice/people/grant"], swift=[r'"voice/people/grant"', r"Text\(PeopleCopy\.watch\)\.tag"]),
        F("people.remove", "Remove a person from this machine, after a confirm",
          web=["/voice/people/remove", r"PEOPLE_COPY\.removeAsk\(p\.name\)"],
          swift=[r'"voice/people/remove"', r"PeopleCopy\.removeAsk"]),
        F("sessions.private", "Private: keep a session of this machine to yourself, or share it with people again",
          web=['id="row-private"', "/voice/share"], swift=[r'"voice/share"', r"PeopleCopy\.makePrivate : PeopleCopy\.makeShared"]),
        F("people.settings", "What people can do on this machine: approve requests, start sessions, how their sessions start",
          web=['id="people-can"', "/voice/people/settings"], swift=[r'"voice/people/settings"', r"PeopleCopy\.canDo\b"]),
        F("sessions.new.there", "Start a session on a machine somebody invited you to: its folders, whose it is, how it starts sessions",
          web=[r"/voice/new-session' \+ \(picked\.here", r"PEOPLE_COPY\.startsThere\("],
          swift=[r'URLQueryItem\(name: "machine"', r"PeopleCopy\.owned\(target\.owner"]),
    ]),
    ("Approvals and alerts", [
        F("approve.card", "A permission request as a card with the exact request, Deny and Approve",
          web=['id="attention"', "/voice/approve"], swift=[r"struct (?:RequestCard|ApprovalCard)\b", r'"voice/approve"']),
        F("approve.asked", "A request somebody else is asked first for: who and how long, Approve only once it is yours, and "
          "who answered", web=[r"PEOPLE_COPY\.askedFirst\(", r"x\.can_answer === false", r"PEOPLE_COPY\.resolved\("],
          swift=[r"PeopleCopy\.askedFirst\(", r"can_answer", r"PeopleCopy\.resolved\("]),
        F("approve.voice", "Any request can be approved by a spoken yes: read out short or word for word; the card says "
          "which (a secret is never said: tap)", web=["voice_can_approve"], swift=[r"voice_can_approve"]),
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
        F("mute", "Mute Pointe: one button beside the status line, every reply as text, each device's own choice",
          web=['id="mutebtn"', "/voice/reading'", "pointe.reading", r"muteQuery\(\)"],
          swift=[r"struct MuteButton\b", ident("muteButton"), r'"voice/reading"', r"MuteChoice\.callURL"]),
        F("mute.writing", "Muted, the state line says Writing… where it would say Speaking…",
          web=["'Speaking…'", "'Writing…'", "muteWriting"], swift=[r"MuteCopy\.speaking", r"MuteCopy\.writing", r"MuteChoice\.writing"]),
        F("mute.cut", "Muting mid-reply stops what the device still holds to play",
          web=[r"muteSet[\s\S]{0,400}postMessage\('flush'\)"], swift=[r"func hush\(", r"call\.hush\(\)"]),
        F("thinking", "The status line says Thinking… from the end of the turn until the reply",
          web=["'Thinking…'", r"phaseIs\(s, 'thinking'\)", r"\[data-state=thinking\]"],
          swift=[r"ThinkingCopy\.thinking", r"ThinkingRule\.phase\(", r"case \.thinking: \.shrink"]),
        F("thinking.working", "The status line names the session that has the request: \"billing is working…\"",
          web=["is working…`", r"phaseIs\(s, 'working'\)", r"\[data-state=working\]"],
          swift=[r"ThinkingCopy\.working\(", r'waiting\?\.name == "working"']),
        F("thinking.link", "The call's own link says the turn was taken: Thinking… without waiting for a status",
          web=[r"m\.type === 'phase'", r"function phaseRemote\("], swift=[r"ThinkingRule\.message\(", r"toldPhase = "]),
        F("thinking.motion", "The state's dot tells thinking, speaking and working apart by motion, and Reduce Motion stops it",
          web=[r"@keyframes think", r"prefers-reduced-motion: reduce"], swift=[r"struct StateDot\b", r"accessibilityReduceMotion"]),
        F("tones", "Session tones: a setting, off by default, and a session's row names its tone",
          web=['id="pref-tones"', "'reports.tones'", r"function harnessMark[\s\S]{0,700}toneLabel\(x\)"],
          swift=[ident("sessionTonesSetting"), r'"reports\.tones"', r"tone: TonesCopy\.label\(s\)"]),
        F("mic.addressed", "Only when I say Pointe: the microphone setting between Always on and push to talk, and the state line says how to talk",
          web=['id="micmode-addressed"', '<option value="addressed">', r"addressedLine\(s\)"],
          swift=[r'Text\("Say “Pointe”"\)\.tag\(AddressedCopy\.mode\)', r'Text\("Only when I say Pointe"\)\.tag\(AddressedCopy\.mode\)',
                 r"AddressedCopy\.line\(status\)"]),
        F("approvals.record", "The approvals record: each answer that went through Pointe, when, by voice or tap, the exact request, the voice lock's score",
          web=['id="approvals-list"', r"fetch\('/voice/approvals'\)", r"function approvalLock\("],
          swift=[r"struct ApprovalsSheet\b", r'request\("voice/approvals"\)', r"static func lock\(_ a: API\.Approval\)", ident("approvalsItem")]),
        F("a11y.motion", "Reduce Motion: no animation runs, no symbol pulses and no scroll glides",
          web=[r"@media \(prefers-reduced-motion: reduce\)", r"const glide = \(\) => matchMedia\('\(prefers-reduced-motion: reduce\)'\)"],
          swift=[r"func withAnimation<Result>", r"func motion<V: Equatable>", r"func pulsing\(", r"Motion\.reduced\(system\)"]),
        F("a11y.state", "A screen reader hears the state line as one element, with the line under it",
          web=['id="statesay" role="status"'], swift=[r'accessibilityLabel\("\\\(title\), \\\(subtitle\)"\)', ident("statusLine")]),
        F("a11y.agent", "A session's agent is its name in plain text, read as \"runs on Codex\"",
          web=[r"'runs on ' \+ h\.name", r"el\('span', 'hmark', h\.name\)"], swift=[r'accessibilityLabel\("runs on \\\(name\)"\)', r"Harness\.name\("]),
        F("thinking.bubble", "The call bubble and the menu bar item show thinking",
          web="The page has no bubble and no menu bar item: its state line is always on screen.",
          ios="The iPhone has no bubble: its state line is the call screen's.",
          mac=[r"BubbleRule\.stateGlyph\(", r"glyph == \.thinking"]),
        F("thinking.cue", "The waiting sound: a setting, on by default",
          web=['id="pref-cue"', "'thinking.cue'"], swift=[ident("waitCueSetting"), r'"thinking\.cue"']),
        F("progress", "Progress updates while a session works: a setting, off by default",
          web=['id="pref-progress"', "'progress.spoken'"], swift=[ident("progressSetting"), r'"progress\.spoken"']),
        F("skip", "Skip what Pointe is saying: one button beside the status line, after the mute button, only while it speaks",
          web=['id="skipbtn"', "/voice/skip'", "skipShows"], swift=[r"struct SkipButton\b", ident("skipButton"), r'"voice/skip"', r"SkipRule\.shows"]),
        F("skip.cut", "Skipping stops what the device still holds to play",
          web=[r"skipNow[\s\S]{0,300}postMessage\('flush'\)"], swift=[r"func skipNow\(\)[\s\S]{0,200}call\.hush\(\)"]),
        F("talk.copy", "The conversation's text can be selected and copied",
          web=[r"#talk li \{ -webkit-user-select: text", r"function selecting\("], swift=[r"CopyCopy\.copy", r"static func copyText\("]),
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
        F("mac.talkmode", "The talk mode and the talk shortcut (\"Hold ⌃⌥Space\"), in the window and the bubble",
          mac=[r"BubbleRule\.talkMode\(", ident("talkMode"), ident("bubble.mode")], web=MAC_SHELL, ios=MAC_SHELL),
        F("mac.airpods", "Play/pause in a call: Mute Pointe, Skip or Nothing, set in Settings; taken only during a call; the window and bubble say what an AirPods press does",
          mac=[r"presses\.update\(onCall:", ident("settings.playPause"), ident("airPodsHint"), ident("bubble.airPods")],
          web="a browser tab gets no AirPods mute gesture and no media keys from other apps; the page has Space and a headset's play/pause while it has the focus",
          ios="iOS mutes the input itself on the press, and the iPhone's play/pause is the talk button or drive mode's mute (ios.airpods)"),
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
        F("ios.nowplaying", "Drive mode on the lock screen",
          ios=[r"nowPlayingInfo = driving"], web=PHONE_ONLY_HARDWARE, mac=PHONE_ONLY_HARDWARE),
        F("ios.control", "Talk to Pointe from Control Center, the Lock Screen or the Action button: one press opens Pointe talking to the orchestrator, the next sends",
          ios=[r"struct TalkControl: ControlWidget", r"openAppWhenRun = true", r"TalkLaunch\.press\("],
          web=IPHONE_SYSTEM + "; the page's from-any-app is a system-wide shortcut running `pointe talk`",
          mac=IPHONE_SYSTEM + "; the Mac app's is its talk shortcut (talk.key)"),
        F("ios.live-activity", "The call on the Lock Screen and in the Dynamic Island, with Send, Cancel, Talk and Hang up",
          ios=[r"ActivityConfiguration\(for: TalkActivityAttributes", r"struct SendTalkIntent\b", r"struct CancelTalkIntent\b"],
          web=IPHONE_SYSTEM, mac=IPHONE_SYSTEM + "; the Mac app's call bubble does the same (mac.bubble)"),
        F("ios.widget", "A Home Screen tile: Talk to Pointe, with the Mac's status where the app group allows",
          ios=[r"struct TalkWidget: Widget", r"TalkLaunchCopy\.line\(", r"store\.publish\("],
          web=IPHONE_SYSTEM, mac=IPHONE_SYSTEM + "; the Mac app's menu bar item shows the same (mac.menubar)"),
        F("ios.outside-setting", "Turn Talk from outside the app on or off",
          ios=[ident("talkOutsideSetting")], web=IPHONE_SYSTEM, mac=IPHONE_SYSTEM),
    ]),
]

FEATURES = [f for _, group in GROUPS for f in group]


# ---------- the Linux hub ----------

@dataclass(frozen=True)
class Branch:
    """What one Mac-only branch in pointe/ means for a Linux hub. `kind`: "path", the hub does the same another way;
    "limit", part of the features is not on a Linux hub (said in the matrix); "bound", the features cannot be on a Linux
    hub and carry a Linux reason. `features` may be empty for a branch no feature row covers (setup, uninstall)."""
    kind: str
    features: tuple[str, ...]
    linux: str


def B(kind: str, linux: str, *features: str) -> Branch:
    return Branch(kind, features, linux)


SETUP_ONLY = "not a feature row: the terminal setup and uninstall, run once"
# Every function in pointe/ whose behaviour depends on running on a Mac (mac_only_branches finds them), by file and
# function. tests/test_parity_matrix.py fails on a branch missing here and on an entry whose branch is gone: a new
# Mac-only branch needs its Linux decision written down.
LINUX_BRANCHES: dict[str, Branch] = {
    "keys.py:on_a_mac": B("path", "`pointe key` asks in the terminal with hidden typing and saves the key in the login "
                          "keyring (Secret Service), not the Keychain", "keys.status"),
    "agents.py:_ask_secret": B("path", "`pointe agent add` asks for the agent's credential in the terminal with hidden typing, "
                               "not in a Mac dialog", "agents.add"),
    "agents.py:delete_secret": B("path", "removing an agent deletes its credential from the Secret Service (secret-tool), not the "
                                 "Keychain", "agents.remove"),
    "vendors.py:from_store": B("path", "keys are read from the Secret Service (secret-tool), not the Keychain", "keys.status"),
    "vendors.py:_stored": B("path", "only Pointe's own key names are read: the pre-release names are a Mac Keychain history",
                            "keys.status"),
    "daemon.py:add_key": B("path", "the page's Add answers with the terminal command (pointe key <vendor>, hidden typing) "
                           "instead of opening a key window", "keys.status"),
    "daemon.py:_status_machines": B("path", "the hub names its own system, linux, in the machines list", "machines.list"),
    "node.py:_os": B("path", "a node tells the hub its system, linux, for the machines list", "machines.list"),
    "daemon.py:_start_harnesses": B("path", "the agent list says Claude Code opens in a tmux window on this machine",
                                    "sessions.new"),
    "harnesses/claude_code.py:ClaudeCode.can_start": B("path", "starting Claude Code needs tmux; without it the start says "
                                                       "how to install it", "sessions.new"),
    "harnesses/claude_code.py:opens_where": B("path", "a started session opens in a tmux window (tmux attach -t pointe)",
                                              "sessions.new", "sessions.add"),
    "harnesses/claude_code.py:could_not_open": B("path", "a failed start names tmux", "sessions.new", "sessions.add"),
    "harnesses/claude_code.py:open_window": B("path", "a started or reopened session runs in a tmux window, not a Terminal "
                                              "window", "sessions.new", "sessions.add"),
    "harnesses/claude_code.py:<module>": B("path", "Claude Code's managed settings are read from /etc/claude-code"),
    "daemon.py:add_sessions_options": B("limit", "a Linux hub joins its open sessions and its machines' sessions, and does "
                                        "not offer to reopen its own recent ones (reopen_here is false)", "sessions.add"),
    "local.py:supported": B("limit", "the one-step local mode needs an Apple-silicon Mac; on Linux each role is set to local "
                            "by hand (docs/features/local.md), and the page's line shows it", "local-mode"),
    "local.py:supported_voice": B("limit", "Voice stays local needs an Apple-silicon Mac (MLX); on Linux ears and mouth are "
                                  "set to local by hand", "local-mode"),
    "vendors.py:_local_ears": B("path", "local ears are faster-whisper instead of MLX Whisper", "local-mode"),
    "pair.py:_wifi": B("path", "Same network listens on the private address of the default route (wired or Wi-Fi)",
                       "pair.show"),
    "pair.py:_open_picture": B("path", "the pairing QR is printed in the terminal; no picture opens", "pair.show"),
    "pair.py:main": B("path", "Twingate through a Docker-bridged connector gets the --listen docker hint", "pair.show"),
    "terminal_setup.py:chrome": B("path", SETUP_ONLY + "; Chrome or Chromium is looked up on the PATH"),
    "terminal_setup.py:desktop": B("path", SETUP_ONLY + "; a screen exists only in a desktop session (DISPLAY, WAYLAND_DISPLAY)"),
    "terminal_setup.py:first_setup": B("path", SETUP_ONLY + "; it says \"this machine\" and does not require Chrome first"),
    "uninstall.py:_in_keychain": B("path", SETUP_ONLY + "; keys are looked up in the login keyring"),
    "uninstall.py:plan": B("path", SETUP_ONLY + "; keyring items are listed, and no pre-release Keychain names"),
    "uninstall.py:remove": B("path", SETUP_ONLY + "; keyring items are removed with secret-tool"),
}


def _is_platform_test(node: ast.AST) -> bool:
    """`sys.platform` or `platform.system()`: a test of which system this is."""
    if isinstance(node, ast.Attribute) and node.attr == "platform" and isinstance(node.value, ast.Name) and node.value.id == "sys":
        return True
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "system"
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "platform")


def mac_only_branches(root: Path = ROOT) -> dict[str, list[int]]:
    """"file:Class.function" (or "file:<module>") to the lines where pointe/ asks which system it runs on."""
    found: dict[str, list[int]] = {}
    for path in sorted((root / "pointe").rglob("*.py")):
        rel = str(path.relative_to(root / "pointe"))

        def walk(node: ast.AST, scope: list[str]) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    walk(child, scope + [child.name])
                    continue
                if _is_platform_test(child):
                    key = f"{rel}:{'.'.join(scope) or '<module>'}"
                    found.setdefault(key, []).append(child.lineno)
                walk(child, scope)

        walk(ast.parse(path.read_text(), str(path)), [])
    return found


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
    key = {"web": "page", "ios": "iphone", "mac": "mac", "linux": "page"}[surface]  # a Linux hub's help is the page's
    data = json.loads((root / "pointe" / "product_help.json").read_text())
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
             "Written by `python3 tools/parity.py` from the code of the four surfaces; do not edit by hand. The Linux hub",
             "serves the page: its column is the page's unless a row or a Mac-only branch (at the end) says otherwise.",
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
            c = baseline["counts"].get(s)  # a surface added after the baseline has no count in it
            lines.append(f"| {NAMES[s]} | " + (" | ".join(str(c[k]) for k in ("yes", "partial", "no", "n/a")) if c
                                               else "not a surface then | | |") + " |")
    for title, group in GROUPS:
        lines += ["", f"## {title}", "", "| Feature | Page | iPhone | Mac | Linux hub |", "|---|---|---|---|---|"]
        for f in group:
            cells = []
            for s in SURFACES:
                cell = matrix[f.id][s]
                text = MARK[cell.state]
                if s == "linux" and cell.state == "yes" and cell.refs == matrix[f.id]["web"].refs:
                    text += " (the page)"
                elif cell.refs:
                    text += " `" + cell.refs[0] + "`"
                cells.append(text)
            lines.append(f"| {f.title} <br>`{f.id}` | " + " | ".join(cells) + " |")
    bound = [(f, s) for f in FEATURES for s in SURFACES if s in f.bound]
    lines += ["", "## Bound to a platform", "", "A feature a surface cannot have, and why. Everything else is on all four.", "",
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
    lines += ["", "## The Linux hub: what the daemon does differently off a Mac", "",
              "Each function in `pointe/` that asks which system it runs on (`LINUX_BRANCHES`). A path does the same another",
              "way; a limit leaves part of the features out on Linux; a bound feature carries its Linux reason above.", "",
              "| Branch | Kind | Features | On a Linux hub |", "|---|---|---|---|"]
    for key, b in sorted(LINUX_BRANCHES.items()):
        lines.append(f"| `{key}` | {b.kind} | " + (", ".join(f"`{x}`" for x in b.features) or "none") + f" | {b.linux} |")
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
