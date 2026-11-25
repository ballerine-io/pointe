import Foundation
#if os(macOS)
import AVFAudio
import MediaPlayer
#endif

/// The Mac app's AirPods press (docs/features/mute.md, "AirPods and play/pause"). Two inputs, both Pointe's only while a
/// call is up:
/// - the stem press, macOS 14's input-mute gesture (`AVAudioApplication.setInputMuteStateChangeHandler`): the mic off
///   and on, with the system's own chime; in push to talk the talk button, as on the iPhone;
/// - play/pause (`MPRemoteCommandCenter`): another headset's button, the keyboard's ⏯ key, or an AirPods press macOS
///   sends as one. What it does is the person's choice in Settings (`PlayPause`).
/// One press never does both (`PressArbiter`). The iPhone's press is `Call.remoteCommands` and iOS's own input mute.
public enum PlayPause: String, CaseIterable, Sendable {
    case mutePointe, skip, nothing

    public static let key = "pointe.playPause"

    public static func stored(_ defaults: UserDefaults = .standard) -> PlayPause {
        defaults.string(forKey: key).flatMap(PlayPause.init(rawValue:)) ?? .mutePointe
    }

    public static func store(_ choice: PlayPause, _ defaults: UserDefaults = .standard) { defaults.set(choice.rawValue, forKey: key) }

    public var label: String {
        switch self {
        case .mutePointe: MuteCopy.mute
        case .skip: "Skip"
        case .nothing: "Nothing"
        }
    }
}

public enum AirPodsPress {
    public enum Gesture: Equatable, Sendable {
        case mic(off: Bool)
        case talk
    }

    /// What a stem press does. `accept`: the system keeps the mute it asked for (it plays its chime and shows it); in
    /// push to talk it is refused, the input stays unmuted, and the gate decides what is sent.
    public static func gesture(muted: Bool, pushToTalk: Bool) -> (action: Gesture, accept: Bool) {
        pushToTalk ? (.talk, false) : (.mic(off: muted), true)
    }

    /// Beside the talk mode in the window and the bubble, during a call. "Mic off" is the microphone's word: "mute" is
    /// Pointe's voice (Mute.swift).
    public static func hint(pushToTalk: Bool, micOff: Bool) -> String {
        pushToTalk ? "AirPods: press to talk" : "AirPods: press for mic \(micOff ? "on" : "off")"
    }

    public static let glyph = "airpods"
}

/// One press, one action. Nothing documents that macOS sends a stem press as the gesture or as play/pause and never
/// both, so the first to arrive wins and the other source is dropped for `window`. A second press of the same source is
/// always a press; a double press is shorter than the window and is the headset's own gesture (end the call, next track).
final class PressArbiter: @unchecked Sendable {
    enum Source: Sendable { case gesture, playPause }

    static let window: TimeInterval = 0.5
    static let shared = PressArbiter()

    private let lock = NSLock()
    private var last: (source: Source, at: TimeInterval)?

    func admit(_ source: Source, at now: TimeInterval) -> Bool {
        lock.withLock {
            if let last, last.source != source, now - last.at < Self.window { return false }
            last = (source, now)
            return true
        }
    }
}

/// Where play/pause is taken and given back: MPRemoteCommandCenter on the Mac, a stand-in in the tests.
@MainActor
protocol RemoteCommands: AnyObject {
    func take(_ press: @escaping @MainActor () -> Void)
    func release()
}

/// Play/pause, taken only while a call is up and given back at hang-up, so outside a call the music keeps it. Never
/// taken when Settings says Nothing.
@MainActor
final class CallPresses {
    private let center: RemoteCommands
    private let arbiter: PressArbiter
    private let clock: () -> TimeInterval
    private var choice = PlayPause.mutePointe
    private(set) var taken = false
    var perform: (PlayPause) -> Void = { _ in }

    init(center: RemoteCommands, arbiter: PressArbiter = .shared, clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.center = center
        self.arbiter = arbiter
        self.clock = clock
    }

    func update(onCall: Bool, choice: PlayPause) {
        self.choice = choice
        let want = onCall && choice != .nothing
        guard want != taken else { return }
        taken = want
        if want { center.take { [weak self] in self?.pressed() } } else { center.release() }
    }

    private func pressed() {
        guard taken, arbiter.admit(.playPause, at: clock()) else { return }
        perform(choice)
    }
}

/// AVAudioApplication's input mute on macOS, or a stand-in in the tests. `listen(nil)` stops.
protocol InputMuteSystem: AnyObject, Sendable {
    func listen(_ handler: (@Sendable (Bool) -> Bool)?)
    func setMuted(_ muted: Bool)
}

/// The stem press during a call. macOS hands the gesture to the handler (on its own queue, or synchronously from inside
/// setInputMuted); the handler answers at once and `onGesture` carries the action. The system's mute is kept equal to
/// the mic, so the next press asks for the right one; the app's own change is not heard back as a press.
final class MuteGesture: @unchecked Sendable {
    private let system: InputMuteSystem
    private let arbiter: PressArbiter
    private let clock: @Sendable () -> TimeInterval
    private let onGesture: @Sendable (AirPodsPress.Gesture) -> Void
    private let lock = NSLock()
    private var listening = false
    private var pushToTalk = false
    private var syncing = false
    private var systemMuted = false

