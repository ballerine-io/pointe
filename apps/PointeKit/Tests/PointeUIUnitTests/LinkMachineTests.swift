import XCTest
import PointeKit
@testable import PointeUI

/// The call's link as decisions (LinkMachine in CallWire.swift): what a drop, a quiet link or a new network does, and
/// what ends the call. tests/test_calllink.py holds the Mac's side to the same protocol.
final class LinkMachineTests: XCTestCase {
    private func live(token: String? = "tok") -> LinkMachine {
        var m = LinkMachine()
        m.start()
        m.opened()
        if let token { m.answered(token: token) }
        return m
    }

    func testConnectDialsThenALinkThatDropsIsDialledAgainAlmostAtOnceWithTheCallsToken() {
        var m = LinkMachine()
        m.start()
        XCTAssertEqual(m.state, .connecting)
        m.opened()
        m.answered(token: "tok")
        XCTAssertEqual(m.state, .live)
        let next = m.dropped(code: 1006, http: nil, reason: "", place: "mac:7443", random: 1)
        XCTAssertEqual(next, .dial(after: Redial.first))
        XCTAssertEqual(m.state, .reconnecting)
        XCTAssertEqual(m.token, "tok", "the redial's hello brings this call back")
        XCTAssertNil(m.problem)
    }

    /// 1.23: the socket opened (the count went back to 0), then the Mac closed it 4409 because it still held the dead
    /// call, and the phone took that for a first try: the call ended as "A call is already up". A redial keeps trying.
    func testARedialThatMeetsTheMacsHeldCallKeepsTryingInsteadOfEndingAsBusy() {
        var m = live()
        _ = m.dropped(code: 1006, http: nil, reason: "", place: "h:1", random: 0)
        m.opened()  // the redial's socket opened...
        let next = m.dropped(code: 4409, http: 101, reason: "a call is already up", place: "h:1", random: 0)  // ...and was turned away
        XCTAssertEqual(m.state, .reconnecting)
        XCTAssertNil(m.problem)
        XCTAssertEqual(next, .dial(after: 0.25), "the second wait of the backoff: the first redial did not reset it")
    }

    func testConnectOnAMacWhereAnotherCallIsUpSaysSo() {
        var m = LinkMachine()
        m.start()
        m.opened()
        XCTAssertEqual(m.dropped(code: 4409, http: 101, reason: "", place: "h:1", random: 0), .stop)
        XCTAssertEqual(m.problem, ConnectCopy.busy)
        XCTAssertEqual(m.state, .off)
    }

    func testAFirstDialThatNeverOpensSaysWhyButARedialThatCannotReachTheMacKeepsTrying() {
        var m = LinkMachine()
        m.start()
        XCTAssertEqual(m.dropped(code: 0, http: nil, reason: "", place: "mac:7443", random: 0), .stop)
        XCTAssertEqual(m.problem, ConnectCopy.unreachableHere("mac:7443"))
        var r = live()
        _ = r.dropped(code: 1006, http: nil, reason: "", place: "mac:7443", random: 0)
        XCTAssertEqual(r.dropped(code: 0, http: nil, reason: "", place: "mac:7443", random: 0), .dial(after: 0.25))
        XCTAssertNil(r.problem)
    }

    func testUnpairingEndsTheCallWhateverTheState() {
        for code in [4401, 1008] {
            var m = live()
            XCTAssertEqual(m.dropped(code: code, http: 101, reason: "unpaired", place: "h:1", random: 0), .stop)
            XCTAssertEqual(m.problem, ConnectCopy.notPairedHere)
            XCTAssertNil(m.token)
        }
        var redialling = live()
        _ = redialling.dropped(code: 1006, http: nil, reason: "", place: "h:1", random: 0)
        XCTAssertEqual(redialling.dropped(code: 0, http: 403, reason: "", place: "h:1", random: 0), .stop)
    }

    func testTheBackoffGrowsUntilTheMacAnswersThenStartsAgain() {
        var m = live()
        var waits: [TimeInterval] = []
        for _ in 0..<7 {
            if case .dial(let after) = m.dropped(code: 1006, http: nil, reason: "", place: "h:1", random: 1) { waits.append(after) }
        }
        XCTAssertEqual(waits, [0.25, 0.5, 1, 2, 4, 8, 8])
        m.opened()
        m.answered(token: "tok")
        XCTAssertEqual(m.dropped(code: 1006, http: nil, reason: "", place: "h:1", random: 1), .dial(after: 0.25))
    }

    func testAQuietLinkIsGivenUpAndANewNetworkIsUsedAtOnce() {
        var m = live()
        XCTAssertEqual(m.quiet(random: 1), .dial(after: 0.25))
        XCTAssertEqual(m.state, .reconnecting)
        XCTAssertEqual(m.quiet(random: 1), .none, "already dialling")
        XCTAssertEqual(m.networkChanged(), .dial(after: 0))
        var l = live()
        XCTAssertEqual(l.networkChanged(), .dial(after: 0))
        var off = LinkMachine()
        XCTAssertEqual(off.networkChanged(), .none, "no call, nothing to move")
    }

    func testHangingUpForgetsTheCall() {
        var m = live()
        m.hungUp()
        XCTAssertEqual(m.state, .off)
        XCTAssertNil(m.token)
        m.start()
        XCTAssertEqual(m.state, .connecting)
        XCTAssertNil(m.token, "a new Connect is a new call")
    }

    /// The phone's words for the state, the page's too (tests/test_copy_parity.py reads ui.html).
    func testTheReconnectingLineSaysTheCallGoesOn() {
        XCTAssertEqual(ConnectCopy.redialling, "The connection dropped. The call picks up where it was when it is back; Cancel ends it.")
    }
}
