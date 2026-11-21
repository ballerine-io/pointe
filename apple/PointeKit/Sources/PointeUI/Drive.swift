import AVFAudio
import CoreMotion
import MediaPlayer
import SwiftUI

// Drive & walk mode (docs/features/drive-mode.md): short answers, nothing to read or tap. The
// Mac owns the mode and its rules (drive.py): a spoken yes approves only what it can read out whole and is safe from the
// road, a no counts from anyone, and anything else waits for a tap once the user has stopped. The phone asks for the
// mode, shows it, and suggests it in the car; it never enters it by itself.

extension API {
    struct DriveStatus: Decodable, Equatable {
        var on: Bool
        let since: Double?
        let how: String?            // "voice" or "button"
        var pending: [DrivePending]?
    }

    /// A request waiting now, and whether a spoken yes may answer it while driving.
    struct DrivePending: Decodable, Equatable {
        let session: String
        let request_id: String?
        let voice: Bool
    }

    /// On or off. The Mac refuses (409) with no call up or a meeting on.
    func drive(_ on: Bool) async throws {
        var r = URLRequest(url: pairing.base.appendingPathComponent("voice/drive"))
        r.httpMethod = "POST"
        r.setValue("Bearer \(pairing.key)", forHTTPHeaderField: "Authorization")
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try? JSONSerialization.data(withJSONObject: ["on": on])
        r.timeoutInterval = 10
        let (data, response) = try await session.data(for: r)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw Failure.status(code, detail ?? "HTTP \(code)")
        }
    }
}

extension API.Status {
    var driving: Bool { drive?.on == true }
}

/// Word for word the page's copy (ui.html): the two must not drift.
enum DriveCopy {
    static let button = "Drive"
    static let title = "Drive mode"
    static let stop = "I've stopped"
    static let hint = "Short answers. Pointe approves by voice only what it can read out and is safe from the road."
    static let voice = "Say yes or no."
    static let voiceStrong = "Say yes or no, in a full sentence."
    static let road = "Not for the road: it waits until you stop. Say no to deny it."
    static let unreadable = "Can\u{2019}t be read out: it waits until you stop. Say no to deny it."
    static let suggest = "Switch to Drive mode?"
    static let suggestYes = "Drive mode"
    static let suggestNo = "Not now"
    static let suggestSetting = "Suggest Drive mode in the car"
    static let allQuiet = "All quiet"
    static let unchanged = "Drive mode did not change."

    /// Why the Mac did not switch: its reason, or the page's line when it gave none.
    static func refused(_ detail: String) -> String {
        let d = detail.trimmingCharacters(in: .whitespaces)
        if d == "no call is up" { return "Start the call first." }
        return d.isEmpty || d.hasPrefix("HTTP ") ? unchanged : CallView.sentence(d)
    }
    static func needsYou(_ name: String) -> String { "\(name) needs you" }
    static func working(_ n: Int) -> String { "\(n) working" }

    /// What the card says instead of buttons: whether a spoken yes can answer this request while driving.
    static func hint(for session: API.Session, status: API.Status?) -> String {
        let pending = status?.drive?.pending?.first { $0.request_id == session.request_id }
        if pending?.voice == true { return status?.voice_lock?.enrolled == true ? voiceStrong : voice }
        return session.voice_can_approve == true ? road : unreadable
    }

    /// The one big line: who needs you, else what the call is doing.
    static func line(status: API.Status?, speaking: Bool, hearing: Bool) -> String {
        if let first = status?.drive?.pending?.first { return needsYou(first.session) }
        if speaking { return "Speaking" }
        if hearing { return "Listening" }
        let n = status?.sessions.filter(\.working).count ?? 0
        return n > 0 ? working(n) : allQuiet
    }
}

/// The drive screen: one line to glance at, the live caption, and the only button is "I've stopped".
struct DriveScreen: View {
    let status: API.Status?
    let speaking: Bool
    let stop: () -> Void

    private var caption: String {
        if let hearing = status?.hearing, !hearing.isEmpty { return hearing }
        return status?.talk?.last?.text ?? ""
    }

    var body: some View {
        VStack(spacing: 18) {
            Spacer(minLength: 0)
            Label(DriveCopy.title, systemImage: "car.fill")
                .font(.brand(.caption, .semibold)).kerning(1.4).foregroundStyle(Brand.muted).textCase(.uppercase)
            Text(DriveCopy.line(status: status, speaking: speaking, hearing: !(status?.hearing ?? "").isEmpty))
                .font(.display(36)).multilineTextAlignment(.center)
                .minimumScaleFactor(0.6).lineLimit(2)
                .contentTransition(.opacity)
                .accessibilityIdentifier("driveLine")
            if !caption.isEmpty {
                Text(caption).font(.brand(.title3)).foregroundStyle(Brand.muted).multilineTextAlignment(.center).lineLimit(3)
                    .accessibilityIdentifier("driveCaption")
            }
            Text(DriveCopy.hint).font(.brand(.footnote)).foregroundStyle(Brand.muted).multilineTextAlignment(.center)
            Button(action: stop) {
                Text(DriveCopy.stop).font(.brand(.title3, .semibold)).frame(maxWidth: .infinity).padding(.vertical, 8)
            }
            .buttonStyle(.brandQuiet).controlSize(.large)
            .accessibilityIdentifier("driveStop")
            Spacer(minLength: 0)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .dynamicTypeSize(...DynamicTypeSize.xxxLarge)  // already the largest type in the app, set to be read at a glance
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine, lineWidth: 1).padding(.horizontal, 14).padding(.vertical, 8))
    }
}

