import PointeKit
import XCTest
@testable import PointeUI

/// How each app reaches Pointe: the iPhone with its pairing's key on the Mac's phone listener, the Mac app with the page's
/// key on loopback, and on the Mac only once the listener was verified (docs/design/macos-app.md, "Authentication").
final class DaemonLinkTests: XCTestCase {
    private let pairing = Pairing(host: "studio.example.ts.net", port: 7443, fingerprint: String(repeating: "a", count: 64),
                                  key: String(repeating: "k", count: 32))

    func testAPhonesRequestCarriesItsKeyAndItsNameAndGoesToThePhoneListener() throws {
        let link = DaemonLink(pairing)
        let r = link.request("voice/approve", method: "POST", body: ["session": "docs"])
        XCTAssertEqual(r.url?.absoluteString, "https://studio.example.ts.net:7443/voice/approve")
        XCTAssertEqual(r.value(forHTTPHeaderField: "Authorization"), "Bearer " + String(repeating: "k", count: 32))
        XCTAssertNotNil(r.value(forHTTPHeaderField: "X-Pointe-Device"))
        XCTAssertNil(r.value(forHTTPHeaderField: "Cookie"))
        XCTAssertEqual(r.timeoutInterval, 10)
        XCTAssertEqual(try JSONSerialization.jsonObject(with: try XCTUnwrap(r.httpBody)) as? [String: String], ["session": "docs"])
        XCTAssertEqual(link.callRequest?.url?.absoluteString, "wss://studio.example.ts.net:7443/voice/phone")
        XCTAssertTrue(link.ready)
        XCTAssertEqual(link.device, "iPhone")
        XCTAssertEqual(link.place, "studio.example.ts.net:7443")
    }

    func testTheMacsRequestCarriesThePageCookieOnLoopbackAndNeverTheKeyInAURL() throws {
        let link = DaemonLink(local: LocalDaemon(endpoint: { DaemonEndpoint(port: 7999, credential: .pageKey("k3y")) }))
        let r = link.request("voice/dictionary", query: [URLQueryItem(name: "term", value: "Quillfeather")])
        XCTAssertEqual(r.url?.absoluteString, "http://127.0.0.1:7999/voice/dictionary?term=Quillfeather")
        XCTAssertEqual(r.value(forHTTPHeaderField: "Cookie"), "pointe_local=k3y")
        XCTAssertNil(r.value(forHTTPHeaderField: "Authorization"))
        XCTAssertNil(r.value(forHTTPHeaderField: "Origin"))
        XCTAssertNil(r.value(forHTTPHeaderField: "X-Pointe-Device"))
        XCTAssertFalse(r.httpShouldHandleCookies)
        let call = try XCTUnwrap(link.callRequest)
        XCTAssertEqual(call.url?.absoluteString, "ws://127.0.0.1:7999/voice/call")
        XCTAssertEqual(call.value(forHTTPHeaderField: "Cookie"), "pointe_local=k3y")
        XCTAssertEqual(link.device, "Mac")
    }

    /// The page key is sent only to a listener the app verified: with none, nothing is asked and nothing is dialled.
    func testWithoutAVerifiedDaemonNothingIsSent() async {
        let link = DaemonLink(local: LocalDaemon(endpoint: { nil }))
        XCTAssertFalse(link.ready)
        XCTAssertNil(link.callRequest)
        let r = link.request("voice/status")
        XCTAssertNil(r.value(forHTTPHeaderField: "Cookie"))
        XCTAssertNotEqual(r.url?.scheme, "http")
        let api = API(link: link, session: link.session(onOpen: {}))
        do {
            _ = try await api.status()
            XCTFail("no endpoint: nothing to ask")
        } catch {
            XCTAssertEqual((error as? URLError)?.code, .cannotConnectToHost)
        }
        do {
            try await api.newSession(["confirm": "made-up"])
            XCTFail("no endpoint: nothing is started")
        } catch {
            XCTAssertEqual((error as? URLError)?.code, .cannotConnectToHost)
        }
    }

    /// A daemon that stops answering is forgotten at once: whoever listens on the port next is checked first.
    func testAnEndpointThatDoesNotAnswerIsReportedLost() async {
        final class Flag: @unchecked Sendable { var lost = false }
        let flag = Flag()
        // the discard port: nothing answers HTTP there
        let link = DaemonLink(local: LocalDaemon(endpoint: { DaemonEndpoint(port: 9, credential: .pageKey("made-up")) }, lost: { flag.lost = true }))
        do {
            _ = try await API(link: link, session: link.session(onOpen: {})).status()
            XCTFail("nothing listens there")
        } catch {
            XCTAssertTrue(flag.lost)
        }
    }

    @MainActor
    func testTheTitleIsTheSameLineForTheScreenAndTheMenuBar() {
        let call = Call(pairing: pairing)
        func title(_ phase: Call.State, _ status: API.Status? = nil, dumping: Bool = false, muted: Bool = false, speaking: Bool = false) -> String {
            CallTitle.line(phase: phase, reach: .ok, status: status, call: call, macName: "studio", dumping: dumping, talking: false,
                           speaking: speaking, muted: muted)
        }
        XCTAssertEqual(title(.off), ConnectCopy.notConnected)
        XCTAssertEqual(title(.connecting), "Connecting to studio…")
        XCTAssertEqual(title(.reconnecting), "Reconnecting…")
        XCTAssertEqual(title(.live), "Listening")
        XCTAssertEqual(title(.live, muted: true), "Muted")
        XCTAssertEqual(title(.live, speaking: true), "Speaking")
        XCTAssertEqual(title(.live, dumping: true, muted: true), BrainDumpCopy.state, "the brain dump comes before the mic's own state")
        XCTAssertEqual(CallTitle.line(phase: .off, reach: .unreachable, status: nil, call: call, macName: "studio", dumping: false, talking: false,
                                      speaking: false, muted: false), ConnectCopy.unreachableTitle)
    }
}
