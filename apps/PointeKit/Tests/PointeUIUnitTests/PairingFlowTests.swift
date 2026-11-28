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
        // One machine: several machines off (PairedMachinesTests covers it on).
        PairingFlow(keeper: keeper, ownerCheck: { _ in owned(); return owner }, redeem: redeem,
                    answers: { p in answers ? nil : ConnectionProblem(cause: .timedOut, host: p.host, port: p.port) }, several: { false })
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
        let failed = flow(keeper, owner: true, redeem: { i in throw ConnectionProblem(cause: .codeSpent, host: i.host, port: i.port) })
        failed.scanInside()
        XCTAssertTrue(failed.scanning, "paired: the scanner opens over the call")
        failed.scanned(evilCode)
        await failed.confirm()
        XCTAssertFalse(failed.scanning, "the scanner closes, so the note about the code shows")
        XCTAssertEqual(keeper.saves, [], "a code that was not redeemed replaces nothing")
        XCTAssertEqual(failed.pairing, home)
        XCTAssertEqual(failed.problem?.cause, .codeSpent)
        XCTAssertTrue(failed.kept?.contains("studio.example.ts.net") == true, "it says the old pairing is kept")

        let silent = flow(keeper, owner: true, answers: false)
        silent.scanned(evilLink)
        await silent.confirm()
        XCTAssertEqual(keeper.saves, [], "a pairing whose Mac does not answer replaces nothing")
        XCTAssertEqual(silent.pairing, home)
        XCTAssertEqual(silent.problem?.cause, .timedOut, "and says why")

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

    // MARK: a code that did not pair stays on screen until the person acts (docs/phone.md)

    private lazy var nowhereCode = "pointe://pair?v=2&host=pointe.example.internal&port=7443&fp=\(fp)&code=AB12-CD34"

    /// The owner's morning: the name did not resolve, an orange line showed and went, and the screen was stuck.
    func testAFailedCodeStaysUntilThePersonActsAndTryAgainTradesTheSameCode() async {
        var tries = 0
        let keeper = Keeper(nil)
        let flow = flow(keeper, redeem: { i in
            tries += 1
            throw ConnectionProblem(cause: .nameNotFound, host: i.host, port: i.port)
        })
        flow.scanned(nowhereCode)
        let before = flow.attempt
        await flow.confirm()
        XCTAssertEqual(flow.problem?.cause, .nameNotFound)
        XCTAssertEqual(flow.problem?.place, "pointe.example.internal:7443")
        XCTAssertNil(flow.note, "the problem is the card, not a note that goes by itself")
        XCTAssertGreaterThan(flow.attempt, before, "the camera reads again behind it")
        try? await Task.sleep(for: .milliseconds(50))
        XCTAssertNotNil(flow.problem, "nothing clears it but the person")

        await flow.retry()
        XCTAssertEqual(tries, 2, "Try again trades the same code: the Mac spends it only when it pairs")
        XCTAssertEqual(flow.problem?.cause, .nameNotFound, "still failing: still said")

        flow.pairAgain()
        XCTAssertNil(flow.problem)
        XCTAssertFalse(flow.scanning, "unpaired: the pairing screen's own camera, not a sheet")
        await flow.retry()
        XCTAssertEqual(tries, 2, "after Pair again there is no old code to try")
    }

    func testTryAgainPairsOnceTheMacIsBack() async {
        var up = false
        let keeper = Keeper(nil)
        let made = Pairing(host: "pointe.example.internal", port: 7443, fingerprint: fp, key: key)
        let flow = flow(keeper, redeem: { i in
            guard up else { throw ConnectionProblem(cause: .timedOut, host: i.host, port: i.port) }
            return (made, "Studio")
        })
        flow.scanned(nowhereCode)
        await flow.confirm()
        XCTAssertEqual(flow.problem?.cause, .timedOut)
        up = true  // `colima start`: the connector is back
        await flow.retry()
        XCTAssertNil(flow.problem)
        XCTAssertEqual(keeper.stored, made)
        XCTAssertEqual(flow.note?.state, .done)
    }

    func testANewCodeTakesThePlaceOfTheProblem() async {
        let flow = flow(Keeper(nil), redeem: { i in throw ConnectionProblem(cause: .refused, host: i.host, port: i.port) })
        flow.scanned(nowhereCode)
        await flow.confirm()
        XCTAssertNotNil(flow.problem)
        flow.scanned(evilCode)
        XCTAssertNil(flow.problem, "a new code is the person acting")
        XCTAssertEqual(flow.offer?.host, "evil.example")
    }

    func testOverTheCallPairAgainOpensTheScannerAndKeepsThePairing() async {
        let keeper = Keeper(home)
        let flow = flow(keeper, redeem: { i in throw ConnectionProblem(cause: .nameNotFound, host: i.host, port: i.port) })
        flow.scanned(nowhereCode)
        await flow.confirm()
        XCTAssertEqual(flow.kept, "Still paired with studio.example.ts.net.")
        flow.pairAgain()
        XCTAssertTrue(flow.scanning, "paired: the scanner over the call")
        XCTAssertNil(flow.kept)
        XCTAssertEqual(flow.pairing, home)
    }

    /// A pairing went through: that note goes by itself. Anything that failed, or is still working, stays.
    func testOnlyASuccessGoesByItself() {
        XCTAssertEqual(PairingFlow.dismissAfter(PairingNote(text: "Paired with Studio.", state: .done)), .seconds(6))
        XCTAssertNil(PairingFlow.dismissAfter(PairingNote(text: "That is not a Pointe pairing code.", state: .failed)))
        XCTAssertNil(PairingFlow.dismissAfter(PairingNote(text: "Pairing with your Mac…", state: .working)))
    }

    /// Unpair, then a first pairing (which asks no Face ID), was the way around "replacing a pairing needs Face ID".
    func testUnpairingNeedsTheOwnerAndNamesTheMac() async {
        let keeper = Keeper(home)
        var reasons: [String] = []
        let no = PairingFlow(keeper: keeper, ownerCheck: { reasons.append($0); return false },
                             redeem: { _ in throw Refused() }, answers: { _ in nil })
        await no.unpair()
        XCTAssertEqual(keeper.stored, home, "no Face ID, no unpair")
        XCTAssertEqual(no.pairing, home)
        XCTAssertTrue(reasons.first?.contains("studio.example.ts.net") == true, reasons.first ?? "the owner was not asked")

        let yes = flow(keeper, owner: true)
        await yes.unpair()
        XCTAssertNil(keeper.stored)
        XCTAssertNil(yes.pairing)
    }

    /// The alert names one Mac: a code the camera reads under it, or a paste, does not change what Pair confirms.
    func testTheConfirmPairsOnlyTheOfferOnScreen() async {
        let keeper = Keeper(nil)
        let flow = flow(keeper)
        let mine = "pointe://pair?v=1&host=studio.example.ts.net&port=7443&fp=\(fp)&key=\(key)"
        flow.scanned(mine)
        let shown = try? XCTUnwrap(flow.offer)
        flow.scanned(evilLink)
        XCTAssertEqual(flow.offer, shown, "a scan while an offer is on screen is ignored")

        flow.cancel()
        flow.scanned(evilLink)  // the offer changed under an alert still showing the first
        await flow.confirmTapped(shown!)?.value
        XCTAssertEqual(keeper.saves, [], "Pair on the old alert pairs nothing")
        XCTAssertNil(flow.offer)

        flow.scanned(mine)
        await flow.confirmTapped(flow.offer!)?.value
        XCTAssertEqual(keeper.stored?.host, "studio.example.ts.net")
    }

    func testTheConfirmSaysToCompareTheCertificateWithTheMac() {
        let flow = flow(Keeper(nil))
        flow.scanned(evilLink)
        let message = flow.offer?.message ?? ""
        XCTAssertTrue(message.contains(String(otherFp.prefix(16))) && message.contains("should match what your Mac shows"), message)
    }
}
