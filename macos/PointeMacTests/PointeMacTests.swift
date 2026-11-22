import PointeKit
import PointeMacKit
import PointeUI
import SwiftUI
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

    // MARK: the call bubble

    /// The bubble is the call's: while one is up or being placed, and with none only when pinned. Off is off.
    func testTheBubbleShowsOnACallOrWhenPinned() {
        XCTAssertFalse(BubbleRule.shows(on: true, pinned: false, phase: .off), "no call: no bubble saying Not connected")
        for phase in [MacSession.Phase.connecting, .live, .reconnecting] { XCTAssertTrue(BubbleRule.shows(on: true, pinned: false, phase: phase)) }
        XCTAssertTrue(BubbleRule.shows(on: true, pinned: true, phase: .off), "pinned: on screen with no call too")
        XCTAssertFalse(BubbleRule.shows(on: false, pinned: true, phase: .live), "turned off, by × or the menu: never")
    }

    /// Always on, or in push to talk the shortcut as the person set it, with Hold or Tap.
    func testTheTalkModeNamesTheShortcut() {
        XCTAssertEqual(BubbleRule.talkMode(pushToTalk: false, hold: true, shortcut: "⌥Space"), "Always on")
        XCTAssertEqual(BubbleRule.talkMode(pushToTalk: true, hold: true, shortcut: "⌥Space"), "Hold ⌥Space")
        XCTAssertEqual(BubbleRule.talkMode(pushToTalk: true, hold: false, shortcut: Shortcut.standard.display), "Tap ⌃⌥Space")
        XCTAssertEqual(BubbleRule.talkMode(pushToTalk: true, hold: true, shortcut: nil), "Push to talk", "no shortcut that works: none named")
        XCTAssertNotEqual(BubbleRule.talkModeGlyph(pushToTalk: true), BubbleRule.talkModeGlyph(pushToTalk: false))
    }

    /// Why a call did not start comes first; heard words keep their newest end; a session's name keeps its start, so
    /// "…ser access capability question" cannot happen.
    func testTheDetailLineSaysWhyAndKeepsANamesStart() {
        let name = "billing retry tests and the user access capability question"
        let off = BubbleRule.detail(problem: MacCopy.micDenied, phase: .off, hearing: "", session: name)
        XCTAssertEqual(off.text, MacCopy.micDenied)
        XCTAssertTrue(off.bad)
        XCTAssertFalse(off.keepsEnd)
        let named = BubbleRule.detail(problem: nil, phase: .off, hearing: "", session: name)
        XCTAssertEqual(named.text, name)
        XCTAssertFalse(named.keepsEnd, "a name is cut at its end")
        let heard = BubbleRule.detail(problem: "an old reason", phase: .live, hearing: "run the checkout tests", session: name)
        XCTAssertEqual(heard.text, "run the checkout tests", "on a call an old reason is gone")
        XCTAssertTrue(heard.keepsEnd)
        XCTAssertEqual(BubbleRule.detail(problem: nil, phase: .off, hearing: "", session: nil).text, MacCopy.appName)
    }

    /// A call the person placed that ended with a reason opens the window, where Connect says the reason and its fix;
    /// one being placed waits; one that started, or that the person cancelled, opens nothing.
    func testAFailedDialOpensTheWindowAndOneBeingPlacedWaits() {
        XCTAssertNil(BubbleRule.failedDial(phase: .connecting, problem: nil))
        XCTAssertNil(BubbleRule.failedDial(phase: .reconnecting, problem: nil))
        XCTAssertEqual(BubbleRule.failedDial(phase: .live, problem: nil), false)
        XCTAssertEqual(BubbleRule.failedDial(phase: .off, problem: MacCopy.busy), true)
        XCTAssertEqual(BubbleRule.failedDial(phase: .off, problem: nil), false)
    }

    /// Small and full size swap around the corner nearest the screen's edges; a new bubble, and Reset Position, sit
    /// top right; a place on a display that went away is not kept.
    func testTheBubbleKeepsItsCornerAndComesHome() {
        let screen = NSRect(x: 0, y: 0, width: 1512, height: 916)
        let topRight = NSRect(x: 1228, y: 804, width: 264, height: 80)
        XCTAssertEqual(BubbleRule.resized(topRight, to: BubbleRule.small, in: screen), NSRect(x: 1412, y: 840, width: 80, height: 44))
        let bottomLeft = NSRect(x: 40, y: 30, width: 80, height: 44)
        XCTAssertEqual(BubbleRule.resized(bottomLeft, to: BubbleRule.full, in: screen), NSRect(x: 40, y: 30, width: 264, height: 80))
        let home = BubbleRule.home(size: BubbleRule.full, in: screen)
        XCTAssertTrue(screen.contains(NSRect(origin: home, size: BubbleRule.full)))
        XCTAssertGreaterThan(home.x, screen.midX)
        XCTAssertTrue(BubbleRule.reachable(topRight, screens: [screen]))
        XCTAssertFalse(BubbleRule.reachable(NSRect(x: 2400, y: 300, width: 264, height: 80), screens: [screen]))
    }

    /// The bug behind "nothing happens when I click it": the panel never becomes key and the app is not active, so a
    /// view that does not take the first mouse never sees the click. The bubble's host takes it, and the panel is not
    /// dragged by its background (which would take the mouse down before the view could tell a click from a drag).
    func testTheBubbleTakesTheFirstClick() throws {
        let panel = Windows.bubblePanel(Text("bubble"))
        let host = try XCTUnwrap(panel.contentView as? BubbleHost<Text>)
        XCTAssertTrue(host.acceptsFirstMouse(for: nil))
        XCTAssertFalse(panel.isMovableByWindowBackground)
        XCTAssertFalse(panel.canBecomeKey, "it never takes the keyboard from the app in front")
        XCTAssertTrue(panel.styleMask.contains(.nonactivatingPanel))
        XCTAssertEqual(panel.frame.size, BubbleRule.full)
    }

    /// A launch the person made opens the window (the menu bar item may be behind the notch); one at login does not.
    func testOnlyALaunchAtLoginOpensNoWindow() {
        XCTAssertTrue(AppDelegate.opensWindow(asLoginItem: false))
        XCTAssertFalse(AppDelegate.opensWindow(asLoginItem: true))
        XCTAssertFalse(AppDelegate.launchedAsLoginItem, "a test run is no login item")
    }
}
