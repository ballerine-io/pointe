import AVFAudio
import AudioToolbox
import Foundation
import Network
import Observation
import PointeKit
#if os(iOS)
import MediaPlayer
#else
import AppKit
#endif

/// One call to the Mac: the device's voice processing (echo cancellation) in, the bot's voice out, over one WebSocket.
/// A link that drops is dialled again at once and the Mac puts the phone back on the same call (LinkMachine, phone.py
/// protocol 5), until the user hangs up. The voice and the socket run off the main thread (CallWire). The same call on
/// the iPhone (to the Mac it paired with) and in the Mac app (to the daemon on its own Mac): what differs is the link
/// and how each system gives a microphone.
@MainActor @Observable
final class Call {
    enum State: Equatable { case off, connecting, live, reconnecting }

    private(set) var state: State = .off
    private(set) var muted = false
    private(set) var problem: String?
    private(set) var botSpeaking = false
    /// The last round trip the Mac measured with its pings, in ms; nil before the first.
    private(set) var rttMs: Int?
    /// Whole seconds since anything arrived from the Mac (audio, a ping), while live: a call can die silently, a VPN
    /// dropping or the phone sleeping, and keep looking live. Past `deadAfter` with nothing, the link is given up and
    /// dialled again. Counted twice a second, not on each arrival: what a view reads must not change 50 times a second.
    private(set) var quietSecs = 0
    nonisolated static let deadAfter: TimeInterval = 6
    /// Push to talk (PushToTalk.swift): what holds the microphone open.
    private(set) var talk = TalkGate()
    /// Why the Mac closed the last press by itself ("held too long", "no audio"), until the next press.
    private(set) var talkClosedWhy: String?
    /// Hold or tap (PushToTalk.swift): this phone's choice, kept on it.
    var talkStyle = TalkStyle.stored() { didSet { UserDefaults.standard.set(talkStyle.rawValue, forKey: TalkStyle.key) } }
    /// A word on the state line right after a press closed ("Sent"; or, after a tap in Hold mode, where Tap to talk is).
    private(set) var talkNote: String?
    /// Debug builds: what the last press did, read by the UI tests and apps/ios/e2e/ptt_latency.py: "open" or "held 2480 ms",
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

    let link: DaemonLink
    @ObservationIgnored private var session: URLSession!  // made in init, once `self` can be captured for the socket's opening
    @ObservationIgnored private var wire: CallWire?
    @ObservationIgnored private var machine = LinkMachine()
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let playFormat = AVAudioFormat(standardFormatWithSampleRate: Wire.downRate, channels: 1)!
    @ObservationIgnored private var playout: Playout!
    @ObservationIgnored private var sender = TalkSender()  // what of the microphone goes; while push to talk is closed, the last moments held
    @ObservationIgnored private var wanted = false
    @ObservationIgnored private var redialTask: Task<Void, Never>?
    @ObservationIgnored private var watchdog: Task<Void, Never>?
    @ObservationIgnored private var pathMonitor: NWPathMonitor?
    @ObservationIgnored private var lastPath: String?
    /// Debug builds: what the link did, read by apps/ios/e2e/bad_network.py through the UI test: dials, resumes, the
    /// speaker's underruns and gaps, the microphone audio dropped, and the main thread's longest stall.
    private(set) var netTrace = ""
    @ObservationIgnored private var dials = 0
    @ObservationIgnored private var resumes = 0
    @ObservationIgnored private var droppedUp: TimeInterval = 0
    @ObservationIgnored private var redialSince: TimeInterval?
    @ObservationIgnored private var redialSecs: TimeInterval = 0
    @ObservationIgnored private var muteObserver: NSObjectProtocol?
    #if os(macOS)
    private var deviceObserver: NSObjectProtocol?
    #endif
    /// False while the call is up on audio that gave no echo cancellation (a Mac device whose voice processing would not
    /// start): the screen says to use headphones.
    private(set) var cancelsEcho = true
    @ObservationIgnored private var keepAlive: Task<Void, Never>?
    /// How often the phone tells the Mac it is there, on its own (protocol 4). Well inside the Mac's 12 s.
    nonisolated static let aliveEvery: Duration = .seconds(2)

    convenience init(pairing: Pairing) { self.init(link: DaemonLink(pairing)) }

