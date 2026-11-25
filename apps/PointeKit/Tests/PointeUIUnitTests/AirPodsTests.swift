import XCTest
@testable import PointeUI

/// The Mac app's AirPods press (docs/features/mute.md, "AirPods and play/pause"). A stem press is the system's mute
/// gesture: the mic off and on. Play/pause (another headset, the keyboard's key, an AirPods press macOS sends as one)
/// does what Settings says. Both are Pointe's only during a call, and one press never does both.
@MainActor
final class AirPodsTests: XCTestCase {
    func testAStemPressIsTheMicInAlwaysOnAndTalksInPushToTalk() {
        XCTAssertEqual(AirPodsPress.gesture(muted: true, pushToTalk: false).action, .mic(off: true))
        XCTAssertTrue(AirPodsPress.gesture(muted: true, pushToTalk: false).accept, "the system's mute is the mic's")
        XCTAssertEqual(AirPodsPress.gesture(muted: false, pushToTalk: false).action, .mic(off: false))
        let ptt = AirPodsPress.gesture(muted: true, pushToTalk: true)
        XCTAssertEqual(ptt.action, .talk, "in push to talk the press is the talk button, as on the iPhone")
        XCTAssertFalse(ptt.accept, "and the input is not muted: the gate decides what is sent")
    }

    func testTheHintSaysWhatThePressDoesNow() {
        XCTAssertEqual(AirPodsPress.hint(pushToTalk: false, micOff: false), "AirPods: press for mic off")
        XCTAssertEqual(AirPodsPress.hint(pushToTalk: false, micOff: true), "AirPods: press for mic on")
        XCTAssertEqual(AirPodsPress.hint(pushToTalk: true, micOff: false), "AirPods: press to talk")
    }

