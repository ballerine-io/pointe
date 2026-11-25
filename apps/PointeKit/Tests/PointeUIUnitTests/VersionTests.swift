import XCTest
@testable import PointeUI

final class VersionTests: XCTestCase {
    func testAppAloneWhenTheMacIsUnknownOrTheSame() {
        XCTAssertEqual(AppVersion.line(app: "1.2.0 (2)", mac: nil), "1.2.0 (2)")
        XCTAssertEqual(AppVersion.line(app: "1.2.0 (2)", mac: ""), "1.2.0 (2)")
        XCTAssertEqual(AppVersion.line(app: "1.2.0 (2)", mac: "1.2.0"), "1.2.0 (2)")
    }

    func testTheMacIsNamedWhenItRunsAnotherBuild() {
        XCTAssertEqual(AppVersion.line(app: "1.2.0 (2)", mac: "1.1.0"), "1.2.0 (2) · Mac 1.1.0")
    }

    /// Major version 0 is the beta: the version line says so, and a 1.x line does not.
    func testABetaVersionSaysBeta() {
        XCTAssertEqual(AppVersion.line(app: "0.8.0 (46)", mac: nil), "0.8.0 (46) · beta")
        XCTAssertEqual(AppVersion.line(app: "0.8.0 (46)", mac: "0.7.0"), "0.8.0 (46) · beta · Mac 0.7.0")
        XCTAssertEqual(AppVersion.line(app: "1.0.0 (50)", mac: nil), "1.0.0 (50)")
        XCTAssertEqual(AppVersion.line(app: "10.0.0", mac: nil), "10.0.0")
    }

    /// The iPhone app ships through the App Store, where a beta is refused (App Review 2.2; TestFlight marks its own
    /// builds): its line never says beta. The Mac app, a download, does.
    func testTheStoreAppDoesNotSayBeta() {
        XCTAssertEqual(AppVersion.line(app: "0.8.6 (66)", mac: nil, store: true), "0.8.6 (66)")
        XCTAssertEqual(AppVersion.line(app: "0.8.6 (66)", mac: "0.8.5", store: true), "0.8.6 (66) · Mac 0.8.5")
        XCTAssertEqual(AppVersion.line(app: "0.8.6 (66)", mac: nil, store: false), "0.8.6 (66) · beta")
    }

    /// A header with little room drops the build number before it cuts a word.
    func testTheShortVersionHasNoBuildNumber() {
        XCTAssertFalse(AppVersion.short.contains("("))
        XCTAssertTrue(AppVersion.app.hasPrefix(AppVersion.short))
    }
}
