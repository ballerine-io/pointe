import SwiftUI
import XCTest
@testable import PointeUI

#if os(macOS)
/// Escape belongs to a sheet's cancel role: the button at the leading side of a Mac sheet (Sessions' New session) must
/// not take it, or Escape opens a second sheet instead of closing the first.
final class SheetEscapeTests: XCTestCase {
    func testTheLeadingButtonOfAMacSheetIsNotItsCancelAction() {
        let placement = String(describing: ToolbarItemPlacement.sheetLeading)
        XCTAssertFalse(placement.lowercased().contains("cancel"), placement)
        XCTAssertNotEqual(placement, String(describing: ToolbarItemPlacement.cancellationAction))
    }
}
#endif
