import PointeKit
import XCTest
@testable import Pointe

/// What is the Mac target's own: the rest is tested in the package (`swift test` in apple/PointeKit).
final class PointeMacTests: XCTestCase {
    /// The page key is sent only to an endpoint the locator verified: with none, nothing is dialled and nothing asked.
    func testWithoutAVerifiedDaemonNothingIsSent() async {
        let live = LiveDaemon(box: EndpointBox())
        do {
            _ = try await live.status()
            XCTFail("no endpoint: nothing to ask")
        } catch {
            XCTAssertEqual((error as? URLError)?.code, .cannotConnectToHost)
        }
        do {
            _ = try await BoxDialer(box: EndpointBox()).dial()
            XCTFail("no endpoint: nothing to dial")
        } catch {
            XCTAssertEqual(error as? CallClose, CallClose(code: 0))
        }
    }

    /// A daemon that stops answering is forgotten at once: whoever listens on the port next is checked first.
    func testAnEndpointThatDoesNotAnswerIsForgotten() async {
        let box = EndpointBox()
        box.set(DaemonEndpoint(port: 9, credential: .pageKey("made-up")))  // the discard port: nothing answers HTTP there
        do {
            _ = try await LiveDaemon(box: box).status()
            XCTFail("nothing listens there")
        } catch {
            XCTAssertNil(box.endpoint)
        }
    }

    /// The menu bar mark is the brand's small drawing in both states; only its strength changes.
    func testTheMenuBarImageFollowsTheState() {
        XCTAssertEqual(MenuBarLabel.image(.off), "MenuOff")
        XCTAssertEqual(MenuBarLabel.image(.down), "MenuOff")
        for kind in [MenuBarState.Kind.live, .talking, .speaking, .needsYou] { XCTAssertEqual(MenuBarLabel.image(kind), "MenuLive") }
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

    func testTheBrainDumpButtonStartsThenFinishes() async {
        let daemon = StubDaemon()
        let store = await PointeStore(api: daemon, authenticator: FixedOwner(answer: true), appVersion: "1.0.0")
        await store.refresh()
        await store.dumpButton()
        let dumping = await store.dump?.isDumping
        XCTAssertEqual(dumping, true)
        await store.dumpButton()
        let review = await store.dump?.inReview
        XCTAssertEqual(review, true)
        await store.dumpButton()  // in review the button changes nothing: the review is on screen
        let calls = await daemon.calls
        XCTAssertEqual(calls, ["dump start", "dump done"])
    }
}
