import Foundation
import Observation

/// Where the pairings are kept: the Keychain in the app (`KeychainPairing`), something else in a test. A keeper that
/// holds one pairing gets the several-machine calls as that one.
protocol PairingKeeping: Sendable {
    /// The current machine.
    func load() -> Pairing?
    /// This machine in place of every other.
    func save(_ pairing: Pairing)
    /// Every pairing.
    func forget()
    /// Every machine, in the list's order.
    func all() -> [Pairing]
    /// Beside the others (the same machine's entry replaced), and current.
    func add(_ pairing: Pairing)
    /// This one only; the current one moves to the first left.
    func remove(_ pairing: Pairing)
    /// Calls go to this one.
    func select(_ pairing: Pairing)
}

extension PairingKeeping {
    func all() -> [Pairing] { load().map { [$0] } ?? [] }
    func add(_ pairing: Pairing) { save(pairing) }
    func remove(_ pairing: Pairing) { forget() }
    func select(_ pairing: Pairing) {}
}

/// The Keychain and this device's choice of machine.
struct KeychainPairing: PairingKeeping {
    private var machines: PairedMachines { PairedMachines(vault: PairingStore.vault, choice: DefaultsChoice()) }
    func load() -> Pairing? { machines.current }
    func save(_ pairing: Pairing) { machines.only(pairing) }
    func forget() { machines.removeAll() }
    func all() -> [Pairing] { machines.ordered }
    func add(_ pairing: Pairing) { machines.add(pairing) }
    func remove(_ pairing: Pairing) { machines.remove(pairing) }
    func select(_ pairing: Pairing) { machines.select(pairing) }
}

/// A code scanned or pasted in the app, waiting for the owner's yes: the Mac it names, and the one it would replace.
struct PairingOffer: Equatable {
    let link: PairingLink
    /// The host paired now, when there is one: replacing it needs Face ID.
    let replaces: String?
    /// Several machines: this one goes beside the others. Adding to a phone that has one needs Face ID too: it opens a
    /// microphone into more sessions.
    var adding = false

    private var place: (host: String, port: Int, fingerprint: String) {
        switch link {
        case .ready(let p): (p.host, p.port, p.fingerprint)
        case .invite(let i): (i.host, i.port, i.fingerprint)
        }
    }

    var host: String { place.host }
    var title: String {
        if adding { return "Add \(host) to this phone?" }
        return replaces.map { "Replace your Mac \($0) with \(host)?" } ?? "Pair with \(host)?"
    }
    var message: String {
        if adding {
            return "Pointe will talk to \(host):\(place.port), certificate \(place.fingerprint.prefix(16))…, which should match what that machine shows beside the code. Go on only if the machine is yours, or its owner gave you this code. The machines you have stay."
        }
        return "Pointe will talk only to \(host):\(place.port), certificate \(place.fingerprint.prefix(16))…, which should match what your Mac shows beside the code. Go on only if this is your own Mac."
    }
    var action: String { adding ? "Add" : replaces == nil ? "Pair" : "Replace" }
    var ownerReason: String { adding ? "Add \(host) to this phone" : "Replace your Mac \(replaces ?? "") with \(host)" }
    /// Face ID before it is kept.
    var needsOwner: Bool { adding || replaces != nil }
}

/// Which Mac the iPhone talks to, and who may change it (SECURITY.md, "The iPhone app"). Only a code scanned or pasted
/// in the app is offered, and only the owner's confirm keeps it; a `pointe://` link opened from outside (another app, a
/// web page, the Camera) pairs nothing. Replacing a pairing needs Face ID, and the old one stays until the new answers.
@MainActor @Observable
final class PairingFlow {
    /// The current machine: the call goes to it.
    private(set) var pairing: Pairing?
    /// Every machine on this phone, in the list's order (one, with several machines off).
    private(set) var pairings: [Pairing] = []
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
    private let several: () -> Bool

