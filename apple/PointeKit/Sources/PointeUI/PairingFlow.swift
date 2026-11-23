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
        "Pointe will talk only to \(host):\(place.port), certificate \(place.fingerprint.prefix(16))…. Go on only if this is your own Mac and you scanned the code it shows."
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

    private let keeper: PairingKeeping
    private let ownerCheck: (String) async -> Bool
    private let redeem: (PairingInvite) async throws -> (Pairing, String)
    private let answers: (Pairing) async -> Bool

    /// `redeem` trades a one-time code for the phone key; `answers` asks a pairing's Mac over its pinned connection.
    init(keeper: PairingKeeping, ownerCheck: @escaping (String) async -> Bool,
         redeem: @escaping (PairingInvite) async throws -> (Pairing, String), answers: @escaping (Pairing) async -> Bool) {
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

    /// A code from the scanner or the paste field: offered to the owner, never kept before the confirm.
    func scanned(_ code: String) {
        guard let link = PairingLink(code) else {
            note = PairingNote(text: "That is not a Pointe pairing code.", state: .failed)
            attempt += 1
            return
        }
        offer = PairingOffer(link: link, replaces: pairing?.host)
    }

    func cancel() {
        offer = nil
        attempt += 1
    }

    /// The confirm button: the offer leaves the screen at once, and the rest follows.
    func confirmTapped() {
        guard let offer else { return }
        self.offer = nil
        Task { await finish(offer) }
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
        let kept = offer.replaces.map { " Still paired with \($0)." } ?? ""
        switch offer.link {
        case .ready(let p):
            if offer.replaces != nil, !(await answers(p)) {
                note = PairingNote(text: PairingInvite.unreachable(host: p.host) + kept, state: .failed)
                attempt += 1
                return
            }
            adopt(p)
            note = PairingNote(text: "Paired with your Mac. Tap Connect to call.", state: .done)
        case .invite(let invite):
            note = PairingNote(text: "Pairing with your Mac…", state: .working)
            do {
                let (p, mac) = try await redeem(invite)
                adopt(p)
                note = PairingNote(text: "Paired with \(mac). Tap Connect to call.", state: .done)
            } catch PairingInvite.Failure.said(let why) {
                note = PairingNote(text: why + kept, state: .failed)
                attempt += 1
            } catch {
                note = PairingNote(text: PairingInvite.unreachable(host: invite.host) + kept, state: .failed)
                attempt += 1
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

    func unpair() {
        keeper.forget()
        pairing = nil
    }
}