    func testPlayPauseMutesPointeUntilSettingsSaysOtherwise() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "airpods-tests-\(UUID())"))
        XCTAssertEqual(PlayPause.stored(defaults), .mutePointe)
        PlayPause.store(.skip, defaults)
        XCTAssertEqual(PlayPause.stored(defaults), .skip)
        defaults.set("made-up", forKey: PlayPause.key)
        XCTAssertEqual(PlayPause.stored(defaults), .mutePointe, "an unknown value is the default")
        XCTAssertEqual(PlayPause.allCases.map(\.label), ["Mute Pointe", "Skip", "Nothing"])
        XCTAssertEqual(PlayPause.mutePointe.label, MuteCopy.mute)
    }

    func testPlayPauseIsTakenOnlyDuringACall() {
        let center = FakeCenter()
        let presses = CallPresses(center: center)
        presses.update(onCall: false, choice: .mutePointe)
        XCTAssertEqual(center.takes, 0, "no call: play/pause stays with the music")
        presses.update(onCall: true, choice: .mutePointe)
        presses.update(onCall: true, choice: .mutePointe)
        XCTAssertEqual(center.takes, 1, "taken once for the call")
        XCTAssertTrue(center.held)
        presses.update(onCall: true, choice: .skip)
        XCTAssertEqual(center.takes, 1, "a new choice during the call keeps what is held")
        presses.update(onCall: false, choice: .skip)
        XCTAssertFalse(center.held, "hang up: given back")
        XCTAssertEqual(center.releases, 1)
        presses.update(onCall: true, choice: .nothing)
        XCTAssertFalse(center.held, "Nothing: never taken, so the music keeps its key during a call too")
        presses.update(onCall: true, choice: .mutePointe)
        presses.update(onCall: true, choice: .nothing)
        XCTAssertFalse(center.held, "switched to Nothing mid-call: given back at once")
    }

    func testAPressDoesWhatSettingsSays() {
        let center = FakeCenter()
        var now: TimeInterval = 100
        let presses = CallPresses(center: center, arbiter: PressArbiter(), clock: { now })
        var done: [PlayPause] = []
        presses.perform = { done.append($0) }
        presses.update(onCall: true, choice: .mutePointe)
        center.press()
        now += 1
        presses.update(onCall: true, choice: .skip)
        center.press()
        XCTAssertEqual(done, [.mutePointe, .skip])
    }

    func testThePressWindowLetsOneSourceWin() {
        let arbiter = PressArbiter()
        XCTAssertTrue(arbiter.admit(.gesture, at: 10))
        XCTAssertFalse(arbiter.admit(.playPause, at: 10.2), "the same press, sent twice: the second is dropped")
        XCTAssertTrue(arbiter.admit(.gesture, at: 10.3), "a second stem press is a press")
        XCTAssertTrue(arbiter.admit(.playPause, at: 10.3 + PressArbiter.window), "past the window: a press of its own")
        XCTAssertFalse(arbiter.admit(.gesture, at: 10.4 + PressArbiter.window))
    }

    func testOnePressNeverFiresBoth() {
        let arbiter = PressArbiter()
        let system = FakeInputMute()
        let gestures = Heard()
        let clock = Clock(50)
        let gesture = MuteGesture(system: system, arbiter: arbiter, clock: { clock.now }, onGesture: gestures.add)
        let center = FakeCenter()
        let presses = CallPresses(center: center, arbiter: arbiter, clock: { clock.now })
        var done: [PlayPause] = []
        presses.perform = { done.append($0) }
        gesture.start(muted: false, pushToTalk: false)
        presses.update(onCall: true, choice: .mutePointe)

        XCTAssertTrue(system.press(muted: true), "the stem press: mic off")
        clock.now += 0.1
        center.press()
        XCTAssertEqual(gestures.all, [.mic(off: true)])
        XCTAssertEqual(done, [], "the play/pause the same press sent does nothing")

        clock.now += 2
        center.press()
        clock.now += 0.1
        XCTAssertFalse(system.press(muted: false), "play/pause came first: the gesture is refused, the mic stays as it is")
        XCTAssertEqual(gestures.all, [.mic(off: true)])
        XCTAssertEqual(done, [.mutePointe])
    }

    func testTheGestureIsHeardOnlyDuringACall() {
        let system = FakeInputMute()
        let gestures = Heard()
        let gesture = MuteGesture(system: system, onGesture: gestures.add)
        XCTAssertNil(system.handler, "no call: macOS keeps the press")
        gesture.start(muted: true, pushToTalk: false)
        XCTAssertNotNil(system.handler)
        XCTAssertEqual(system.muted, true, "a call that starts with the mic off tells the system so")
        XCTAssertTrue(gestures.all.isEmpty, "telling the system is not a press")
        gesture.start(muted: true, pushToTalk: false)
        XCTAssertEqual(system.listens, 1, "the audio restarting after a device change listens once")
        gesture.stop()
        XCTAssertNil(system.handler, "hang up: the press is macOS's again")
        XCTAssertEqual(system.muted, false, "and the app's input is not left muted")
    }

    func testTheMicButtonKeepsTheSystemInStepWithoutAnEcho() {
        let system = FakeInputMute()
        let gestures = Heard()
        let gesture = MuteGesture(system: system, onGesture: gestures.add)
        gesture.start(muted: false, pushToTalk: false)
        gesture.sync(muted: true)
        XCTAssertEqual(system.muted, true, "so the next stem press asks for mic on")
        XCTAssertEqual(system.echoes, 1, "macOS calls the handler from inside setInputMuted")
        XCTAssertTrue(gestures.all.isEmpty, "the app's own change is not a press")
        gesture.sync(muted: true)
        XCTAssertEqual(system.sets, 1, "unchanged: the system is not told again")
        XCTAssertTrue(system.press(muted: false))
        gesture.sync(muted: false)
        XCTAssertEqual(system.sets, 1, "the gesture already set the system: the mic following it is not told back")
    }

    func testInPushToTalkTheStemPressTalks() {
        let system = FakeInputMute()
        let gestures = Heard()
        let gesture = MuteGesture(system: system, onGesture: gestures.add)
        gesture.start(muted: false, pushToTalk: false)
        gesture.set(pushToTalk: true)
        XCTAssertFalse(system.press(muted: true), "refused: the input stays unmuted")
        XCTAssertEqual(gestures.all, [.talk])
        XCTAssertEqual(system.muted, false)
    }

    func testTheRemoteCommandsAreTheMacsAndCallScoped() throws {
        let source = try String(contentsOf: Repo.root.appendingPathComponent("apps/PointeKit/Sources/PointeUI/AirPods.swift"), encoding: .utf8)
        XCTAssertTrue(source.contains("playbackState = .playing") && source.contains("playbackState = .stopped"),
                      "macOS sends remote commands to the app that says it plays, and only while it does")
        let shell = try String(contentsOf: Repo.root.appendingPathComponent("apps/PointeKit/Sources/PointeUI/MacShell.swift"), encoding: .utf8)
        XCTAssertTrue(shell.contains("presses.update(onCall: onRealCall") && shell.contains("onRealCall: Bool { demo == nil &&"),
                      "a real call only: never a demo")
    }
}

@MainActor
private final class FakeCenter: RemoteCommands {
    var takes = 0, releases = 0
    private var target: (@MainActor () -> Void)?
    var held: Bool { target != nil }

    func take(_ press: @escaping @MainActor () -> Void) { takes += 1; target = press }
    func release() { releases += 1; target = nil }
    func press() { target?() }
}

/// Like AVAudioApplication on macOS: setInputMuted calls the handler synchronously, and a handler that returns true
/// makes its value the system's.
private final class FakeInputMute: InputMuteSystem, @unchecked Sendable {
    var handler: (@Sendable (Bool) -> Bool)?
    var muted = false
    var listens = 0, sets = 0, echoes = 0

    func listen(_ handler: (@Sendable (Bool) -> Bool)?) {
        if handler != nil { listens += 1 }
        self.handler = handler
    }

    func setMuted(_ value: Bool) {
        sets += 1
        if let handler {
            echoes += 1
            if handler(value) { muted = value }
        } else {
            muted = value
        }
    }

    /// A stem press: the handler decides, and the system keeps the value only when it accepts.
    func press(muted value: Bool) -> Bool {
        guard let handler else { return false }
        let accepted = handler(value)
        if accepted { muted = value }
        return accepted
    }
}

private final class Clock: @unchecked Sendable {
    var now: TimeInterval
    init(_ now: TimeInterval) { self.now = now }
}

private final class Heard: @unchecked Sendable {
    private(set) var all: [AirPodsPress.Gesture] = []
    func add(_ gesture: AirPodsPress.Gesture) { all.append(gesture) }
}
