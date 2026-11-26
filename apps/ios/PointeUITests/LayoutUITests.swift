import XCTest

/// Where things sit on the call screen (docs/design/ux-review-ios.md), on the demo call: nothing under the keyboard,
/// nothing off the screen at the largest type, one Hang up, and the labels VoiceOver reads.
@MainActor
final class LayoutUITests: XCTestCase {
    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String, _ more: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-demo", screen] + more
        app.launch()
        XCTAssertTrue(app.buttons["micRing"].waitForExistence(timeout: 20), "the call screen is up")
        return app
    }

    private func text(_ app: XCUIApplication, _ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", fragment)).firstMatch
    }

    private func onScreen(_ app: XCUIApplication, _ element: XCUIElement, _ name: String, file: StaticString = #filePath, line: UInt = #line) {
        let window = app.windows.firstMatch.frame
        XCTAssertTrue(element.exists, "\(name) exists", file: file, line: line)
        XCTAssertGreaterThanOrEqual(element.frame.minX, window.minX - 0.5, "\(name) starts on the screen", file: file, line: line)
        XCTAssertLessThanOrEqual(element.frame.maxX, window.maxX + 0.5, "\(name) ends on the screen", file: file, line: line)
        XCTAssertGreaterThanOrEqual(element.frame.minY, 20, "\(name) is under the status bar, not behind it", file: file, line: line)
        XCTAssertLessThanOrEqual(element.frame.maxY, window.maxY + 0.5, "\(name) is not below the screen", file: file, line: line)
    }

    /// The Sessions sheet's bar holds New session, Add sessions and Done, and its title truncated there to "Ses…" (the
    /// App Store screenshot showed it). The title is the list's first row: whole, under the bar, in line with the switch.
    func testTheSessionsSheetTitleIsWholeOnItsOwnRow() {
        let app = launch("sessions")
        let title = app.descendants(matching: .any)["sessionsTitle"].firstMatch
        XCTAssertTrue(title.waitForExistence(timeout: 15), "the sheet's title row")
        XCTAssertEqual(title.label, "Sessions")
        onScreen(app, title, "the title")
        let bar = app.navigationBars["Sessions"]
        XCTAssertTrue(bar.exists, "the bar keeps the sheet's name")
        XCTAssertGreaterThanOrEqual(title.frame.minY, bar.frame.maxY - 0.5, "the title is under the bar, not squeezed in it")
        let modes = app.descendants(matching: .any)["modePicker"].firstMatch
        XCTAssertTrue(modes.exists)
        XCTAssertEqual(title.frame.minX, modes.frame.minX, accuracy: 1, "in line with the Orchestrator/Session switch")
        XCTAssertLessThanOrEqual(title.frame.maxY, modes.frame.minY + 0.5, "over the switch")
    }

    /// The bug this file started with: with the keyboard up, the type bar sat on the newest bubble.
    func testTheTypeBarAndTheKeyboardNeverCoverTheNewestLine() {
        let app = launch("typing")
        let field = app.descendants(matching: .any)["typeField"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 10), "the type bar is open")
        _ = app.keyboards.firstMatch.waitForExistence(timeout: 5)  // absent with a hardware keyboard: the bar alone must clear the line
        let newest = text(app, "whether the retry")
        XCTAssertTrue(newest.waitForExistence(timeout: 5), "what is being heard is the newest line")
        RunLoop.current.run(until: Date().addingTimeInterval(1.5))  // the keyboard's animation and the scroll that follows it

        XCTAssertLessThanOrEqual(newest.frame.maxY, field.frame.minY + 1, "the newest line ends above the type bar")
        XCTAssertGreaterThan(newest.frame.minY, app.descendants(matching: .any)["statusLine"].firstMatch.frame.maxY - 1,
                             "and starts under the header: all of it shows")
        let ring = app.buttons["micRing"]
        XCTAssertLessThanOrEqual(field.frame.maxY, ring.frame.minY + 1, "the type bar is above the mic")
        if app.keyboards.firstMatch.exists {
            XCTAssertLessThanOrEqual(ring.frame.maxY, app.keyboards.firstMatch.frame.minY + 1, "the mic is above the keyboard")
        }
        onScreen(app, app.buttons["Settings"], "the header")
    }

    /// The same, when a line arrives while the keyboard is already up: closing and reopening the bar keeps the end in view.
    func testOpeningTheTypeBarKeepsTheNewestLineInView() {
        let app = launch("call")
        let newest = text(app, "whether the retry")
        XCTAssertTrue(newest.waitForExistence(timeout: 5))
        app.buttons["Type"].tap()
        let field = app.descendants(matching: .any)["typeField"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        RunLoop.current.run(until: Date().addingTimeInterval(1.5))
        XCTAssertLessThanOrEqual(newest.frame.maxY, field.frame.minY + 1, "the newest line moved up with the bar")
        XCTAssertTrue(newest.isHittable, "and is still on screen")
    }

    /// Accessibility XXXL: the chrome stops growing, so the header stays on the screen and the bar's five controls stay in it.
    func testTheCallScreenFitsAtTheLargestType() {
        let app = launch("request", ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"])
        onScreen(app, app.buttons["Settings"], "the menu")
        onScreen(app, app.buttons["Start a meeting"], "the meeting button")
        onScreen(app, app.descendants(matching: .any)["statusLine"].firstMatch, "the state line")
        for name in ["Brain dump", "Type", "Sessions", "hangUp", "micRing"] {
            onScreen(app, app.buttons[name], name)
            XCTAssertTrue(app.buttons[name].isHittable, "\(name) can be tapped")
        }
        let controls = ["Brain dump", "Type", "micRing", "Sessions", "hangUp"].map { app.buttons[$0].frame }
        for (a, b) in zip(controls, controls.dropFirst()) {
            XCTAssertLessThanOrEqual(a.maxX, b.minX + 0.5, "the bar's controls do not run into each other")
        }
        // The card is taller than the room left: it scrolls above the bar, resting on its buttons, and never pushes the
        // header off the screen. A swipe to find Approve was QA round 5's finding 1.
        answerInReach(app)
        onScreen(app, app.buttons["Settings"], "the menu")
    }

    private func answerInReach(_ app: XCUIApplication, file: StaticString = #filePath, line: UInt = #line) {
        for name in ["Approve", "Deny"] {
            XCTAssertTrue(app.buttons[name].waitForExistence(timeout: 5), "\(name) is there", file: file, line: line)
            onScreen(app, app.buttons[name], name, file: file, line: line)
            XCTAssertTrue(app.buttons[name].isHittable, "\(name) takes a tap without a swipe", file: file, line: line)
            XCTAssertLessThanOrEqual(app.buttons[name].frame.maxY, app.buttons["micRing"].frame.minY, "\(name) is above the bar",
                                     file: file, line: line)
        }
    }

    /// At accessibility XL every card that answers keeps its buttons in reach: the request, a long one, and a conflict.
    func testTheAnswerButtonsNeedNoSwipeAtAccessibilityXL() {
        for screen in ["request", "longRequest", "longNames"] {
            let app = launch(screen, ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXL"])
            answerInReach(app)
            onScreen(app, app.buttons["Settings"], "the menu, on \(screen)")
        }
        let app = launch("conflict", ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXL"])
        let dismiss = app.buttons["Dismiss"]
        XCTAssertTrue(dismiss.waitForExistence(timeout: 5))
        onScreen(app, dismiss, "the conflict's Dismiss")
        XCTAssertTrue(dismiss.isHittable, "Dismiss takes a tap without a swipe")
    }

    /// Drive mode at the largest type: the header stays under the status bar and the bar stays on the screen. Before,
    /// Hang up was at y=787 on a 667-point screen and no swipe reached it.
    func testDriveModeKeepsTheHeaderAndTheBarOnTheScreenAtLargeType() {
        for size in ["UICTContentSizeCategoryL", "UICTContentSizeCategoryAccessibilityXL", "UICTContentSizeCategoryAccessibilityXXXL"] {
            let app = launch("drive", ["-UIPreferredContentSizeCategoryName", size])
            XCTAssertTrue(app.descendants(matching: .any)["driveLine"].firstMatch.waitForExistence(timeout: 10))
            onScreen(app, app.buttons["Settings"], "the menu at \(size)")
            onScreen(app, app.buttons["driveButton"], "the Drive switch at \(size)")
            for name in ["hangUp", "micRing", "Sessions"] {
                onScreen(app, app.buttons[name], "\(name) at \(size)")
                XCTAssertTrue(app.buttons[name].isHittable, "\(name) takes a tap at \(size)")
            }
        }
    }

    /// The empty stage at accessibility XL with the Mac unreachable: drawn in the stage, not over the header, and Try
    /// again in reach.
    func testMacNotReachableStaysInTheStageAtAccessibilityXL() {
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_PAIR"] = "pointe://pair?v=1&host=127.0.0.1&port=1&fp=\(String(repeating: "ab", count: 32))&key=\(String(repeating: "k", count: 40))"
        app.launchArguments = ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXL"]
        app.launch()
        let button = app.buttons["problemTryAgain"]  // a failed connection shows the problem card (ProblemCard)
        XCTAssertTrue(button.waitForExistence(timeout: 20), "the problem card's Try again")
        // At this size the card is taller than the stage, which scrolls: Try again is in reach once scrolled to.
        let dock = app.segmentedControls["micModeSwitch"]
        for _ in 0..<6 where button.frame.maxY > (dock.exists ? dock.frame.minY : app.windows.firstMatch.frame.maxY) {
            app.otherElements["connectionProblem"].swipeUp(velocity: .slow)
        }
        onScreen(app, button, "Try again")
        XCTAssertTrue(button.isHittable, "Try again takes a tap")
        onScreen(app, app.buttons["Settings"], "the menu")
        let line = app.descendants(matching: .any)["statusLine"].firstMatch
        if line.exists, app.staticTexts["connectTitle"].isHittable {
            XCTAssertGreaterThanOrEqual(app.staticTexts["connectTitle"].frame.minY, app.buttons["Settings"].frame.maxY, "the title is under the header")
        }
        XCTAssertFalse(app.buttons["Type"].isEnabled, "with no call, Type waits for one")
    }

    /// The pairing screen at the largest type scrolls: Pair and Try a demo were below the screen, out of reach, and the
    /// demo is App Review's only way in.
    func testThePairingScreenScrollsToItsButtonsAtTheLargestType() {
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_FORGET"] = "1"
        app.launchArguments = ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        app.launch()
        let demo = app.buttons["tryDemo"]
        XCTAssertTrue(demo.waitForExistence(timeout: 15), "the pairing screen")
        let bottom = app.windows.firstMatch.frame.maxY
        for _ in 0..<6 where !(demo.isHittable && demo.frame.maxY <= bottom) { app.swipeUp(velocity: .slow) }
        XCTAssertTrue(demo.isHittable, "Try a demo is reached by scrolling")
        onScreen(app, demo, "Try a demo")
        XCTAssertTrue(app.buttons["Pair"].exists)
        app.tryTheDemo()
        XCTAssertTrue(app.buttons["micRing"].waitForExistence(timeout: 10), "and it opens the demo call")
    }

    /// At large type the command's box gives up its height first: Deny and Approve are on the screen without a scroll.
    /// (On a 4.7-inch phone the card's own words outgrow the dock at these sizes: there the card scrolls, as above.)
    func testAtLargeTypeDenyAndApproveNeedNoScroll() throws {
        for screen in ["request", "longRequest"] {
            let app = launch(screen, ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityL"])
            if app.windows.firstMatch.frame.height < 700 { throw XCTSkip("a 4.7-inch phone: the card scrolls") }
            for name in ["Deny", "Approve"] {
                XCTAssertTrue(app.buttons[name].waitForExistence(timeout: 5), "\(screen): \(name)")
                XCTAssertTrue(app.buttons[name].isHittable, "\(screen): \(name) can be tapped without scrolling")
                XCTAssertLessThanOrEqual(app.buttons[name].frame.maxY, app.buttons["micRing"].frame.minY, "\(screen): \(name) is above the bar")
            }
            XCTAssertLessThan(app.buttons["Approve"].frame.height, 90, "\(screen): Approve is one line, not broken inside the word")
            app.terminate()
        }
    }

    /// Fix it at large text shows every word of what was heard: cut to one line, the text the person is there to check
    /// ended in an ellipsis.
    func testFixItShowsAllOfWhatWasHeardAtLargeType() {
        let app = XCUIApplication()
        app.launchArguments = ["-demo", "edit", "-demoEnglish", "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXL"]
        app.launch()
        let heard = app.staticTexts["fixHeard"], kicker = app.staticTexts.matching(NSPredicate(format: "label ==[c] %@", "heard")).firstMatch
        XCTAssertTrue(heard.waitForExistence(timeout: 20), "the Fix it sheet")
        XCTAssertGreaterThan(heard.frame.height, kicker.frame.height * 1.8, "the heard words wrap instead of being cut to one line")
        let title = app.navigationBars["Fix it"].staticTexts["Fix it"]
        XCTAssertGreaterThan(title.frame.height, 22, "the sheet's title grows with the text too, not fixed at 17 points")
    }

    /// A command of nine lines scrolls in its own box: Deny and Approve stay where the thumb is.
    func testAVeryLongCommandLeavesTheAnswerOnScreen() {
        let app = launch("longRequest")
        for name in ["Deny", "Approve"] {
            XCTAssertTrue(app.buttons[name].waitForExistence(timeout: 5))
            onScreen(app, app.buttons[name], name)
            XCTAssertTrue(app.buttons[name].isHittable, "\(name) can be tapped without scrolling")
            XCTAssertLessThanOrEqual(app.buttons[name].frame.maxY, app.buttons["micRing"].frame.minY, "\(name) is above the bar")
        }
        XCTAssertTrue(text(app, "test_refunds_1.py").exists, "the command is there, word for word")
        onScreen(app, app.buttons["Settings"], "the header")
    }

    /// One Hang up on a live call, and the names VoiceOver reads for the controls, the state and the bubbles.
    func testOneHangUpAndTheLabelsVoiceOverReads() {
        let app = launch("call")
        XCTAssertEqual(app.buttons["hangUp"].label, "Hang up")
        XCTAssertFalse(app.buttons["topConnect"].exists, "no second Hang up in the header while the bar has one")
        XCTAssertEqual(app.buttons["micRing"].label, "Turn mic off")
        for name in ["Settings", "Start a meeting", "Brain dump", "Type", "Sessions"] {
            XCTAssertTrue(app.buttons[name].exists, "\(name) is a named button")
        }
        let line = app.descendants(matching: .any)["statusLine"].firstMatch
        XCTAssertTrue(line.label.contains("Listening") && line.label.contains("Orchestrating 3 sessions"), line.label)
        XCTAssertTrue(app.buttons["All sessions, orchestrator mode, on"].exists, "the All chip says its mode")
        XCTAssertTrue(text(app, "river-lantern, needs you").exists, "a session chip says its name and state")
        XCTAssertTrue(text(app, "Pointe: Docs is on it.").exists, "a reply is read as Pointe's")
        XCTAssertTrue(text(app, "You: ").exists, "a turn of yours is read as yours")
    }

    /// VoiceOver walks the header, then the strip chip by chip, left to right: each chip its own element in the strip's
    /// own container, beside Settings and never inside it, and a plain tap on one lands.
    func testTheSessionChipsAreTheirOwnElementsInStripOrder() {
        let app = launch("call")
        let chips = ["All sessions, orchestrator mode, on", "river-lantern, needs you", "billing/main, working", "docs, idle"]
        let strip = app.scrollViews.containing(.button, identifier: "harnessMark.codex").firstMatch
        XCTAssertTrue(strip.exists && strip.identifier != "conversation", "the chips sit in a strip of their own")
        XCTAssertEqual(strip.buttons.allElementsBoundByIndex.map(\.label), chips, "in strip order")
        let inside = app.buttons["Settings"].descendants(matching: .any).allElementsBoundByIndex.map(\.label).filter { !$0.isEmpty }
        XCTAssertTrue(Set(inside).isDisjoint(with: chips + ["All"]), "no chip is read as part of Settings: \(inside)")
        for chip in chips.prefix(2) { XCTAssertTrue(app.buttons[chip].isHittable, "\(chip) takes a tap") }
        app.buttons["river-lantern, needs you"].tap()
        let line = app.descendants(matching: .any)["statusLine"].firstMatch
        XCTAssertTrue(NSPredicate(format: "label CONTAINS %@", "Focused on river-lantern").wait(for: line, timeout: 5), line.label)
    }

    /// The empty stage keeps its own identifiers: the conversation's must not cover them.
    func testTheEmptyStageKeepsItsIdentifiers() {
        let app = XCUIApplication()
        app.launchEnvironment["POINTE_PAIR"] = "pointe://pair?v=1&host=127.0.0.1&port=1&fp=\(String(repeating: "ab", count: 32))&key=\(String(repeating: "k", count: 40))"
        app.launch()
        let title = app.staticTexts["problemTitle"]
        XCTAssertTrue(NSPredicate(format: "label == %@", "Pointe is not answering").wait(for: title, timeout: 20),
                      "the problem's title by its identifier: \(title.exists ? title.label : "missing")")
        XCTAssertEqual(app.staticTexts["problemDetail"].label, "127.0.0.1 answered, but nothing listens on port 1.")
        XCTAssertEqual(app.buttons["problemTryAgain"].label, "Try again")
        XCTAssertEqual(app.staticTexts["connectHint"].label, "Once connected, tap the keyboard to type", "the type bar is behind the keyboard button")
        XCTAssertTrue(app.scrollViews["conversation"].exists, "the conversation keeps its own")
    }

    /// At the accessibility sizes the request card's agent badge sits under the session's name, which gets the whole
    /// width: beside it, a long name broke inside its words (docs/design/ux-review-ios.md, C7).
    func testALongNameOnTheRequestCardHasTheCardsWidthAtTheLargestType() {
        let app = launch("longNames", ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXL"])
        let name = text(app, "idempotency-keys-for-refunds needs approval")
        // the card's own badge: the session strip's agent mark has the same label
        let badge = app.descendants(matching: .any)["requestAgent"].firstMatch
        XCTAssertTrue(name.waitForExistence(timeout: 10) && badge.exists, "the card and its badge")
        XCTAssertGreaterThanOrEqual(badge.frame.minY, name.frame.maxY - 1, "the badge is under the name, not beside it")
    }

    /// A long session name at the largest sizes made the card taller than the dock even with the command at two lines:
    /// only the tops of Deny and Approve showed. Now what is above them scrolls inside the card, and they stay whole.
    func testALongNameAtTheLargestTypeLeavesDenyAndApproveWhole() {
        let app = launch("longNames", ["-demoEnglish", "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXL"])
        for name in ["Deny", "Approve"] {
            let button = app.buttons[name]
            XCTAssertTrue(button.waitForExistence(timeout: 10), name)
            XCTAssertTrue(button.isHittable, "\(name) can be tapped without scrolling")
            XCTAssertGreaterThan(button.frame.height, 40, "\(name) is whole, not its top edge")
            XCTAssertLessThanOrEqual(button.frame.maxY, app.buttons["micRing"].frame.minY, "\(name) is above the bar")
        }
    }

    /// The header's round buttons are drawn at 36 points and take a 44-point touch: a tap just off the circle still lands.
    func testASmallHeaderButtonTakesATouchBesideIt() {
        let app = launch("call")
        func tapUnder(_ button: XCUIElement) {  // the circle's radius is 18: two points under what is drawn
            button.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).withOffset(CGVector(dx: 0, dy: 20)).tap()
        }
        tapUnder(app.buttons["Start a meeting"])
        XCTAssertTrue(app.navigationBars["Start a meeting"].waitForExistence(timeout: 5), "the meeting sheet opened")
        app.navigationBars["Start a meeting"].buttons["Cancel"].tap()
        XCTAssertTrue(app.navigationBars["Start a meeting"].waitForNonExistence(timeout: 5))
        tapUnder(app.buttons["Settings"])
        XCTAssertTrue(app.navigationBars["Settings"].waitForExistence(timeout: 5), "Settings opened")
    }
}
