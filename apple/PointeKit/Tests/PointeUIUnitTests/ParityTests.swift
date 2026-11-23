import XCTest
@testable import PointeUI

/// What the page already did and the app now does too.
final class ParityTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testTheMacsProblemIsDecodedAndShownAfterTheAppsOwn() throws {
        let s = try status(#"{"connected": true, "sessions": [], "problem": "the brain key was refused"}"#)
        XCTAssertEqual(s.problem, "the brain key was refused")
        XCTAssertNil(try status(#"{"connected": true, "sessions": []}"#).problem)  // an older Mac sends none
        XCTAssertEqual(CallView.shownProblem(screen: nil, call: nil, mac: s.problem), "the brain key was refused")  // as the page shows it
        XCTAssertEqual(CallView.shownProblem(screen: "Start the call first.", call: nil, mac: s.problem), "Start the call first.")
        XCTAssertEqual(CallView.shownProblem(screen: nil, call: "Pointe needs the microphone.", mac: s.problem), "Pointe needs the microphone.")
        XCTAssertNil(CallView.shownProblem(screen: nil, call: nil, mac: ""))
    }
}

final class IdleHangupTests: XCTestCase {
    func testAnIdleHangUpIsNotRedialledButADroppedLinkIs() throws {
        let idle = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": false, "sessions": [], "idle_hangup": true}"#.utf8))
        XCTAssertEqual(idle.idle_hangup, true)
        XCTAssertFalse(Call.redials(idleHangup: idle.idle_hangup))
        XCTAssertTrue(Call.redials(idleHangup: false))
        XCTAssertTrue(Call.redials(idleHangup: nil))  // the Mac unreachable, or one without the field: keep trying
        XCTAssertFalse(Call.idleHangupNote.isEmpty)
    }
}

final class LocalModeTests: XCTestCase {
    func testTheLocalModeLineIsDecodedAndAnOlderMacSendsNone() throws {
        let s = try JSONDecoder().decode(API.Status.self, from: Data(
            #"{"connected": true, "sessions": [], "local": {"mode": "full", "models": "missing", "line": "Fully local: on · models not downloaded (pointe local)"}}"#.utf8))
        XCTAssertEqual(s.local?.line, "Fully local: on · models not downloaded (pointe local)")
        XCTAssertEqual(s.local?.models, "missing")
        XCTAssertEqual(s.local?.short, "Fully local · models missing")  // what fits a menu item
        XCTAssertNil(try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": true, "sessions": []}"#.utf8)).local)
    }
}

/// Each app says these lines in its own words: the phone speaks of the Mac it paired with, the Mac app of Pointe on
/// this Mac and of pressing where a finger taps. The test runs on both, so both halves are checked.
final class WordsOfEachDeviceTests: XCTestCase {
    func testTheLinesThatDifferAreThisDevices() {
        if Surface.isMac {
            XCTAssertEqual(ConnectCopy.doesHere, "Starts the call on this Mac's microphone")
            XCTAssertEqual(ConnectCopy.tapConnectHere, "Press Connect to start talking")
            XCTAssertTrue(ConnectCopy.notPairedHere.hasPrefix("Pointe on this Mac refused this app."))
            XCTAssertTrue(ConnectCopy.micDeniedHere.contains("System Settings"))
            XCTAssertTrue(ConnectCopy.idleHangupHere.hasSuffix("Press Connect to talk again."))
            XCTAssertEqual(ConnectCopy.unreachableHere("anything"), "Pointe on this Mac is not running. Start it here, or run pointe open in a terminal.")
            XCTAssertEqual(AlertCopy.phoneHere, "Alerts on this Mac")
            XCTAssertTrue(AlertCopy.helpHere.contains("Touch ID") && !AlertCopy.helpHere.contains("Face ID"))
            XCTAssertEqual(CallView.ownerReason("Approve what docs wants to run"), "approve what docs wants to run", "macOS says: Pointe is trying to …")
            XCTAssertEqual(Surface.ownerSymbol, "touchid")
        } else {
            XCTAssertEqual(ConnectCopy.doesHere, ConnectCopy.does)
            XCTAssertEqual(ConnectCopy.tapConnectHere, ConnectCopy.tapConnect)
            XCTAssertEqual(ConnectCopy.notPairedHere, ConnectCopy.notPaired)
            XCTAssertEqual(ConnectCopy.micDeniedHere, ConnectCopy.micDenied)
            XCTAssertEqual(ConnectCopy.idleHangupHere, ConnectCopy.idleHangup)
            XCTAssertEqual(ConnectCopy.unreachableHere("mac.lan:7443"), ConnectCopy.unreachable("mac.lan:7443"))
            XCTAssertEqual(AlertCopy.phoneHere, AlertCopy.phone)
            XCTAssertEqual(AlertCopy.helpHere, AlertCopy.help)
            XCTAssertEqual(CallView.ownerReason("Approve what docs wants to run"), "Approve what docs wants to run")
            XCTAssertEqual(Surface.ownerSymbol, "faceid")
        }
    }
}

final class CallElsewhereTests: XCTestCase {
    func testWithNoCallHereTheMacsCallShowsAsElsewhere() {
        XCTAssertEqual(ConnectCopy.offTitle(reach: .ok, macOnACall: true), "On a call elsewhere")
        XCTAssertEqual(ConnectCopy.offTitle(reach: .ok, macOnACall: false), "Not connected")
        // a stale status says nothing. The Mac app is on the Mac: it says Pointe there is not answering, not "Mac not reachable".
        XCTAssertEqual(ConnectCopy.offTitle(reach: .unreachable, macOnACall: true), Surface.isMac ? "Pointe is not answering" : "Mac not reachable")
        XCTAssertEqual(ConnectCopy.offTitle(reach: .rejected, macOnACall: true), Surface.isMac ? "Not connected" : "Not paired")
    }
}

/// Connect is its own control, with the page's words (tests/e2e/page_parity.py holds the same literals), and it says
/// why when the call did not come up.
final class ConnectCopyTests: XCTestCase {
    func testTheWordsAreThePages() {
        XCTAssertEqual(ConnectCopy.connect, "Connect")
        XCTAssertEqual(ConnectCopy.tryAgain, "Try again")
        XCTAssertEqual(ConnectCopy.hangUp, "Hang up")
        XCTAssertEqual(ConnectCopy.cancel, "Cancel")
        XCTAssertEqual(ConnectCopy.connectFirst, "Connect first")
        XCTAssertEqual(ConnectCopy.notConnected, "Not connected")
        XCTAssertEqual(ConnectCopy.notPairedTitle, "Not paired")
        XCTAssertEqual(ConnectCopy.elsewhere, "On a call elsewhere")
        XCTAssertEqual(ConnectCopy.busy, "A call is already up on another page or phone. Hang up there first.")
        XCTAssertTrue(ConnectCopy.unreachable("studio.example:7443")
            .hasPrefix("Can't reach your Mac at studio.example:7443. Is Twingate or Tailscale on? Is the Mac awake?"))
        XCTAssertTrue(ConnectCopy.unreachable("h").contains("Settings → Phone → Connect your phone"))  // the listener may be off
        XCTAssertTrue(ConnectCopy.notPaired.contains("Settings → Phone → Connect your phone"))
        XCTAssertEqual(ConnectCopy.idleHangup, "The Mac hung up after 30 minutes of quiet. Tap Connect to talk again.")
        // the button under it says Try again when the microphone was refused: the words name that button (QA round 2)
        XCTAssertTrue(ConnectCopy.micDenied.hasSuffix("then tap Try again."))
        XCTAssertEqual(ConnectCopy.connecting("studio"), "Connecting to studio…")
    }

    func testARefusedMicrophoneOffersTheSettingsThatAllowIt() {
        let denied = ConnectFace.make(phase: .off, reach: .ok, host: "h:1", problem: ConnectCopy.micDeniedHere, macOnACall: false)
        XCTAssertEqual(denied.button, ConnectCopy.tryAgain)
        XCTAssertTrue(denied.why.contains(ConnectCopy.tryAgain) || Surface.isMac, "the line names the button it sits over")
        XCTAssertTrue(denied.opensSettings, "nothing opened Settings: the person had to find the switch alone")
        let other = ConnectFace.make(phase: .off, reach: .ok, host: "h:1", problem: "The call did not connect.", macOnACall: false)
        XCTAssertFalse(other.opensSettings)
        XCTAssertFalse(ConnectFace.make(phase: .off, reach: .ok, host: "h:1", problem: nil, macOnACall: false).opensSettings)
    }

    func testTheFaceSaysWhatATapDoesOrWhyTheLastOneFailed() {
        let idle = ConnectFace.make(phase: .off, reach: .ok, host: "h:1", problem: nil, macOnACall: false)
        XCTAssertEqual(idle, ConnectFace(why: Surface.isMac ? "Starts the call on this Mac's microphone" : "Starts the call on this iPhone's microphone",
                                         bad: false, button: "Connect", pill: "Connect", dialling: false))
        let elsewhere = ConnectFace.make(phase: .off, reach: .ok, host: "h:1", problem: nil, macOnACall: true)
        XCTAssertEqual(elsewhere.why, ConnectCopy.elsewhereWhyHere); XCTAssertEqual(elsewhere.button, "Connect")
        let dialling = ConnectFace.make(phase: .connecting, reach: .ok, host: "h:1", problem: nil, macOnACall: false)
        XCTAssertEqual(dialling.button, "Cancel"); XCTAssertTrue(dialling.dialling); XCTAssertFalse(dialling.bad)
        let away = ConnectFace.make(phase: .off, reach: .unreachable, host: "mac.lan:7443", problem: nil, macOnACall: false)
        XCTAssertEqual(away.button, "Try again"); XCTAssertTrue(away.bad)
        XCTAssertEqual(away.why, ConnectCopy.unreachableHere("mac.lan:7443"))
        XCTAssertEqual(away.why.contains("mac.lan:7443"), !Surface.isMac, "the phone says where it looked; the Mac app looks at its own Mac")
        let unpaired = ConnectFace.make(phase: .off, reach: .rejected, host: "h:1", problem: "older problem", macOnACall: false)
        XCTAssertEqual(unpaired.why, ConnectCopy.notPairedHere)  // the refused key outranks a stale call problem
        let busy = ConnectFace.make(phase: .off, reach: .ok, host: "h:1", problem: ConnectCopy.busy, macOnACall: true)
        XCTAssertEqual(busy.why, ConnectCopy.busy); XCTAssertEqual(busy.button, "Try again")
        let live = ConnectFace.make(phase: .live, reach: .ok, host: "h:1", problem: nil, macOnACall: true)
        XCTAssertEqual(live.pill, "Hang up"); XCTAssertEqual(live.button, "Connect")  // the stage is gone while live
        let redial = ConnectFace.make(phase: .reconnecting, reach: .ok, host: "h:1", problem: nil, macOnACall: false)
        XCTAssertEqual(redial.why, ConnectCopy.redialling); XCTAssertEqual(redial.pill, "Cancel")
    }

    func testADroppedLinkIsRedialledButARefusalOrAFirstDialThatNeverOpenedIsNot() {
        XCTAssertNil(Call.refusal(code: 1006, http: nil, reason: "", firstDial: false, retries: 3, place: "h:1"))  // live, dropped: redial
        XCTAssertNil(Call.refusal(code: 4409, http: nil, reason: "", firstDial: false, retries: 2, place: "h:1"))  // our own dead call
        XCTAssertEqual(Call.refusal(code: 4409, http: nil, reason: "", firstDial: true, retries: 0, place: "h:1"), ConnectCopy.busy)
        XCTAssertEqual(Call.refusal(code: 0, http: 403, reason: "", firstDial: true, retries: 0, place: "h:1"), ConnectCopy.notPairedHere)
        XCTAssertEqual(Call.refusal(code: 4401, http: 101, reason: "unpaired", firstDial: false, retries: 1, place: "h:1"), ConnectCopy.notPairedHere)
        XCTAssertEqual(Call.refusal(code: 0, http: nil, reason: "", firstDial: true, retries: 0, place: "mac.lan:7443"),
                       ConnectCopy.unreachableHere("mac.lan:7443"))
        XCTAssertEqual(Call.refusal(code: 1011, http: 101, reason: "no audio", firstDial: true, retries: 0, place: "h:1"),
                       "The call did not connect: no audio.")
        XCTAssertEqual(Call.refusal(code: 0, http: 502, reason: "", firstDial: true, retries: 0, place: "h:1"),
                       "The call did not connect: HTTP 502.")
    }
}

final class DriveRefusedTests: XCTestCase {
    func testTheMacsReasonOrThePagesLine() {
        XCTAssertEqual(DriveCopy.refused("a meeting is on"), "A meeting is on.")
        XCTAssertEqual(DriveCopy.refused("no call is up"), "Start the call first.")
        XCTAssertEqual(DriveCopy.refused("HTTP 500"), "Drive mode did not change.")  // no reason given
        XCTAssertEqual(DriveCopy.refused(""), "Drive mode did not change.")
    }
}

final class BriefingScheduleTests: XCTestCase {
    func testTheSchedulesChecksAreThePages() {
        XCTAssertEqual(BriefingCopy.check(time: "08:30", days: []), "Pick at least one day for the briefing.")
        XCTAssertNil(BriefingCopy.check(time: "08:30", days: [0]))
        XCTAssertNil(BriefingCopy.check(time: "", days: []))  // not scheduled: no day needed
    }

    func testNotSavedSaysTheMacsReason() {
        XCTAssertEqual(BriefingCopy.notSaved("not a setting, or a wrong value: briefing.days"),
                       "Not saved: not a setting, or a wrong value: briefing.days.")
        XCTAssertEqual(BriefingCopy.notSaved("HTTP 502"), "Not saved: the Mac did not answer.")
        XCTAssertEqual(BriefingCopy.notSaved(nil), "Not saved: the Mac did not answer.")
    }
}

final class RecentRequestsTests: XCTestCase {
    func testRecentRequestsAndTheContextCountAreDecodedAndWritten() throws {
        let s = try JSONDecoder().decode(API.Status.self, from: Data(#"""
            {"connected": true, "sessions": [], "tokens": {"context": 12480, "reply": 40, "audio_in": 0, "at": "10:42:07"},
             "recent": [{"at": "10:41:50", "said": "tell docs", "message": "x", "to": ["docs", "billing/main"], "how": "(named)"},
                        {"at": "10:42:01", "said": "push it", "message": "y", "to": [], "how": "blocked: ambiguous"}]}
            """#.utf8))
        XCTAssertEqual(SessionsCopy.routed(s.recent![0]), "10:41:50 → docs + billing/main (named)")
        XCTAssertEqual(SessionsCopy.routed(s.recent![1]), "10:42:01 blocked: ambiguous")
        XCTAssertEqual(SessionsCopy.context(s.tokens), "12,480 tokens as of 10:42:07")
        XCTAssertNil(SessionsCopy.context(nil))  // no call yet: nothing to count
    }
}

final class RenameTests: XCTestCase {
    func testARefusedRenameSaysTheMacsReason() {
        XCTAssertEqual(SessionsCopy.renameRefused("pricing is already taken"), "Not renamed: pricing is already taken.")
        XCTAssertEqual(SessionsCopy.renameRefused("HTTP 500"), "Not renamed: the Mac did not answer.")
    }
}

/// Words the page says too: each in the page's dictionary (ui.html) and the app's, word for word
/// (tests/test_copy_parity.py checks the same from the other side).
final class SharedWordsTests: XCTestCase {
    private func page() throws -> String {
        return try Repo.text("ui.html")
    }

    func testTheMeetingSheetSaysWhatPointeDoesInPlainWords() throws {
        XCTAssertEqual(MeetingCopy.lede, "Pointe sits in and takes notes for you. It stays quiet unless you let it speak.")
        XCTAssertTrue(try page().contains("lede: '\(MeetingCopy.lede)'"))
    }

    func testUnderConnectTheTypeLineSaysHowToReachTheTypeBar() throws {
        XCTAssertEqual(ConnectCopy.typeLaterTap, "Once connected, tap the keyboard to type")
        XCTAssertTrue(try page().contains("typeLaterTap: '\(ConnectCopy.typeLaterTap)'"))
    }

    func testADisabledLockLevelSaysWhy() throws {
        XCTAssertEqual(VoiceLockCopy.needsVoice, "Enrol your voice to use the other levels.")
        XCTAssertTrue(try page().contains("needsVoice: '\(VoiceLockCopy.needsVoice)'"))
    }

    func testAHoldIsAShortTitleAndALineUnderIt() throws {
        let page = try page().replacingOccurrences(of: "\\'", with: "'")
        XCTAssertTrue(page.contains("holding: '\(TurnsCopy.holding)', holdingHow: '\(TurnsCopy.holdingHow)'"))
    }
}

final class SpeakerTurnsTests: XCTestCase {
    func testACountSaysWhatItCounts() {
        XCTAssertEqual(MeetingCopy.turns(9), "9 turns")
        XCTAssertEqual(MeetingCopy.turns(1), "1 turn")
        XCTAssertEqual(MeetingCopy.turns(0), "0 turns")
    }
}

final class OwnerSymbolTests: XCTestCase {
    /// A control that asks for the owner shows the device's own sensor (Touch ID on a Mac): one symbol, from Surface.
    func testOnlySurfaceNamesTheOwnerCheckSymbol() throws {
        let sources = try FileManager.default.contentsOfDirectory(atPath: Repo.root.appendingPathComponent("apple/PointeKit/Sources/PointeUI").path)
        for name in sources where name.hasSuffix(".swift") && name != "Platform.swift" {
            let text = try Repo.source(name)
            XCTAssertFalse(text.contains("systemImage: \"faceid\"") || text.contains("systemImage: \"touchid\""),
                           "\(name) names the sensor itself: use Surface.ownerSymbol")
        }
    }
}

/// A Mac has no finger: the lines it shows say click and right-click where the phone's say tap and long-press. The
/// daemon's read-back ("Say yes or tap.") is one line for every device, so the Mac app words it for itself on screen.
final class TouchWordsTests: XCTestCase {
    func testTheMacSaysClickWhereThePhoneSaysTap() {
        let readBack = "Start a Claude Code session in shop on studio, named shop-2? Say yes or tap."
        if Surface.isMac {
            XCTAssertEqual(Surface.shown(readBack), "Start a Claude Code session in shop on studio, named shop-2? Say yes or click.")
            XCTAssertEqual(BrainDumpCopy.hintHere, "When you're done: click Done, or say “done” or “over to you”.")
            XCTAssertTrue(MeetingCopy.notYouHere.hasPrefix("Not you? Right-click a line in the Transcript"))
        } else {
            XCTAssertEqual(Surface.shown(readBack), readBack)
            XCTAssertEqual(BrainDumpCopy.hintHere, BrainDumpCopy.hint)
            XCTAssertTrue(MeetingCopy.notYouHere.hasPrefix("Not you? Long-press a line in the Transcript"))
        }
        XCTAssertEqual(Surface.shown("Nothing to change here."), "Nothing to change here.")
    }
}
