import XCTest
@testable import PointeUI

/// Push to talk felt dead for the first second: a press sent only what the microphone gave after the gate opened, and
/// only at its next buffer. The microphone runs all call long; while the gate is closed the last moments are held, and a
/// press sends from its touch-down on, at once. Buffers of 100 ms, as the iPhone's voice processing gives them.
final class TalkSenderTests: XCTestCase {
    private let buffer = 1600  // 100 ms at 16 kHz

    /// Sample n of the made-up microphone, captured at n / 16000 s: each value says when it was captured.
    private func mic(_ sender: inout TalkSender, upTo end: TimeInterval, from start: TimeInterval = 0, sending: Bool) -> [[Float]] {
        var out: [[Float]] = []
        var t = start
        while t < end - 1e-9 {
            let first = Int((t * Wire.upRate).rounded())
            let samples = (first..<first + buffer).map { Float($0) }
            t += Double(buffer) / Wire.upRate
            out += sender.capture(samples, end: t, sending: sending)
        }
        return out
    }

    private func capturedAt(_ sample: Float) -> TimeInterval { Double(sample) / Wire.upRate }

    func testClosedSendsNothing() {
        var sender = TalkSender()
        XCTAssertEqual(mic(&sender, upTo: 5, sending: false).count, 0)
    }

    /// The first chunk goes in the press itself, not at the next buffer, and it starts before the touch.
    func testAPressSendsFromItsTouchAtOnce() {
        var sender = TalkSender()
        _ = mic(&sender, upTo: 2.0, sending: false)
        let touched = 1.95  // handled at 2.0: 50 ms after the touch, between two buffers
        let (chunks, from) = sender.opened(touched: touched)
        XCTAssertFalse(chunks.isEmpty, "something goes at the press")
        XCTAssertEqual(capturedAt(chunks[0][0]), touched - TalkSender.margin, accuracy: 0.001, "from the touch, less the margin")
        XCTAssertEqual(from ?? 0, touched - TalkSender.margin, accuracy: 0.001)
        let next = mic(&sender, upTo: 2.1, from: 2.0, sending: true)
        let all = (chunks + next).flatMap { $0 }
        XCTAssertEqual(all, (Int(all[0])..<Int(all[0]) + all.count).map(Float.init), "no gap and nothing twice")
    }

    /// A touch that took 700 ms to reach the gate still sends what was said from the touch on.
    func testATouchHandledLateLosesNothing() {
        var sender = TalkSender()
        _ = mic(&sender, upTo: 3.0, sending: false)
        let (chunks, _) = sender.opened(touched: 2.3)
        XCTAssertLessThanOrEqual(capturedAt(chunks[0][0]), 2.3)
        XCTAssertEqual(capturedAt(chunks[0][0]), 2.3 - TalkSender.margin, accuracy: 0.001)
    }

    /// Nothing from before the touch (less the margin) leaves the phone, however much is held.
    func testNothingFromBeforeTheTouchIsSent() {
        var sender = TalkSender()
        _ = mic(&sender, upTo: 4.0, sending: false)
        let (chunks, _) = sender.opened(touched: 3.98)
        let first = chunks.flatMap { $0 }.first ?? .infinity
        XCTAssertGreaterThanOrEqual(capturedAt(first), 3.98 - TalkSender.margin - 0.001)
    }

    /// Held for as long as it can reach back, not longer.
    func testWhatIsHeldIsBounded() {
        var sender = TalkSender()
        _ = mic(&sender, upTo: 10, sending: false)
        let (chunks, from) = sender.opened(touched: 1)  // a touch older than anything held
        XCTAssertEqual(from ?? 0, 10 - TalkSender.keep, accuracy: 0.001)
        XCTAssertEqual(chunks.flatMap { $0 }.count, Int(TalkSender.keep * Wire.upRate) / Wire.chunk * Wire.chunk)
    }

    func testAlwaysOnSendsEverythingAsItComes() {
        var sender = TalkSender()
        let chunks = mic(&sender, upTo: 1, sending: true)
        XCTAssertEqual(chunks.count, Int(Wire.upRate) / Wire.chunk)
        XCTAssertEqual(capturedAt(chunks[0][0]), 0)
        XCTAssertTrue(sender.opened(touched: 1).chunks.isEmpty, "nothing was held while sending")
    }

    /// A dropped link or a hang-up forgets what was held.
    func testResetForgetsWhatWasHeld() {
        var sender = TalkSender()
        _ = mic(&sender, upTo: 2, sending: false)
        sender.reset()
        let (chunks, from) = sender.opened(touched: 1.9)
        XCTAssertTrue(chunks.isEmpty)
        XCTAssertNil(from)
    }

    /// Press to first frame: the old path waited for the next buffer (up to 100 ms) and sent nothing from before the
    /// gate; this one sends at the press. Times in the press handler, as the call records them.
    func testPressToFirstFrameIsThePressItself() {
        var sender = TalkSender()
        _ = mic(&sender, upTo: 2.0, sending: false)
        let handled = 2.0
        let (chunks, from) = sender.opened(touched: 1.91)
        XCTAssertFalse(chunks.isEmpty)
        let firstFrameAfterTouch = handled - 1.91  // sent in the handler
        XCTAssertLessThan(firstFrameAfterTouch, 0.15, "under 150 ms from the touch")
        XCTAssertLessThanOrEqual(from ?? .infinity, 1.91, "and its audio starts at the touch or before")
    }
}

/// The touch's time, which SwiftUI gives as a date, on the audio clock.
final class RingTalkTimeTests: XCTestCase {
    func testTheEventsUptimeAsADateFrom2001() {
        let uptime: TimeInterval = 1_500_000
        let touch = Date(timeIntervalSinceReferenceDate: uptime - 0.09)  // what the gesture gave on the simulator
        XCTAssertEqual(RingTalk.uptime(of: touch, now: Date(), uptime: uptime), uptime - 0.09, accuracy: 1e-6)
    }

    func testAWallClockDate() {
        let now = Date()
        XCTAssertEqual(RingTalk.uptime(of: now.addingTimeInterval(-0.12), now: now, uptime: 500), 500 - 0.12, accuracy: 1e-6)
    }

    func testAnythingElseIsNow() {
        XCTAssertEqual(RingTalk.uptime(of: .distantPast, now: Date(), uptime: 500), 500)
        XCTAssertEqual(RingTalk.uptime(of: .distantFuture, now: Date(), uptime: 500), 500)
    }
}
