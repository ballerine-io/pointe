import AVFAudio
import AudioToolbox
import Foundation
import MediaPlayer
import Observation

/// One call to the Mac: the iPhone's voice processing (hardware echo cancellation) in, the bot's voice out, over one
/// WebSocket. Reconnects by itself unless the user hung up.
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
    /// The call on screen, for the "Pointe: Talk" intent.
    static weak var current: Call?

    private let pairing: Pairing
    private let session: URLSession
    private var socket: URLSessionWebSocketTask?
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let playFormat = AVAudioFormat(standardFormatWithSampleRate: Wire.downRate, channels: 1)!
    private var pending: [Float] = []
    private var wanted = false
    private var retries = 0
    private var queued = 0
    private var muteObserver: NSObjectProtocol?

    init(pairing: Pairing) {
        self.pairing = pairing
        let delegate = PinnedDelegate(fingerprint: pairing.fingerprint)
        session = URLSession(configuration: .ephemeral, delegate: delegate, delegateQueue: nil)
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        delegate.onOpen = { [weak self] in Task { @MainActor in self?.state = .live; self?.retries = 0; self?.lastHeard = Date(); self?.opened() } }
        Call.current = self
    }

    var api: API { API(pairing: pairing, session: session) }

    func start() async {
        guard state == .off || state == .reconnecting else { return }
        wanted = true
        state = state == .off ? .connecting : state
        problem = nil
        guard await AVAudioApplication.requestRecordPermission() else {
            problem = "Pointe needs the microphone: allow it in Settings."
            state = .off; wanted = false
            return
        }
        do { try startAudio() } catch {
            problem = "The microphone could not start: \(error.localizedDescription)"
            state = .off; wanted = false
            return
        }
        var request = URLRequest(url: pairing.callURL)
        request.setValue("Bearer \(pairing.key)", forHTTPHeaderField: "Authorization")
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
        try? AVAudioApplication.shared.setInputMuted(value)
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

    func talkPress(_ input: TalkGate.Input) { changeTalk { $0.press(input) } }
    func talkRelease(_ input: TalkGate.Input) { changeTalk { $0.release(input) } }
    func talkToggle() { changeTalk { $0.toggle() } }

    /// The Mac's status: a press it closed by itself closes here too, with a chime.
    func follow(_ status: API.PTTStatus?) {
        if let mode = status?.mode { setMicrophone(mode) }
        if let why = talk.follow(status) {
            talkClosedWhy = why
            AudioServicesPlaySystemSound(1113)
        }
    }

    private func changeTalk(_ change: (inout TalkGate) -> Void) {
        let was = talk.isOpen
        change(&talk)
        guard talk.isOpen != was else { return }
        if talk.isOpen { talkClosedWhy = nil }
        sendTalk(talk.isOpen)
    }

    private func sendTalk(_ open: Bool) {
        socket?.send(.string(TalkGate.message(open: open, at: Date()))) { _ in }
    }

    /// A new link: the press starts closed (the Mac's does too), and the Mac learns this phone knows push to talk.
    private func opened() {
        talk.reset()
        let hello: [String: Any] = ["type": "hello", "protocol": 3, "device": "iPhone", "capabilities": ["ptt"]]
        if let data = try? JSONSerialization.data(withJSONObject: hello), let text = String(data: data, encoding: .utf8) {
            socket?.send(.string(text)) { _ in }
        }
    }

    /// An AirPods press as play/pause, when iOS sends it as a remote command: toggle to talk.
    private func remoteCommands(on: Bool) {
        let center = MPRemoteCommandCenter.shared()
        for command in [center.togglePlayPauseCommand, center.playCommand, center.pauseCommand] {
            command.removeTarget(nil)
            if on {
                command.addTarget { [weak self] _ in
                    Task { @MainActor in self?.talkToggle() }
                    return .success
                }
            }
        }
    }

    // MARK: audio

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
                         block: Call.tap(rate: format.sampleRate) { [weak self] down in Task { @MainActor in self?.send(down) } })
        engine.prepare()
        try engine.start()
        player.play()
    }

    /// In push to talk an AirPods press (which mutes the input) toggles talking instead, and the input is unmuted again.
    private func inputMuteChanged(_ value: Bool) {
        guard talk.ptt else { muted = value; return }
        if value {
            talkToggle()
            setMuted(false)
        }
    }

    private func send(_ samples: [Float]) {
        guard state == .live, !muted, talk.sends(), let socket else {
            if !talk.sends() { pending.removeAll() }
            return
        }
        pending += samples
        while pending.count >= Wire.chunk {
            let chunk = Array(pending.prefix(Wire.chunk))
            pending.removeFirst(Wire.chunk)
            socket.send(.data(Wire.pcm16(chunk))) { _ in }
        }
    }

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
    nonisolated private static func tap(rate: Double, _ deliver: @escaping @Sendable ([Float]) -> Void) -> AVAudioNodeTapBlock {
        { buffer, _ in
            guard let data = buffer.floatChannelData?[0] else { return }
            let samples = Array(UnsafeBufferPointer(start: data, count: Int(buffer.frameLength)))
            deliver(Wire.resample(samples, from: rate, to: Wire.upRate))
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

    /// Text from the Mac: an interrupt, or a heartbeat ping to answer (protocol 2).
    private func control(_ text: String, on socket: URLSessionWebSocketTask) {
        guard let data = text.data(using: .utf8),
              let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        switch message["type"] as? String {
        case "interrupt": flush()
        case "ping":
            rttMs = message["rtt_ms"] as? Int
            if let id = message["id"] as? Int,
               let pong = try? JSONSerialization.data(withJSONObject: ["type": "pong", "id": id]),
               let reply = String(data: pong, encoding: .utf8) {
                socket.send(.string(reply)) { _ in }
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
        if code.rawValue == 4409 && retries == 0 {  // while redialling it is our own dead call, closed by the Mac within 12 s
            problem = "A call is already up on another page or phone."
            wanted = false
        }
        stop(state: wanted ? .reconnecting : .off)
        guard wanted else { return }  // keep trying until the user hangs up: a VPN can take a while to come back
        retries += 1
        let delay = UInt64(min(16, 1 << retries)) * 1_000_000_000
        Task { try? await Task.sleep(nanoseconds: delay); if self.wanted { await self.start() } }
    }

    private func stop(state: State) {
        socket?.cancel(with: .normalClosure, reason: nil)
        socket = nil
        flush()
        pending.removeAll()
        talk.reset()
        if state == .off {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
        self.state = state
    }
}
