import Darwin
import XCTest

/// What the page did and the app now does too, on the -demo fixtures. No Mac needed.
/// Screenshots go to PARITY_SHOTS when it names a folder.
@MainActor
final class ParityUITests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen]
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["PARITY_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    func testSettingsShowTheMacsLocalModeReadOnly() throws {
        launch("call")
        app.openSettings()
        let line = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS %@", "Voice stays on your Mac · models here")).firstMatch
        // A read-only line takes no tap, so settingsItem, which scrolls until its item is hittable, scrolled past it
        // and back: scroll until the line is drawn on the screen.
        let bottom = app.windows.firstMatch.frame.maxY
        for _ in 0..<10 where !(line.exists && line.frame.maxY < bottom) { app.collectionViews.firstMatch.swipeUp(velocity: .slow) }
        shot("settings-local")
        XCTAssertTrue(line.waitForExistence(timeout: 5), "the local mode line is in Settings")
    }

    /// A screenshot for the eye: XCUITest cannot see where a glyph lands. Hebrew and Arabic end at the left edge.
    func testRightToLeftMessagesSnapshot() throws {
        launch("rtl")
        let bot = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "הבדיקות עוברות")).firstMatch
        XCTAssertTrue(bot.waitForExistence(timeout: 15))
        shot("rtl-conversation")
    }

    /// The Sessions sheet opens at half height: on an SE its lazy list has not drawn the lower rows yet. Pull it up.
    private func expandSessionsSheet() {
        let bar = app.navigationBars["Sessions"]
        XCTAssertTrue(bar.waitForExistence(timeout: 15))
        let top = app.windows.firstMatch.frame.height * 0.2
        for _ in 0..<4 where bar.frame.minY > top {  // a swipe now and then only scrolls: until the sheet is full height
            bar.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
                .press(forDuration: 0.1, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.02)))
            sleep(1)
        }
        XCTAssertLessThanOrEqual(bar.frame.minY, top, "the Sessions sheet is full height")
    }

    func testDisconnectingASessionAsksFirst() throws {
        launch("sessions")
        expandSessionsSheet()
        let row = app.cells.containing(.staticText, identifier: "docs").firstMatch  // the sheet's row, not the chip under it
        XCTAssertTrue(row.waitForExistence(timeout: 15))
        row.swipeLeft()
        app.buttons["Disconnect"].firstMatch.tap()
        let ask = app.staticTexts["Disconnect docs from the voice? It keeps running in its terminal."]
        XCTAssertTrue(ask.waitForExistence(timeout: 5), "a swipe asks before it disconnects")
        shot("disconnect-confirm")
        // outside the popover: cancel. The region that dismisses it covers the screen; above the popover is the status
        // bar on a tall iPhone, where a tap reaches nothing.
        let outside = app.otherElements["PopoverDismissRegion"]
        if outside.exists {
            outside.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.9)).tap()
        } else {
            app.coordinate(withNormalizedOffset: .zero).withOffset(CGVector(dx: ask.frame.midX, dy: max(30, ask.frame.minY - 80))).tap()
        }
        XCTAssertTrue(ask.waitForNonExistence(timeout: 5))
        XCTAssertTrue(row.exists, "Cancel keeps the session")
    }

    func testTheSessionsSheetShowsRecentRequestsAndTheContextCount() throws {
        launch("sessions")
        expandSessionsSheet()
        XCTAssertTrue(app.staticTexts["Recent requests"].waitForExistence(timeout: 15) || app.otherElements["Recent requests"].exists)
        app.swipeUp()
        let routed = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", "→ docs (named)")).firstMatch
        XCTAssertTrue(routed.waitForExistence(timeout: 5), "where the request went")
        XCTAssertTrue(app.descendants(matching: .any)["contextTokens"].waitForExistence(timeout: 5))
        shot("sessions-recent")
    }

    /// The mic is the call's one primary control: in the middle of the screen, in every state (owner's 1.0 feedback).
    /// Screenshots of each state, per device, go to PARITY_SHOTS for the eye.
    func testTheMicSitsInTheMiddleInEveryState() throws {
        let device = (ProcessInfo.processInfo.environment["SIMULATOR_DEVICE_NAME"] ?? "device").replacingOccurrences(of: " ", with: "-")
        var off: [String] = []
        func measure(_ name: String) {
            let mic = app.buttons.matching(NSPredicate(format: "label IN %@", ["Turn mic off", "Turn mic on", "Microphone", "Talking", "Hold to talk"])).firstMatch
            XCTAssertTrue(mic.waitForExistence(timeout: 15), name)
            shot("mic-\(device)-\(name)")
            let width = app.windows.firstMatch.frame.width
            let gap = mic.frame.midX - width / 2
            if abs(gap) > 1 { off.append("\(name): \(Int(gap)) pt from the middle") }
        }
        for screen in ["call", "talking", "meeting", "machines", "drive"] {
            launch(screen)
            measure(screen)
        }
        app.buttons["driveButton"].firstMatch.tap()  // drive mode off: the bar the Mac's 1.0 shows most of the time
        sleep(1)
        measure("drive-off")
        XCTAssertTrue(off.isEmpty, off.joined(separator: "; "))
    }

    func testASessionChipCanBeRenamed() throws {
        launch("call")
        let chip = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "river-lantern")).firstMatch
        XCTAssertTrue(chip.waitForExistence(timeout: 15))
        chip.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).press(forDuration: 1.2)  // under the header material: not "hittable", still on screen
        app.buttons["Rename"].firstMatch.tap()
        let field = app.alerts.textFields.firstMatch
        let opened = field.waitForExistence(timeout: 5)
        shot("rename")
        XCTAssertTrue(opened, "the rename box opens")
        XCTAssertEqual(field.value as? String, "river-lantern", "with the current name")
        app.alerts.buttons["Cancel"].tap()
        XCTAssertTrue(field.waitForNonExistence(timeout: 5))
    }

    // MARK: machines (docs/design/multi-machine.md, "iPhone app"), on the -demo machines fixtures

    private func label(_ text: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

    private func chip(_ name: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", name + ",")).firstMatch
    }

    /// docs/design/brand-v6.md, section 9: the Sessions sheet groups by named machine, and each row says its agent.
    func testTheSessionsSheetGroupsByMachineAndMarksEachSessionsAgent() throws {
        launch("machinesSessions")
        XCTAssertTrue(any("machineSection.studio").waitForExistence(timeout: 15))
        XCTAssertTrue(any("machineChip.devbox").exists, "the machine filter is in the sheet")
        XCTAssertTrue(label("runs on Claude").exists && label("runs on Codex").exists, "a harness mark on each row")
        shot("machines-sessions")
        app.swipeUp()  // a list draws its rows as they come on screen
        XCTAssertTrue(any("machineSection.devbox").waitForExistence(timeout: 5))
        XCTAssertTrue(any("machineSection.devbox").label.contains("devbox · Linux · 23 ms"))
        XCTAssertTrue(label("runs on OpenCode").waitForExistence(timeout: 5))
        XCTAssertTrue(any("machineSection.laptop").waitForExistence(timeout: 5))
    }

    func testOneMachineHasOneSectionAndNoMachineHeader() throws {
        launch("sessions")
        XCTAssertTrue(app.staticTexts["On the voice"].waitForExistence(timeout: 15))
        XCTAssertFalse(any("machineSection.studio").exists)
        XCTAssertTrue(label("runs on Codex").exists, "the mark shows with one machine too")
    }

    /// Appearance is in Settings with the page's three choices; System is the one in force until another is picked.
    func testSettingsOfferSystemLightAndDark() throws {
        launch("call")
        let item = app.settingsItem("appearanceSetting", .button)
        XCTAssertTrue(item.waitForExistence(timeout: 5), "Appearance is in Settings")
        XCTAssertTrue(item.label.contains("Appearance"), item.label)
        item.tap()
        for choice in ["System", "Light", "Dark"] {
            XCTAssertTrue(app.buttons[choice].waitForExistence(timeout: 5), choice)
        }
        shot("settings-appearance")
        app.buttons["System"].tap()
    }

    /// The machine filter lives in the Sessions sheet (one row of chips on the call screen): open it, pick, close it.
    private func filterMachine(_ id: String) {
        app.buttons["Sessions"].firstMatch.tap()
        XCTAssertTrue(any("machineChip.\(id)").waitForExistence(timeout: 10), "the filter is in the Sessions sheet")
        any("machineChip.\(id)").tap()
        app.buttons["Done"].firstMatch.tap()
        XCTAssertTrue(any("machineChip.\(id)").waitForNonExistence(timeout: 5))
    }

    func testOneMachineShowsNoMachineChipsOrBadges() throws {
        launch("machinesOne")
        XCTAssertTrue(chip("billing/main").waitForExistence(timeout: 15))
        XCTAssertFalse(any("machineDivider.studio").exists, "no machine divider with one machine")
        app.buttons["Sessions"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["On the voice"].waitForExistence(timeout: 10))
        XCTAssertFalse(any("machineChip.all").exists, "no filter with one machine")
        XCTAssertFalse(label("on studio").exists, "no machine badge with one machine")
        shot("machines-one")
    }

    func testMachineChipsFilterTheSessionsAndSendNothing() throws {
        launch("machines")
        XCTAssertTrue(chip("billing/main").waitForExistence(timeout: 15))
        XCTAssertFalse(any("machineChip.all").exists, "one row of chips on the call screen: no machine filter there")
        for name in ["studio", "devbox", "laptop"] { XCTAssertTrue(any("machineDivider.\(name)").exists, "the strip is grouped by \(name)") }
        app.buttons["Sessions"].firstMatch.tap()
        for id in ["all", "studio", "devbox", "laptop"] {
            XCTAssertTrue(any("machineChip.\(id)").waitForExistence(timeout: 10), id)
        }
        app.buttons["Done"].firstMatch.tap()
        XCTAssertTrue(chip("shop devbox, on devbox").exists, "a machine badge on each chip while machines mix")
        XCTAssertTrue(label("Orchestrating 6 sessions · 2 need you").exists)
        shot("machines-all")
        filterMachine("devbox")
        XCTAssertTrue(chip("billing/main").waitForNonExistence(timeout: 5), "devbox only")
        XCTAssertTrue(chip("api").exists)
        XCTAssertTrue(label("Orchestrating 3 sessions on devbox · 2 need you").waitForExistence(timeout: 5), "the line is filtered too")
        XCTAssertTrue(app.buttons["All sessions, orchestrator mode, on"].exists, "a chip changes no mode")
        shot("machines-filter-devbox")
        filterMachine("all")
        XCTAssertTrue(chip("billing/main").waitForExistence(timeout: 5))
    }

    func testAnOfflineSessionIsDimmedAndSaysSo() throws {
        launch("machines")
        let notes = chip("notes")
        XCTAssertTrue(notes.waitForExistence(timeout: 15))
        XCTAssertTrue(notes.label.contains("on laptop") && notes.label.contains("offline"), notes.label)
        XCTAssertTrue(any("machineDivider.laptop").label.contains("offline"))
    }

    func testTheApprovalCardSaysShopDotDevbox() throws {
        launch("machines")
        XCTAssertTrue(label("shop · devbox needs approval").waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["Approve"].exists && app.buttons["Deny"].exists)
        shot("machines-request")
    }

    func testTheDriveCardSaysShopDotDevboxToo() throws {
        launch("machinesDrive")
        let card = any("driveRequest")
        XCTAssertTrue(card.waitForExistence(timeout: 15))
        XCTAssertTrue(card.label.contains("shop · devbox needs approval"), card.label)
        shot("machines-drive")
    }

    func testAnOfflineRequestHasNoApproveOrDeny() throws {
        launch("machinesOffline")
        XCTAssertTrue(label("notes · laptop needs approval").waitForExistence(timeout: 15))
        XCTAssertTrue(any("requestOffline").exists, "offline: answer it in its terminal")
        XCTAssertFalse(app.buttons["Approve"].exists)
        XCTAssertFalse(app.buttons["Deny"].exists)
        shot("machines-offline-request")
    }

    func testAChipOpensTheSessionsSheetOnItsMachine() throws {
        launch("machines")
        XCTAssertTrue(chip("billing/main").waitForExistence(timeout: 15))
        filterMachine("laptop")  // the strip scrolls: on its own machine, the chip is on screen
        let notes = chip("notes")
        XCTAssertTrue(notes.waitForExistence(timeout: 5))
        notes.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).press(forDuration: 1.2)
        app.buttons["Sessions on laptop"].firstMatch.tap()
        XCTAssertTrue(any("machineChip.all").waitForExistence(timeout: 5))
        any("machineChip.all").tap()  // every machine again: the one asked for still comes first
        let section = any("machineSection.laptop")
        XCTAssertTrue(section.waitForExistence(timeout: 5))
        let studio = any("machineSection.studio")
        XCTAssertTrue(studio.waitForExistence(timeout: 5))
        XCTAssertLessThan(section.frame.minY, studio.frame.minY, "the laptop's section comes first")
        XCTAssertTrue(label("offline since").exists)
        shot("machines-sheet-laptop")
        for name in ["studio", "devbox"] { XCTAssertTrue(any("machineSection.\(name)").exists, name) }
    }

    func testAHebrewSessionNameOnAMachine() throws {
        launch("machines")
        XCTAssertTrue(chip("billing/main").waitForExistence(timeout: 15))
        filterMachine("devbox")
        let hebrew = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "חנות")).firstMatch
        XCTAssertTrue(hebrew.waitForExistence(timeout: 5), app.buttons.allElementsBoundByIndex.map(\.label).joined(separator: " | "))
        shot("machines-rtl")
    }

    // Face ID in the simulator: enrol, then match or not, through the simulator's own notifications.
    // notify(3) is not in Swift's Darwin module: looked up by name.
    private func openMachines() {
        app.settingsItem("machinesItem", .button).tap()
        XCTAssertTrue(any("machine.devbox").waitForExistence(timeout: 5))
        if !any("inviteMachine").exists { app.swipeUp() }  // a small screen: the invite sits under the list
    }

    func testSettingsMachinesListsEachMachine() throws {
        launch("machines")
        openMachines()
        XCTAssertTrue(label("studio (this Mac)").exists)
        XCTAssertTrue(label("Linux · online · 23 ms · 3 sessions · key 3f2a9c41d07be215").exists)
        XCTAssertTrue(label("macOS · offline since").exists)
        XCTAssertFalse(any("revoke.studio").exists, "this Mac cannot be revoked")
        XCTAssertTrue(any("revoke.devbox").exists)
        shot("settings-machines")
    }

    func testInvitingAMachineNeedsFaceIDThenShowsTheCodeCountingDown() throws {
        Biometry.enrol()
        launch("machines")
        openMachines()
        any("inviteMachine").tap()
        Biometry.allowFaceID()
        sleep(1)
        XCTAssertFalse(any("inviteCode").exists, "no code before Face ID")
        Biometry.match(false)
        sleep(2)
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        if springboard.buttons["Cancel"].firstMatch.exists { springboard.buttons["Cancel"].firstMatch.tap() }
        XCTAssertTrue(any("inviteCode").waitForNonExistence(timeout: 3), "a failed Face ID shows no code")
        any("inviteMachine").tap()
        sleep(1)
        Biometry.match(true)
        let code = any("inviteCode")
        XCTAssertTrue(code.waitForExistence(timeout: 10), "the code after Face ID")
        XCTAssertEqual(code.label, "K7PQ-2MXD")
        XCTAssertTrue(label("pointe node join 'pointe://hub?v=1&host=demo.invalid&port=7443").exists, "the whole line to paste")
        let first = any("inviteCountdown").label
        XCTAssertTrue(first.range(of: #"^Expires in (10:00|9:[3-5][0-9])$"#, options: .regularExpression) != nil,
                      "about ten minutes (a slow simulator takes a few seconds to read it): \(first)")
        sleep(2)
        let later = any("inviteCountdown").label
        XCTAssertNotEqual(first, later, "it counts down")
        shot("settings-machines-invite")
        any("cancelInvite").tap()
        XCTAssertTrue(any("inviteMachine").waitForExistence(timeout: 5), "Cancel withdraws the code")
    }

    func testRevokingAMachineAsksThenNeedsFaceID() throws {
        Biometry.enrol()
        launch("machines")
        openMachines()
        any("revoke.devbox").tap()
        XCTAssertTrue(label("Revoke devbox? Its sessions leave the voice").waitForExistence(timeout: 5), "it asks first")
        shot("settings-machines-revoke")
        any("confirmRevoke").tap()
        Biometry.allowFaceID()
        sleep(1)
        XCTAssertTrue(any("machine.devbox").exists, "nothing revoked before Face ID")
        Biometry.match(true)
        XCTAssertTrue(any("machinesDone").waitForExistence(timeout: 10))
        XCTAssertTrue(any("machine.devbox").waitForNonExistence(timeout: 5), "revoked")
    }
}
