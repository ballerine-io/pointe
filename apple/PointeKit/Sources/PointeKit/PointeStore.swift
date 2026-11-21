import Foundation
import Observation

/// Asks the person at the device to prove they are there, before an Approve (Touch ID, the watch, the password).
public protocol Authenticating: Sendable {
    func confirm(reason: String) async -> Bool
}

/// Posts and withdraws the notifications `AlertPlan` decided on.
@MainActor
public protocol AlertPosting: AnyObject {
    func delivered() async -> Set<String>
    func post(_ notes: [AlertNote])
    func withdraw(_ ids: [String])
}

/// What the menu bar item says: never by colour alone, always a symbol and, when sessions wait, their number.
public struct MenuBarState: Equatable, Sendable {
    public enum Kind: String, Sendable { case down, off, live, talking, speaking, needsYou }
    public let kind: Kind
    public let count: Int
    /// The state in words: the item's help tag and what VoiceOver reads.
    public let title: String

    public var symbol: String {
        switch kind {
        case .down: "waveform.slash"
        case .off: "waveform"
        case .live: "waveform.circle"
        case .talking: "mic.fill"
        case .speaking: "speaker.wave.2.fill"
        case .needsYou: "exclamationmark.bubble.fill"
        }
    }

    public var accessibilityLabel: String { "\(MacCopy.appName): \(title)" }
}

/// A request that waits for a click: the session, and exactly what Approve would approve.
public struct PendingApproval: Equatable, Identifiable, Sendable {
    public let session: API.Session
    public let label: String
    public let request: String
    public let requestId: String
    public let offline: Bool
    public var id: String { requestId }
}

/// One machine's sessions, for the sidebar.
public struct SessionGroup: Equatable, Identifiable, Sendable {
    public let name: String
    public let header: String
    public let offline: Bool
    public let sessions: [API.Session]
    public var id: String { name }
}

/// The app's one model: the daemon's status, polled, and every action a screen can take. It decides nothing about
/// approvals: it carries the click to the daemon, after asking who is there.
@MainActor @Observable
public final class PointeStore {
    public private(set) var status: API.Status?
    public private(set) var prefs: API.Prefs?
    public private(set) var reach: Reach = .unreachable
    /// Status checks that failed in a row: three says "not answering", as the page does.
    public private(set) var fails = 0
    /// The last thing that went wrong with an action, in the daemon's own words; cleared by the next one that works.
    public var notice: String?
    /// Brain dump review: the To: the user picked for this dump, and whether Send was clicked once.
    public var dumpPicked: DumpTarget?
    public private(set) var dumpSendArmed = false
    public private(set) var busy = false
    /// Why the New session sheet's last Start or its options failed, in the daemon's words: shown in the sheet.
    public private(set) var startProblem: String?

    public var api: any DaemonAPI
    public var call: CallLink?
    public var alerts: (any AlertPosting)?
    /// Alerts are posted only while the app's window is not in front.
    public var appIsFront: @MainActor () -> Bool = { true }
    public var alertsEnabled = false

    private let authenticator: any Authenticating
    private let appVersion: String
    private var poller: Task<Void, Never>?
    private var posted: Set<String> = []
    private var dumpSeen = ""

    public init(api: any DaemonAPI, authenticator: any Authenticating, appVersion: String, call: CallLink? = nil) {
        self.api = api
        self.authenticator = authenticator
        self.appVersion = appVersion
        self.call = call
    }

    // MARK: polling

    public static let pollEvery: TimeInterval = 0.7

