import XCTest
@testable import PointeUI

final class DemoTests: XCTestCase {
    func testTryADemoIsACallWithARequestWaiting() throws {
        let demo = try XCTUnwrap(Demo.tryIt, "the fixture decodes in every build")
        XCTAssertTrue(demo.tried)
        XCTAssertEqual(demo.screen, .request)
        let waiting = demo.status.sessions.filter(\.waiting)
        XCTAssertEqual(waiting.count, 1)
        XCTAssertEqual(waiting.first?.request, "git push --force-with-lease origin retry-fix")
        XCTAssertFalse(demo.status.talk?.isEmpty ?? true, "a conversation shows, not the empty Connect stage")
    }

    func testALaunchArgumentDemoIsNotTried() throws {
        XCTAssertFalse(try XCTUnwrap(Demo.make(.call)).tried)
        XCTAssertNil(Demo.fromLaunch(), "the test host passes no -demo")
    }

    /// The site's pictures are in English only: `-demoEnglish` leaves no Hebrew in the screens they are taken from.
    func testTheEnglishDemoHasNoHebrewOnTheScreensTheSiteShows() throws {
        let hebrew: (String) -> Bool = { $0.unicodeScalars.contains { (0x0590...0x05FF).contains($0.value) } }
        for screen in [Demo.Screen.call, .machines, .machinesSessions, .challenge, .startPending, .brainDumpReview, .drive, .briefing] {
            XCTAssertFalse(hebrew(Demo.inEnglish(Demo.source(screen))), "\(screen)")
            XCTAssertNotNil(Demo.make(screen, english: true), "\(screen) still decodes")
        }
        XCTAssertTrue(hebrew(Demo.source(.machines)), "the default keeps its Hebrew session: the right-to-left checks read it")
    }

    func testTheDemoPairsWithNothingReal() {
        XCTAssertTrue(Demo.pairing.host.hasSuffix(".invalid"), "a reserved name: it can never reach a machine")
    }
}
