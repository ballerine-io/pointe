#if os(iOS)
@preconcurrency import ActivityKit
import PointeKit
import WidgetKit

/// "Talk to Pointe" from outside the app, carried out (the rules are PointeKit's `TalkLaunch`; the intents are in
/// apps/ios/PointeShared). The press opens the app; this holds the iPhone's one call, so the press and the call screen act on
/// the same call, and the Live Activity's buttons reach it with the app in the background.
///
/// What it may do is short on purpose: dial, put Pointe in Orchestrator mode, open and close the push-to-talk press, hang
/// up, and show the call in a Live Activity. It never answers a request: approving stays a tap behind Face ID, or a
/// spoken yes behind the voice lock, as on the call screen.
@MainActor
public final class PhoneTalk: TalkLauncher, CallShell {
    public static let shared = PhoneTalk()

    /// The phone's own setting and the widget's last look, in the app group when the build has one.
    let store = TalkStore() ?? TalkStore(defaults: .standard)
    private var call: Call?
    private var pairing: Pairing?
    private var activity: Activity<TalkActivityAttributes>?
    private var shown: TalkActivityState?
    private var watching: Task<Void, Never>?
    private var lastStatus: API.Status?
    var demoSkipped = false  // the Mac shell's: a phone has no key that skips from outside the call screen

    var request: ShellRequest? { nil }

    private init() {}

    /// At launch: a Live Activity from an earlier run has no call behind it (a call does not outlive the app's process).
    public func start() {
        TalkLaunchers.current = self
        for old in Activity<TalkActivityAttributes>.activities {
            Task { await old.end(nil, dismissalPolicy: .immediate) }
        }
        #if DEBUG  // UI tests (apps/ios/e2e/talk_outside_ui.py): the press the Control or the Action button makes, once paired
        if ProcessInfo.processInfo.arguments.contains("-talkPress") {
            Task {
                for _ in 0..<100 where PairingStore.load() == nil { try? await Task.sleep(for: .milliseconds(100)) }
                print("pointe: talk press: \(await press().said)")
            }
        }
        #endif
    }

    /// The one call for this pairing. A new pairing is a new call: the old one pins the old certificate.
    func call(for pairing: Pairing) -> Call {
        if let call, self.pairing == pairing { return call }
        if let old = call, old.state != .off { Task { old.hangUp() } }
        let fresh = Call(pairing: pairing)
        call = fresh
        self.pairing = pairing
        return fresh
    }

    var outside: Bool {
        get { store.outside }
        set {
            store.outside = newValue
            publish(lastStatus, reach: lastStatus == nil ? nil : .ok)
        }
    }

    // MARK: TalkLauncher

    public func press() async -> TalkOutcome {
        guard let pairing = PairingStore.load() else {
            publish(nil, reach: nil)
            return .refused(.notPaired)
        }
        let call = call(for: pairing)
        switch TalkLaunch.press(now(call)) {
        case .wait:
            return TalkOutcome(TalkLaunchCopy.dialling)
        case .refuse(let why):
            return .refused(why)
        case .open:
            call.talkToggle()
            showActivity(call)
            Task { await orchestrate(call.api) }  // while you talk: the words go only at the send
            return TalkOutcome(TalkLaunchCopy.talkingNow)
        case .send:
            call.talkToggle()
            showActivity(call)
            return TalkOutcome(TalkLaunchCopy.sent)
        case .start:
            return await start(call)
        }
    }

    public func send() async -> TalkOutcome {
        guard let call else { return TalkOutcome(TalkLaunchCopy.nothingSent) }
        guard TalkLaunch.send(now(call)) == .send else { return TalkOutcome(TalkLaunchCopy.nothingSent) }
        call.talkToggle()
        refreshActivity()
        return TalkOutcome(TalkLaunchCopy.sent)
    }

    /// Cancel and Hang up. A press still open is dropped with the call: the Mac sends a press only after its release,
    /// and a call that ends first never releases it (tests/test_ptt_message.py).
    public func cancel() async -> TalkOutcome {
        let wasOpen = call?.talk.isOpen == true
        await endActivity(problem: nil)  // first: once the call stops, nothing keeps the app running
        if let call, call.state != .off { await call.hangUpAndWait() }
        return TalkOutcome(wasOpen ? TalkLaunchCopy.cancelled : TalkLaunchCopy.hungUp)
    }

    private func now(_ call: Call) -> TalkLaunch.Now {
        TalkLaunch.Now(outside: store.outside, paired: true, call: Self.phase(call.state), ptt: call.talk.ptt,
                       pressOpen: call.talk.isOpen)
    }

    nonisolated static func phase(_ state: Call.State) -> TalkLaunch.Phase {
        switch state {
        case .off: .off
        case .connecting: .connecting
        case .live: .live
        case .reconnecting: .reconnecting
        }
    }

