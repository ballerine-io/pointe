import CoreText
import SwiftUI
#if os(iOS)
import LocalAuthentication
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
    @State private var flow: PairingFlow
    @State private var tried: Demo?  // "Try a demo" on the pairing screen; nothing is paired or saved
    @AppStorage(Theme.key) private var theme = Theme.fallback.rawValue  // Settings' Appearance: System, Light or Dark

    public init() {
        _flow = State(initialValue: PairingFlow(keeper: KeychainPairing(), ownerCheck: Self.ownerCheck,
                                                redeem: Self.redeem, answers: Self.answers))
    }

    public var body: some View {
        Group {
            if let demo = Demo.fromLaunch() {
                CallView(pairing: Demo.pairing, unpair: {}, demo: demo)
            } else if let tried {
                CallView(pairing: Demo.pairing, unpair: { self.tried = nil }, demo: tried)
            } else if let pairing = flow.pairing {
                CallView(pairing: pairing, unpair: { flow.unpair() })
                    .id(pairing)  // a new pairing is a new call: the old one pins the old certificate
            } else {
                PairView(flow: flow, tryDemo: { tried = Demo.tryIt })
            }
        }
        .overlay(alignment: .top) { if let note = flow.note { PairingBanner(note: note) { flow.note = nil } } }
        .task(id: flow.note) {  // a success goes by itself; a problem stays a while longer
            guard let note = flow.note, note.state != .working else { return }
            try? await Task.sleep(for: .seconds(note.state == .done ? 6 : 15))
            if flow.note == note { flow.note = nil }
        }
        .preferredColorScheme(Theme.stored(theme).scheme)
        .tint(Brand.accent)
        .font(.brand(.body))
        .foregroundStyle(Brand.text)
        // A pointe:// link from another app, a web page or the Camera pairs nothing: any of them can open one
        // (SECURITY.md, "The iPhone app"). It only says to scan the code inside Pointe.
        .onOpenURL { url in flow.opened(url) }
        .sheet(isPresented: Binding(get: { flow.fromOutside || flow.scanning },
                                    set: { if !$0 { flow.fromOutside = false; flow.scanning = false } })) {
            if flow.fromOutside {
                ScanInsideSheet(scan: { tried = nil; flow.scanInside() }, close: { flow.fromOutside = false })
            } else {
                NavigationStack {
                    PairView(flow: flow, tryDemo: nil)
                        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { flow.scanning = false } } }
                }
            }
        }
        .task {  // tests and the simulator: a link given at launch replaces any earlier pairing (no other app sets this)
            if let link = ProcessInfo.processInfo.environment["POINTE_PAIR"], let p = Pairing(link: link), p != flow.pairing {
                flow.adopt(p)
            }
        }
    }

    /// Face ID or the passcode, as for Approve: replacing the Mac this phone talks to.
    private static func ownerCheck(_ reason: String) async -> Bool {
        (try? await LAContext().evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)) == true
    }

    private static func redeem(_ invite: PairingInvite) async throws -> (Pairing, String) {
        let (device, id) = await MainActor.run { (UIDevice.current.name, UIDevice.current.identifierForVendor?.uuidString ?? "") }
        return try await invite.redeem(device: device, id: id)
    }

    /// The new Mac answers its status with the new key, over a connection pinned to its certificate.
    private static func answers(_ pairing: Pairing) async -> Bool {
        let link = DaemonLink(pairing)
        let session = link.session(onOpen: {})
        defer { session.finishTasksAndInvalidate() }
        guard let (_, response) = try? await session.data(for: link.request("voice/status")) else { return false }
        return (response as? HTTPURLResponse)?.statusCode == 200
    }
}

#endif

struct PairingNote: Equatable {
    enum State { case working, done, failed }
    let text: String
    let state: State
}

/// What became of a pairing code, over whatever the app shows.
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