/// A waiting request while driving: what it is, and how it may be answered. No buttons: "I've stopped" leaves the mode
/// first, and then the normal card (Face ID) answers it.
struct DriveRequestCard: View {
    let session: API.Session
    let status: API.Status?
    var more = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label { Text("\(MachineView(status).label(session)) needs approval") } icon: { Image(systemName: "hand.raised.fill").foregroundStyle(Brand.accent) }
                .font(.brand(.headline))
            Text(session.isOffline ? MachinesCopy.offlineCard : DriveCopy.hint(for: session, status: status)).font(.brand(.title3, .semibold))
                .accessibilityIdentifier("driveHint")
            if more > 0 { Text("\(more) more waiting").font(.brand(.caption)).foregroundStyle(Brand.muted) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
        .sensoryFeedback(.warning, trigger: session.request_id)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("driveRequest")
    }
}

/// "Switch to Drive mode?": only ever a suggestion, never entered by itself.
struct DriveSuggestion: View {
    let accept: () -> Void
    let dismiss: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "car.fill").foregroundStyle(Brand.accent)
            Text(DriveCopy.suggest).font(.brand(.subheadline, .semibold))
            Spacer()
            Button(DriveCopy.suggestNo, action: dismiss).buttonStyle(.brandQuiet).controlSize(.small)
            Button(DriveCopy.suggestYes, action: accept).buttonStyle(.brandPrimary).controlSize(.small)
                .accessibilityIdentifier("driveSuggestYes")
        }
        .padding(12)
        .brandCard()
        .accessibilityIdentifier("driveSuggestion")
    }
}

/// When to suggest the mode: the car's audio (CarPlay) carries the call, or the phone has sensed driving for a minute.
/// Once per trip: dismissed, it is not suggested again until the car and the motion have both gone away.
struct DriveSuggester: Equatable {
    static let automotiveSecs: TimeInterval = 60
    private(set) var inCar = false
    private(set) var automotiveSince: Date?
    private(set) var dismissed = false

    mutating func route(inCar: Bool) { self.inCar = inCar; rearm() }

    mutating func motion(automotive: Bool, at now: Date) {
        if automotive { automotiveSince = automotiveSince ?? now } else { automotiveSince = nil }
        rearm()
    }

    mutating func dismiss() { dismissed = true }

    func suggests(enabled: Bool, live: Bool, driving: Bool, meeting: Bool, now: Date) -> Bool {
        guard enabled, live, !driving, !meeting, !dismissed else { return false }
        if inCar { return true }
        if let since = automotiveSince { return now.timeIntervalSince(since) >= Self.automotiveSecs }
        return false
    }

    private mutating func rearm() { if !inCar && automotiveSince == nil { dismissed = false } }

    /// CarPlay's audio route. A plain Bluetooth car kit looks like any headset to iOS, so motion covers that case.
    static func carRoute(_ route: AVAudioSessionRouteDescription = AVAudioSession.sharedInstance().currentRoute) -> Bool {
        route.outputs.contains { $0.portType == .carAudio }
    }
}

/// The per-device setting and the sensors behind the suggestion. Motion is asked only when the user turns the setting
/// on with a tap (iOS shows its permission prompt then); otherwise only CarPlay's route is used.
@MainActor @Observable
final class DriveSensors {
    static let settingKey = "pointe.drive.suggest"
    var suggester = DriveSuggester()
    var enabled: Bool { UserDefaults.standard.object(forKey: Self.settingKey) as? Bool ?? true }
    private let motion = CMMotionActivityManager()
    private var routeObserver: NSObjectProtocol?

    func start() {
        suggester.route(inCar: DriveSuggester.carRoute())
        if routeObserver == nil {
            routeObserver = NotificationCenter.default.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil,
                                                                   queue: .main) { [weak self] _ in
                Task { @MainActor in self?.suggester.route(inCar: DriveSuggester.carRoute()) }
            }
        }
        if enabled && CMMotionActivityManager.authorizationStatus() == .authorized { startMotion() }
    }

    func setEnabled(_ on: Bool) {
        UserDefaults.standard.set(on, forKey: Self.settingKey)
        if on && CMMotionActivityManager.isActivityAvailable() { startMotion() } else { motion.stopActivityUpdates() }
    }

    private func startMotion() {
        guard CMMotionActivityManager.isActivityAvailable() else { return }
        motion.startActivityUpdates(to: .main) { [weak self] activity in
            guard let activity else { return }
            Task { @MainActor in self?.suggester.motion(automotive: activity.automotive, at: Date()) }
        }
    }
}

/// The lock screen while driving: "Pointe · river-lantern needs you". Play/pause there mutes (Call.driving).
enum DriveNowPlaying {
    static func info(status: API.Status?) -> [String: Any] {
        let line = DriveCopy.line(status: status, speaking: false, hearing: false)
        return [MPMediaItemPropertyTitle: "Pointe · \(line)", MPMediaItemPropertyArtist: DriveCopy.title]
    }

    @MainActor static func update(status: API.Status?, driving: Bool) {
        MPNowPlayingInfoCenter.default().nowPlayingInfo = driving ? info(status: status) : nil
    }
}
