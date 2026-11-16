import XCTest
@testable import Pointe

/// The conversation follows the newest line until your finger takes it off; then new lines wait behind the New pill.
final class ScrollFollowTests: XCTestCase {
    /// The QA tour on a real daemon: the drag's first move reached the geometry callback before the scroll phase said a
    /// finger was down, so the view thought it was still following and the next line pulled it to the end.
    func testAFingerThatScrollsUpStopsTheFollowWhicheverCallbackComesFirst() {
        var follow = ScrollFollow()
        XCTAssertTrue(follow.moved(bottom: false), "not a finger yet: a layout change, back to the end")
        follow.phase(scrolling: true)
        follow.phase(scrolling: false)
        XCTAssertFalse(follow.newLine(), "scrolled up: the view stays where you read")
        XCTAssertTrue(follow.unseen, "and the New pill shows")
    }

    func testPhaseFirstThenTheMove() {
        var follow = ScrollFollow()
        follow.phase(scrolling: true)
        XCTAssertFalse(follow.moved(bottom: false))
        follow.phase(scrolling: false)
        XCTAssertFalse(follow.newLine())
        XCTAssertTrue(follow.unseen)
    }

    func testAtTheEndANewLineScrollsAndBackAtTheEndThePillGoes() {
        var follow = ScrollFollow()
        XCTAssertTrue(follow.newLine())
        XCTAssertFalse(follow.unseen)
        follow.phase(scrolling: true)
        _ = follow.moved(bottom: false)
        follow.phase(scrolling: false)
        _ = follow.newLine()
        XCTAssertFalse(follow.moved(bottom: true), "scrolled back down by hand")
        XCTAssertFalse(follow.unseen)
        XCTAssertTrue(follow.newLine(), "following again")
    }

    func testTheKeyboardOrACardTakingRoomKeepsTheNewestLineInView() {
        var follow = ScrollFollow()
        XCTAssertTrue(follow.moved(bottom: false), "no finger: back to the end")
        XCTAssertTrue(follow.atBottom)
        XCTAssertTrue(follow.stillFollowing, "the deferred scroll still goes")
    }
}
