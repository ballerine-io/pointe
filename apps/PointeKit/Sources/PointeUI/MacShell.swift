#if os(macOS)
import AppKit
import PointeKit
import SwiftUI

/// The Mac app's side of a call, for its shell: the menu bar item, the call bubble, the talk shortcut and the
/// notifications (docs/design/macos-app.md). It holds the one call, which outlives the window, and reads the same
/// status the window does; the window itself is the shared call screen (`PointeMacRoot`), the one the iPhone draws.
@MainActor @Observable
public final class MacSession: CallShell {
    public enum Phase: Sendable { case off, connecting, live, reconnecting }
    /// What the menu bar item shows beside the mark: never by colour alone.
    public enum Glyph: Sendable { case down, off, live, talking, speaking, thinking, needsYou }
    public enum Command: Sendable { case settings, sessions, newSession, addSessions, brainDump, meeting, type, about, briefing, machines, phone, nightShift, approve, deny }

    /// A session that waits for an answer, for the menu.
    public struct Waiting: Identifiable, Equatable, Sendable {
        public let id: String
        public let label: String
    }

    let link: DaemonLink
    let call: Call
    private(set) var demo: Demo?
    private(set) var status: API.Status?
    private(set) var reach = Reach.ok
    private(set) var request: ShellRequest?
    private var requests = 0
    private var heard = Date.distantPast  // when the window last brought a status: while it does, this does not fetch
    private var poller: Task<Void, Never>?

    /// `daemon`: where the app verified Pointe to be on this Mac. A demo given at launch (`-demo call`) needs none.
    public init(daemon: LocalDaemon) {
        link = DaemonLink(local: daemon)
        call = Call(link: link)
        demo = Demo.fromLaunch()
        status = demo?.status
        AlertCenter.shared.local = link
        if let demo { call.follow(demo.status.ptt) }
    }

    /// Invented sessions on screen: nothing is fetched, sent or heard.
    public var isDemo: Bool { demo != nil }

    // MARK: what the shell shows

    public var phase: Phase {
        if demo != nil { return .live }
        switch call.state {
        case .off: return .off
        case .connecting: return .connecting
        case .live: return .live
        case .reconnecting: return .reconnecting
        }
    }

    public var live: Bool { phase == .live }
    public var pushToTalk: Bool { call.talk.ptt }
    public var talking: Bool { call.talk.ptt && call.talk.shows(macOpen: status?.ptt?.open == true) }
    public var muted: Bool { demo == nil ? call.muted : demo?.screen == .muted }
    public var speaking: Bool { demo == nil ? call.botSpeaking : demo?.screen == .speaking && !demoSkipped }
    var demoSkipped = false
    /// The owner's turn was taken and nothing is said yet: the state line says "Thinking…" (Thinking.swift).
    public var thinking: Bool { live && stateTitle == ThinkingCopy.thinking }
    public var hearing: String { status?.hearing ?? "" }
    public var activeSession: String? { status?.active }
    public var sessionCount: Int { status?.sessions.count ?? 0 }
    /// The daemon's version, once it has answered.
    public var daemonVersion: String? { status?.version }
    /// The daemon answers this app (false: stopped, or the key was refused).
    public var reachable: Bool { reach == .ok }
    /// Why the last call ended or did not start, in the words Connect shows.
    public var callProblem: String? { call.problem }
    public var talkLabel: String { call.talkStyle.label }
    public var holdToTalk: Bool { call.talkStyle == .hold }
    /// False while the call is up on audio that gave no echo cancellation.
    public var cancelsEcho: Bool { call.cancelsEcho }

    private var macName: String { status?.machines?.first { $0.here == true }?.name ?? link.host }

    /// The call screen's own state line.
    public var stateTitle: String {
        CallTitle.line(phase: demo == nil ? call.state : .live, reach: reach, status: status, call: call, macName: macName,
                       dumping: status?.dumping ?? false, talking: talking, speaking: speaking, muted: muted)
    }

    /// Sessions that wait on the person: a request to approve, or a question.
    public var needCount: Int {
        (status?.sessions ?? []).filter { !$0.isOffline && ($0.waiting || $0.needs != nil) }.count
    }

    public var waiting: [Waiting] {
        let machines = MachineView(status)
        return (status?.sessions ?? []).compactMap { s in
            guard s.waiting, s.canApprove, let id = s.request_id else { return nil }
            return Waiting(id: id, label: machines.label(s))
        }
    }

    public var glyph: Glyph {
        if reach != .ok && phase != .live { return .down }
        if needCount > 0 { return .needsYou }
        guard phase == .live else { return .off }
        return talking ? .talking : speaking ? .speaking : thinking ? .thinking : .live
    }

    /// The menu bar item's help tag and what VoiceOver reads.
    public var menuTitle: String {
        if reach != .ok && phase != .live { return reach == .rejected ? MacCopy.keyRefused : MacCopy.notAnswering }
        return needCount > 0 ? MacCopy.needYou(needCount) : stateTitle
    }

