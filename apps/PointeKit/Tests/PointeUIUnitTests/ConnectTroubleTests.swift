import XCTest
@testable import PointeUI

/// The call screen when the paired Mac can't be reached: the status poll's failure, read into one cause with the
/// route's fix, on the stage until the Mac answers or the person acts (docs/phone.md).
final class ConnectTroubleTests: XCTestCase {
    private let fp = String(repeating: "a", count: 64)
    private lazy var named = DaemonLink(Pairing(host: "pointe.example.internal", port: 7443, fingerprint: fp, key: String(repeating: "k", count: 32)))

    func testThePhonesFailedPollIsReadIntoOneCauseWithWhereItLooked() {
        let p = named.problem(URLError(.cannotFindHost), pinRefused: false)
        XCTAssertEqual(p?.cause, .nameNotFound)
        XCTAssertEqual(p?.place, "pointe.example.internal:7443")
        XCTAssertEqual(p?.route, .name)
        XCTAssertEqual(named.problem(URLError(.cancelled), pinRefused: true)?.cause, .certificateChanged)
        XCTAssertEqual(named.problem(status: 401)?.cause, .notPaired)
        XCTAssertEqual(named.problem(status: 403)?.cause, .notPaired)
        XCTAssertNil(named.problem(status: 500), "not about the connection")
    }

    func testAMacThatAnswersButIsTooOldOrTooNewIsSaid() throws {
        func status(_ extra: String) throws -> API.Status {
            try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": false, "sessions": []\#(extra)}"#.utf8))
        }
        XCTAssertNil(named.problem(version: try status("")), "a Mac from before the check")
        XCTAssertNil(named.problem(version: try status(#", "phone_protocol": 4, "oldest_phone_protocol": 1"#)))
        XCTAssertEqual(named.problem(version: try status(#", "phone_protocol": 3"#))?.cause, .macTooOld)
        XCTAssertEqual(named.problem(version: try status(#", "phone_protocol": 9, "oldest_phone_protocol": 9"#))?.cause, .appTooOld)
    }

    func testTheMacAppKeepsItsOwnWords() {
        let local = DaemonLink(local: LocalDaemon(endpoint: { nil }))
        XCTAssertNil(local.problem(URLError(.cannotConnectToHost), pinRefused: false), "the Mac app looks at its own Mac: MacCopy")
        XCTAssertNil(local.problem(status: 403))
    }

    func testTheStageShowsTheProblemInsteadOfTheOldGuessAndOffersTheWayForward() {
        let p = ConnectionProblem(cause: .nameNotFound, host: "pointe.example.internal", port: 7443)
        let face = ConnectFace.make(phase: .off, reach: .unreachable, host: "pointe.example.internal:7443", problem: nil,
                                    macOnACall: false, trouble: p)
        XCTAssertEqual(face.trouble, p)
        XCTAssertEqual(face.why, p.detail)
        XCTAssertTrue(face.bad)
        XCTAssertEqual(face.button, "Try again")
        let dialling = ConnectFace.make(phase: .connecting, reach: .unreachable, host: "h:1", problem: nil, macOnACall: false, trouble: p)
        XCTAssertEqual(dialling.trouble, p, "a Try again in flight keeps the cause on screen")
        XCTAssertEqual(dialling.button, "Cancel")
        let back = ConnectFace.make(phase: .off, reach: .ok, host: "h:1", problem: nil, macOnACall: false, trouble: nil)
        XCTAssertNil(back.trouble, "the Mac answered: nothing to fix")
        let old = ConnectionProblem(cause: .macTooOld, host: "h", port: 1)
        let answering = ConnectFace.make(phase: .off, reach: .ok, host: "h:1", problem: nil, macOnACall: false, trouble: old)
        XCTAssertEqual(answering.trouble, old, "a Mac that answers and is too old is still a problem")
        XCTAssertEqual(answering.why, old.detail)
    }
}