    /// No call: dial at once, and ask the Mac its settings while the call comes up. The press opens as soon as the call is
    /// live: the app is in front by then (the intent opens it), so the microphone is already running.
    private func start(_ call: Call) async -> TalkOutcome {
        let api = call.api
        let prefs = Task { try? await api.prefs() }
        let orchestrated = Task { await orchestrate(api) }
        showActivity(call)
        await call.start()
        let until = Date().addingTimeInterval(TalkLaunch.dialFor)
        while call.state == .connecting || call.state == .reconnecting, Date() < until {
            try? await Task.sleep(for: .milliseconds(20))
        }
        guard call.state == .live else {
            let why = call.problem ?? ConnectCopy.unreachableHere(call.place)
            if call.state != .off { call.hangUp() }
            await endActivity(problem: why)
            return .refused(.failed(why))
        }
        if let microphone = (await prefs.value)?.microphone { call.setMicrophone(microphone) }
        if call.talk.ptt && !call.talk.isOpen { call.talkToggle() }
        refreshActivity()
        _ = await orchestrated.value
        return TalkOutcome(call.talk.ptt ? TalkLaunchCopy.talkingNow : TalkLaunchCopy.listeningNow)
    }

    /// A press talks to the orchestrator: Session mode is switched, anything else the Mac is in is left alone.
    private func orchestrate(_ api: API) async {
        guard let status = try? await api.status() else { return }
        publish(status, reach: .ok)
        if TalkLaunch.orchestrates(mode: status.mode) { try? await api.mode("orchestrator") }
    }

    // MARK: the Live Activity

    private func showActivity(_ call: Call) {
        watch()  // Live Activities off for Pointe: none, and nothing else changes
        guard activity == nil, ActivityAuthorizationInfo().areActivitiesEnabled else { return refreshActivity() }
        let state = activityState(call)
        do {
            activity = try Activity.request(attributes: TalkActivityAttributes(started: Date()),
                                            content: ActivityContent(state: state, staleDate: nil))
            shown = state
        } catch {
            print("pointe: no Live Activity: \(error)")
        }
    }

    private func activityState(_ call: Call?) -> TalkActivityState {
        TalkActivityState.of(call: Self.phase(call?.state ?? .off), ptt: call?.talk.ptt ?? true, pressOpen: call?.talk.isOpen == true,
                             speaking: call?.botSpeaking == true, note: call?.talkNote, needs: MachineView(lastStatus).needingYou(),
                             mac: macName(lastStatus), problem: call?.problem)
    }

    private func refreshActivity() {
        guard let activity else { return }
        let state = activityState(call)
        guard state != shown else { return }
        shown = state
        Task { await activity.update(ActivityContent(state: state, staleDate: nil)) }
    }

    private func endActivity(problem: String?) async {
        watching?.cancel()
        watching = nil
        guard let activity else { return }
        self.activity = nil
        shown = nil
        var state = activityState(call)
        if let problem { state.detail = problem }
        await activity.end(ActivityContent(state: state, staleDate: nil), dismissalPolicy: problem == nil ? .immediate : .default)
    }

    /// While the Live Activity is up: the Mac's word on the press (a press it closed by itself), what needs you, and the
    /// call's own health, once a second, with or without a screen. The call ending ends the activity.
    private func watch() {
        guard watching == nil else { return }
        watching = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, let call = self.call else { return }
                if call.state == .off {
                    await self.endActivity(problem: call.problem)
                    self.publish(self.lastStatus, reach: .ok)
                    return
                }
                call.checkHealth()
                if let status = try? await call.api.status() {
                    call.follow(status.ptt)
                    self.publish(status, reach: .ok)
                }
                self.refreshActivity()
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    // MARK: the widget

    /// CallView's poll: each status the call screen fetched.
    func polled(_ status: API.Status?, reach: Reach) {
        publish(status, reach: Self.reach(reach))
        refreshActivity()
    }

    nonisolated static func reach(_ reach: Reach) -> TalkSnapshot.Reach {
        switch reach {
        case .ok: .ok
        case .unreachable: .unreachable
        case .rejected: .rejected
        }
    }

    /// The widget's look: nil `reach` when nothing was asked (no pairing).
    func publish(_ status: API.Status?, reach: TalkSnapshot.Reach?) {
        if let status { lastStatus = status }
        let paired = pairing != nil || PairingStore.load() != nil
        let snapshot = TalkSnapshot(outside: store.outside, paired: paired, reach: reach ?? .unreachable, mac: macName(lastStatus),
                                    needs: reach == .ok ? MachineView(lastStatus).needingYou() : 0,
                                    call: Self.phase(call?.state ?? .off), at: Date())
        if store.publish(snapshot) { WidgetCenter.shared.reloadTimelines(ofKind: TalkWidgetKind.home) }
    }

    /// Background App Refresh: one look at the Mac for the widget, when the feature is on.
    func refreshWidget() async {
        guard store.outside, let pairing = PairingStore.load() else { return publish(nil, reach: nil) }
        do {
            publish(try await API.standalone(DaemonLink(pairing)).status(), reach: .ok)
        } catch API.Failure.status(let code, _) where code == 401 || code == 403 {
            publish(nil, reach: .rejected)
        } catch {
            publish(nil, reach: .unreachable)
        }
    }

    private func macName(_ status: API.Status?) -> String {
        status?.machines?.first { $0.here == true }?.name ?? (pairing ?? PairingStore.load())?.host ?? "your Mac"
    }
}
#endif