    /// The one brain dump button's words: start, done, or back to the review.
    public var dumpLabel: String { BrainDumpCopy.buttonLabel(status?.brain_dump) }

    // MARK: what the shell does

    /// Begins the status check that runs while the window is closed. The window's own check feeds this while it is open.
    public func start() {
        guard demo == nil, poller == nil else { return }
        poller = Task { [weak self] in
            while !Task.isCancelled {
                await self?.check()
                try? await Task.sleep(for: .milliseconds(700))
            }
        }
    }

    private func check() async {
        guard Date().timeIntervalSince(heard) > 1.5 else { return }  // the window is fetching
        call.checkHealth()
        do {
            let fresh = try await call.api.status()
            if fresh != status { status = fresh }
            call.follow(fresh.ptt)
            await AlertCenter.shared.sync(fresh.attention, api: call.api, machines: MachineView(fresh))
            if reach != .ok { reach = .ok }
        } catch API.Failure.status(let code, _) where code == 401 || code == 403 {
            if reach != .rejected { reach = .rejected }
        } catch {
            if reach != .unreachable { reach = .unreachable }
        }
    }

    /// Right now, after something changed that the next check should not wait for (the daemon just started).
    public func refresh() async {
        heard = .distantPast
        await check()
    }

    func polled(_ status: API.Status?, reach: Reach) {
        heard = Date()
        if status != self.status { self.status = status }
        if reach != self.reach { self.reach = reach }
    }

    public func connect() async {
        guard demo == nil, call.state == .off else { return }
        await call.start()
    }

    public func hangUp() {
        guard demo == nil else { return }
        call.hangUp()
    }

    public func toggleCall() async {
        if call.state == .off { await connect() } else { hangUp() }
    }

    public func toggleMute() { if live, !call.talk.ptt { call.toggleMute() } }

    /// The talk shortcut or the bubble went down. On a call in push to talk it is the talk button (a hold, or a tap in
    /// Tap to talk); in Always on it mutes. False with no call: the caller brings the window forward instead.
    @discardableResult
    public func talkDown() -> Bool {
        guard call.state == .live else { return false }
        let touched = ProcessInfo.processInfo.systemUptime
        if !call.talk.ptt { call.toggleMute() }
        else if call.talkStyle == .tap { call.talkToggle(touched: touched) }
        else { call.talkPress(.shortcut, touched: touched) }
        return true
    }

    public func talkUp() {
        if call.state == .live, call.talk.ptt, call.talkStyle == .hold { call.talkRelease(.shortcut) }
    }

    /// The skip shortcut, or the bubble's skip button: what Pointe is saying stops, here at once and on the Mac's side,
    /// and it goes on to the next line that waits. False with nothing being said: the key does nothing then.
    @discardableResult
    public func skip() -> Bool {
        guard speaking else { return false }
        if demo != nil { demoSkipped = true; return true }
        call.hush()
        let api = call.api
        Task { try? await api.skip() }
        return true
    }

    /// Asks the call screen for a sheet or an action; the caller brings the window forward first.
    public func ask(_ command: Command) {
        requests += 1
        let wanted: ShellRequest.Command = switch command {
        case .settings: .settings
        case .sessions: .sessions
        case .newSession: .newSession
        case .addSessions: .addSessions
        case .brainDump: .brainDump
        case .meeting: .meeting
        case .type: .type
        case .about: .about
        case .briefing: .briefing
        case .machines: .machines
        case .phone: .phone
        case .nightShift: .nightShift
        case .approve: .approve
        case .deny: .deny
        }
        request = ShellRequest(id: requests, command: wanted)
    }

    // MARK: the demo

    /// "Try a demo", from the setup panel: invented sessions, with a request waiting. Nothing is fetched or sent.
    public func tryDemo() {
        guard demo == nil, call.state == .off else { return }
        demo = Demo.tryIt
        status = demo?.status
        reach = .ok
        if let demo { call.follow(demo.status.ptt) }
    }

    public func exitDemo() {
        guard demo?.tried == true else { return }
        demo = nil
        status = nil
        heard = .distantPast
    }

    // MARK: settings that are the daemon's and are set at the Mac only

    /// The folders a new session may start in, beside those of current and recent sessions; nil when the daemon did not say.
    public func sessionFolders() async -> [String]? {
        guard demo == nil, let (data, _) = try? await call.api.send(call.api.request("voice/prefs")),
              let prefs = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return prefs["sessions.folders"] as? [String] ?? []
    }

    /// Nil when the daemon took them; otherwise why not, in its words.
    public func setSessionFolders(_ paths: [String]) async -> String? {
        do {
            try await call.api.setPrefs(["sessions.folders": paths])
            return nil
        } catch API.Failure.status(_, let detail) {
            return detail
        } catch {
            return MacCopy.unreachable(MacCopy.thisMac)
        }
    }

    // MARK: alerts

