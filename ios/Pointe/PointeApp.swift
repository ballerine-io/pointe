import SwiftUI

@main
struct PointeApp: App {
    @State private var pairing: Pairing?
    @State private var note: PairingNote?

    init() {
        if ProcessInfo.processInfo.environment["POINTE_FORGET"] == "1" { PairingStore.forget() }  // UI tests start unpaired
        _pairing = State(initialValue: PairingStore.load())
        AlertCenter.shared.start()  // before an action that launched the app is handed over
    }

    var body: some Scene {
        WindowGroup {
            Group {
                if let demo = Demo.fromLaunch() {
                    CallView(pairing: Demo.pairing, unpair: {}, demo: demo)
                } else if let pairing {
                    CallView(pairing: pairing, unpair: { PairingStore.forget(); self.pairing = nil })
                        .id(pairing)  // a new pairing is a new call: the old one pins the old certificate
                } else {
                    PairView(submit: accept)
                }
            }
            .overlay(alignment: .top) { if let note { PairingBanner(note: note) { self.note = nil } } }
            .task(id: note) {  // a success goes by itself; a problem stays a while longer
                guard let note, note.state != .working else { return }
                try? await Task.sleep(for: .seconds(note.state == .done ? 6 : 15))
                if self.note == note { self.note = nil }
            }
            .preferredColorScheme(.dark)
            .tint(Brand.orange)
            .onOpenURL { url in accept(url.absoluteString) }  // scanned with the Camera app: pointe://pair?...
            .task {  // tests and the simulator: a link given at launch replaces any earlier pairing
                if let link = ProcessInfo.processInfo.environment["POINTE_PAIR"], let p = Pairing(link: link), p != pairing {
                    PairingStore.save(p); pairing = p
                }
            }
        }
        .backgroundTask(.appRefresh(AlertCenter.refreshTask)) { await AlertCenter.shared.refresh() }
    }

    /// A `pointe://pair` link from the Camera, the scanner or a paste: a pairing to keep, or a one-time code to trade.
    private func accept(_ link: String) {
        switch PairingLink(link) {
        case .ready(let p)?:
            PairingStore.save(p); pairing = p
            note = PairingNote(text: "Paired with your Mac. Tap Connect to call.", state: .done)
        case .invite(let invite)?:
            note = PairingNote(text: "Pairing with your Mac…", state: .working)
            Task { @MainActor in
                do {
                    let (p, mac) = try await invite.redeem(device: UIDevice.current.name,
                                                           id: UIDevice.current.identifierForVendor?.uuidString ?? "")
                    PairingStore.save(p); pairing = p
                    note = PairingNote(text: "Paired with \(mac). Tap Connect to call.", state: .done)
                } catch PairingInvite.Failure.said(let why) {
                    note = PairingNote(text: why, state: .failed)
                } catch {
                    note = PairingNote(text: PairingInvite.unreachable(host: invite.host), state: .failed)
                }
            }
        case nil:
            note = PairingNote(text: "That is not a Pointe pairing code.", state: .failed)
        }
    }
}

struct PairingNote: Equatable {
    enum State { case working, done, failed }
    let text: String
    let state: State
}

/// What became of a pairing link, over whatever the app shows.
struct PairingBanner: View {
    let note: PairingNote
    let dismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            switch note.state {
            case .working: ProgressView()
            case .done: Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
            case .failed: Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Brand.orange)
            }
            Text(note.text).font(.callout.weight(.semibold)).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("pairing-note")
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(note.state == .failed ? Brand.orange : .white.opacity(0.12)))
        .padding(.horizontal, 16).padding(.top, 8)
        .onTapGesture(perform: dismiss)
        .accessibilityAddTraits(.updatesFrequently)
    }
}

enum Brand {
    static let orange = Color(red: 1, green: 0.31, blue: 0.12)
    static let card = Color(red: 0.075, green: 0.11, blue: 0.165)
    static let background = Color(red: 0.043, green: 0.063, blue: 0.094)
}
