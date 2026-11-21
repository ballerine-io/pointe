import CoreText
import SwiftUI
#if os(iOS)
import UIKit
#endif

/// What an app does once, before its first screen (the iPhone app's `init`): the pairing a UI test asked to forget,
/// this device's name for the Mac's list, the alerts, the brand's fonts.
@MainActor
public enum PointeBoot {
    public static func start() {
        #if os(iOS)
        if ProcessInfo.processInfo.environment["POINTE_FORGET"] == "1" { PairingStore.forget() }  // UI tests start unpaired
        API.deviceHeader = API.header(for: UIDevice.current.name)
        #endif
        Brand.registerFonts()
        AlertCenter.shared.start()  // before an action that launched the app is handed over
        Brand.install()
    }

    /// Where the fonts and the logo are.
    nonisolated public static let bundle = Bundle.module

    #if os(iOS)
    /// Background App Refresh: the task's name, and what it does (Alerts.swift).
    public static let refreshTask = AlertCenter.refreshTask
    public static func refresh() async { await AlertCenter.shared.refresh() }
    #endif
}

#if os(iOS)
/// The iPhone app: the pairing screen until a Mac is paired, then the call.
public struct PointeRoot: View {
    @State private var pairing: Pairing?
    @State private var note: PairingNote?
    @State private var tried: Demo?  // "Try a demo" on the pairing screen; nothing is paired or saved
    @AppStorage(Theme.key) private var theme = Theme.fallback.rawValue  // Settings' Appearance: System, Light or Dark

    public init() {
        _pairing = State(initialValue: PairingStore.load())
    }

    public var body: some View {
        Group {
            if let demo = Demo.fromLaunch() {
                CallView(pairing: Demo.pairing, unpair: {}, demo: demo)
            } else if let tried {
                CallView(pairing: Demo.pairing, unpair: { self.tried = nil }, demo: tried)
            } else if let pairing {
                CallView(pairing: pairing, unpair: { PairingStore.forget(); self.pairing = nil })
                    .id(pairing)  // a new pairing is a new call: the old one pins the old certificate
            } else {
                PairView(submit: accept, tryDemo: { tried = Demo.tryIt })
            }
        }
        .overlay(alignment: .top) { if let note { PairingBanner(note: note) { self.note = nil } } }
        .task(id: note) {  // a success goes by itself; a problem stays a while longer
            guard let note, note.state != .working else { return }
            try? await Task.sleep(for: .seconds(note.state == .done ? 6 : 15))
            if self.note == note { self.note = nil }
        }
        .preferredColorScheme(Theme.stored(theme).scheme)
        .tint(Brand.accent)
        .font(.brand(.body))
        .foregroundStyle(Brand.text)
        .onOpenURL { url in accept(url.absoluteString) }  // scanned with the Camera app: pointe://pair?...
        .task {  // tests and the simulator: a link given at launch replaces any earlier pairing
            if let link = ProcessInfo.processInfo.environment["POINTE_PAIR"], let p = Pairing(link: link), p != pairing {
                PairingStore.save(p); pairing = p
            }
        }
    }

    /// A `pointe://pair` link from the Camera, the scanner or a paste: a pairing to keep, or a one-time code to trade.
    private func accept(_ link: String) {
        tried = nil  // a pairing code opened during the demo leaves it
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

#endif

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
            case .done: Image(systemName: "checkmark.circle.fill").foregroundStyle(Brand.successText)
            case .failed: Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Brand.accent)
            }
            Text(note.text).font(.brand(.callout, .semibold)).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("pairing-note")
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(note.state == .failed ? Brand.orangeLine : Brand.lineStrong))
        .padding(.horizontal, 16).padding(.top, 8)
        .onTapGesture(perform: dismiss)
        .accessibilityAddTraits(.updatesFrequently)
    }
}
