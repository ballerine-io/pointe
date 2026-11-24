#if os(macOS)
import XCTest
@testable import PointeUI

/// Pair a phone from the Mac app: the steps of the page's Settings → Phone (ui.html), apart from how they are drawn.
final class PhonePairingTests: XCTestCase {
    private let t0 = Date(timeIntervalSince1970: 1_700_000_000)

    private func routes(_ json: String) throws -> API.PhoneRoutes { try JSONDecoder().decode(API.PhoneRoutes.self, from: Data(json.utf8)) }

    private let found = """
    {"routes": [{"kind": "tailscale", "host": "studio.example.ts.net", "label": "Tailscale", "words": "Works anywhere.", "usable": true,
                 "recommended": true, "current": true, "problem": null, "new_certificate": false},
                {"kind": "wifi", "host": "192.168.1.20", "label": "This Wi-Fi", "words": "Only at home.", "usable": true},
                {"kind": "host", "host": "studio.corp.example", "label": "studio.corp.example", "usable": false, "problem": "That name does not reach this Mac."}],
     "advice": "Tailscale is on: the phone needs it too."}
    """

    func testTheRecommendedRouteIsPickedAndATypedNameThatWorksReplacesIt() throws {
        var p = PhonePairing()
        p.found(try routes(found), typed: nil)
        XCTAssertEqual(p.pick?.kind, "tailscale")
        p.found(try routes(found), typed: "studio.corp.example")
        XCTAssertEqual(p.pick?.kind, "tailscale", "a name that does not reach the Mac is not picked")
        let usable = found.replacingOccurrences(of: #""usable": false, "problem": "That name does not reach this Mac.""#, with: #""usable": true"#)
        p.found(try routes(usable), typed: " Studio.Corp.Example ")
        XCTAssertEqual(p.pick?.host, "studio.corp.example")
    }

    /// The Mac checks the route before the code shows (phone_check.py): a route that does not reach this Mac is said
    /// beside the code with its fix; one that works, or a Mac from before the check, says nothing.
    func testTheCodeCarriesTheMacsCheckOfTheRoute() throws {
        func invite(_ check: String) throws -> API.PhoneInvite {
            try JSONDecoder().decode(API.PhoneInvite.self, from: Data("""
            {"code": "K7PQ-2MXD", "link": "pointe://pair?v=2", "expires_in": 300\(check)}
            """.utf8))
        }
        let failed = #", "check": {"ok": false, "kind": "name", "label": "a name you route yourself (Twingate, a VPN or a tunnel)", "host": "pointe.example.internal", "said": "pointe.example.internal does not reach this Mac.", "fix": "Is your VPN app on, on both devices?", "help": "https://github.com/ballerine-io/pointe/blob/main/docs/phone.md#pairing"}"#
        var p = PhonePairing()
        p.made(try invite(failed), now: t0)
        XCTAssertEqual(p.warning?.said, "pointe.example.internal does not reach this Mac.")
        XCTAssertEqual(p.warning?.fix, "Is your VPN app on, on both devices?")
        XCTAssertEqual(p.warning?.ok, false)
        XCTAssertEqual(p.warning?.help.flatMap(URL.init(string:))?.fragment, "pairing")
        p.made(try invite(failed.replacingOccurrences(of: #""ok": false"#, with: #""ok": null"#)), now: t0)
        XCTAssertNotNil(p.warning, "this Mac could not tell: said, as a note")
        XCTAssertNil(p.warning?.ok)
        p.made(try invite(failed.replacingOccurrences(of: #""ok": false"#, with: #""ok": true"#)), now: t0)
        XCTAssertNil(p.warning, "a route that works says nothing")
        p.made(try invite(""), now: t0)
        XCTAssertNil(p.warning, "a Mac from before the check")
        p.finish()
        XCTAssertNil(p.warning, "the warning goes with the code")
    }

    func testTheCodeCountsDownAndEndsWhenThePhonePairsOrItExpires() {
        var p = PhonePairing()
        p.made(API.PhoneInvite(code: "K7PQ-2MXD", link: "pointe://pair?v=2&host=h&port=7443&fp=00&code=K7PQ-2MXD", expires_in: 600), now: t0)
        XCTAssertEqual(p.step, .code)
        XCTAssertEqual(p.left(now: t0), "10:00")
        XCTAssertEqual(p.left(now: t0.addingTimeInterval(61)), "8:59")
        XCTAssertFalse(p.follow(API.PhoneInviteState(expires_in: 540, paired: nil, ended: nil), now: t0.addingTimeInterval(60)))
        XCTAssertFalse(p.follow(nil, now: t0.addingTimeInterval(61)), "one missed answer does not end the code")
        var paired = p
        XCTAssertTrue(paired.follow(API.PhoneInviteState(expires_in: 500, paired: .init(name: "Mira’s iPhone"), ended: nil), now: t0.addingTimeInterval(90)))
        XCTAssertEqual(paired.done, "Connected: Mira’s iPhone")
        XCTAssertEqual(paired.step, .list)
        XCTAssertNil(paired.invite, "the code is gone from the screen")
        var expired = p
        XCTAssertTrue(expired.follow(API.PhoneInviteState(expires_in: 0, paired: nil, ended: nil), now: t0.addingTimeInterval(120)))
        XCTAssertEqual(expired.problem, PhoneCopy.expired)
        var late = p
        XCTAssertTrue(late.follow(nil, now: t0.addingTimeInterval(601)), "the countdown ends it even when the Mac stopped answering")
        var ended = p
        XCTAssertTrue(ended.follow(API.PhoneInviteState(expires_in: 300, paired: nil, ended: "Three wrong codes: the code was cancelled."), now: t0))
        XCTAssertEqual(ended.problem, "Three wrong codes: the code was cancelled.")
    }

    func testUnpairTakesTwoClicksWithinThreeSeconds() {
        var p = PhonePairing()
        XCTAssertFalse(p.confirmUnpair("p1", now: t0))
        XCTAssertFalse(p.confirmUnpair("p2", now: t0.addingTimeInterval(1)), "another phone's first click")
        XCTAssertFalse(p.confirmUnpair("p1", now: t0.addingTimeInterval(1.5)), "p1's click was replaced")
        XCTAssertTrue(p.confirmUnpair("p1", now: t0.addingTimeInterval(2)))
        XCTAssertFalse(p.confirmUnpair("all", now: t0.addingTimeInterval(10)))
        XCTAssertFalse(p.confirmUnpair("all", now: t0.addingTimeInterval(14)), "too late: it is a first click again")
    }

    func testThePhonesInStatusDecodeAndAnOlderDaemonSendsNone() throws {
        let status = try JSONDecoder().decode(API.Status.self, from: Data(#"""
        {"connected": false, "sessions": [], "phones": {"paired": [{"id": "p1", "name": "Mira’s iPhone", "online": true, "last_seen": 1700000000,
          "paired_at": 1699990000, "legacy": false}, {"id": "legacy", "name": "Paired phone", "legacy": true}]}}
        """#.utf8))
        XCTAssertEqual(status.phones?.paired.map(\.name), ["Mira’s iPhone", "Paired phone"])
        XCTAssertTrue(PhoneSheet.seen(status.phones!.paired[0], now: t0).hasPrefix("online now · paired "))
        XCTAssertEqual(PhoneSheet.seen(status.phones!.paired[1], now: t0), "not seen yet · paired before this Mac gave each phone its own key")
        XCTAssertNil(try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": false, "sessions": []}"#.utf8)).phones)
    }

    func testTheCodeIsDrawnOnThisMac() {
        XCTAssertNotNil(PhoneSheet.qr("pointe://pair?v=2&host=studio.example.ts.net&port=7443&fp=00&code=K7PQ-2MXD"))
    }

    /// The iPhone's confirm names the certificate's first 16 hex characters (PairingOffer.message): the sheet shows them.
    func testBesideTheCodeTheSheetShowsTheCertificateTheIPhoneConfirmShows() {
        let fp = "0123456789abcdef" + String(repeating: "ab", count: 24)
        XCTAssertEqual(PhoneCopy.certificateLine("pointe://pair?v=2&host=studio.example.ts.net&port=7443&fp=\(fp)&code=K7PQ-2MXD"),
                       "Your iPhone should show certificate 0123456789abcdef…")
        XCTAssertNil(PhoneCopy.certificateLine("pointe://pair?v=2&host=studio.example.ts.net&port=7443&fp=00&code=K7PQ-2MXD"))
    }
}
#endif
