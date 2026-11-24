import XCTest

/// Meeting mode, driven by apps/ios/e2e/meeting_ui.py. Every test here runs only when TEST_RUNNER_MEETING_SHOTS names a
/// folder (screenshots and the cue files the driver and this test hand each other); tests/e2e/ios_app.py skips them.
/// - testMeetingEndToEnd: a real test daemon, the call held by a fake browser playing a synthetic room.
/// - testOlderMac, testNoSonioxKey, testMacUnreachable: apps/ios/e2e/fake_mac.py in the daemon's place.
/// - testDemoScreens: the -demo fixtures, for the accessibility audit and the screenshots.
@MainActor
final class MeetingUITests: XCTestCase {
    private var shots = ""
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func ready(pair: Bool = true) throws {
        let env = ProcessInfo.processInfo.environment
        guard let folder = env["MEETING_SHOTS"] else { throw XCTSkip("meeting: set TEST_RUNNER_MEETING_SHOTS") }
        shots = folder
        app = XCUIApplication()
        if pair { app.launchEnvironment["POINTE_PAIR"] = try XCTUnwrap(env["POINTE_PAIR"], "set TEST_RUNNER_POINTE_PAIR") }
    }

    private func shot(_ name: String) {
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(shots)/\(name).png"))
    }

    /// Tells the driver a step is done.
    private func cue(_ name: String) { FileManager.default.createFile(atPath: "\(shots)/cue-\(name)", contents: Data()) }