    init(link: DaemonLink) {
        self.link = link
        engine.attach(player)
        #if os(iOS)
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        #endif  // the Mac wires the player when the call starts: its output format must be read before the mixer exists
        playout = Playout(player: player, format: playFormat) { [weak self] speaking in
            Task { @MainActor in if self?.botSpeaking != speaking { self?.botSpeaking = speaking } }
        }
        session = link.session { [weak self] in
            Task { @MainActor in self?.opened() }
        }
    }

    var api: API { API(link: link, session: session) }
    /// Where the Mac is dialled, for a reason that names it.
    var place: String { link.place }

    func start() async {
        guard state == .off || state == .reconnecting else { return }
        wanted = true
        machine.start()
        sync()
        let allowed = Call.synthetic ? true : await AVAudioApplication.requestRecordPermission()
        guard allowed else {
            apply(machine.end(ConnectCopy.micDeniedHere))
            return
        }
        do { try startAudio() } catch {
            apply(machine.end(ConnectCopy.micFailed(error.localizedDescription)))
            return
        }
        watch()
        dial()
    }

    /// A new socket for the call: the first, or one that brings the call back (the hello carries its token).
    private func dial() {
        redialTask?.cancel()
        redialTask = nil
        guard wanted else { return }
        guard let request = link.callRequest(reading: MuteChoice.stored()) else {  // the Mac app, and no daemon is verified on this Mac
            linkEnded(code: URLSessionWebSocketTask.CloseCode.invalid.rawValue, http: nil, reason: "")
            return
        }
        dials += 1
        wire?.close(.goingAway)  // a dial still opening (back from the background mid-redial): this one replaces it
        let wire = CallWire(socket: session.webSocketTask(with: request), playout: playout) { [weak self] wire, event in
            Task { @MainActor in self?.wireEvent(event, from: wire) }
        }
        self.wire = wire
        wire.start(hello: Wire.hello(device: link.device, resume: machine.token))
        trace()
    }

    func hangUp() {
        wanted = false
        machine.hungUp()
        Task { try? await api.hungUp() }  // a held prompt goes back to the terminal
        stop(state: .off, close: .normalClosure)
    }

    /// Hang up for a caller that iOS may suspend as soon as it returns (a Live Activity's button): the Mac is told
    /// before the socket closes and the audio session goes, which is what kept the app running.
    func hangUpAndWait() async {
        wanted = false
        machine.hungUp()
        try? await api.hungUp()
        stop(state: .off, close: .normalClosure)
    }

    func toggleMute() { setMuted(!muted) }

