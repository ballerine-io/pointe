import AVFAudio
import AudioToolbox
import Foundation
import Observation
import PointeKit
#if os(iOS)
import MediaPlayer
#else
import AppKit
#endif

/// One call to the Mac: the device's voice processing (echo cancellation) in, the bot's voice out, over one WebSocket.
/// Reconnects by itself unless the user hung up. The same call on the iPhone (to the Mac it paired with) and in the Mac
/// app (to the daemon on its own Mac): what differs is the link and how each system gives a microphone.
@MainActor @Observable
final class Call {
    enum State: Equatable { case off, connecting, live, reconnecting }

    private(set) var state: State = .off
    private(set) var muted = false
    private(set) var problem: String?
    private(set) var botSpeaking = false
    /// The last round trip the Mac measured with its pings, in ms; nil before the first.
    private(set) var rttMs: Int?
    /// When anything last arrived from the Mac (audio, a ping): a call can die silently, a VPN dropping or the phone
    /// sleeping, and keep looking live. Past `deadAfter` with nothing, it is treated as dead and reconnected.
    private(set) var lastHeard = Date.distantPast
    nonisolated static let deadAfter: TimeInterval = 6
    /// Push to talk (PushToTalk.swift): what holds the microphone open.
    private(set) var talk = TalkGate()
    /// Why the Mac closed the last press by itself ("held too long", "no audio"), until the next press.
    private(set) var talkClosedWhy: String?
    /// Hold or tap (PushToTalk.swift): this phone's choice, kept on it.
    var talkStyle = TalkStyle.stored() { didSet { UserDefaults.standard.set(talkStyle.rawValue, forKey: TalkStyle.key) } }
    /// A word on the state line right after a press closed ("Sent"; or, after a tap in Hold mode, where Tap to talk is).
    private(set) var talkNote: String?
    /// Debug builds: what the last press did, read by the UI tests and ios/e2e/ptt_latency.py: "open" or "held 2480 ms",
    /// then, from the touch, when the gate opened, when the first chunk left and from when its audio was captured.
    private(set) var talkTrace = ""
    private var talkOpenedAt: Date?
    #if DEBUG
    private var pressTouched: TimeInterval = 0  // the touch that opened the gate, on the audio clock
    private var pressTrace = ""                 // "gate +8 ms · first frame +9 ms · audio from -100 ms", from that touch
    private var awaitingFirstFrame = false
    #endif
    private var talkNotes = 0
    /// Drive mode is on (the Mac's word): an AirPods or lock-screen play/pause mutes, when iOS sends it as one.
    var driving = false { didSet { if driving != oldValue { remoteCommands(on: talk.ptt) } } }
    /// The call on screen, for the "Pointe: Talk" intent.
    static weak var current: Call?

    let link: DaemonLink
    private var session: URLSession!  // made in init, once `self` can be captured for the socket's opening
    private var socket: URLSessionWebSocketTask?
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let playFormat = AVAudioFormat(standardFormatWithSampleRate: Wire.downRate, channels: 1)!
    private var sender = TalkSender()  // what of the microphone goes; while push to talk is closed, the last moments held
    private var wanted = false
    private var retries = 0
    private var queued = 0
    private var muteObserver: NSObjectProtocol?
    #if os(macOS)
    private var deviceObserver: NSObjectProtocol?
    #endif
    /// False while the call is up on audio that gave no echo cancellation (a Mac device whose voice processing would not
    /// start): the screen says to use headphones.
    private(set) var cancelsEcho = true
    /// The newest ping answered on this link, repeated by the keep-alive.
    private var answered = 0
    private var keepAlive: Task<Void, Never>?
    /// How often the phone tells the Mac it is there, on its own (protocol 4). Well inside the Mac's 12 s.
    nonisolated static let aliveEvery: Duration = .seconds(2)

    convenience init(pairing: Pairing) { self.init(link: DaemonLink(pairing)) }

