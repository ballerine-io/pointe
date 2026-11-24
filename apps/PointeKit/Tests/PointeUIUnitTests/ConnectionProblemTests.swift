import XCTest
@testable import PointeUI

/// What the phone says when it can't reach its Mac (docs/phone.md): the route read from the paired address, the cause
/// read from what the phone saw, and one message and fix for each.
final class ConnectionProblemTests: XCTestCase {
    private let mac = "pointe.example.internal"

    func testTheRouteIsReadFromTheAddressAsPointePairWritesIt() {
        let cases: [(String, PhoneRoute)] = [
            ("192.168.1.20", .wifi), ("10.0.0.7", .wifi), ("172.20.1.4", .wifi), ("127.0.0.1", .wifi),
            ("100.101.102.103", .tailscale), ("studio.tail1234.ts.net", .tailscale), ("Studio.Tail1234.TS.net.", .tailscale),
            ("pointe.example.internal", .name), ("mac.corp.example", .name), ("100.example.com", .name),
        ]  // the same table as tests/test_phone_check.py
        for (host, route) in cases { XCTAssertEqual(PhoneRoute(host: host), route, host) }
    }

    // MARK: the system's error → the cause

    func testEachURLErrorIsOneCause() {
        let table: [(URLError.Code, ConnectionCause)] = [
            (.cannotFindHost, .nameNotFound), (.dnsLookupFailed, .nameNotFound),
            (.timedOut, .timedOut), (.networkConnectionLost, .timedOut),
            (.cannotConnectToHost, .refused),
            (.notConnectedToInternet, .offline), (.dataNotAllowed, .offline),
            (.serverCertificateUntrusted, .certificateChanged), (.secureConnectionFailed, .certificateChanged),
            (.serverCertificateHasUnknownRoot, .certificateChanged),
        ]
        for (code, cause) in table {
            XCTAssertEqual(ConnectionCause.of(URLError(code), route: .name), cause, "\(code)")
        }
        let odd = ConnectionCause.of(URLError(.badServerResponse), route: .name)
        guard case .other(let why) = odd else { return XCTFail("\(odd)") }
        XCTAssertFalse(why.isEmpty, "the system's own words are kept")
    }

    func testAnNSErrorInTheURLDomainIsReadTheSameWay() {
        let ns = NSError(domain: NSURLErrorDomain, code: NSURLErrorCannotFindHost)
        XCTAssertEqual(ConnectionCause.of(ns, route: .name), .nameNotFound)
    }

    /// The pinned delegate cancels a certificate it was not paired with: the system calls that "cancelled".
    func testACertificateThePinRefusedIsAChangedCertificateWhateverTheErrorSays() {
        XCTAssertEqual(ConnectionCause.of(URLError(.cancelled), pinRefused: true, route: .tailscale), .certificateChanged)
        XCTAssertEqual(ConnectionCause.of(URLError(.timedOut), pinRefused: true, route: .wifi, onMacNetwork: false), .certificateChanged)
    }

    func testOnAWiFiRouteOffTheMacsNetworkTheCauseIsTheNetwork() {
        for code in [URLError.Code.timedOut, .cannotConnectToHost, .networkConnectionLost] {
            XCTAssertEqual(ConnectionCause.of(URLError(code), route: .wifi, onMacNetwork: false), .wrongNetwork, "\(code)")
            XCTAssertNotEqual(ConnectionCause.of(URLError(code), route: .wifi, onMacNetwork: true), .wrongNetwork, "\(code)")
            XCTAssertNotEqual(ConnectionCause.of(URLError(code), route: .name, onMacNetwork: false), .wrongNetwork, "only Wi-Fi")
        }
        XCTAssertEqual(ConnectionCause.of(URLError(.notConnectedToInternet), route: .wifi, onMacNetwork: false), .offline,
                       "no network at all is said as that")
    }

    func testTheHTTPAnswerThatRefusesIsOneCause() {
        XCTAssertEqual(ConnectionCause.of(status: 401, pairing: false), .notPaired)
        XCTAssertEqual(ConnectionCause.of(status: 403, pairing: false), .notPaired)
        XCTAssertEqual(ConnectionCause.of(status: 403, pairing: true), .codeSpent)
        XCTAssertEqual(ConnectionCause.of(status: 404, pairing: true), .macTooOld, "a Mac whose Pointe has no pairing route")
        XCTAssertNil(ConnectionCause.of(status: 404, pairing: false), "a missing route is that route's own problem")
        XCTAssertEqual(ConnectionCause.of(status: 429, pairing: true), .tooManyTries)
        XCTAssertNil(ConnectionCause.of(status: 200, pairing: false))
        XCTAssertNil(ConnectionCause.of(status: 500, pairing: false))
    }

    func testEitherSideTooOldIsSaidAndAMacFromBeforeTheCheckIsNot() {
        XCTAssertNil(ConnectionCause.of(macProtocol: nil, oldestApp: nil))
        XCTAssertNil(ConnectionCause.of(macProtocol: PhoneProtocol.app, oldestApp: 1))
        XCTAssertEqual(ConnectionCause.of(macProtocol: PhoneProtocol.oldestMac - 1, oldestApp: nil), .macTooOld)
        XCTAssertEqual(ConnectionCause.of(macProtocol: PhoneProtocol.app + 1, oldestApp: PhoneProtocol.app + 1), .appTooOld)
    }

