import XCTest

/// The accessibility pass (docs/features/accessibility.md), on the -demo fixtures: no Mac needed. VoiceOver has a name
/// for every control of the call screen; Reduce Motion stops every pulse; at the largest text size the state line is
/// whole. `-pointe.reduceMotion YES` stands in for the system's Reduce Motion, which a UI test cannot switch.
/// Screenshots go to A11Y_SHOTS.
@MainActor
final class AccessibilityUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = true }

    private func launch(_ screen: String, _ more: [String] = [], dark: Bool = false) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen, "-demoEnglish", "-pointe.theme", dark ? "dark" : "light"] + more
        app.launch()
        XCTAssertTrue(line().waitForExistence(timeout: 15), "\(screen): the call screen")
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["A11Y_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func line() -> XCUIElement { app.descendants(matching: .any)["statusLine"].firstMatch }

    /// The controls VoiceOver could not name: no label at all, or a symbol's file name ("mic.fill") read as one.
    private func unnamed() -> [String] {
        let kinds: [(XCUIElement.ElementType, String)] = [(.button, "button"), (.switch, "switch"), (.toggle, "toggle"), (.textField, "text field"),
                                                           (.textView, "text view"), (.slider, "slider"), (.link, "link"), (.menuButton, "menu")]
        var bad: [String] = []
        for (kind, word) in kinds {
            for e in app.descendants(matching: kind).allElementsBoundByIndex where e.exists {
                let label = e.label.trimmingCharacters(in: .whitespacesAndNewlines)
                let hint = e.placeholderValue ?? ""
                let symbol = label.range(of: #"^[a-z0-9]+(\.[a-z0-9]+)+$"#, options: .regularExpression) != nil
                if (label.isEmpty && hint.isEmpty) || symbol { bad.append("\(word) '\(e.identifier)' is read as '\(label)'") }
            }
        }
        return bad
    }

    func testEveryControlOfTheCallScreenHasAName() {
        for screen in ["call", "request", "speaking", "thinking", "working", "writing", "held", "hold", "talking", "voiceLockEnrolled"] {
            launch(screen)
            XCTAssertEqual(unnamed(), [], "\(screen): VoiceOver has a name for every control")
            XCTAssertFalse(line().label.isEmpty, "\(screen): the state line is read")
            app.terminate()
        }
    }

    func testTheMainControlsAreReadByTheirOwnWords() {
        launch("speaking")
        for (id, words) in [("micRing", "mic"), ("muteButton", "Pointe"), ("skipButton", "Skip"), ("sessionsButton", "Sessions"),
                            ("typeButton", "Type"), ("dumpButton", "Brain dump"), ("hangUp", "Hang up")] {
            let control = app.buttons[id].firstMatch
            XCTAssertTrue(control.exists, "\(id) is on the call screen")
            XCTAssertTrue(control.label.localizedCaseInsensitiveContains(words), "\(id) is read as '\(control.label)'")
        }
        XCTAssertTrue(app.buttons["Settings"].exists, "the ••• button is read as Settings")
    }

    /// How many different pictures of the element there are over a second and a half.
    private func pictures(of element: XCUIElement) -> Int {
        var seen = Set<Data>()
        for _ in 0..<8 {
            seen.insert(element.screenshot().pngRepresentation)
            usleep(180_000)
        }
        return seen.count
    }

    func testReduceMotionStopsEveryPulse() {
        // Thinking: the dot shrinks and grows. Working: it breathes. The call: the wave beside the words being heard.
        for screen in ["thinking", "working"] {
            launch(screen)
            XCTAssertGreaterThan(pictures(of: line()), 1, "\(screen): the dot moves when motion is allowed")
            app.terminate()
            launch(screen, ["-pointe.reduceMotion", "YES"])
            XCTAssertEqual(pictures(of: line()), 1, "\(screen): with Reduce Motion the dot is still")
            XCTAssertTrue(line().label.hasPrefix(screen == "thinking" ? "Thinking…" : "billing/main is working…"), "the words still say the state")
            shot("iphone-reduce-motion-\(screen)-light")
            app.terminate()
        }
        launch("call", ["-pointe.reduceMotion", "YES"])
        let talk = app.descendants(matching: .any)["conversation"].firstMatch
        XCTAssertTrue(talk.exists)
        XCTAssertEqual(pictures(of: talk), 1, "with Reduce Motion nothing in the conversation moves by itself")
        for (id, screen) in [("challengeCard", "challenge"), ("dumpState", "brainDump")] {
            app.terminate()
            launch(screen, ["-pointe.reduceMotion", "YES"])
            XCTAssertEqual(pictures(of: app.windows.firstMatch), 1, "\(screen) (\(id)): with Reduce Motion no symbol pulses")
        }
    }

    func testAtTheLargestTextSizeTheStateLineIsWhole() {
        let largest = ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        launch("call", largest)
        let short = line().frame
        app.terminate()
        for dark in [false, true] {
            launch("working", largest, dark: dark)
            let long = line().frame, window = app.windows.firstMatch.frame
            XCTAssertTrue(line().label.hasPrefix("billing/main is working…"))
            XCTAssertGreaterThan(long.height, short.height * 1.5, "the long line wraps to more lines; it is not cut to one")
            XCTAssertTrue(window.insetBy(dx: -1, dy: -1).contains(long), "the whole line is on the screen: \(long) in \(window)")
            let mute = app.buttons["muteButton"].firstMatch
            XCTAssertTrue(mute.exists && mute.isHittable, "the mute button is still there to press")
            XCTAssertFalse(mute.frame.intersects(long.insetBy(dx: 2, dy: 2)), "and not on top of the words")
            XCTAssertTrue(app.buttons["micRing"].firstMatch.isHittable, "the microphone is still in reach")
            shot("iphone-largest-text-\(dark ? "dark" : "light")")
            app.terminate()
        }
    }
}