    public func start() {
        guard poller == nil else { return }
        poller = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(for: .seconds(Self.pollEvery))
            }
        }
    }

    public func stop() {
        poller?.cancel()
        poller = nil
    }

    /// One status check, and everything that follows from it.
    public func refresh() async {
        do {
            let fresh = try await api.status()
            if status != fresh { status = fresh }
            if reach != .ok { reach = .ok }
            fails = 0
        } catch API.Failure.status(let code, _) where code == 401 || code == 403 {
            reach = .rejected
            fails += 1
        } catch {
            fails += 1
            if fails >= 3 || status == nil { reach = .unreachable }
        }
        call?.follow(status?.ptt)
        call?.checkHealth()
        if let dump = status?.brain_dump?.id, dump != dumpSeen {
            dumpSeen = dump
            dumpPicked = nil
            dumpSendArmed = false
        }
        await planAlerts()
        if prefs == nil, reach == .ok { await loadPrefs() }
    }

    public func loadPrefs() async {
        if let fresh = try? await api.prefs() { prefs = fresh }
    }

    private func planAlerts() async {
        guard let alerts else { return }
        let items = reach == .ok ? (status?.attention ?? []) : []
        let plan = AlertPlan.plan(items, posted: posted, delivered: await alerts.delivered(), appActive: appIsFront(),
                                  enabled: alertsEnabled, watchApprove: prefs?.watchApprove == true, machines: machines)
        posted = plan.posted
        if !plan.withdraw.isEmpty { alerts.withdraw(plan.withdraw) }
        if !plan.post.isEmpty { alerts.post(plan.post) }
    }

    // MARK: what the screens show

    public var machines: MachineView { MachineView(status) }

    public var groups: [SessionGroup] {
        let view = machines
        guard let status, !status.sessions.isEmpty else { return [] }
        let names = view.names.isEmpty ? [""] : view.names
        return names.compactMap { name in
            let sessions = view.names.isEmpty ? status.sessions : view.onMachine(name)
            guard !sessions.isEmpty || view.info(name)?.isOffline == true else { return nil }
            return SessionGroup(name: name, header: name.isEmpty ? MacCopy.thisMac : view.header(name),
                                offline: view.isOffline(name), sessions: sessions)
        }
    }

    public var pending: [PendingApproval] {
        let view = machines
        return (status?.sessions ?? []).compactMap { s in
            guard s.waiting, s.canApprove, let request = s.request, let id = s.request_id else { return nil }
            return PendingApproval(session: s, label: view.label(s), request: request, requestId: id, offline: s.isOffline)
        }
    }

    /// Sessions that wait on the person: a request to approve, or a question.
    public var needCount: Int {
        (status?.sessions ?? []).filter { !$0.isOffline && ($0.waiting || $0.needs != nil) }.count
    }

    public static func tag(_ s: API.Session) -> String {
        s.isOffline ? MacCopy.tagOffline : s.waiting ? MacCopy.tagApprove : s.needs != nil ? MacCopy.tagNeedsYou
            : s.working ? MacCopy.tagWorking : MacCopy.tagIdle
    }

    /// This device holds the call (the daemon says one is up, and ours is live).
    public var mine: Bool { call?.state == .live }
    public var onACallElsewhere: Bool { status?.connected == true && !mine && call?.state != .connecting }

    /// The state line: the page's order of cases and its words (ui.html, showState).
    public var stateTitle: String {
        let phase = call?.state ?? .off
        if reach == .rejected { return MacCopy.notConnected }
        if fails >= 3 { return MacCopy.notAnswering }
        if phase == .reconnecting { return MacCopy.reconnecting }
        if phase == .connecting { return MacCopy.connecting(MacCopy.thisMac) }
        guard let status, phase == .live, let call else { return onACallElsewhere ? MacCopy.elsewhere : MacCopy.notConnected }
        if call.talk.ptt, call.talk.isOpen { return call.talkStyle.talkingLine }
        if status.dumping { return BrainDumpCopy.state }
        if status.hold != nil { return TurnsCopy.holding }
        if call.muted && !call.talk.ptt { return MacCopy.muted }
        if call.botSpeaking { return MacCopy.speaking }
        if !(status.hearing ?? "").isEmpty { return MacCopy.hearingYou }
        if call.talk.ptt {
            if let note = call.talkNote { return note }
            if let why = call.talkClosedWhy { return TalkGate.closedLine(why, style: call.talkStyle) }
            return call.talkStyle.label
        }
        return MacCopy.listening
    }

    public var menuBar: MenuBarState {
        let need = needCount
        let phase = call?.state ?? .off
        if reach != .ok && phase != .live { return MenuBarState(kind: .down, count: 0, title: reach == .rejected ? MacCopy.notConnected : MacCopy.notAnswering) }
        if need > 0 { return MenuBarState(kind: .needsYou, count: need, title: MacCopy.needYou(need)) }
        guard phase == .live, let call else { return MenuBarState(kind: .off, count: 0, title: stateTitle) }
        if call.talk.ptt && call.talk.isOpen { return MenuBarState(kind: .talking, count: 0, title: stateTitle) }
        if call.botSpeaking { return MenuBarState(kind: .speaking, count: 0, title: stateTitle) }
        return MenuBarState(kind: .live, count: 0, title: stateTitle)
    }

    /// The Connect panel's reason line and whether it is a problem.
    public var connectWhy: (line: String, bad: Bool) {
        if reach == .rejected { return (MacCopy.keyRefused, true) }
        if reach == .unreachable { return (MacCopy.daemonDown, true) }
        if let problem = call?.problem, !problem.isEmpty { return (problem, true) }
        if let problem = status?.problem, !problem.isEmpty { return (problem, true) }
        if onACallElsewhere { return (MacCopy.elsewhereWhy, false) }
        return (MacCopy.does, false)
    }

    public var versionNote: (line: String, fix: String)? { VersionCheck.note(app: appVersion, daemon: status?.version) }

    /// The words being heard, and the label over them while they are a press's draft.
    public var hearing: String { status?.hearing ?? "" }
    public var draftLine: String? { TalkDraft.line(draft: status?.ptt?.draft, open: call?.talk.isOpen == true) }

    // MARK: actions

    private func act(_ work: () async throws -> Void) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            try await work()
            notice = nil
            await refresh()
            return true
        } catch API.Failure.status(_, let detail) {
            notice = detail
        } catch {
            notice = MacCopy.unreachable(MacCopy.thisMac)
        }
        return false
    }

    /// A click on Approve: who is there is asked first; the daemon then takes it only for the request still pending.
    @discardableResult
    public func approve(_ approval: PendingApproval) async -> Bool {
        guard !approval.offline, approval.session.canApprove else { return false }
        guard await authenticator.confirm(reason: MacCopy.approveReason) else { return false }
        return await answer(approval, allow: true)
    }

    /// Deny never asks who is there.
    @discardableResult
    public func deny(_ approval: PendingApproval) async -> Bool {
        guard !approval.offline else { return false }
        return await answer(approval, allow: false)
    }

    private func answer(_ approval: PendingApproval, allow: Bool) async -> Bool {
        busy = true
        defer { busy = false }
        do {
            try await api.answer(session: approval.session.name, requestId: approval.requestId, allow: allow, viaNotification: false)
            notice = nil
        } catch API.Failure.status(409, _) {
            notice = MacCopy.alreadyAnswered
        } catch API.Failure.status(_, let detail) {
            notice = detail
            return false
        } catch {
            notice = MacCopy.unreachable(MacCopy.thisMac)
            return false
        }
        await refresh()
        return true
    }

    /// An action on a notification, bound to the request it was posted for. The daemon refuses an Approve unless the
    /// request could be read out and "Approve from notifications" is on. Returns what to tell the user, or nil.
    public func answerFromNotification(_ decision: AlertAnswer.Decision) async -> String? {
        do {
            try await api.answer(session: decision.session, requestId: decision.requestId, allow: decision.allow, viaNotification: true)
            await refresh()
            return nil
        } catch {
            switch AlertAnswer.outcome(error) {
            case .alreadyAnswered: return MacCopy.alreadyAnswered
            case .approveInApp: return MacCopy.approveOnPage
            case .unreachable, nil: return MacCopy.unreachable(MacCopy.thisMac)
            }
        }
    }

    public func switchTo(_ name: String) async {
        guard status?.active != name else { return }
        _ = await act { try await api.switchTo(name) }
    }

    public func disconnect(_ name: String) async { _ = await act { try await api.disconnect(name) } }

    @discardableResult
    public func say(_ text: String) async -> Bool {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return false }
        return await act { try await api.say(text) }
    }

    @discardableResult
    public func correct(_ turn: API.Turn, to text: String) async -> Bool {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text != turn.text else { return false }
        return await act { try await api.correct(turn: turn.id, to: text) }
    }

    public func setMicrophone(_ mode: String) async {
        if await act({ try await api.setPrefs(["microphone": .string(mode)]) }) { await loadPrefs() }
    }

    public func setPatience(_ level: String) async {
        if await act({ try await api.setPrefs(["turns.patience": .string(level)]) }) { await loadPrefs() }
    }

    public func setApproveFromNotifications(_ on: Bool) async {
        if on, !(await authenticator.confirm(reason: MacCopy.approveReason)) { return }
        if await act({ try await api.setPrefs(["alerts.watch_approve": .bool(on)]) }) { await loadPrefs() }
    }

    /// Lowering the lock takes a guard away: who is there is asked first, as the iPhone app does.
    public func setVoiceLock(_ level: VoiceLockLevel) async {
        let current = status?.voice_lock?.lockLevel ?? .off
        guard level != current else { return }
        if VoiceLockLevel.isLowering(from: current, to: level), !(await authenticator.confirm(reason: MacCopy.lowerLockReason)) { return }
        _ = await act { try await api.voiceLock(level: level.rawValue) }
    }

    // MARK: brain dump

    public var dump: API.BrainDump? { status?.brain_dump }
    public var sessionNames: [String] { (status?.sessions ?? []).filter { !$0.isOffline }.map(\.name) }
    public var dumpTarget: DumpTarget? {
        dump.flatMap { BrainDumpCopy.target($0, picked: dumpPicked, active: status?.active, sessions: sessionNames) }
    }
    public var dumpChoices: [DumpTarget] { dump.map { BrainDumpCopy.choices($0, sessions: sessionNames) } ?? [] }

    public func dumpAction(_ action: String, text: String? = nil) async {
        dumpSendArmed = false
        _ = await act { try await api.dump(action, text: text, session: nil, to: nil) }
    }

    /// Send takes two clicks: the first arms it ("Tap again to send"), the second sends to the target shown.
    public func dumpSend() async {
        guard dump?.inReview == true, let target = dumpTarget else { return }
        guard dumpSendArmed else { dumpSendArmed = true; return }
        dumpSendArmed = false
        _ = await act {
            switch target {
            case .orchestrator: try await api.dump("send", text: nil, session: nil, to: "orchestrator")
            case .session(let name): try await api.dump("send", text: nil, session: name, to: nil)
            }
        }
    }

    public func disarmDumpSend() { dumpSendArmed = false }

    // MARK: new session (docs/design/new-session.md)

    public var starting: [NewSession.Starting] { status?.starting ?? [] }
    public var startPending: NewSession.Pending? { status?.start_pending }

    /// What the sheet offers; nil, with the reason in `startProblem`, when the daemon did not say.
    public func startOptions() async -> NewSession.Options? {
        await starts { try await api.startOptions() }
    }

    /// The sheet's Start: who is there is asked first. False keeps the sheet open, with the daemon's reason in it.
    public func start(_ draft: NewSession.Draft) async -> Bool {
        guard await authenticator.confirm(reason: MacCopy.startReason) else { return false }
        let started: Void? = await starts { try await api.newSession(draft.body) }
        if started != nil { await refresh() }
        return started != nil
    }

    private func starts<T>(_ work: () async throws -> T) async -> T? {
        busy = true
        defer { busy = false }
        do {
            let result = try await work()
            startProblem = nil
            return result
        } catch API.Failure.status(_, let detail) {
            startProblem = detail
        } catch {
            startProblem = MacCopy.unreachable(MacCopy.thisMac)
        }
        return nil
    }

    /// Start on a read-back's card: who is there is asked first, as for Approve.
    @discardableResult
    public func confirmStart(_ pending: NewSession.Pending) async -> Bool {
        guard await authenticator.confirm(reason: MacCopy.startReason) else { return false }
        return await act { try await api.newSession(["confirm": pending.id]) }
    }

    /// The folders added for new sessions, as a whole list: the daemon checks each one and may refuse.
    public func setSessionFolders(_ paths: [String]) async {
        if await act({ try await api.setPrefs(["sessions.folders": .strings(paths)]) }) { await loadPrefs() }
    }

    /// Cancel never asks who is there.
    @discardableResult
    public func cancelStart(_ pending: NewSession.Pending) async -> Bool {
        await act { try await api.newSession(["cancel": pending.id]) }
    }
}
