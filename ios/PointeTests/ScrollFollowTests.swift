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

    /// Measured on the simulator with the dock up: 518.7 points show between the insets, the dock's 138 below them, and at
    /// the end the offset plus what shows is the content's height. That is the end, whatever the dock's height.
    func testTheEndIsTheEndWithTheDockUp() {
        XCTAssertTrue(ScrollPin(offset: 2239.3, container: 518.7, content: 2758).bottom, "scrolled to the end")
        XCTAssertTrue(ScrollPin(offset: 2200, container: 518.7, content: 2758).bottom, "within the slack of it")
        XCTAssertFalse(ScrollPin(offset: 1785.3, container: 518.7, content: 2758).bottom, "a screen above it")
        XCTAssertTrue(ScrollPin(offset: 0, container: 518.7, content: 300).bottom, "a short conversation is always at its end")
    }

    /// The pill goes at the tap, before the scroll gets there, and a line arriving on the way is followed.
    func testTappingThePillFollowsAgainAtOnce() {
        var follow = ScrollFollow()
        follow.phase(scrolling: true)
        _ = follow.moved(bottom: false)
        follow.phase(scrolling: false)
        XCTAssertFalse(follow.newLine())
        XCTAssertTrue(follow.pillShown)
        follow.jumpToEnd()
        XCTAssertFalse(follow.pillShown, "gone at the tap")
        follow.phase(scrolling: false, animating: true)
        XCTAssertTrue(follow.newLine(), "a line on the way is followed, not a new pill")
        XCTAssertTrue(follow.moved(bottom: false), "still on its way to the end")
        XCTAssertFalse(follow.stillFollowing, "the animated scroll is already going there: no jump on top of it")
        follow.phase(scrolling: false)
        XCTAssertFalse(follow.moved(bottom: true))
        XCTAssertFalse(follow.pillShown)
    }

    /// Reading above, then scrolling back down by hand with the dock up: the geometry at the end says the end, so the
    /// pill goes. Before, the dock's inset came off twice and this stayed false.
    func testScrollingBackDownByHandWithTheDockUpClearsThePill() {
        var follow = ScrollFollow()
        follow.phase(scrolling: true)
        _ = follow.moved(bottom: ScrollPin(offset: 1300, container: 518.7, content: 2758).bottom)
        follow.phase(scrolling: false)
        _ = follow.newLine()
        XCTAssertTrue(follow.pillShown)
        follow.phase(scrolling: true)
        _ = follow.moved(bottom: ScrollPin(offset: 2239.3, container: 518.7, content: 2758).bottom)
        XCTAssertFalse(follow.pillShown, "at the end: the pill goes")
        follow.phase(scrolling: false)
        XCTAssertTrue(follow.newLine(), "and the next line is followed")
    }

    /// Scrolled back down by hand: as the list still glides at the end, a new line makes the content taller. The finger
    /// did not move the view away, so the pill must not come back and the line must be followed.
    func testALineArrivingWhileTheListGlidesAtTheEndIsFollowed() {
        var follow = ScrollFollow()
        follow.phase(scrolling: true)
        _ = follow.moved(bottom: false, offset: 1300)
        _ = follow.newLine()
        _ = follow.moved(bottom: ScrollPin(offset: 2239.3, container: 518.7, content: 2758).bottom, offset: 2239.3)
        XCTAssertFalse(follow.pillShown)
        let grown = ScrollPin(offset: 2239.3, container: 518.7, content: 2835)  // one more line, the list still gliding
        _ = follow.moved(bottom: grown.bottom, offset: 2239.3)
        follow.phase(scrolling: true)  // the glide's next phase: still no finger moving it away
        _ = follow.moved(bottom: false, offset: 2238.3)  // measured: the glide settles a point back
        XCTAssertTrue(follow.newLine(), "the new line is followed")
        XCTAssertFalse(follow.pillShown, "no pill: the finger did not leave the end")
        _ = follow.moved(bottom: false, offset: 2100)  // now the finger does drag up
        XCTAssertFalse(follow.newLine())
        XCTAssertTrue(follow.pillShown)
    }
}
