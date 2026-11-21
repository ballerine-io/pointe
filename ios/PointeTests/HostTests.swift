import XCTest
@testable import PointeUI

/// What only the app itself can show: the shared module's tests (apple/PointeKit/Tests/PointeUIUnitTests) run without an
/// app around them, on the Mac and in the simulator; these run inside the iPhone app.
final class HostTests: XCTestCase {
    func testTheAppVersionComesFromTheBundle() {
        XCTAssertFalse(AppVersion.app.isEmpty)
        XCTAssertNotEqual(AppVersion.app, "dev")
    }

    func testTheBrandFontsAreRegisteredInTheApp() {
        for face in [Brand.displayLight, Brand.displayRegular, Brand.textFace(.regular), Brand.textFace(.medium), Brand.textFace(.semibold)] {
            XCTAssertEqual(UIFont(name: face, size: 17)?.fontName, face, "\(face) is not registered (PointeBoot.start)")
        }
    }

    func testTheLogoIsInTheModulesBundle() {
        XCTAssertNotNil(UIImage(named: "ChorusMark", in: PointeBoot.bundle, with: nil))
    }
}
