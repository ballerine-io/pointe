import XCTest

/// The night shift (docs/design/night-shift.md), on the -demo fixtures. No Mac needed, and no Face ID: these stop before
/// Start is tapped. Screenshots go to NIGHT_SHIFT_SHOTS when it names a folder.
@MainActor
final class NightShiftUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen, "-demoEnglish"]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["NIGHT_SHIFT_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    private func text(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    /// Whether anything is drawn in the image's first two columns of points: text that starts at its frame's edge and is
    /// clipped there; words set inside a margin leave those columns the background's colour.
    static func inkAtLeftEdge(_ image: UIImage) -> Bool {
        guard let cg = image.cgImage else { return false }
        let (w, h) = (cg.width, cg.height)
        var px = [UInt8](repeating: 0, count: w * h * 4)
        let ctx = CGContext(data: &px, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4, space: CGColorSpaceCreateDeviceRGB(),
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
        ctx?.draw(cg, in: CGRect(x: 0, y: 0, width: w, height: h))
        let ground = Array(px[0..<3])
        let columns = Int(2 * image.scale)
        for y in 0..<h {
            for x in 0..<columns {
                let i = (y * w + x) * 4
                if zip(px[i..<(i + 3)], ground).contains(where: { abs(Int($0) - Int($1)) > 40 }) { return true }
            }
        }
        return false
    }

    func testTheStartSheetHasItsFieldsAndStartNeedsATask() {
        launch("nightShiftStart")
        let start = app.buttons["nightShiftStart"]
        XCTAssertTrue(start.waitForExistence(timeout: 15), "the start sheet")
        XCTAssertEqual(start.label, "Start shift")
        XCTAssertFalse(start.isEnabled, "no task yet: nothing to start")
        XCTAssertTrue(text("Give your sessions work for while you are away.").exists, "the lede")
        let session = any("nightShiftSession.0"), task = any("nightShiftTask.0")
        XCTAssertTrue(session.waitForExistence(timeout: 5) && task.exists)
        XCTAssertTrue(session.label.contains("billing") || (session.value as? String ?? "").contains("billing"), "the first session on the voice is picked")
        XCTAssertEqual(task.placeholderValue, "What it should get done tonight")
        // In a zero-inset row the lede's first letters were clipped at the row's edge: its words start inside the frame.
        let lede = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Give your sessions work")).firstMatch
        XCTAssertFalse(Self.inkAtLeftEdge(lede.screenshot().image), "the lede's first letters are not cut at the edge")
        shot("night-shift-start")

        task.tap()
        task.typeText("finish the retry work and open a PR")
        XCTAssertTrue(start.isEnabled, "a task for a session: Start is offered")

        app.swipeUp()
        for id in ["nightShiftAdd", "nightShiftHours", "nightShiftMessages", "nightShiftNotify"] {
            XCTAssertTrue(any(id).waitForExistence(timeout: 5), id)
        }
        XCTAssertTrue(text("Hours").exists && text("Messages").exists)
        XCTAssertEqual(app.switches["nightShiftNotify"].value as? String, "0", "quiet by default")
        XCTAssertTrue(app.switches["nightShiftNotify"].label.contains("Alert me about blockers overnight"))
        XCTAssertTrue(text("Pointe approves nothing: a session that needs approval waits for you.").exists, "the rule")
        any("nightShiftAdd").tap()
        XCTAssertTrue(any("nightShiftTask.1").waitForExistence(timeout: 5), "Add a task adds a row")
        XCTAssertTrue(start.isEnabled, "an empty row does not hold Start back")
        shot("night-shift-start-filled")

        app.buttons["nightShiftCancel"].tap()
        XCTAssertTrue(start.waitForNonExistence(timeout: 5))
        XCTAssertTrue(any("nightShiftEmpty").waitForExistence(timeout: 5), "Cancel starts nothing")
        XCTAssertEqual(any("nightShiftEmpty").label, "No night shift yet.")
        XCTAssertTrue(any("nightShiftOpenStart").exists)
    }

    func testARunningShiftShowsItsStripAndStopEndsIt() {
        launch("nightShift")
        let strip = any("nightShiftStrip"), stop = app.buttons["nightShiftStop"]
        XCTAssertTrue(strip.waitForExistence(timeout: 15))
        XCTAssertTrue(strip.label.contains("Night shift") && strip.label.contains("2 of 5 done · 1 blocked"), strip.label)
        XCTAssertEqual(stop.label, "Stop shift")
        shot("night-shift-running")
        strip.tap()
        XCTAssertTrue(app.navigationBars["Night shift"].waitForExistence(timeout: 5), "a tap opens the ledger")
        XCTAssertTrue(any("nightShiftRunning").waitForExistence(timeout: 5))
        app.buttons["nightShiftDone"].tap()
        XCTAssertTrue(stop.waitForExistence(timeout: 5))
        stop.tap()
        XCTAssertTrue(strip.waitForNonExistence(timeout: 5), "stopped: the strip goes")
    }

    func testNightShiftIsInSettingsBesideBriefing() {
        launch("nightShift")
        let entry = app.settingsItem("nightShiftItem", .button)
        XCTAssertTrue(entry.waitForExistence(timeout: 5), "Night shift is in Settings")
        XCTAssertEqual(entry.label, "Night shift")
        entry.tap()
        XCTAssertTrue(app.navigationBars["Night shift"].waitForExistence(timeout: 5))
        XCTAssertTrue(any("nightShiftHeadline").waitForExistence(timeout: 5))
    }

    func testTheLedgerLeadsWithWhatWasDecidedAndWhatWaits() {
        launch("nightShiftLedger")
        XCTAssertTrue(app.navigationBars["Night shift"].waitForExistence(timeout: 15))
        let headline = any("nightShiftHeadline")
        XCTAssertTrue(headline.waitForExistence(timeout: 5))
        XCTAssertEqual(headline.label, "Six hours in: 2 of 5 tasks done, 1 blocked.")
        XCTAssertFalse(any("nightShiftOpenStart").exists, "one shift at a time")
        shot("night-shift-ledger")

        // the parts in the product's order: each is found below the one before it, scrolling as needed
        var above: (id: String, element: XCUIElement)?
        for part in ["decided", "asked", "done", "blocked", "inFlight", "notStarted"] {
            let header = any("nightShiftSection.\(part)")
            for _ in 0..<6 where !header.exists { app.swipeUp(velocity: .slow) }
            XCTAssertTrue(header.exists, part)
            if let above, above.element.exists {
                XCTAssertLessThan(above.element.frame.minY, header.frame.minY, "\(above.id) comes before \(part)")
            }
            above = (part, header)
            if part == "done" { shot("night-shift-ledger-done") }
        }
        XCTAssertTrue(text("The exact request").exists, "a blocker that is an approval shows it")
        XCTAssertTrue(any("nightShiftRequest").label.contains("git push origin fix-flaky-test"), "word for word")
        shot("night-shift-ledger-blocked")
        for _ in 0..<4 where !any("nightShiftHistory.ns-2").exists { app.swipeUp(velocity: .slow) }
        XCTAssertTrue(text("Last 7 shifts").exists)
        XCTAssertTrue(any("nightShiftHistory.ns-2").exists && any("nightShiftHistory.ns-1").exists)
    }

    func testAReadBackShowsAsACardAndCancelNeedsNoFaceID() {
        launch("nightShiftPending")
        let cancel = app.buttons["nightShiftPendingCancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["Start this night shift?"].exists)
        let line = any("nightShiftLine")
        XCTAssertTrue(line.label.hasPrefix("Night shift. billing: finish the retry work and open a PR."), "the exact read-back: \(line.label)")
        XCTAssertTrue(line.label.hasSuffix("Start? Say yes or tap."))
        XCTAssertEqual(app.buttons["nightShiftConfirm"].label, "Start shift")
        shot("night-shift-pending")
        cancel.tap()
        XCTAssertTrue(cancel.waitForNonExistence(timeout: 5), "Cancel drops it at once")
        XCTAssertFalse(any("nightShiftStrip").exists, "and starts nothing")
    }
}
