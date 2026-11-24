import Foundation
import Observation

/// Where the pairing is kept: the Keychain in the app (`PairingStore`), something else in a test.
protocol PairingKeeping: Sendable {
    func load() -> Pairing?
    func save(_ pairing: Pairing)
    func forget()
}

struct KeychainPairing: PairingKeeping {
    func load() -> Pairing? { PairingStore.load() }
    func save(_ pairing: Pairing) { PairingStore.save(pairing) }
    func forget() { PairingStore.forget() }
}

/// A code scanned or pasted in the app, waiting for the owner's yes: the Mac it names, and the one it would replace.
struct PairingOffer: Equatable {
    let link: PairingLink
    /// The host paired now, when there is one: replacing it needs Face ID.
    let replaces: String?

    private var place: (host: String, port: Int, fingerprint: String) {
        switch link {
        case .ready(let p): (p.host, p.port, p.fingerprint)
        case .invite(let i): (i.host, i.port, i.fingerprint)
        }
    }

    var host: String { place.host }
    var title: String { replaces.map { "Replace your Mac \($0) with \(host)?" } ?? "Pair with \(host)?" }
    var message: String {
        "Pointe will talk only to \(host):\(place.port), certificate \(place.fingerprint.prefix(16))…, which should match what your Mac shows beside the code. Go on only if this is your own Mac."
    }
    var action: String { replaces == nil ? "Pair" : "Replace" }
    var ownerReason: String { "Replace your Mac \(replaces ?? "") with \(host)" }
}

/// Which Mac the iPhone talks to, and who may change it (SECURITY.md, "The iPhone app"). Only a code scanned or pasted
/// in the app is offered, and only the owner's confirm keeps it; a `pointe://` link opened from outside (another app, a
/// web page, the Camera) pairs nothing. Replacing a pairing needs Face ID, and the old one stays until the new answers.
@MainActor @Observable
final class PairingFlow {
    private(set) var pairing: Pairing?
    var note: PairingNote?
    /// A link arrived from outside the app: the sheet that says to scan inside Pointe.
    var fromOutside = false
    /// The scanner over the call, to pair with another Mac.
    var scanning = false
    /// The code waiting for the owner's confirm.
    private(set) var offer: PairingOffer?
    /// Changes when a scan ends without pairing: the scanner starts again.
    private(set) var attempt = 0
    /// Why the last code did not pair, read from what the phone saw. Nothing clears it on a timer: only Try again,
    /// Pair again, or a new code (a line that showed and went left the owner on a screen with no way forward).
    private(set) var problem: ConnectionProblem?
    /// Under the problem when a replacement failed: the pairing that is kept.
    private(set) var kept: String?
    /// The code that failed, for Try again: the Mac spends a code only when it pairs.
    private var failed: PairingOffer?

    private let keeper: PairingKeeping
    private let ownerCheck: (String) async -> Bool
    private let redeem: (PairingInvite) async throws -> (Pairing, String)
    private let answers: (Pairing) async -> ConnectionProblem?

    /// `redeem` trades a one-time code for the phone key; `answers` asks a pairing's Mac over its pinned connection:
    /// nil when it answered, else why not.
    init(keeper: PairingKeeping, ownerCheck: @escaping (String) async -> Bool,
         redeem: @escaping (PairingInvite) async throws -> (Pairing, String),
         answers: @escaping (Pairing) async -> ConnectionProblem?) {
        self.keeper = keeper
        self.ownerCheck = ownerCheck
        self.redeem = redeem
        self.answers = answers
        pairing = keeper.load()
    }

    /// A link the system opened the app with. Its content is never used: any app or web page can open one.
    func opened(_ url: URL) {
        offer = nil
        fromOutside = true
    }

    /// "Scan the code" on that sheet: the pairing screen's own scanner, or the scanner over the call.
    func scanInside() {
        fromOutside = false
        scanning = pairing != nil
    }