    init(system: InputMuteSystem, arbiter: PressArbiter = .shared,
         clock: @escaping @Sendable () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         onGesture: @escaping @Sendable (AirPodsPress.Gesture) -> Void) {
        self.system = system
        self.arbiter = arbiter
        self.clock = clock
        self.onGesture = onGesture
    }

    /// The call's audio started (again, after a device change): the gesture is Pointe's until `stop`.
    func start(muted: Bool, pushToTalk: Bool) {
        let first = lock.withLock {
            self.pushToTalk = pushToTalk
            defer { listening = true }
            return !listening
        }
        if first { system.listen { [weak self] muted in self?.heard(muted) ?? false } }
        sync(muted: muted)
    }

    func stop() {
        guard lock.withLock({ listening }) else { return }
        sync(muted: false)
        system.listen(nil)
        lock.withLock { listening = false }
    }

    func set(pushToTalk: Bool) { lock.withLock { self.pushToTalk = pushToTalk } }

    /// The mic changed in the app (its button, Space, the talk shortcut, or after a gesture).
    func sync(muted: Bool) {
        let tell = lock.withLock {
            guard listening, systemMuted != muted else { return false }
            syncing = true
            return true
        }
        guard tell else { return }
        system.setMuted(muted)  // calls `heard` from inside: no lock held across it
        lock.withLock {
            syncing = false
            systemMuted = muted
        }
    }

    private func heard(_ muted: Bool) -> Bool {
        let (echo, ptt) = lock.withLock { (syncing, pushToTalk) }
        if echo { return true }
        guard arbiter.admit(.gesture, at: clock()) else { return false }
        let press = AirPodsPress.gesture(muted: muted, pushToTalk: ptt)
        if press.accept { lock.withLock { systemMuted = muted } }
        onGesture(press.action)
        return press.accept
    }
}

#if os(macOS)
/// macOS 14+. Apple: the handler is where a macOS app mutes its own input; the system calls it for a Bluetooth gesture
/// (certain AirPods and Beats) and for setInputMuted. Observing the notification as well is what opts the app in: without
/// an observer audiomxd logs "no recording audio apps found that are opted in to input muting" and rejects the press
/// (github.com/joelmgallant/airpods-meet-mute, 2026-11-09). The gesture reaches only an app that records from the
/// AirPods, which a call does.
final class SystemInputMute: InputMuteSystem, @unchecked Sendable {
    private var observer: NSObjectProtocol?

    func listen(_ handler: (@Sendable (Bool) -> Bool)?) {
        do { try AVAudioApplication.shared.setInputMuteStateChangeHandler(handler) } catch {
            print("pointe: the AirPods press is not available: \(error.localizedDescription)")
        }
        if let observer { NotificationCenter.default.removeObserver(observer) }
        observer = handler == nil ? nil : NotificationCenter.default.addObserver(
            forName: AVAudioApplication.inputMuteStateChangeNotification, object: nil, queue: .main) { _ in }
    }

    func setMuted(_ muted: Bool) { try? AVAudioApplication.shared.setInputMuted(muted) }
}

/// Play/pause on the Mac. macOS sends the remote commands to the Now Playing app, which is the one that says it plays:
/// while held, Pointe's call is Now Playing ("Pointe call" in Control Center), and the keyboard's ⏯ key is Pointe's.
/// Music that starts during the call becomes Now Playing and takes it back.
@MainActor
final class MacRemoteCommands: RemoteCommands {
    private static var commands: [MPRemoteCommand] {
        let center = MPRemoteCommandCenter.shared()
        return [center.togglePlayPauseCommand, center.playCommand, center.pauseCommand]
    }

    func take(_ press: @escaping @MainActor () -> Void) {
        for command in Self.commands {
            command.removeTarget(nil)
            command.isEnabled = true
            command.addTarget(handler: Self.target(press))
        }
        let info = MPNowPlayingInfoCenter.default()
        info.nowPlayingInfo = [MPMediaItemPropertyTitle: "Pointe call"]
        info.playbackState = .playing
    }

    func release() {
        for command in Self.commands {
            command.removeTarget(nil)
            command.isEnabled = false
        }
        let info = MPNowPlayingInfoCenter.default()
        info.playbackState = .stopped
        info.nowPlayingInfo = nil
    }

    /// Built outside the main actor: a closure written in a @MainActor method asserts that it runs on the main thread,
    /// and MediaPlayer does not promise which thread calls it.
    nonisolated private static func target(_ press: @escaping @MainActor () -> Void) -> (MPRemoteCommandEvent) -> MPRemoteCommandHandlerStatus {
        { _ in
            Task { @MainActor in press() }
            return .success
        }
    }
}
#endif