    public var alertsOn: Bool { AlertCenter.shared.enabled }
    /// Asks macOS the first time; the result is whether alerts are on now.
    public func setAlerts(_ on: Bool) async -> Bool { await AlertCenter.shared.setEnabled(on) }
    /// Whether the call window is the one the person is looking at (no notification then), and what a click on a
    /// notification does.
    public func alerts(isFront: @escaping @MainActor () -> Bool, opened: @escaping @MainActor () -> Void) {
        AlertCenter.shared.isFront = isFront
        AlertCenter.shared.opened = opened
    }
}

/// The Mac app's window: the call screen the iPhone app draws, on this Mac's daemon.
public struct PointeMacRoot: View {
    private let session: MacSession
    @AppStorage(Theme.key) private var theme = Theme.fallback.rawValue

    private let settings: AnyView?

    /// `settings`: the sections of Settings that belong to this Mac alone (the shortcut, the bubble, Pointe on this Mac),
    /// which the app draws: they come after the ones every surface has.
    public init<Sections: View>(session: MacSession, @ViewBuilder settings: () -> Sections) {
        self.session = session
        self.settings = AnyView(settings())
    }

    public init(session: MacSession) {
        self.session = session
        settings = nil
    }

    public var body: some View {
        CallView(link: session.link, call: session.call, shell: session, unpair: { session.exitDemo() }, demo: session.demo)
            .id(session.demo?.tried == true)  // the demo is another screen, with its own state
            .environment(\.macSettings, settings)
            .preferredColorScheme(Theme.stored(theme).scheme)
            .tint(Brand.accent)
            .font(.brand(.body))
            .foregroundStyle(Brand.text)
    }
}

extension EnvironmentValues {
    @Entry var macSettings: AnyView? = nil
}

/// What the setup guide opens itself: before Pointe runs on this Mac there is no call screen to host Settings and About,
/// and the guide's own words send people to Settings, Model keys. Every other command waits for the call screen.
public enum MacSetupSheet: String, Identifiable, Sendable {
    case settings, about

    public var id: String { rawValue }

    public init?(_ command: MacSession.Command) {
        switch command {
        case .settings: self = .settings
        case .about: self = .about
        default: return nil
        }
    }
}

/// The setup guide's Settings (Appearance and this Mac's own sections, its keys among them) and About.
public struct MacSetupSheetView: View {
    let sheet: MacSetupSheet
    let version: String?
    let sections: AnyView
    @AppStorage(Theme.key) private var theme = Theme.fallback.rawValue
    @Environment(\.dismiss) private var dismiss

    public init<Sections: View>(sheet: MacSetupSheet, version: String?, @ViewBuilder sections: () -> Sections) {
        self.sheet = sheet
        self.version = version
        self.sections = AnyView(sections())
    }

    public var body: some View {
        Group {
            switch sheet {
            case .about: AboutSheet(mac: version)
            case .settings:
                NavigationStack {
                    BrandForm {
                        Section {
                            Picker(selection: $theme) {
                                ForEach(Theme.allCases) { Text($0.label).tag($0.rawValue) }
                            } label: { Label(Theme.setting, systemImage: "circle.lefthalf.filled") }
                                .pickerStyle(.menu)
                                .accessibilityIdentifier("appearanceSetting")
                        }
                        sections
                    }
                    .sheetTitle("Settings")
                    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
                }
            }
        }
        .preferredColorScheme(Theme.stored(theme).scheme)
        .font(.brand(.body))
        .foregroundStyle(Brand.text)
        .sheetSurface()
    }
}

/// The brand's colours and type, for what the Mac app draws itself (the bubble, the setup panel, its own settings).
public enum PointeLook {
    public static var bg: Color { Brand.bg }
    /// The brand's mark, as the call screen's header draws it.
    public static var mark: Image { Image("ChorusMark", bundle: .module) }
    public static var card: Color { Brand.card }
    public static var raised: Color { Brand.raised }
    public static var group: Color { Brand.group }
    public static var text: Color { Brand.text }
    public static var muted: Color { Brand.muted }
    public static var dim: Color { Brand.dim }
    public static var line: Color { Brand.line }
    public static var lineStrong: Color { Brand.lineStrong }
    public static var orange: Color { Brand.orange }
    public static var onOrange: Color { Brand.onOrange }
    public static var accent: Color { Brand.accent }
    public static var successText: Color { Brand.successText }
    public static var primary: Color { Brand.primary }
    public static var onPrimary: Color { Brand.onPrimary }
    public static func font(_ style: Font.TextStyle = .body, _ weight: Font.Weight = .regular) -> Font { .brand(style, weight) }
    public static func display(_ size: CGFloat) -> Font { .display(size) }
    /// The Chorus mark, for the Mac target's own screens (the setup guide), as the call screen's header draws it.
    public static func mark(_ size: CGFloat) -> some View {
        Image("ChorusMark", bundle: .module).resizable().frame(width: size, height: size).accessibilityHidden(true)
    }
    /// The key Appearance is stored under ("system", "light", "dark"), so the app's own windows follow it.
    public static let themeKey = Theme.key
}
#endif