    init(link: DaemonLink) {
        self.link = link
        engine.attach(player)
        #if os(iOS)
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        #endif  // the Mac wires the player when the call starts: its output format must be read before the mixer exists
        session = link.session { [weak self] in
            Task { @MainActor in self?.state = .live; self?.retries = 0; self?.lastHeard = Date(); self?.opened() }
        }
        Call.current = self
    }

    var api: API { API(link: link, session: session) }
    /// Where the Mac is dialled, for a reason that names it.
    var place: String { link.place }

    func start() async {
        guard state == .off || state == .reconnecting else { return }
        wanted = true
        state = state == .off ? .connecting : state
        problem = nil
        guard await AVAudioApplication.requestRecordPermission() else {
            problem = ConnectCopy.micDeniedHere
            state = .off; wanted = false
            return
        }
        do { try startAudio() } catch {
            problem = ConnectCopy.micFailed(error.localizedDescription)
            state = .off; wanted = false
            return
        }
        guard let request = link.callRequest else {  // the Mac app, and no daemon is verified on this Mac
            dropped(code: .invalid)
            return
        }
        let socket = session.webSocketTask(with: request)
        self.socket = socket
        socket.resume()
        receive(socket)
    }

    func hangUp() {
        wanted = false
        Task { try? await api.hungUp() }  // a held prompt goes back to the terminal
        stop(state: .off)
    }

    func toggleMute() { setMuted(!muted) }

    private func setMuted(_ value: Bool) {
        muted = value
        #if os(iOS)
        try? AVAudioApplication.shared.setInputMuted(value)
        #endif  // on the Mac a muted call sends nothing (`send`): macOS has no input mute an app can set by itself
    }

    // MARK: push to talk

    /// The Mac's "microphone" setting. In push to talk the input stays unmuted: the gate decides what is sent.
    func setMicrophone(_ mode: String) {
        guard mode != talk.mode else { return }
        let was = talk.isOpen
        talk.mode = mode
        talk.reset()
        if was { sendTalk(false) }
        if talk.ptt && muted { setMuted(false) }
        remoteCommands(on: talk.ptt)
    }

    /// `touched`: when the finger came down, on the audio clock (`systemUptime`); nil when it is now.
    func talkPress(_ input: TalkGate.Input, touched: TimeInterval? = nil) { changeTalk(touched: touched) { $0.press(input) } }
    func talkRelease(_ input: TalkGate.Input) { changeTalk { $0.release(input) } }
    func talkToggle(touched: TimeInterval? = nil) { changeTalk(touched: touched) { $0.toggle() } }

    /// The Mac's status: a press it closed by itself closes here too, with a chime.
    func follow(_ status: API.PTTStatus?) {
        if let mode = status?.mode { setMicrophone(mode) }
        if let why = talk.follow(status) {
            talkClosedWhy = why
            #if os(iOS)
            AudioServicesPlaySystemSound(1113)
            #else
            NSSound(named: "Tink")?.play()
            #endif
        }
    }

    private func changeTalk(touched: TimeInterval? = nil, _ change: (inout TalkGate) -> Void) {
        let was = talk.isOpen
        change(&talk)
        guard talk.isOpen != was else { return }
        if talk.isOpen {
            talkClosedWhy = nil
            talkNote = nil
            talkOpenedAt = Date()
            #if DEBUG
            let now = ProcessInfo.processInfo.systemUptime
            pressTouched = touched ?? now
            pressTrace = "gate +\(Call.ms(now - pressTouched)) ms"
            awaitingFirstFrame = true
            talkTrace = "open · \(pressTrace)"
            #endif
        } else {
            let held = talkOpenedAt.map { Date().timeIntervalSince($0) } ?? 0
            #if DEBUG
            talkTrace = "held \(Int(held * 1000)) ms · \(pressTrace)"
            #endif
            let short = talkStyle == .hold && held < TalkStyle.shortPress
            note(short ? TalkStyle.shortPressLine : TalkStyle.sentLine, for: short ? TalkStyle.shortPressFor : TalkStyle.sentFor)
        }
        sendTalk(talk.isOpen)
        if talk.isOpen { sendHeld(touched: touched ?? ProcessInfo.processInfo.systemUptime) }
    }

