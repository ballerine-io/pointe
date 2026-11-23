import XCTest
@testable import PointeUI

/// Who may change which Mac the iPhone talks to (SECURITY.md, "The iPhone app"): only a code scanned or pasted in the
/// app, after the owner confirms it; replacing a pairing also needs Face ID, and the old one stays until the new answers.
@MainActor
final class PairingFlowTests: XCTestCase {
    private let fp = String(repeating: "ab", count: 32)
    private let otherFp = String(repeating: "cd", count: 32)
    private let key = String(repeating: "k", count: 43)
    private lazy var home = Pairing(host: "studio.example.ts.net", port: 7443, fingerprint: fp, key: key)
    private lazy var evilLink = "pointe://pair?v=1&host=evil.example&port=443&fp=\(otherFp)&key=\(String(repeating: "e", count: 40))"
    private lazy var evilCode = "pointe://pair?v=2&host=evil.example&port=443&fp=\(otherFp)&code=ABCD-EFGH"

    final class Keeper: PairingKeeping, @unchecked Sendable {
        var stored: Pairing?
        var saves: [Pairing] = []
        init(_ stored: Pairing?) { self.stored = stored }
        func load() -> Pairing? { stored }
        func save(_ pairing: Pairing) { saves.append(pairing); stored = pairing }
        func forget() { stored = nil }
    }

    private struct Refused: Error {}

    private func flow(_ keeper: Keeper, owner: Bool = true, answers: Bool = true, owned: @escaping () -> Void = {},
                      redeem: @escaping (PairingInvite) async throws -> (Pairing, String) = { _ in throw Refused() }) -> PairingFlow {
        PairingFlow(keeper: keeper, ownerCheck: { _ in owned(); return owner }, redeem: redeem, answers: { _ in answers })
    }

    func testALinkFromOutsideTheAppPairsNothingAndLeavesThePairingAsItWas() async {
        for link in [evilLink, evilCode] {
            let keeper = Keeper(home)
            let flow = flow(keeper, redeem: { _ in XCTFail("a link from outside is never redeemed"); throw Refused() })
            flow.opened(URL(string: link)!)
            XCTAssertTrue(flow.fromOutside, "it says to scan inside Pointe")
            XCTAssertNil(flow.offer, "and offers nothing to confirm")
            await flow.confirm()
            XCTAssertEqual(keeper.stored, home)
            XCTAssertEqual(keeper.saves, [])
            XCTAssertEqual(flow.pairing, home)
        }
        let unpaired = Keeper(nil)
        let flow = flow(unpaired)
        flow.opened(URL(string: evilLink)!)
        await flow.confirm()
        XCTAssertNil(unpaired.stored, "not even on a phone with no pairing yet")
        XCTAssertNil(flow.pairing)
    }

    func testAScanInTheAppShowsTheHostAndCertificateAndPairsOnlyOnConfirm() async {
        let keeper = Keeper(nil)
        var asked = false
        let flow = flow(keeper, owned: { asked = true })
        flow.scanned(evilLink)
        let offer = try? XCTUnwrap(flow.offer)
        XCTAssertEqual(offer?.host, "evil.example")
        XCTAssertTrue(offer?.message.contains("evil.example:443") == true, offer?.message ?? "")
        XCTAssertTrue(offer?.message.contains(String(otherFp.prefix(16))) == true, "the certificate's first characters")
        XCTAssertEqual(keeper.saves, [], "nothing is kept before the owner confirms")
        await flow.confirm()
        XCTAssertEqual(keeper.stored?.host, "evil.example")
        XCTAssertFalse(asked, "a first pairing is a confirm, no Face ID")
        XCTAssertNil(flow.offer)
    }

    func testCancelKeepsWhatWasThere() {
        let keeper = Keeper(home)
        let flow = flow(keeper)
        flow.scanned(evilLink)
        flow.cancel()
        XCTAssertNil(flow.offer)
        XCTAssertEqual(keeper.saves, [])
        XCTAssertEqual(flow.pairing, home)
    }

    func testReplacingAPairingNamesBothMacsAndNeedsTheOwner() async {
        let keeper = Keeper(home)
        let flow = flow(keeper, owner: false)
        flow.scanned(evilLink)
        XCTAssertEqual(flow.offer?.replaces, "studio.example.ts.net")
        XCTAssertTrue(flow.offer?.title.contains("studio.example.ts.net") == true && flow.offer?.title.contains("evil.example") == true,
                      flow.offer?.title ?? "")
        await flow.confirm()
        XCTAssertEqual(keeper.saves, [], "no Face ID, no replace")
        XCTAssertEqual(flow.pairing, home)

        let yes = self.flow(keeper, owner: true)
        yes.scanned(evilLink)
        await yes.confirm()
        XCTAssertEqual(keeper.stored?.host, "evil.example")
        XCTAssertEqual(yes.pairing?.host, "evil.example")
    }

    func testTheOldPairingStaysUntilTheNewOneAnswers() async {
        let keeper = Keeper(home)
        let failed = flow(keeper, owner: true, redeem: { _ in throw PairingInvite.Failure.said("This code has expired.") })
        failed.scanInside()
        XCTAssertTrue(failed.scanning, "paired: the scanner opens over the call")
        failed.scanned(evilCode)
        await failed.confirm()
        XCTAssertFalse(failed.scanning, "the scanner closes, so the note about the code shows")
        XCTAssertEqual(keeper.saves, [], "a code that was not redeemed replaces nothing")
        XCTAssertEqual(failed.pairing, home)
        XCTAssertEqual(failed.note?.state, .failed)
        XCTAssertTrue(failed.note?.text.contains("studio.example.ts.net") == true, "it says the old pairing is kept")

        let silent = flow(keeper, owner: true, answers: false)
        silent.scanned(evilLink)
        await silent.confirm()
        XCTAssertEqual(keeper.saves, [], "a pairing whose Mac does not answer replaces nothing")
        XCTAssertEqual(silent.pairing, home)

        let redeemed = Pairing(host: "evil.example", port: 443, fingerprint: otherFp, key: String(repeating: "n", count: 43))
        let good = flow(keeper, owner: true, redeem: { _ in (redeemed, "Studio") })
        good.scanned(evilCode)
        await good.confirm()
        XCTAssertEqual(keeper.stored, redeemed)
        XCTAssertEqual(good.note?.state, .done)
    }

    func testSomethingElseIsNotAPairingCode() {
        let keeper = Keeper(home)
        let flow = flow(keeper)
        flow.scanned("https://evil.example/")
        XCTAssertNil(flow.offer)
        XCTAssertEqual(flow.note?.state, .failed)
        XCTAssertEqual(keeper.saves, [])
    }
}