    func testTheIPv4NetworksOfThisPhoneDecideWhetherTheMacsAddressIsOnThem() {
        let home = LocalNetwork.Interface(address: IPv4("192.168.1.31")!, netmask: IPv4("255.255.255.0")!)
        XCTAssertEqual(LocalNetwork.contains("192.168.1.20", in: [home]), true)
        XCTAssertEqual(LocalNetwork.contains("192.168.7.20", in: [home]), false)
        XCTAssertEqual(LocalNetwork.contains("192.168.1.20", in: []), false, "no Wi-Fi: not on the Mac's")
        XCTAssertEqual(LocalNetwork.contains("127.0.0.1", in: []), true, "this device")
        XCTAssertNil(LocalNetwork.contains(mac, in: [home]), "a name is not an address on a network")
        XCTAssertNil(IPv4("192.168.1"))
        XCTAssertNil(IPv4("192.168.1.256"))
        XCTAssertNil(IPv4("1.2.3.4.5"))
    }

    // MARK: the cause → the words

    func testEachCauseHasItsOwnTitleAndOneFix() {
        let causes: [ConnectionCause] = [.nameNotFound, .timedOut, .refused, .offline, .wrongNetwork, .certificateChanged,
                                         .notPaired, .macTooOld, .appTooOld, .codeSpent, .tooManyTries, .other("x")]
        let titles = causes.map { ConnectionProblem(cause: $0, host: mac, port: 7443).title }
        XCTAssertEqual(Set(titles).count, causes.count, "one title each: \(titles)")
        for cause in causes {
            let p = ConnectionProblem(cause: cause, host: mac, port: 7443)
            XCTAssertFalse(p.detail.isEmpty || p.fix.isEmpty, "\(cause)")
            XCTAssertTrue(p.tried.hasPrefix("Tried pointe.example.internal:7443 · "), p.tried)
            XCTAssertTrue(p.actions.contains(.pairAgain) && p.actions.contains(.howToFix), "\(cause): a way forward and help")
        }
    }

    /// The owner's morning: the Twingate connector (Docker on Colima) had stopped, and the name did not resolve.
    func testANameThatDoesNotResolveSaysSoAndNamesTheConnector() {
        let p = ConnectionProblem(cause: .nameNotFound, host: mac, port: 7443)
        XCTAssertEqual(p.title, "Can't find your Mac")
        XCTAssertEqual(p.detail, "This phone can't look up pointe.example.internal.")
        XCTAssertEqual(p.tried, "Tried pointe.example.internal:7443 · a name you route yourself (Twingate, a VPN or a tunnel)")
        XCTAssertEqual(p.fix, "Is your VPN app on, on both devices? Is the connector on the Mac running? With Docker or Colima it stops after a restart: run `colima start`.")
        XCTAssertEqual(p.actions, [.tryAgain, .pairAgain, .howToFix])
        XCTAssertEqual(p.route.help.host, "github.com")
    }

    func testEachRouteGivesItsOwnHint() {
        XCTAssertEqual(ConnectionProblem(cause: .timedOut, host: "studio.tail1234.ts.net", port: 7443).fix, "Is Tailscale connected on both?")
        let wifi = ConnectionProblem(cause: .wrongNetwork, host: "192.168.1.20", port: 7443)
        XCTAssertEqual(wifi.title, "Not on your Mac's Wi-Fi")
        XCTAssertEqual(wifi.detail, "Your Mac is at 192.168.1.20 on its Wi-Fi, and this phone is not on that network.")
        XCTAssertEqual(wifi.fix, "Both must be on the same network; it stops working when either one moves.")
    }

    func testARefusalOrANewCertificateLeadsWithPairAgain() {
        for cause in [ConnectionCause.certificateChanged, .notPaired, .codeSpent] {
            let p = ConnectionProblem(cause: cause, host: mac, port: 7443)
            XCTAssertEqual(p.actions.first, .pairAgain, "\(cause)")
            XCTAssertFalse(p.actions.contains(.tryAgain), "trying again cannot help: \(cause)")
            XCTAssertTrue(p.fix.hasPrefix("Pair again"), p.fix)
        }
        XCTAssertEqual(ConnectionProblem(cause: .macTooOld, host: mac, port: 7443).fix,
                       "Update the plugin on the Mac: claude plugin update pointe@pointe, then /pointe:stop and /pointe:voice.")
        XCTAssertEqual(ConnectionProblem(cause: .appTooOld, host: mac, port: 7443).fix, "Update the app: on the Mac, run pointe apps ios.")
        XCTAssertEqual(ConnectionProblem(cause: .refused, host: mac, port: 7443).detail,
                       "pointe.example.internal answered, but nothing listens on port 7443.")
    }
}

/// Trading a one-time code with a Mac that is not there fails with the cause, not a guess.
final class RedeemProblemTests: XCTestCase {
    func testACodeForAPortNobodyListensOnIsRefusedWithWhereItLooked() async {
        let invite = PairingInvite(host: "127.0.0.1", port: 1, fingerprint: String(repeating: "ab", count: 32), code: "AB12-CD34")
        do {
            _ = try await invite.redeem(device: "Test iPhone", id: "t")
            XCTFail("nothing listens on port 1")
        } catch let problem as ConnectionProblem {
            XCTAssertEqual(problem.cause, .refused)
            XCTAssertEqual(problem.place, "127.0.0.1:1")
        } catch {
            XCTFail("a ConnectionProblem, not \(error)")
        }
    }
}

final class ProblemCardTests: XCTestCase {
    /// The command in a fix shows as code: the two backticks were drawn as marks around "colima start".
    func testACommandInAFixIsDrawnAsCodeWithoutItsBackticks() {
        let line = ProblemCard.rich(RouteCopy.nameHint)
        XCTAssertEqual(String(line.characters), "Is your VPN app on, on both devices? Is the connector on the Mac running? With Docker or Colima it stops after a restart: run colima start.")
        XCTAssertTrue(line.runs.contains { $0.inlinePresentationIntent?.contains(.code) == true })
    }
}
