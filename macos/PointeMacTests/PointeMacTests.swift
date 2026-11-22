import PointeKit
import PointeUI
import XCTest
@testable import Pointe

/// What is the Mac target's own: the shell around the shared screens. The screens, the call, the models and the rules
/// are tested in the package (`swift test` in apple/PointeKit), on the Mac and in the iPhone simulator.
@MainActor
final class PointeMacTests: XCTestCase {
    /// The menu bar mark is the brand's small drawing in both states; only its strength changes.
    func testTheMenuBarImageFollowsTheState() {
        XCTAssertEqual(MenuBarLabel.image(.off), "MenuOff")
        XCTAssertEqual(MenuBarLabel.image(.down), "MenuOff")
        for glyph in [MacSession.Glyph.live, .talking, .speaking, .needsYou] { XCTAssertEqual(MenuBarLabel.image(glyph), "MenuLive") }
        for name in ["MenuOff", "MenuLive"] { XCTAssertNotNil(NSImage(named: name), name) }
    }

    /// Loopback HTTP is the one exception to App Transport Security; the app is a menu bar agent and says why it
    /// wants the microphone.
    func testTheBundleAsksForNoMoreThanItNeeds() throws {
        let info = try XCTUnwrap(Bundle.main.infoDictionary)
        let transport = try XCTUnwrap(info["NSAppTransportSecurity"] as? [String: Any])
        XCTAssertEqual(transport.keys.sorted(), ["NSAllowsLocalNetworking"])
        XCTAssertEqual(info["LSUIElement"] as? Bool, true)
        XCTAssertFalse((info["NSMicrophoneUsageDescription"] as? String ?? "").isEmpty)
        XCTAssertNil(info["CFBundleURLTypes"], "no URL scheme: nothing outside can open the app with data")
    }

    /// The box is what the shared screens ask for the daemon's address: empty until the locator verified a listener,
    /// and emptied by `lost`, so the page key waits for the next check.
    func testTheEndpointIsForgottenWhenNothingAnswers() {
        let box = EndpointBox()
        XCTAssertNil(box.endpoint)
        let daemon = LocalDaemon(endpoint: { box.endpoint }, lost: { box.set(nil) })
        box.set(DaemonEndpoint(port: 7999, credential: .pageKey("made-up")))
        XCTAssertNotNil(box.endpoint)
        XCTAssertEqual(daemon, daemon)
        box.set(nil)
        XCTAssertNil(box.endpoint)
    }

    /// With no call and no daemon the shell says so, and a press of the talk shortcut is not a talk press: the caller
    /// brings the window forward instead.
    func testWithNoCallTheShellIsOffAndTheShortcutOpensTheWindow() {
        let session = MacSession(daemon: LocalDaemon(endpoint: { nil }))
        XCTAssertEqual(session.phase, .off)
        XCTAssertFalse(session.live)
        XCTAssertEqual(session.glyph, .off)
        XCTAssertEqual(session.needCount, 0)
        XCTAssertTrue(session.waiting.isEmpty)
        XCTAssertFalse(session.talkDown(), "no call: the shortcut opens the window")
        session.talkUp()
        XCTAssertEqual(session.dumpLabel, "Brain dump")
    }

    /// "Try a demo" shows invented sessions with a request waiting, live, and leaving it puts the shell back.
    func testTheDemoShowsARequestAndLeavesNothingBehind() {
        let session = MacSession(daemon: LocalDaemon(endpoint: { nil }))
        session.tryDemo()
        XCTAssertTrue(session.isDemo)
        XCTAssertEqual(session.phase, .live)
        XCTAssertEqual(session.needCount, 1)
        XCTAssertEqual(session.glyph, .needsYou)
        XCTAssertEqual(session.menuTitle, MacCopy.needYou(1))
        XCTAssertEqual(session.waiting.count, 1)
        session.exitDemo()
        XCTAssertFalse(session.isDemo)
        XCTAssertEqual(session.phase, .off)
        XCTAssertEqual(session.needCount, 0)
    }

    /// Every menu command has a key, and no two share one (docs/design/parity.md, "Keys").
    func testTheMenusWordsAreTheSheetsTitles() {
        XCTAssertEqual(MacMenu.newSession, "New Session")
        XCTAssertEqual(MacMenu.sessions, "Sessions and Mode")
        XCTAssertEqual(MacMenu.meeting, "Start a Meeting")
        XCTAssertEqual(MacMenu.nightShift, NightShiftCopy.title, "the ledger's own title, as on the page and the phone")
    }
}