    /// Pointe was muted mid-sentence: what this device still holds to play stops now, before the Mac's own cut arrives.
    func hush() {
        guard state != .off else { return }
        playout.flush()
    }

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
        guard state == .live, let wire else { return }
        wire.send(audio: held.chunks)
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
        wire?.send(text: TalkGate.message(open: open, at: Date()))
    }

    /// A new link: the press starts closed. The hello went out with the socket; the Mac answers it with the call.
    private func opened() {
        guard wanted, wire != nil else { return }
        machine.opened()
        sync()
        talk.reset()
        keepAlive?.cancel()
        keepAlive = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: Call.aliveEvery)
                guard let self, self.state == .live, let wire = self.wire else { return }
                wire.sendAlive()
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

    /// Debug builds, for apps/ios/e2e/bad_network.py: a voice-like tone in place of the microphone and a silent speaker, so a
    /// run in the simulator never opens the Mac's microphone or plays into the room. Release builds have neither.
    #if DEBUG
    #if os(iOS)
    nonisolated static let synthetic = ProcessInfo.processInfo.environment["POINTE_SYNTHETIC_MIC"] == "1"
    @ObservationIgnored private var syntheticMic: Task<Void, Never>?

    private func startSynthetic() throws {
        try AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
        try AVAudioSession.sharedInstance().setActive(true)
        engine.mainMixerNode.outputVolume = 0
        engine.prepare()
        try engine.start()
        player.play()
        syntheticMic?.cancel()
        syntheticMic = Task { @MainActor [weak self] in
            var n = 0
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(20))
                let samples = (0..<Wire.chunk).map { i in Float(sin(Double(n * Wire.chunk + i) * 0.06)) * 0.2 }
                n += 1
                self?.send(samples, end: ProcessInfo.processInfo.systemUptime)
            }
        }
    }
    #else
    nonisolated static let synthetic = false
    #endif
    #else
    nonisolated static let synthetic = false
    #endif

    #if os(iOS)
    private func startAudio() throws {
        guard !engine.isRunning else { return }
        #if DEBUG && os(iOS)
        if Call.synthetic { return try startSynthetic() }
        #endif
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
        playout.flush()
        engine.stop()
        do { try startAudio() } catch {
            wanted = false
            Task { try? await api.hungUp() }
            apply(machine.end(ConnectCopy.micFailed(error.localizedDescription)), close: .normalClosure)
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
        guard state == .live, !muted, let wire else {  // muted or no call: nothing is sent, and nothing is held
            sender.reset()
            return
        }
        let chunks = sender.capture(samples, end: end, sending: talk.sends())
        wire.send(audio: chunks)
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

    // MARK: link

    private func wireEvent(_ event: CallWire.Event, from wire: CallWire) {
        guard wire === self.wire else { return }  // a socket the call already left
        switch event {
        case .rtt(let ms):
            rttMs = ms
        case .control(.ptt(let open)):  // a system-wide shortcut on the Mac pressed the gate: this phone sends as if its own press held it
            changeTalk { $0.set(open: open) }
        case .control(.call(let token, let resumed, _, _)):
            machine.answered(token: token)
            if resumed {
                resumes += 1
                if talk.ptt { sendTalk(false) }  // the press starts closed on a new link, here and on the Mac
            }
            trace()
        case .control:
            break
        case .text(let text):  // the owner said "stop talking, I'll read" or "talk again": this device keeps it for its next call
            if let data = text.data(using: .utf8), let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               message["type"] as? String == "reading", let on = MuteChoice.message(message) {
                MuteChoice.store(on)
            }
        case .ended(let code, let http, let reason):
            linkEnded(code: code, http: http, reason: reason)
        }
    }

    /// Checked every second while a call is wanted (the screens call it too): a live call that went quiet is given up
    /// and dialled again, not left showing "Listening".
    func checkHealth() {
        guard wanted, state == .live, let wire else {
            if quietSecs != 0 { quietSecs = 0 }
            return
        }
        let quiet = wire.quiet
        if Int(quiet) != quietSecs { quietSecs = Int(quiet) }
        if quiet > Call.deadAfter {
            print("pointe: nothing from the Mac for \(Int(Call.deadAfter)) s: dialling again")
            apply(machine.quiet(random: .random(in: 0..<1)), close: .goingAway)
        }
    }

    /// The call's own clock while it is wanted: health twice a second, whatever the screen is busy with.
    private func watch() {
        guard watchdog == nil else { return }
        watchdog = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(500))
                guard let self, self.wanted else { return }
                self.checkHealth()
                self.trace()
            }
        }
        watchPath()
    }

    /// The phone's network changed (Wi-Fi to cellular, a VPN coming up): a socket on the old one can hang for seconds
    /// before anything says so. The call is dialled on the new one at once, and the Mac moves it there.
    private func watchPath() {
        guard pathMonitor == nil, !link.isLocal else { return }
        let monitor = NWPathMonitor()
        monitor.pathUpdateHandler = { [weak self] path in
            let name = Call.pathName(path)
            Task { @MainActor in self?.pathChanged(name) }
        }
        monitor.start(queue: DispatchQueue(label: "io.ballerine.pointe.path"))
        pathMonitor = monitor
    }

    nonisolated static func pathName(_ path: NWPath) -> String {
        guard path.status == .satisfied else { return "none" }
        return path.availableInterfaces.first.map { "\($0.type)/\($0.name)" } ?? "some"
    }

    private func pathChanged(_ path: String) {
        defer { lastPath = path }
        guard let last = lastPath, last != path, path != "none", wanted else { return }
        print("pointe: the network changed (\(last) to \(path)): moving the call to it")
        apply(machine.networkChanged(), close: .goingAway)
    }

    /// The app came back to the foreground: dial now a call that dropped while it was away.
    func resume() async {
        guard wanted, state == .reconnecting else { return }
        dial()
    }

    private func linkEnded(code: Int, http: Int?, reason: String) {
        apply(machine.dropped(code: code, http: http, reason: reason, place: place, random: .random(in: 0..<1)), close: .goingAway,
              hungUpByMac: code == URLSessionWebSocketTask.CloseCode.normalClosure.rawValue)
    }

    /// Do what the machine decided: the link given up is closed; then dial again, or end the call.
    private func apply(_ action: LinkMachine.Action, close: URLSessionWebSocketTask.CloseCode = .goingAway, hungUpByMac: Bool = false) {
        switch action {
        case .none:
            sync()
        case .stop:
            wanted = false
            stop(state: .off, close: close)
        case .dial(let after):
            stop(state: .reconnecting, close: close)
            redialTask = Task { @MainActor [weak self] in
                try? await Task.sleep(for: .seconds(after))
                guard let self, !Task.isCancelled, self.wanted else { return }
                // The Mac's idle timer closes the link like a hang-up (1000): ask it before calling back, as the page
                // does. A link that was lost is dialled at once: the Mac holds that call for the phone.
                if hungUpByMac || self.machine.token == nil,
                   let status = try? await self.api.status(), !Call.redials(idleHangup: status.idle_hangup) {
                    self.apply(self.machine.end(Call.idleHangupNote))
                    return
                }
                self.dial()
            }
        }
    }

    private func sync() {
        if state != machine.state { state = machine.state }
        if problem != machine.problem { problem = machine.problem }
    }

    private func trace() {
        #if DEBUG
        droppedUp = max(droppedUp, wire?.droppedUp ?? 0)
        let stall = MainStall.shared
        if state == .reconnecting, redialSince == nil { redialSince = ProcessInfo.processInfo.systemUptime }
        if state != .reconnecting, let since = redialSince {
            redialSecs += ProcessInfo.processInfo.systemUptime - since
            redialSince = nil
        }
        let line = "dials=\(dials) resumes=\(resumes) underruns=\(playout.underruns) gapMs=\(playout.gapMs) "
            + "upDroppedMs=\(Int(droppedUp * 1000)) stalls=\(stall.count) maxStallMs=\(stall.maxMs) "
            + "reconnectingMs=\(Int(redialSecs * 1000)) shown=\(NetProbe.shownLine) sent=\(NetProbe.sentLine)"
        if line != netTrace { netTrace = line }
        #endif
    }

    nonisolated static let idleHangupNote = ConnectCopy.idleHangupHere

    /// Why a dropped link is not called back, in the words Connect shows; nil for a live call that dropped, which is
    /// redialled by itself. The Mac turning this phone away (its key unpaired: 401/403 at the upgrade, or a 4401 or 1008
    /// close), a call already up when the user tapped Connect (4409), or a first dial that never opened: that one stays
    /// off and says why, instead of redialling for ever against a Mac that is away. `firstDial` is the user's own dial,
    /// whatever the socket did: a redial that opened and then met the Mac's 4409 (its dead call, or a moment before it
    /// knows this phone is back) keeps trying, where 1.23 counted the open as a first try and ended the call as busy.
    nonisolated static func refusal(code: Int, http: Int?, reason: String, firstDial: Bool, place: String) -> String? {
        if code == 4401 || code == 1008 || http == 401 || http == 403 { return ConnectCopy.notPairedHere }
        guard firstDial else { return nil }
        if code == 4409 { return ConnectCopy.busy }
        if http == nil && code <= 0 { return ConnectCopy.unreachableHere(place) }  // never answered: no upgrade, no close frame
        return ConnectCopy.failed(reason.isEmpty ? (http.map { "HTTP \($0)" } ?? "code \(code)") : reason)
    }

    /// A link that dropped is called back; a call the Mac's idle timer ended is not (nil: the Mac did not say).
    nonisolated static func redials(idleHangup: Bool?) -> Bool { idleHangup != true }

    /// The link is closed (1000 for a hang-up, 1001 when it is given up and the call goes on over a new one); off also
    /// stops the audio.
    private func stop(state: State, close: URLSessionWebSocketTask.CloseCode) {
        keepAlive?.cancel()
        keepAlive = nil
        redialTask?.cancel()
        redialTask = nil
        wire?.close(close)
        wire = nil
        playout.flush()
        sender.reset()
        talk.reset()
        if quietSecs != 0 { quietSecs = 0 }
        if state == .off {
            #if DEBUG && os(iOS)
            syntheticMic?.cancel()
            syntheticMic = nil
            if Call.synthetic {
                engine.stop()
                sync()
                if self.state != state { self.state = state }
                return
            }
            #endif
            watchdog?.cancel()
            watchdog = nil
            pathMonitor?.cancel()
            pathMonitor = nil
            lastPath = nil
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
        sync()
        if self.state != state { self.state = state }
        trace()
    }
}