    /// Right after the press message, on the same socket: the audio from the touch on, held while the gate was closed.
    private func sendHeld(touched: TimeInterval) {
        let held = sender.opened(touched: touched)
        guard state == .live, let socket else { return }
        for chunk in held.chunks { socket.send(.data(Wire.pcm16(chunk))) { _ in } }
        #if DEBUG
        if let from = held.from, !held.chunks.isEmpty { traceFirstFrame(from: from) }
        #endif
    }

    private func note(_ line: String, for secs: TimeInterval) {
        talkNotes += 1
        let n = talkNotes
        talkNote = line
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(secs))
            if let self, talkNotes == n { talkNote = nil }
        }
    }

    private func sendTalk(_ open: Bool) {
        socket?.send(.string(TalkGate.message(open: open, at: Date()))) { _ in }
    }

    /// A new link: the press starts closed (the Mac's does too), and the Mac learns this phone knows push to talk.
    private func opened() {
        talk.reset()
        let hello: [String: Any] = ["type": "hello", "protocol": 4, "device": link.device, "capabilities": ["ptt"]]
        if let data = try? JSONSerialization.data(withJSONObject: hello), let text = String(data: data, encoding: .utf8) {
            socket?.send(.string(text)) { _ in }
        }
        keepAlive?.cancel()
        keepAlive = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: Call.aliveEvery)
                guard let self, self.state == .live, let socket = self.socket else { return }
                socket.send(.string(Call.alive(answered: self.answered))) { _ in }
            }
        }
    }

    /// The phone is here, sent every 2 s whatever arrives (protocol 4). The Mac's pings come in order behind its audio,
    /// so on a path slower than the bot's voice they wait behind seconds of it, and the pong with them: the Mac took the
    /// phone for gone after 12 s and closed a call that was only behind. This goes the other way, which the audio does
    /// not fill. Shaped as a pong for the newest ping already answered, so a Mac before protocol 4 counts it as one and
    /// measures no round trip from it.
    nonisolated static func alive(answered id: Int) -> String {
        let body: [String: Any] = ["type": "pong", "id": id, "alive": true]
        guard let data = try? JSONSerialization.data(withJSONObject: body, options: .sortedKeys) else { return "" }
        return String(decoding: data, as: UTF8.self)
    }

    /// An AirPods press as play/pause, when iOS sends it as a remote command: toggle to talk. Not on the Mac: taking
    /// the remote commands there makes the app the Now Playing app and takes the media keys from the music.
    private func remoteCommands(on: Bool) {
        #if os(iOS)
        let center = MPRemoteCommandCenter.shared()
        for command in [center.togglePlayPauseCommand, center.playCommand, center.pauseCommand] {
            command.removeTarget(nil)
            if on {
                command.addTarget { [weak self] _ in
                    Task { @MainActor in self?.talkToggle() }
                    return .success
                }
            } else if driving {
                command.addTarget { [weak self] _ in
                    Task { @MainActor in self?.toggleMute() }
                    return .success
                }
            }
        }
        #endif
    }

    // MARK: audio

    #if os(iOS)
    private func startAudio() throws {
        guard !engine.isRunning else { return }
        let audio = AVAudioSession.sharedInstance()
        try audio.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
        try audio.setActive(true)
        let input = engine.inputNode
        try input.setVoiceProcessingEnabled(true)  // the iPhone removes the bot's own voice from the mic
        // An AirPods press (or Control Center) mutes the input; follow it, so "Listening" is never a lie.
        if muteObserver == nil {
            muteObserver = NotificationCenter.default.addObserver(
                forName: AVAudioApplication.inputMuteStateChangeNotification, object: nil, queue: .main) { [weak self] note in
                let isMuted = note.userInfo?[AVAudioApplication.muteStateKey] as? Bool
                Task { @MainActor in self?.inputMuteChanged(isMuted ?? AVAudioApplication.shared.isInputMuted) }
            }
        }
        let format = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format,
                         block: Call.tap(rate: format.sampleRate) { [weak self] down, end in Task { @MainActor in self?.send(down, end: end) } })
        engine.prepare()
        try engine.start()
        player.play()
    }
    #endif

    #if os(macOS)
    /// How the engine is wired, best first. macOS's voice-processing unit refuses to initialise (-10875) when the mixer
    /// feeds it the output device's own stereo format: it takes one channel at the device's rate. Found on a MacBook
    /// Pro's built-in devices (macOS 27); the others are kept so a device that differs still gets a call
    /// (docs/design/macos-app.md, "Audio").
    private enum Wiring: CaseIterable {
        /// Echo cancellation on, the mixer feeding the output one channel.
        case voiceMono
        /// Echo cancellation on, the engine's own connection to the output.
        case voiceDefault
        /// No voice processing: the call works, and the bot can hear itself through loudspeakers.
        case plain
    }

    struct NoMicrophone: LocalizedError { var errorDescription: String? { MacCopy.noMic } }

    private func startAudio() throws {
        guard !engine.isRunning else { return }
        var last: Error = NoMicrophone()
        for wiring in Wiring.allCases {
            do {
                try startAudio(wiring)
                cancelsEcho = wiring != .plain
                watchDevices()
                return
            } catch let error as NoMicrophone {
                throw error
            } catch {
                last = error
                engine.inputNode.removeTap(onBus: 0)
                engine.stop()
                engine.reset()
            }
        }
        throw last
    }

    private func startAudio(_ wiring: Wiring) throws {
        let input = engine.inputNode
        try input.setVoiceProcessingEnabled(wiring != .plain)
        if wiring != .plain {
            // Other apps' audio is ducked as little as the system allows while the call is up.
            input.voiceProcessingOtherAudioDuckingConfiguration = .init(enableAdvancedDucking: false, duckingLevel: .min)
        }
        // The output's format is read before the mixer exists: asking for the mixer connects it to the output in stereo.
        let out = engine.outputNode.inputFormat(forBus: 0)
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        let mono = wiring == .voiceMono ? AVAudioFormat(standardFormatWithSampleRate: out.sampleRate, channels: 1) : nil
        engine.connect(engine.mainMixerNode, to: engine.outputNode, format: mono)
        let format = input.outputFormat(forBus: 0)  // voice processing decides the rate and the channel count; channel 0 is the voice
        guard format.sampleRate > 0, format.channelCount > 0 else { throw NoMicrophone() }
        input.installTap(onBus: 0, bufferSize: 1024, format: format,
                         block: Call.tap(rate: format.sampleRate) { [weak self] down, end in Task { @MainActor in self?.send(down, end: end) } })
        engine.prepare()
        try engine.start()
        player.play()
    }

    /// AirPods joined or left, the default device or its sample rate changed: the engine stopped itself. It is started
    /// again with the new format while the socket stays up; a restart that fails ends the call with the reason.
    private func watchDevices() {
        guard deviceObserver == nil else { return }
        deviceObserver = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.devicesChanged() }
        }
    }

    private func devicesChanged() {
        guard state != .off else { return }
        engine.inputNode.removeTap(onBus: 0)
        player.stop()
        engine.stop()
        queued = 0
        botSpeaking = false
        do { try startAudio() } catch {
            wanted = false
            Task { try? await api.hungUp() }
            stop(state: .off)
            problem = ConnectCopy.micFailed(error.localizedDescription)
        }
    }
    #endif

    /// In push to talk an AirPods press (which mutes the input) toggles talking instead, and the input is unmuted again.
    private func inputMuteChanged(_ value: Bool) {
        guard talk.ptt else { muted = value; return }
        if value {
            talkToggle()
            setMuted(false)
        }
    }

    private func send(_ samples: [Float], end: TimeInterval) {
        guard state == .live, !muted, let socket else {  // muted or no call: nothing is sent, and nothing is held
            sender.reset()
            return
        }
        let chunks = sender.capture(samples, end: end, sending: talk.sends())
        for chunk in chunks { socket.send(.data(Wire.pcm16(chunk))) { _ in } }
        #if DEBUG
        if !chunks.isEmpty { traceFirstFrame(from: end - Double(samples.count) / Wire.upRate) }
        #endif
    }

    #if DEBUG
    /// The first chunk of a press left: when, and from when its audio was captured, both from the touch.
    private func traceFirstFrame(from: TimeInterval) {
        guard awaitingFirstFrame, talk.isOpen else { return }
        awaitingFirstFrame = false
        let now = ProcessInfo.processInfo.systemUptime
        pressTrace += " · first frame +\(Call.ms(now - pressTouched)) ms · audio from \(Call.ms(from - pressTouched)) ms"
        talkTrace = "open · \(pressTrace)"
    }

    nonisolated static func ms(_ seconds: TimeInterval) -> Int { Int((seconds * 1000).rounded()) }
    #endif

    private func play(_ data: Data) {
        let samples = Wire.floats(data)
        guard !samples.isEmpty, let buffer = AVAudioPCMBuffer(pcmFormat: playFormat, frameCapacity: AVAudioFrameCount(samples.count))
        else { return }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { buffer.floatChannelData![0].update(from: $0.baseAddress!, count: samples.count) }
        queued += 1
        botSpeaking = true
        player.scheduleBuffer(buffer, completionHandler: Call.whenPlayed(self))
    }

    /// Built outside the main actor: AVFoundation calls these on its audio thread, and a closure written inside a
    /// @MainActor method would assert that it runs on the main thread, and crash.
    /// `end`: when the buffer's last sample was captured, on the audio clock (`systemUptime`).
    nonisolated private static func tap(rate: Double, _ deliver: @escaping @Sendable ([Float], TimeInterval) -> Void) -> AVAudioNodeTapBlock {
        { buffer, when in
            guard let data = buffer.floatChannelData?[0] else { return }
            let samples = Array(UnsafeBufferPointer(start: data, count: Int(buffer.frameLength)))
            let end = when.isHostTimeValid ? AVAudioTime.seconds(forHostTime: when.hostTime) + Double(buffer.frameLength) / rate
                                           : ProcessInfo.processInfo.systemUptime
            deliver(Wire.resample(samples, from: rate, to: Wire.upRate), end)
        }
    }

    nonisolated private static func whenPlayed(_ call: Call) -> AVAudioNodeCompletionHandler {
        { [weak call] in Task { @MainActor in call?.played() } }
    }

    private func played() {
        queued -= 1
        if queued <= 0 { queued = 0; botSpeaking = false }
    }

    /// The user cut the bot off: drop what is queued at once, or it keeps talking over them.
    private func flush() {
        player.stop()
        queued = 0
        botSpeaking = false
        player.play()
    }

    // MARK: link

    private func receive(_ socket: URLSessionWebSocketTask) {
        socket.receive { [weak self] result in
            Task { @MainActor in
                guard let self, self.socket === socket else { return }
                switch result {
                case .success(let message):
                    self.lastHeard = Date()
                    switch message {
                    case .data(let data): self.play(data)
                    case .string(let text): self.control(text, on: socket)
                    @unknown default: break
                    }
                    self.receive(socket)
                case .failure(let error):
                    print("pointe: call failed: \(error) close=\(socket.closeCode.rawValue)")
                    self.dropped(code: socket.closeCode)
                }
            }
        }
    }

    /// Text from the Mac: an interrupt, a heartbeat ping to answer (protocol 2), or a press made on the Mac (protocol 3).
    private func control(_ text: String, on socket: URLSessionWebSocketTask) {
        guard let data = text.data(using: .utf8),
              let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        switch message["type"] as? String {
        case "interrupt": flush()
        case "ptt":  // a system-wide shortcut on the Mac pressed the gate: this phone sends as if its own press held it
            if let open = message["open"] as? Bool { changeTalk { $0.set(open: open) } }
        case "ping":
            rttMs = message["rtt_ms"] as? Int
            if let id = message["id"] as? Int,
               let pong = try? JSONSerialization.data(withJSONObject: ["type": "pong", "id": id]),
               let reply = String(data: pong, encoding: .utf8) {
                socket.send(.string(reply)) { _ in }
                answered = max(answered, id)
            }
        default: break
        }
    }

    /// Checked every second while a call is wanted: a live call that went quiet is dead, and is redialled.
    func checkHealth() {
        guard wanted else { return }
        if state == .live, Date().timeIntervalSince(lastHeard) > Call.deadAfter {
            print("pointe: nothing from the Mac for \(Int(Call.deadAfter)) s: reconnecting")
            dropped(code: .abnormalClosure)
        }
    }

    /// The app came back to the foreground: redial a call that dropped while it was away.
    func resume() async {
        guard wanted, state == .off || state == .reconnecting else { return }
        retries = 0
        await start()
    }

    private func dropped(code: URLSessionWebSocketTask.CloseCode) {
        let http = (socket?.response as? HTTPURLResponse)?.statusCode
        let reason = socket?.closeReason.flatMap { String(data: $0, encoding: .utf8) } ?? ""
        if let why = Call.refusal(code: code.rawValue, http: http, reason: reason, firstDial: state == .connecting,
                                  retries: retries, place: place) {
            problem = why
            wanted = false
        }
        stop(state: wanted ? .reconnecting : .off)
        guard wanted else { return }  // keep trying until the user hangs up: a VPN can take a while to come back
        retries += 1
        let delay = UInt64(min(16, 1 << retries)) * 1_000_000_000
        Task {
            try? await Task.sleep(nanoseconds: delay)
            guard self.wanted else { return }
            // The Mac's idle timer closes the link like any hang-up: ask it before calling back, as the page does.
            if let status = try? await self.api.status(), !Call.redials(idleHangup: status.idle_hangup) {
                self.wanted = false
                self.problem = Call.idleHangupNote
                self.stop(state: .off)
                return
            }
            await self.start()
        }
    }

    nonisolated static let idleHangupNote = ConnectCopy.idleHangupHere

    /// Why a dropped link is not called back, in the words Connect shows; nil for a live call that dropped, which is
    /// redialled by itself. The Mac turning this phone away (its key unpaired: 401/403 at the upgrade, or a 4401 or 1008
    /// close), a call already up (4409 on the first try: while redialling it is our own dead call, closed by the Mac
    /// within 12 s), or a first dial that never opened: that one stays off and says why, instead of redialling for ever
    /// against a Mac that is away.
    nonisolated static func refusal(code: Int, http: Int?, reason: String, firstDial: Bool, retries: Int, place: String) -> String? {
        if code == 4401 || code == 1008 || http == 401 || http == 403 { return ConnectCopy.notPairedHere }
        if code == 4409 && retries == 0 { return ConnectCopy.busy }
        guard firstDial else { return nil }
        if http == nil && code <= 0 { return ConnectCopy.unreachableHere(place) }  // never answered: no upgrade, no close frame
        return ConnectCopy.failed(reason.isEmpty ? (http.map { "HTTP \($0)" } ?? "code \(code)") : reason)
    }

    /// A link that dropped is called back; a call the Mac's idle timer ended is not (nil: the Mac did not say).
    nonisolated static func redials(idleHangup: Bool?) -> Bool { idleHangup != true }

    private func stop(state: State) {
        keepAlive?.cancel()
        keepAlive = nil
        answered = 0
        socket?.cancel(with: .normalClosure, reason: nil)
        socket = nil
        flush()
        sender.reset()
        talk.reset()
        if state == .off {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
            #if os(iOS)
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
            #else
            if let deviceObserver { NotificationCenter.default.removeObserver(deviceObserver) }
            deviceObserver = nil
            try? engine.inputNode.setVoiceProcessingEnabled(false)  // gives the microphone back: the orange dot goes out
            #endif
        }
        self.state = state
    }
}
