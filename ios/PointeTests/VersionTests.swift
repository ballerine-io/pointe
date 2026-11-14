import XCTest
@testable import Pointe

final class VersionTests: XCTestCase {
    func testAppAloneWhenTheMacIsUnknownOrTheSame() {
        XCTAssertEqual(AppVersion.line(app: "1.2.0 (2)", mac: nil), "1.2.0 (2)")
        XCTAssertEqual(AppVersion.line(app: "1.2.0 (2)", mac: ""), "1.2.0 (2)")
        XCTAssertEqual(AppVersion.line(app: "1.2.0 (2)", mac: "1.2.0"), "1.2.0 (2)")
    }

    func testTheMacIsNamedWhenItRunsAnotherBuild() {
        XCTAssertEqual(AppVersion.line(app: "1.2.0 (2)", mac: "1.1.0"), "1.2.0 (2) · Mac 1.1.0")
    }

    func testTheAppVersionComesFromTheBundle() {
        XCTAssertFalse(AppVersion.app.isEmpty)
        XCTAssertNotEqual(AppVersion.app, "dev")
    }
}