    /// `redeem` trades a one-time code for the phone key; `answers` asks a pairing's Mac over its pinned connection:
    /// nil when it answered, else why not.
    init(keeper: PairingKeeping, ownerCheck: @escaping (String) async -> Bool,
         redeem: @escaping (PairingInvite) async throws -> (Pairing, String),
         answers: @escaping (Pairing) async -> ConnectionProblem?, several: @escaping () -> Bool = { SeveralMachines.on }) {
        self.keeper = keeper
        self.ownerCheck = ownerCheck
        self.redeem = redeem
        self.answers = answers
        self.several = several
        reload()
    }

    private func reload() {
        pairing = keeper.load()
        pairings = keeper.all()
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
        let adding = several() && pairing != nil
        offer = PairingOffer(link: link, replaces: adding ? nil : pairing?.host, adding: adding)
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
        kept = (offer.replaces ?? (offer.adding ? pairing?.label : nil)).map(ProblemCopy.stillPaired)
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
        if offer.needsOwner, !(await ownerCheck(offer.ownerReason)) {
            attempt += 1
            return
        }
        scanning = false  // the note about the code shows over the call, not under the scanner
        switch offer.link {
        case .ready(let p):
            if offer.needsOwner, let why = await answers(p) {
                fail(why, offer)
                return
            }
            adopt(p)
            note = PairingNote(text: offer.adding ? "Added \(p.label)." : "Paired with your Mac.", state: .done)
        case .invite(let invite):
            note = PairingNote(text: "Pairing with your Mac…", state: .working)
            do {
                let (p, mac) = try await redeem(invite)
                adopt(p)
                note = PairingNote(text: offer.adding ? "Added \(mac)." : "Paired with \(mac).", state: .done)
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
        if several() { keeper.add(p) } else { keeper.save(p) }
        reload()
        if pairing == nil { pairing = p }
        scanning = false
    }

    /// Calls go to this machine from now on (a tap in the list, or "call kite"). The call view follows `pairing`.
    func select(_ p: Pairing) {
        guard pairings.contains(where: { $0.storeKey == p.storeKey }) else { return }
        keeper.select(p)
        reload()
    }

    /// The machine's status named it: kept with its id and name, so its entry is found again by its id. Not a change
    /// of machine: the current one stays.
    func learned(_ p: Pairing, id: String?, name: String?) {
        guard let entry = pairings.first(where: { PairedMachines.same($0, p) }) else { return }
        var better = entry
        better.id = entry.id ?? id
        better.name = name ?? entry.name
        guard better != entry else { return }
        let wasCurrent = pairing.map { PairedMachines.same($0, entry) } ?? false
        keeper.add(better)
        if !wasCurrent, let current = pairing { keeper.select(current) }
        reload()
    }

    /// Routes its status listed: kept, so the machine is reached another way when this one fails.
    func learned(_ p: Pairing, routes: [Pairing.Route]) {
        guard let entry = pairings.first(where: { PairedMachines.same($0, p) }) else { return }
        replace(entry, with: entry.learning(routes))
    }

    /// The machine answered on another of its routes: that one is used from now on.
    func reroute(_ p: Pairing, to route: Pairing.Route) {
        guard let entry = pairings.first(where: { PairedMachines.same($0, p) }) else { return }
        replace(entry, with: entry.using(route))
    }

    private func replace(_ entry: Pairing, with better: Pairing) {
        guard better != entry else { return }
        let current = pairing
        keeper.add(better)
        if let current, !PairedMachines.same(current, entry) { keeper.select(current) }
        reload()
    }

    /// The list's Remove, after its confirm: this machine only. Taking access away needs no Face ID.
    func remove(_ p: Pairing) {
        keeper.remove(p)
        reload()
    }

    /// Settings → Unpair this phone, after its confirm. Face ID or the passcode, as for a replace: otherwise someone
    /// holding the unlocked phone could unpair it and scan their own Mac's code, which a first pairing does not ask for.
    /// With several machines it is the current one only.
    func unpair() async {
        guard let current = pairing, await ownerCheck("Unpair this phone from \(current.host)") else { return }
        if several() && pairings.count > 1 { keeper.remove(current) } else { keeper.forget() }
        reload()
    }
}
