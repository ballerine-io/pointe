import XCTest

/// People and machines (docs/design/people-and-machines.md), on the -demo people fixtures. No Mac needed.
/// Screenshots go to PARITY_SHOTS when it names a folder.
@MainActor
final class PeopleUITests: XCTestCase {
    private var app: XCUIApplication!
    /// Demo.machineLine: the line Avi would send.
    private let line = "pointe://machine?v=1&host=avi-box.invalid&port=7443&fp=\(String(repeating: "0", count: 64))&code=M4RT-9WXZ&name=avi-box"

    override func setUp() { continueAfterFailure = false }

    private func launch(_ screen: String, sheet: String? = nil, line: String? = nil) {
        app = XCUIApplication()
        app.launchArguments = ["-demo", screen] + (sheet.map { ["-sheet", $0] } ?? []) + (line.map { ["-machineLine", $0] } ?? [])
        app.launch()
    }

    private func shot(_ name: String) {
        guard let folder = ProcessInfo.processInfo.environment["PARITY_SHOTS"] else { return }
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(folder)/\(name).png"))
    }

    private func any(_ id: String) -> XCUIElement { app.descendants(matching: .any)[id].firstMatch }

    private func label(_ text: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

    /// The Sessions sheet opens at half height and draws its lower rows only when they come on screen: scroll to one.
    private func reveal(_ element: XCUIElement) {
        for _ in 0..<5 where !element.exists { app.swipeUp(velocity: .slow) }
    }

    // MARK: whose it is

    func testTheSessionsListSaysWhoseEachMachineAndSessionIs() throws {
        launch("people", sheet: "sessions")
        XCTAssertTrue(any("machineChip.mine").waitForExistence(timeout: 15), "Mine, once some session is somebody else's")
        XCTAssertTrue(any("machineSection.studio").label.contains("studio · this Mac"), "my own machine says no owner")
        XCTAssertFalse(any("session.shop").label.contains("'s"), "no owner tag on mine")
        let section = any("machineSection.avi-box")
        reveal(section)
        XCTAssertTrue(section.waitForExistence(timeout: 5))
        XCTAssertTrue(section.label.contains("avi-box · Avi's · Linux · 31 ms"), section.label)
        reveal(any("session.tide"))
        XCTAssertTrue(label("Dana is using it").waitForExistence(timeout: 5), "who a session works for")
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Avi's")).firstMatch.exists, "an owner tag on Avi's sessions")
        shot("people-sessions")
    }

    func testMineShowsOnlyMySessions() throws {
        launch("people", sheet: "sessions")
        let mine = any("machineChip.mine")
        XCTAssertTrue(mine.waitForExistence(timeout: 15))
        mine.tap()
        XCTAssertEqual(any("session.billing").value as? String, "private", "the lock, in words")
        for _ in 0..<3 { app.swipeUp(velocity: .slow) }
        XCTAssertFalse(any("machineSection.avi-box").exists, "Mine hides Avi's machine")
        XCTAssertFalse(any("session.tide").exists)
        shot("people-sessions-mine")
    }

    func testWithOnlyMyOwnMachinesThereIsNoMineChipAndNoOwnerTag() throws {
        launch("machines", sheet: "sessions")
        XCTAssertTrue(any("machineChip.all").waitForExistence(timeout: 15))
        XCTAssertFalse(any("machineChip.mine").exists)
        XCTAssertFalse(label("'s ·").exists, "no owner on a machine of my own")
    }

    func testAMachineIOnlyWatchOffersNoApprove() throws {
        launch("peopleWatch")
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "tide,")).firstMatch.waitForExistence(timeout: 15))
        XCTAssertTrue(label("watch only").exists)
        XCTAssertFalse(app.buttons["Approve"].exists, "its prompt is its owner's to answer")
        XCTAssertFalse(app.buttons["Deny"].exists)
        XCTAssertFalse(label("needs approval").exists)
        shot("people-watch-only")
    }

    func testAMachineThatRemovedYouSaysSoAndOffersRemove() throws {
        launch("peopleRemoved", sheet: "sessions")
        let gone = any("machineGone.avi-box")
        XCTAssertTrue(any("machineChip.all").waitForExistence(timeout: 15))
        reveal(gone)
        XCTAssertTrue(gone.waitForExistence(timeout: 5))
        XCTAssertEqual(gone.label, "avi-box removed you")
        XCTAssertTrue(any("machineSection.avi-box").label.contains("offline since"), "an offline machine")
        shot("people-removed-you")
        any("removeMachine.avi-box").tap()
        XCTAssertTrue(label("Remove avi-box? Its sessions leave your voice.").waitForExistence(timeout: 5), "it asks first")
        shot("people-removed-you-confirm")
    }

    // MARK: Add a machine

    func testAddAMachineOpensOnTheCameraWithPaste() throws {
        launch("machines", sheet: "addMachine")
        XCTAssertTrue(app.navigationBars["Add a machine"].waitForExistence(timeout: 15))
        XCTAssertTrue(any("addMachineScanner").exists, "the camera at once")
        XCTAssertTrue(any("addMachinePaste").exists, "Paste instead")
        XCTAssertFalse(any("addMachineName").exists, "no name is asked for")
        XCTAssertFalse(app.buttons["addMachineAdd"].isEnabled, "nothing to add yet")
        shot("add-machine")
    }

    func testSettingsMachinesHasAddAMachineAndPeople() throws {
        launch("people")
        app.settingsItem("machinesItem", .button).tap()
        XCTAssertTrue(any("machine.avi-box").waitForExistence(timeout: 5))
        XCTAssertTrue(label("avi-box · Avi's").exists, "whose it is")
        XCTAssertEqual(any("revoke.avi-box").label, "Remove avi-box", "a machine you were invited to is removed, not revoked")
        if !any("peopleItem").exists { app.swipeUp() }
        XCTAssertTrue(any("addMachine").exists)
        XCTAssertTrue(any("peopleItem").exists)
        shot("settings-machines-people")
    }

    func testAnAddedMachineIsListedWithItsOwnerThenTheDisclosureOnce() throws {
        Biometry.enrol()
        launch("machines", sheet: "addMachine", line: line)
        let add = app.buttons["addMachineAdd"]
        XCTAssertTrue(add.waitForExistence(timeout: 15))
        XCTAssertTrue(any("addMachineLine").exists, "the line that was read, kept")
        add.tap()
        Biometry.allowFaceID()
        sleep(1)
        Biometry.match(true)
        let row = any("machine.avi-box")
        XCTAssertTrue(row.waitForExistence(timeout: 15), "the sheet closed and the machine is in the list")
        XCTAssertTrue(label("avi-box · Avi's").exists)
        let said = any("disclosureText")
        XCTAssertTrue(said.waitForExistence(timeout: 5))
        XCTAssertTrue(said.label.contains("Your voice sends the transcripts of the sessions on avi-box, with credentials masked, to: Deepgram, Gemini. Avi sees this list next to your name."), said.label)
        shot("add-machine-disclosure")
        any("disclosureOK").tap()
        XCTAssertTrue(said.waitForNonExistence(timeout: 5), "one OK, and it is gone")
        shot("settings-machines-with-avis")
    }

    func testARefusalStaysInTheSheetWithTheLineAndANameIsAskedWhenTaken() throws {
        Biometry.enrol()
        launch("people", sheet: "addMachine", line: line)  // this voice has an avi-box already
        let add = app.buttons["addMachineAdd"]
        XCTAssertTrue(add.waitForExistence(timeout: 15))
        add.tap()
        Biometry.allowFaceID()
        sleep(1)
        Biometry.match(true)
        let problem = any("addMachineProblem")
        XCTAssertTrue(problem.waitForExistence(timeout: 10))
        XCTAssertTrue(problem.label.contains("A machine called avi-box is already paired"), problem.label)
        XCTAssertTrue(any("addMachineLine").exists, "the line is kept")
        XCTAssertTrue(any("addMachineName").exists, "Call it, only now")
        shot("add-machine-name-taken")
    }

    // MARK: People

    func testPeopleListsEachPersonWithTheTrustLine() throws {
        launch("people", sheet: "people")
        XCTAssertTrue(any("person.dana").waitForExistence(timeout: 15))
        XCTAssertTrue(label("can talk · online").exists)
        XCTAssertTrue(label("watch only · last seen").exists)
        XCTAssertTrue(label("Their voice uses: Deepgram, Gemini").exists)
        XCTAssertTrue(label("People you invite can make these agents run commands as sam. Keep a session to yourself with Private.").exists)
        XCTAssertTrue(any("personName").exists && any("invitePerson").exists)
        XCTAssertFalse(app.buttons["invitePerson"].isEnabled, "a name first")
        shot("people")
    }

    func testInvitingAPersonNeedsFaceIDThenShowsTheLineAndClosesWhenTheyPair() throws {
        Biometry.enrol()
        launch("people", sheet: "people")
        let name = any("personName")
        XCTAssertTrue(name.waitForExistence(timeout: 15))
        name.tap()
        name.typeText("noa\n")
        if !app.buttons["invitePerson"].isHittable { app.swipeUp() }
        app.buttons["invitePerson"].tap()
        Biometry.allowFaceID()
        sleep(1)
        XCTAssertFalse(any("personInviteLine").exists, "no line before Face ID")
        Biometry.match(true)
        let shown = any("personInviteLine")
        XCTAssertTrue(shown.waitForExistence(timeout: 10), "the line after Face ID")
        XCTAssertTrue(shown.label.hasPrefix("pointe://machine?"), shown.label)
        XCTAssertTrue(any("personInviteQR").exists && any("sharePersonInvite").exists && any("copyPersonInvite").exists)
        XCTAssertTrue(any("personInviteCountdown").label.hasPrefix("Expires in "))
        shot("people-invite")
        XCTAssertTrue(any("person.noa").waitForExistence(timeout: 20), "they paired: the person is in the list")
        XCTAssertFalse(shown.exists, "and the line closed by itself")
        shot("people-invite-paired")
    }

    func testRemovingAPersonAsksThenNeedsFaceID() throws {
        Biometry.enrol()
        launch("people", sheet: "people")
        XCTAssertTrue(any("personMenu.omer").waitForExistence(timeout: 15))
        any("personMenu.omer").tap()
        shot("people-person-menu")
        app.buttons["Remove"].firstMatch.tap()
        XCTAssertTrue(label("Remove Omer? Their voice loses this machine's sessions now.").waitForExistence(timeout: 5), "it asks first")
        any("confirmRemovePerson").tap()
        Biometry.allowFaceID()
        sleep(1)
        XCTAssertTrue(any("person.omer").exists, "nobody removed before Face ID")
        Biometry.match(true)
        XCTAssertTrue(any("person.omer").waitForNonExistence(timeout: 10), "removed")
        XCTAssertTrue(any("peopleDone").exists)
    }

    // MARK: the disclosure, from the status

    func testAMachineAddedElsewhereSaysOnceWhereItsTranscriptsGo() throws {
        launch("peopleAdded")
        let ok = app.alerts.buttons["OK"].firstMatch  // an alert's button keeps no identifier
        XCTAssertTrue(ok.waitForExistence(timeout: 15))
        XCTAssertTrue(label("Your voice sends the transcripts of the sessions on avi-box").exists)
        shot("disclosure")
        ok.tap()
        XCTAssertTrue(ok.waitForNonExistence(timeout: 5))
    }
}