    /// A code from the scanner or the paste field: offered to the owner, never kept before the confirm. While one is
    /// on screen another is ignored: the camera keeps reading under the alert.
    func scanned(_ code: String) {
        guard offer == nil else { return }
        guard let link = PairingLink(code) else {
            note = PairingNote(text: "That is not a Pointe pairing code.", state: .failed)
            attempt += 1
            return
        }
        clearProblem()
        offer = PairingOffer(link: link, replaces: pairing?.host)
    }

    /// Try again: the same code, once more.
    func retry() async {
        guard let failed else { return }
        clearProblem()
        await finish(failed)
    }

    func retryTapped() { Task { await retry() } }

    /// Over a call that still works: the person keeps the pairing they have.
    func dismissProblem() { clearProblem() }

    /// Pair again: a new code from the Mac, on another route if this one does not work. Paired, the scanner opens over
    /// the call and the pairing stays until a new one works; unpaired, the pairing screen's camera reads again.
    func pairAgain() {
        clearProblem()
        attempt += 1
        scanning = pairing != nil
    }

    /// How long a note stays by itself: a pairing that went through goes; a failure or a step in progress stays.
    static func dismissAfter(_ note: PairingNote) -> Duration? { note.state == .done ? .seconds(6) : nil }

    private func clearProblem() {
        problem = nil
        kept = nil
        failed = nil
    }

    private func fail(_ why: ConnectionProblem, _ offer: PairingOffer) {
        note = nil
        problem = why
        kept = offer.replaces.map(ProblemCopy.stillPaired)
        failed = offer
        attempt += 1
    }

    func cancel() {
        offer = nil
        attempt += 1
    }

    /// The confirm button of the alert that showed `presented`: the offer leaves the screen at once, and the rest
    /// follows. An offer that is no longer the one on screen pairs nothing.
    @discardableResult
    func confirmTapped(_ presented: PairingOffer) -> Task<Void, Never>? {
        guard let offer else { return nil }
        self.offer = nil
        guard offer == presented else {
            attempt += 1
            return nil
        }
        return Task { await finish(offer) }
    }

    /// The owner said yes. A replace asks for Face ID first, and keeps the old pairing until the new Mac has answered.
    func confirm() async {
        guard let offer else { return }
        self.offer = nil
        await finish(offer)
    }

    private func finish(_ offer: PairingOffer) async {
        if offer.replaces != nil, !(await ownerCheck(offer.ownerReason)) {
            attempt += 1
            return
        }
        scanning = false  // the note about the code shows over the call, not under the scanner
        switch offer.link {
        case .ready(let p):
            if offer.replaces != nil, let why = await answers(p) {
                fail(why, offer)
                return
            }
            adopt(p)
            note = PairingNote(text: "Paired with your Mac.", state: .done)
        case .invite(let invite):
            note = PairingNote(text: "Pairing with your Mac…", state: .working)
            do {
                let (p, mac) = try await redeem(invite)
                adopt(p)
                note = PairingNote(text: "Paired with \(mac).", state: .done)
            } catch let why as ConnectionProblem {
                fail(why, offer)
            } catch {
                fail(ConnectionProblem(cause: .other(error.localizedDescription), host: invite.host, port: invite.port), offer)
            }
        }
    }

    /// Keeps a pairing that has been confirmed, or the one a UI test gave at launch (an environment variable no other
    /// app can set).
    func adopt(_ p: Pairing) {
        keeper.save(p)
        pairing = p
        scanning = false
    }

    /// Settings → Unpair this phone, after its confirm. Face ID or the passcode, as for a replace: otherwise someone
    /// holding the unlocked phone could unpair it and scan their own Mac's code, which a first pairing does not ask for.
    func unpair() async {
        guard let host = pairing?.host, await ownerCheck("Unpair this phone from \(host)") else { return }
        keeper.forget()
        pairing = nil
    }
}
