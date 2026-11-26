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
        #if DEBUG  // UI tests start unpaired; a Release build takes no pairing change from its launch environment
        if ProcessInfo.processInfo.environment["POINTE_FORGET"] == "1" { PairingStore.forget() }
        #endif
        API.deviceHeader = API.header(for: UIDevice.current.name)
        #endif
        Brand.registerFonts()
        AlertCenter.shared.start()  // before an action that launched the app is handed over
        #if os(iOS)
        PhoneTalk.shared.start()  // before a press from the Lock Screen that launched the app is handed over
        #endif
        Brand.install()
    }

    /// Where the fonts and the logo are.
    nonisolated public static let bundle = Bundle.module

    #if os(iOS)
    /// Background App Refresh: the task's name, and what it does (Alerts.swift).
    public static let refreshTask = AlertCenter.refreshTask
    public static func refresh() async {
        await PhoneTalk.shared.refreshWidget()  // the widget's look at the Mac, when Talk from outside the app is on
        await AlertCenter.shared.refresh()
    }
    #endif
}

#if os(iOS)
/// The iPhone app: the pairing screen until a Mac is paired, then the call.
public struct PointeRoot: View {
    @State private var flow: PairingFlow
    @State private var tried: Demo?  // "Try a demo" on the pairing screen; nothing is paired or saved
    @State private var helping: ConnectionProblem?  // "How to fix" open on a pairing problem
    @State private var machineLine: String?  // a machine invite that opened the app: Add a machine opens on it
    @AppStorage(Theme.key) private var theme = Theme.fallback.rawValue  // Settings' Appearance: System, Light or Dark

    public init() {
        _flow = State(initialValue: PairingFlow(keeper: KeychainPairing(), ownerCheck: Self.ownerCheck,
                                                redeem: Self.redeem, answers: Self.answers))
    }

    public var body: some View {
        Group {
            if let demo = Demo.fromLaunch() {
                CallView(pairing: Demo.pairing, unpair: {}, demo: demo, incoming: $machineLine)
            } else if let tried {
                CallView(pairing: Demo.pairing, unpair: { self.tried = nil }, demo: tried)
            } else if let pairing = flow.pairing {
                // The call is PhoneTalk's, so a press from the Lock Screen can dial it with no screen up.
                CallView(link: DaemonLink(pairing), call: PhoneTalk.shared.call(for: pairing), shell: PhoneTalk.shared,
                         unpair: { Task { await flow.unpair() } }, pairAgain: { flow.pairAgain() }, incoming: $machineLine)
                    .id(pairing)  // a new pairing is a new call: the old one pins the old certificate
            } else {
                PairView(flow: flow, tryDemo: { tried = Demo.tryIt }, help: { helping = $0 })
            }
        }
        .overlay(alignment: .top) {
            if let problem = flow.problem, flow.pairing != nil, tried == nil {
                // Over a call that still works: the new code failed, and the pairing it would have replaced stays.
                ProblemCard(problem: problem, kept: flow.kept, close: { flow.dismissProblem() }) { act($0, problem) }
                    .padding(.horizontal, 16).padding(.top, 8)
            } else if let note = flow.note {
                PairingBanner(note: note) { flow.note = nil }
            }
        }
        .task(id: flow.note) {  // only a pairing that went through goes by itself (PairingFlow.dismissAfter)
            guard let note = flow.note, let after = PairingFlow.dismissAfter(note) else { return }
            try? await Task.sleep(for: after)
            if flow.note == note { flow.note = nil }
        }
        .sheet(isPresented: Binding(get: { helping != nil }, set: { if !$0 { helping = nil } })) {
            if let helping { ConnectionHelpSheet(problem: helping) { self.helping = nil } }
        }
        .preferredColorScheme(Theme.stored(theme).scheme)
        .tint(Brand.accent)
        .font(.brand(.body))
        .foregroundStyle(Brand.text)
        // A pointe:// link from another app, a web page or the Camera pairs nothing: any of them can open one
        // (SECURITY.md, "The iPhone app"). It only says to scan the code inside Pointe. A machine invite
        // (pointe://machine?…) changes no pairing: on a paired phone it opens Add a machine with the line in it, and
        // nothing is sent until the owner chooses Add and passes Face ID (AddMachineModel).
        .onOpenURL { url in
            if let invite = Self.machineInvite(url, paired: flow.pairing != nil || Demo.fromLaunch() != nil) { machineLine = invite }
            else { flow.opened(url) }
        }
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
        .task {  // UI tests in a Debug build: a link given at launch replaces any earlier pairing, with no confirm
            #if DEBUG
            if let link = ProcessInfo.processInfo.environment["POINTE_PAIR"], let p = Pairing(link: link), p != flow.pairing {
                flow.adopt(p)
            }
            #endif
        }
    }

    /// The line of a machine invite that opened the app, on a phone that has a Mac to add it to; nil for any other link.
    static func machineInvite(_ url: URL, paired: Bool) -> String? {
        guard paired, let invite = MachineLine(url.absoluteString) else { return nil }
        return invite.line
    }

    private func act(_ action: ConnectionProblem.Action, _ problem: ConnectionProblem) {
        switch action {
        case .tryAgain: flow.retryTapped()
        case .pairAgain: flow.pairAgain()
        case .howToFix: helping = problem
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

    /// The new Mac answers its status with the new key, over a connection pinned to its certificate: nil, or why not.
    private static func answers(_ pairing: Pairing) async -> ConnectionProblem? {
        let link = DaemonLink(pairing)
        let session = link.session(onOpen: {})
        defer { session.finishTasksAndInvalidate() }
        do {
            let (_, response) = try await session.data(for: link.request("voice/status"))
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            if code == 200 { return nil }
            return link.problem(status: code) ?? ConnectionProblem(cause: .other("HTTP \(code)"), host: pairing.host, port: pairing.port)
        } catch {
            return link.problem(error, pinRefused: (session.delegate as? PinnedDelegate)?.refused ?? false)
        }
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