    /// Waits for the driver.
    private func await(_ name: String, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if FileManager.default.fileExists(atPath: "\(shots)/go-\(name)") { return true }
            Thread.sleep(forTimeInterval: 0.5)
        }
        return false
    }

    /// The element tree, for a step that did not find what it looked for.
    private func dump(_ name: String) {
        try? app.debugDescription.write(toFile: "\(shots)/tree-\(name).txt", atomically: true, encoding: .utf8)
        shot("fail-\(name)")
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    private func text(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] %@", fragment)).firstMatch
    }

    /// Taps a button in the notes once it is clear of the controls at the bottom. The notes scroll under them, and a tap
    /// on a note's button down there lands on the control above it (Ask, which opens the keyboard) instead.
    private func tapInNotes(_ button: XCUIElement) {
        let controls = app.buttons["meetingModeToggle"]
        for _ in 0..<8 where controls.exists && button.frame.maxY > controls.frame.minY - 24 {
            let from = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.55))  // a short drag: a swipe can push it under the banner
            from.press(forDuration: 0.1, thenDragTo: from.withOffset(CGVector(dx: 0, dy: -140)))
        }
        button.tap()
    }

    /// A speaker suggestion with exactly this label (its buttons are part of it while it is open).
    private func row(_ label: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "identifier == 'note-speaker' AND label == %@", label)).firstMatch
    }

    private func menu(_ item: String) {
        let button = app.settingsItem(item, .button)
        XCTAssertTrue(button.waitForExistence(timeout: 5), "Settings item \(item)")
        pick(button)
    }

    /// A tap on a menu item while the menu is still opening is dropped, and the menu stays up: tap until it closes.
    private func pick(_ item: XCUIElement) {
        for _ in 0..<3 {
            item.tap()
            if item.waitForNonExistence(timeout: 3) { return }
        }
    }

    /// Scrolls the sheet until the element is on screen: a long summary pushes the export far down.
    @discardableResult
    private func reveal(_ element: XCUIElement) -> XCUIElement {
        for _ in 0..<12 where !(element.exists && element.isHittable) { app.swipeUp(velocity: .slow) }
        return element
    }

    private func toggle(_ element: XCUIElement) {
        let inner = element.switches.firstMatch
        (inner.exists ? inner : element).tap()
    }

    private func startSheet(linking session: String? = nil) {
        let start = app.buttons["startMeeting"]
        XCTAssertTrue(start.waitForExistence(timeout: 30), "the meeting button is in the top bar")
        start.tap()
        XCTAssertTrue(any("meetingBrief").waitForExistence(timeout: 10), "the start sheet")
    }

    private func consentAndStart() {
        let consent = app.switches["meetingConsent"]
        XCTAssertTrue(consent.waitForExistence(timeout: 15), "the consent step")
        let begin = app.buttons["meetingStart"]
        XCTAssertFalse(begin.isEnabled, "no start without consent")
        toggle(consent)
        XCTAssertTrue(begin.isEnabled, "consent given")
        begin.tap()
        XCTAssertTrue(any("meetingBanner").waitForExistence(timeout: 20), "the recording banner")
    }

    private func longPress(_ fragment: String, then item: String) {
        let line = text(fragment)
        XCTAssertTrue(line.waitForExistence(timeout: 30), "the transcript shows: \(fragment)")
        line.press(forDuration: 1.2)
        let button = app.buttons[item].firstMatch
        XCTAssertTrue(button.waitForExistence(timeout: 5), "\(item) in the menu")
        pick(button)
        if button.exists { dump("menu-\(item)") }
        shot("pressed-\(fragment.prefix(12))")
    }

    private func end() {
        app.buttons["endMeeting"].tap()
        let confirm = app.buttons["End meeting"].firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 10), "ending asks first")
        confirm.tap()
        XCTAssertTrue(app.navigationBars["Meeting ended"].waitForExistence(timeout: 180), "the end sheet, from the Mac's summary")
    }

    // MARK: real daemon

    func testMeetingEndToEnd() throws {
        try ready()
        guard ProcessInfo.processInfo.environment["MEETING_CASE"] == "real" else { throw XCTSkip("the real-daemon case") }
        app.launch()

        // Settings: saved on the Mac, read back from it.
        XCTAssertTrue(app.buttons["startMeeting"].waitForExistence(timeout: 30))
        menu("Meeting settings")
        let notesIn = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Notes in")).firstMatch
        if !notesIn.waitForExistence(timeout: 10) { dump("settings") }
        XCTAssertTrue(notesIn.exists, "the settings loaded from the Mac")
        notesIn.tap()
        app.buttons["English"].firstMatch.tap()
        shot("01-settings")
        app.buttons["Done"].tap()
        cue("prefs-set")
        XCTAssertTrue(self.await("prefs-checked", timeout: 30))
        menu("Meeting settings")
        if !text("English").waitForExistence(timeout: 10) { dump("settings-reopen") }
        XCTAssertTrue(text("English").exists, "reopened: the value came back from the Mac")
        app.buttons["Done"].tap()

        // Start: mode, a linked session, the brief, then the consent step.
        startSheet()
        XCTAssertTrue(any("meetingMode-listening").isSelected, "listening by default")
        toggle(app.switches["pricing"])
        let brief = any("meetingBrief")
        brief.tap()
        brief.typeText("Weekly sync on the checkout pricing launch.")
        shot("02-start")
        app.buttons["meetingContinue"].tap()
        XCTAssertTrue(app.staticTexts["Soniox"].waitForExistence(timeout: 10), "it names the vendor that gets the room audio")
        shot("03-consent")
        consentAndStart()
        cue("started")
        shot("04-banner")

        // A suggested name: Ignore the first, use the next. Each check follows the one suggestion tapped: another can be
        // open at the same time.
        let open = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier == 'note-speaker' AND label CONTAINS 'Use this name'")).firstMatch
        if open.waitForExistence(timeout: 180) {
            shot("05-suggestion")
            let ignored = open.label
            tapInNotes(open.buttons["Ignore"])
            if !row(ignored).waitForNonExistence(timeout: 10) { dump("ignore") }
            XCTAssertFalse(row(ignored).exists, "an ignored suggestion goes away")
            cue("ignored")
            if open.waitForExistence(timeout: 150) {
                let accepted = open.label
                tapInNotes(open.buttons["Use this name"])
                if !row(accepted).waitForNonExistence(timeout: 10) { dump("accept") }
                XCTAssertFalse(row(accepted).exists, "an accepted suggestion is done")
                cue("accepted")
            } else { cue("no-second-suggestion") }
        } else { cue("no-suggestion") }
        XCTAssertTrue(self.await("room-done", timeout: 300))
        shot("06-notes")

        // Filters, the transcript, and "That was me" both ways.
        app.buttons["notesFilter-Questions"].tap()
        shot("07-questions")
        app.buttons["notesFilter-Transcript"].tap()
        longPress("goes live on Thursday", then: "That was me")
        cue("me-dana")
        XCTAssertTrue(self.await("me-dana-checked", timeout: 30))
        shot("08-transcript")
        longPress("move on", then: "That was me")
        cue("me-back")
        XCTAssertTrue(self.await("me-back-checked", timeout: 30))
        app.buttons["notesFilter-All"].tap()

        // A typed question to Pointe: answered in the notes, never aloud.
        app.buttons["Ask"].tap()
        let field = any("typeField")
        XCTAssertTrue(field.waitForExistence(timeout: 5))
        field.typeText("what's waiting for me\n")
        if !text("waiting on you").waitForExistence(timeout: 30) { dump("asked") }
        XCTAssertTrue(text("waiting on you").exists, "the answer arrives as a note")
        shot("09-asked")
        app.buttons["Ask"].tap()
        cue("asked")

        // Look up: only on the tap.
        let lookUp = app.buttons["lookUp"].firstMatch
        if lookUp.waitForExistence(timeout: 60) {
            cue("lookup-ready")
            XCTAssertTrue(self.await("lookup-go", timeout: 30))
            tapInNotes(lookUp)
            cue("lookup-tapped")
            XCTAssertTrue(any("note-answer").waitForExistence(timeout: 240), "the answer arrives as a note")
            shot("10-answer")
        } else { cue("no-lookup") }

        // Participating: three hands, answered three ways.
        app.buttons["meetingModeToggle"].tap()
        cue("participating")
        let later = app.buttons["handLater"]
        XCTAssertTrue(later.waitForExistence(timeout: 240), "a raised hand")
        shot("11-hand")
        later.tap()
        XCTAssertTrue(any("handCard").waitForNonExistence(timeout: 15), "Not now puts it down")
        cue("later")
        let type = app.buttons["handType"]
        if type.waitForExistence(timeout: 240) {
            type.tap()
            XCTAssertTrue(any("handCard").waitForNonExistence(timeout: 15))
            cue("typed")
        } else { cue("no-hand-type") }
        let speak = app.buttons["handSpeak"]
        if speak.waitForExistence(timeout: 240) {
            speak.tap()
            XCTAssertTrue(any("handCard").waitForNonExistence(timeout: 20))
            cue("spoke")
        } else { cue("no-hand-speak") }

        // Both ways, while the driver drops and restores the call.
        XCTAssertTrue(self.await("modes", timeout: 300))
        app.buttons["meetingModeToggle"].tap()
        cue("listening")
        XCTAssertTrue(self.await("listening-checked", timeout: 30))
        app.buttons["meetingModeToggle"].tap()
        cue("participating-again")

        // End while a hand is up, if one comes.
        if any("handCard").waitForExistence(timeout: 150) { shot("12-hand-at-end"); cue("end-with-hand") } else { cue("end-no-hand") }
        end()
        cue("ended")
        sleep(2)
        shot("13-end")

        // Export: share with the transcript, save on the Mac, send the action items.
        let withTranscript = reveal(app.switches["exportTranscript"])
        toggle(withTranscript)
        let share = app.buttons["meetingShare"]
        XCTAssertTrue(share.waitForExistence(timeout: 5))
        let enabled = NSPredicate(format: "isEnabled == true")
        expectation(for: enabled, evaluatedWith: share)
        waitForExpectations(timeout: 15)
        share.tap()
        // The share sheet can take seconds to come up. Never tap a "Close" before it is there: the end sheet has one too.
        let sheet = app.otherElements["ActivityListView"]
        if sheet.waitForExistence(timeout: 15) {
            shot("14-share")
            let closeShare = sheet.buttons["Close"]
            if closeShare.exists { closeShare.tap() } else { app.swipeDown(velocity: .fast) }
            if !sheet.waitForNonExistence(timeout: 10) { dump("share") }
        } else { dump("share-none") }
        XCTAssertTrue(app.navigationBars["Meeting ended"].waitForExistence(timeout: 5), "back on the end sheet after sharing")
        reveal(app.buttons["meetingSave"]).tap()
        if !text("Saved:").waitForExistence(timeout: 20) { dump("saved") }
        XCTAssertTrue(text("Saved:").exists, "saved on the Mac")
        cue("saved")
        let send = reveal(app.buttons["meetingSend"].firstMatch)
        if send.exists {
            send.tap()
            app.buttons["pricing"].firstMatch.tap()
            let confirmSend = app.alerts.buttons["Send"]
            XCTAssertTrue(confirmSend.waitForExistence(timeout: 5), "sending asks first")
            shot("15-send-confirm")
            confirmSend.tap()
            XCTAssertTrue(text("Asked pricing").waitForExistence(timeout: 40), "sent")
            cue("sent")
        } else { cue("no-action-items") }
        shot("16-exported")

        // Close, come back from the menu, discard.
        app.navigationBars["Meeting ended"].buttons["Close"].tap()
        XCTAssertTrue(app.buttons["startMeeting"].waitForExistence(timeout: 10))
        menu("The meeting that ended")
        XCTAssertTrue(app.navigationBars["Meeting ended"].waitForExistence(timeout: 10), "the end sheet comes back")
        reveal(app.buttons["meetingDiscard"]).tap()
        let discard = app.buttons["Discard"].firstMatch
        XCTAssertTrue(discard.waitForExistence(timeout: 5), "discarding asks first")
        discard.tap()
        XCTAssertTrue(app.navigationBars["Meeting ended"].waitForNonExistence(timeout: 10))
        cue("discarded")

        // A second meeting: its own end sheet shows too.
        startSheet()
        app.buttons["meetingContinue"].tap()
        consentAndStart()
        end()
        shot("17-second-end")
        reveal(app.buttons["meetingDiscard"]).tap()
        app.buttons["Discard"].firstMatch.tap()
        cue("second-done")
    }

    // MARK: fake Mac

    func testOlderMac() throws {
        try ready()
        guard ProcessInfo.processInfo.environment["MEETING_CASE"] == "old" else { throw XCTSkip("the older-Mac case") }
        app.launch()
        startSheet()
        app.buttons["meetingContinue"].tap()
        XCTAssertTrue(text("too old for meeting mode").waitForExistence(timeout: 15), "says why, instead of a dead end")
        XCTAssertFalse(app.switches["meetingConsent"].exists, "no consent step without the Mac's vendors")
        shot("20-older-mac")
        app.buttons["Cancel"].tap()
        menu("Meeting settings")
        XCTAssertTrue(text("did not send its meeting settings").waitForExistence(timeout: 15), "no endless spinner")
        shot("21-older-mac-settings")
    }

    func testNoSonioxKey() throws {
        try ready()
        guard ProcessInfo.processInfo.environment["MEETING_CASE"] == "nosoniox" else { throw XCTSkip("the no-Soniox case") }
        app.launch()
        startSheet()
        app.buttons["meetingContinue"].tap()
        XCTAssertTrue(text("needs a Soniox key").waitForExistence(timeout: 15), "the reason is shown")
        toggle(app.switches["meetingConsent"])
        XCTAssertFalse(app.buttons["meetingStart"].isEnabled, "Start stays off without the key")
        shot("22-no-soniox")
    }

    func testMacUnreachable() throws {
        try ready()
        guard ProcessInfo.processInfo.environment["MEETING_CASE"] == "meeting" else { throw XCTSkip("the unreachable case") }
        app.launch()
        XCTAssertTrue(any("meetingBanner").waitForExistence(timeout: 30), "a meeting on the Mac shows on the phone")
        XCTAssertTrue(text("Who owns the rollout checklist").waitForExistence(timeout: 15))
        cue("seen")
        XCTAssertTrue(any("meetingUnreachable").waitForExistence(timeout: 40), "says the Mac is not answering")
        shot("23-unreachable")
        cue("unreachable-seen")
        XCTAssertTrue(any("meetingUnreachable").waitForNonExistence(timeout: 40), "back when it answers")
        XCTAssertTrue(text("Send the rollout checklist").waitForExistence(timeout: 20), "the notes catch up")
        shot("24-caught-up")
    }

    // MARK: what the voice does on the Mac

    /// fake_mac.py's voice case, one step at a time: each is something the owner said on the Mac (a start and its yes, a
    /// rename, a focus, two closes, back to orchestrator mode, the meeting's mode, the end, the spoken send), and the phone
    /// must show it from the status alone, with nothing tapped here.
    func testFollowsWhatTheVoiceDoes() throws {
        try ready()
        guard ProcessInfo.processInfo.environment["MEETING_CASE"] == "voice" else { throw XCTSkip("the voice case") }
        app.launch()
        func chip(_ name: String) -> XCUIElement {
            app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "\(name),")).firstMatch
        }
        let all = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "All sessions")).firstMatch
        let toggle = app.buttons["meetingModeToggle"]
        let steps: [(String, () -> Bool)] = [
            ("the three sessions", { chip("billing").exists && chip("docs").exists && chip("shop").exists }),
            ("a session Pointe is starting shows at once, in sight", {
                let chip = self.any("startingChip.shop-2")
                return chip.exists && self.app.windows.firstMatch.frame.contains(chip.frame)
            }),
            ("it joined", { chip("shop-2").exists && !self.any("startingChip.shop-2").exists }),
            ("renamed by voice", { chip("shop-tests").exists && !chip("shop-2").exists }),
            ("“switch to billing” focuses on it", { chip("billing").label.contains("focused") && !all.label.hasSuffix(", on") }),
            ("“close docs”", { !chip("docs").exists && chip("shop-tests").exists }),
            ("“close all except billing and shop”", { !chip("shop-tests").exists && chip("billing").exists && chip("shop").exists }),
            ("“go back to orchestrator mode”", { all.label.hasSuffix(", on") && !chip("billing").label.contains("focused") }),
            ("a meeting, listening", { self.any("meetingBanner").exists && toggle.label.contains("Listening") }),
            ("“Pointe, join in”", { toggle.label.contains("Participating") }),
            ("the end, and the spoken send read back", {
                self.any("meetingEndSheet").exists && self.any("meetingSent").label.hasPrefix("Pointe asked: “Send 2 action items to billing")
            }),
            ("the yes: where they went", { self.any("meetingSent").label == "Asked billing to take them." }),
        ]
        for (n, (name, shown)) in steps.enumerated() {
            XCTAssertTrue(self.await("step-\(n)", timeout: n == 0 ? 120 : 60), "the driver moved to step \(n)")
            let deadline = Date().addingTimeInterval(10)
            var seen = shown()
            while !seen && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.3)
                seen = shown()
            }
            if !seen { dump("voice-\(n)") }
            XCTAssertTrue(seen, "step \(n): \(name)")
            shot("voice-\(n)")
            cue("step-\(n)")
        }
    }

    // MARK: demo fixtures

    func testDemoScreens() throws {
        try ready(pair: false)
        guard ProcessInfo.processInfo.environment["MEETING_CASE"] == "demo" else { throw XCTSkip("the demo case") }
        let size = ProcessInfo.processInfo.environment["MEETING_TYPE_SIZE"]
        for screen in ["meeting", "meetingHand", "meetingEnd", "meetingStart"] {
            app.launchArguments = ["-demo", screen] + (size.map { ["-UIPreferredContentSizeCategoryName", $0] } ?? [])
            app.launch()
            sleep(2)
            shot("demo-\(screen)\(size == nil ? "" : "-largest")")
            if size == nil {
                try app.performAccessibilityAudit(for: [.sufficientElementDescription, .hitRegion, .elementDetection]) { issue in
                    // SwiftUI's own sheet grabber and system chrome are not ours to label.
                    issue.element?.identifier.isEmpty == true && issue.element?.label.isEmpty == true
                        && issue.element?.elementType == .other
                }
            }
            app.terminate()
        }
        app.launchArguments = ["-demo", "meetingStart", "-noSoniox"]
        app.launch()
        app.buttons["meetingContinue"].tap()
        XCTAssertTrue(text("needs a Soniox key").waitForExistence(timeout: 5))
        shot("demo-no-soniox")
    }
}
