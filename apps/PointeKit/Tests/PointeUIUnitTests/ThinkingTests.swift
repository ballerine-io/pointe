import XCTest
@testable import PointeUI

/// Thinking and working (docs/features/thinking.md) and the progress updates (docs/features/progress.md). From the end
/// of the owner's turn until the reply the state line says "Thinking…", not "Listening"; while a session has their
/// request it names it. The Mac's status says which (`phase`), and the call's own link says "thinking" the moment the
/// turn is taken. The words are the page's and the daemon's.
final class ThinkingTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    private func source(_ file: String) throws -> String {
        try String(contentsOf: Repo.root.appendingPathComponent(file), encoding: .utf8)
    }

    private let thinking = #"{"connected": true, "sessions": [], "phase": {"name": "thinking", "session": null, "since": 1700000000.5}}"#
    private let working = #"{"connected": true, "sessions": [], "phase": {"name": "working", "session": "billing/main", "since": 1700000000.5}}"#
    private let quiet = #"{"connected": true, "sessions": [], "phase": null}"#

    func testTheMacsStatusDecodes() throws {
        XCTAssertEqual(try status(thinking).phase, API.Phase(name: "thinking"))
        XCTAssertEqual(try status(working).phase, API.Phase(name: "working", session: "billing/main"))
        XCTAssertNil(try status(quiet).phase)
        XCTAssertNil(try status(#"{"connected": true, "sessions": []}"#).phase, "a Mac from before the Thinking state")
    }

    func testTheWordsAreTheDaemonsAndThePages() throws {
        let daemon = try source("pointe/thinking.py"), page = try source("pointe/ui_thinking.html"), spoken = try source("pointe/progress.py")
        XCTAssertTrue(daemon.contains("\"thinking\": \"\(ThinkingCopy.thinking)\"") && page.contains("thinking: '\(ThinkingCopy.thinking)'"))
        XCTAssertTrue(daemon.contains("\"working\": \"{session} is working…\"") && page.contains("`${session} is working…`"))
        XCTAssertEqual(ThinkingCopy.working("billing"), "billing is working…")
        XCTAssertTrue(daemon.contains("\"cue\": \"\(ThinkingCopy.cue)\"") && page.contains("cue: '\(ThinkingCopy.cue)'"))
        XCTAssertTrue(daemon.contains("\"cue_hint\": \"\(ThinkingCopy.cueHint)\"") && page.contains("cue_hint: '\(ThinkingCopy.cueHint)'"))
        XCTAssertTrue(spoken.contains("\"setting\": \"\(ThinkingCopy.progress)\"") && page.contains("setting: '\(ThinkingCopy.progress)'"))
        XCTAssertTrue(spoken.contains("\"hint\": \"\(ThinkingCopy.progressHint)\"") && page.contains("hint: '\(ThinkingCopy.progressHint)'"))
    }

    @MainActor
    private func call() -> Call {
        Call(pairing: Pairing(host: "studio.example.ts.net", port: 7443, fingerprint: String(repeating: "a", count: 64),
                              key: String(repeating: "k", count: 32)))
    }

    @MainActor
    func testTheStateLineSaysThinkingWhereItSaidListening() throws {
        let call = call()
        func title(_ json: String, speaking: Bool = false, muted: Bool = false) throws -> String {
            CallTitle.line(phase: .live, reach: .ok, status: try status(json), call: call, macName: "studio", dumping: false,
                           talking: false, speaking: speaking, muted: muted)
        }
        XCTAssertEqual(try title(quiet), "Listening")
        XCTAssertEqual(try title(thinking), "Thinking…")
        XCTAssertEqual(try title(working), "billing/main is working…")
        XCTAssertEqual(try title(thinking, speaking: true), "Speaking…", "sound that plays is said first")
        XCTAssertEqual(try title(working, speaking: true), "Speaking…")
        XCTAssertEqual(try title(thinking, muted: true), "Mic off", "the microphone's own state comes first, as before")
        let writing = #"{"connected": true, "sessions": [], "phase": {"name": "thinking"}, "reading": {"on": true, "held": null, "read_through": -1, "writing": true}}"#
        XCTAssertEqual(try title(writing), "Writing…")
        let held = #"{"connected": true, "sessions": [], "phase": {"name": "thinking"}, "hold": {"since": 1700000000, "said": "so the thing is"}}"#
        XCTAssertNotEqual(try title(held), "Thinking…", "a hold is the owner's: its own line stays")
    }

    @MainActor
    func testNoCallNoThinking() throws {
        let call = call()
        let line = CallTitle.line(phase: .off, reach: .ok, status: try status(thinking), call: call, macName: "studio", dumping: false,
                                  talking: false, speaking: false, muted: false)
        XCTAssertNotEqual(line, "Thinking…")
    }

    // MARK: the call's own link

    func testTheLinksMessageIsRead() {
        XCTAssertEqual(ThinkingRule.message(["type": "phase", "name": "thinking", "session": NSNull()]), API.Phase(name: "thinking"))
        XCTAssertEqual(ThinkingRule.message(["type": "phase", "name": "working", "session": "docs"]), API.Phase(name: "working", session: "docs"))
        XCTAssertNil(ThinkingRule.message(["type": "reading", "on": true]))
        XCTAssertNil(ThinkingRule.message(["type": "phase"]))
    }

    func testWhatTheLinkSaidShowsAtOnceAndOnlyUntilTheStatusHasHadTimeToSayIt() throws {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let told = ThinkingRule.Told(phase: API.Phase(name: "thinking"), at: now)
        let quiet = try status(quiet), thinking = try status(thinking), working = try status(working)
        XCTAssertEqual(ThinkingRule.phase(status: quiet, told: told, now: now.addingTimeInterval(0.05)), API.Phase(name: "thinking"),
                       "before the next poll")
        XCTAssertNil(ThinkingRule.phase(status: quiet, told: told, now: now.addingTimeInterval(ThinkingRule.holdSecs + 0.1)),
                     "the status never said so: nothing was coming")
        XCTAssertEqual(ThinkingRule.phase(status: thinking, told: nil, now: now), API.Phase(name: "thinking"))
        XCTAssertEqual(ThinkingRule.phase(status: working, told: told, now: now.addingTimeInterval(0.05)), API.Phase(name: "working", session: "billing/main"),
                       "the Mac's status is the truth once it speaks")
        XCTAssertNil(ThinkingRule.phase(status: nil, told: told, now: now), "no status: no call to think on")
        let off = try status(#"{"connected": false, "sessions": []}"#)
        XCTAssertNil(ThinkingRule.phase(status: off, told: told, now: now))
        XCTAssertLessThanOrEqual(ThinkingRule.holdSecs, 1.0)
    }

    // MARK: the dot

    func testTheDotTellsTheStatesApartByMoreThanColour() {
        XCTAssertEqual(StateDot.kind(title: "Thinking…", speaking: false), .thinking)
        XCTAssertEqual(StateDot.kind(title: "billing is working…", speaking: false), .working)
        XCTAssertEqual(StateDot.kind(title: "Speaking…", speaking: true), .speaking)
        XCTAssertEqual(StateDot.kind(title: "Writing…", speaking: true), .speaking)
        XCTAssertEqual(StateDot.kind(title: "Listening", speaking: false), .steady)
        XCTAssertTrue(StateDot.Kind.thinking.pointesTurn && StateDot.Kind.speaking.pointesTurn, "orange: Pointe's turn")
        XCTAssertFalse(StateDot.Kind.working.pointesTurn || StateDot.Kind.steady.pointesTurn, "green: yours, or a session's work")
        XCTAssertNotEqual(StateDot.Kind.thinking.motion, StateDot.Kind.speaking.motion)
        XCTAssertEqual(StateDot.Kind.steady.motion, .none)
    }

    func testReduceMotionStopsTheDot() {
        for kind in [StateDot.Kind.thinking, .working, .speaking, .steady] {
            XCTAssertFalse(StateDot.moves(kind, reduceMotion: true), "\(kind)")
        }
        XCTAssertTrue(StateDot.moves(.thinking, reduceMotion: false) && StateDot.moves(.working, reduceMotion: false))
        XCTAssertFalse(StateDot.moves(.steady, reduceMotion: false))
    }

    // MARK: settings

    func testTheTwoSettingsAreTheMacs() throws {
        let prefs = try JSONDecoder().decode(API.Prefs.self, from: Data(#"{"thinking.cue": false, "progress.spoken": true}"#.utf8))
        XCTAssertEqual(prefs.waitCue, false)
        XCTAssertEqual(prefs.progressSpoken, true)
        let old = try JSONDecoder().decode(API.Prefs.self, from: Data(#"{"microphone": "always"}"#.utf8))
        XCTAssertNil(old.waitCue, "a Mac from before the waiting sound: no switch")
        XCTAssertNil(old.progressSpoken)
        let model = CallSettingsModel(status: nil, prefs: prefs, microphone: "always", talkStyle: .hold, live: true, dumping: false,
                                      driving: false, driveSuggest: false, demo: false)
        XCTAssertEqual(model.waitCue, false)
        XCTAssertEqual(model.progressSpoken, true)
        let none = CallSettingsModel(status: nil, prefs: old, microphone: "always", talkStyle: .hold, live: true, dumping: false,
                                     driving: false, driveSuggest: false, demo: false)
        XCTAssertNil(none.waitCue)
        XCTAssertNil(none.progressSpoken)
    }

    func testTheSettingsKeysAreTheDaemons() throws {
        let prefs = try source("pointe/prefs.py"), view = try source("apps/PointeKit/Sources/PointeUI/CallView.swift")
        for key in ["thinking.cue", "progress.spoken"] {
            XCTAssertTrue(prefs.contains("\"\(key)\":") && view.contains("\"\(key)\""), key)
        }
    }

    // MARK: the demo screens

    func testTheDemoScreensShowTheStates() throws {
        XCTAssertEqual(Demo.make(.thinking)?.status.phase, API.Phase(name: "thinking"))
        XCTAssertEqual(Demo.make(.working)?.status.phase, API.Phase(name: "working", session: "billing/main"))
        XCTAssertNil(Demo.make(.call)?.status.phase)
    }
}
