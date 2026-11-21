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

    func testTheDemoPairsWithNothingReal() {
        XCTAssertTrue(Demo.pairing.host.hasSuffix(".invalid"), "a reserved name: it can never reach a machine")
    }
}
