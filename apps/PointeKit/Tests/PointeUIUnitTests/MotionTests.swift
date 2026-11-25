import SwiftUI
import XCTest
@testable import PointeUI

/// Reduce Motion (docs/features/accessibility.md): Motion.swift decides, for every animation in the apps.
@MainActor
final class MotionTests: XCTestCase {
    func testTheSystemSettingReducesMotionAndWithoutItNothingIsForced() {
        XCTAssertTrue(Motion.reduced(true))
        XCTAssertFalse(Motion.forced, "no test run carries -pointe.reduceMotion")
        XCTAssertFalse(Motion.reduced(false))
    }

    func testWithReduceMotionNoStateDotMovesAndTheLineStillSaysTheState() {
        for kind in [StateDot.Kind.speaking, .thinking, .working, .steady] {
            XCTAssertFalse(StateDot.moves(kind, reduceMotion: true), "\(kind)")
        }
        XCTAssertEqual(StateDot.kind(title: ThinkingCopy.thinking, speaking: false), .thinking, "the words carry the state")
    }

    /// The module's own `withAnimation` is the one every screen calls: a change made in it is made, animated or not.
    func testAChangeInsideWithAnimationIsMade() {
        var done = false
        PointeUI.withAnimation(.snappy) { done = true }
        XCTAssertTrue(done)
        XCTAssertEqual(PointeUI.withAnimation { 7 }, 7)
    }
}
