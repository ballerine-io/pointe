import Foundation
import Observation

/// One frame on the call's socket: the bot's voice, or a control message.
public enum CallFrame: Sendable, Equatable {
    case text(String)
    case audio(Data)
}

/// How a link ended: the WebSocket close code (0 or less: no close frame), the HTTP status when the upgrade was
/// refused, and the reason the daemon gave.
public struct CallClose: Error, Sendable, Equatable {
    public let code: Int
    public let http: Int?
    public let reason: String

    public init(code: Int, http: Int? = nil, reason: String = "") {
        self.code = code
        self.http = http
        self.reason = reason
    }
}

/// One open link to the daemon's call socket.
public protocol CallSocket: Sendable {
    func send(text: String)
    func send(audio: Data)
    /// The next frame; throws `CallClose` when the link ends.
    func receive() async throws -> CallFrame
    func close()
}

/// Opens a link. Returns once the socket is open; throws `CallClose` when the daemon turned it away or did not answer.
public protocol CallDialer: Sendable {
    func dial() async throws -> any CallSocket
}

public enum CallAudioError: Error, Equatable, Sendable {
    case denied
    case noMicrophone
    case failed(String)
}

/// The device's microphone and speaker for a call. `deliver` gets 16 kHz mono samples, from any thread.
@MainActor
public protocol CallAudio: AnyObject {
    func start(deliver: @escaping @Sendable ([Float]) -> Void) async throws
    func stop()
    /// 24 kHz mono samples of the bot's voice.
    func play(_ samples: [Float])
    /// The user cut the bot off: drop what is queued at once.
    func flush()
    /// Called on the main actor when the bot's voice starts or stops coming out.
    var onSpeaking: ((Bool) -> Void)? { get set }
}

/// One call to the daemon: the microphone in, the bot's voice out, over one WebSocket (phone.py, protocol 4). It
/// redials by itself unless the user hung up, and knows why a link that will not come back was refused.
@MainActor @Observable
public final class CallLink {
    public enum State: Equatable, Sendable { case off, connecting, live, reconnecting }

    /// The lines a refusal is said in: each surface has its own (the page's, the iPhone's).
    public struct Words: Sendable {
        public var notPaired: String
        public var busy: String
        public var idleHangup: String
        public var micDenied: String
        public var noMic: String
        public var micFailed: @Sendable (String) -> String
        public var unreachable: @Sendable (String) -> String
        public var failed: @Sendable (String) -> String

        public init(notPaired: String, busy: String, idleHangup: String, micDenied: String, noMic: String,
                    micFailed: @escaping @Sendable (String) -> String, unreachable: @escaping @Sendable (String) -> String,
                    failed: @escaping @Sendable (String) -> String) {
            self.notPaired = notPaired; self.busy = busy; self.idleHangup = idleHangup; self.micDenied = micDenied
            self.noMic = noMic; self.micFailed = micFailed; self.unreachable = unreachable; self.failed = failed
        }
    }

    public private(set) var state: State = .off
    public private(set) var muted = false
    public private(set) var problem: String?
    public private(set) var botSpeaking = false
    /// The last round trip the daemon measured with its pings, in ms; nil before the first.
    public private(set) var rttMs: Int?
    /// When anything last arrived from the daemon: a call can die silently and keep looking live. Past `deadAfter`
    /// with nothing, it is treated as dead and redialled.
    public private(set) var lastHeard = Date.distantPast
    public nonisolated static let deadAfter: TimeInterval = 6
    /// Push to talk: what holds the microphone open.
    public private(set) var talk = TalkGate()
    /// Why the daemon closed the last press by itself ("held too long", "no audio"), until the next press.
    public private(set) var talkClosedWhy: String?
    /// Hold or tap: this device's choice.
    public var talkStyle: TalkStyle
    /// A word on the state line right after a press closed ("Sent"; or, after a short press in Hold mode, the hint).
    public private(set) var talkNote: String?
    /// What the last press did and for how long ("open", "held 2480 ms"): read by the UI tests.
    public private(set) var talkTrace = ""

    private let dialer: any CallDialer
    private let audio: any CallAudio
    private let device: String
    private let place: String
    private let words: Words
    private let idleHangup: @Sendable () async -> Bool?
    private let hungUp: @Sendable () async -> Void
    private let sleep: @Sendable (TimeInterval) async -> Void
    private let now: @Sendable () -> Date

    private var socket: (any CallSocket)?
    private var reader: Task<Void, Never>?
    private var pending: [Float] = []
    private var wanted = false
    private var retries = 0
    private var generation = 0
    private var talkOpenedAt: Date?
    private var talkNotes = 0
    /// The newest ping answered on this link, repeated by the keep-alive.
    private var answered = 0
    private var keepAlive: Task<Void, Never>?
    private let aliveEvery: Duration

    /// - Parameters:
    ///   - idleHangup: asks the daemon whether its idle timer ended the last call (status `idle_hangup`): such a call is
    ///     not redialled. nil: the daemon did not say.
    ///   - hungUp: tells the daemon the user hung up, so a held prompt goes back to its terminal.
    public init(dialer: any CallDialer, audio: any CallAudio, device: String, place: String, words: Words,
                talkStyle: TalkStyle = .hold, aliveEvery: Duration = .seconds(2),
                idleHangup: @escaping @Sendable () async -> Bool? = { nil },
                hungUp: @escaping @Sendable () async -> Void = {},
                sleep: @escaping @Sendable (TimeInterval) async -> Void = { try? await Task.sleep(for: .seconds($0)) },
                now: @escaping @Sendable () -> Date = { Date() }) {
        self.dialer = dialer
        self.audio = audio
        self.device = device
        self.place = place
        self.words = words
        self.talkStyle = talkStyle
        self.aliveEvery = aliveEvery
        self.idleHangup = idleHangup
        self.hungUp = hungUp
        self.sleep = sleep
        self.now = now
        audio.onSpeaking = { [weak self] speaking in self?.botSpeaking = speaking }
    }

    public var isWanted: Bool { wanted }

    public func start() async {
        guard state == .off || state == .reconnecting else { return }
        wanted = true
        if state == .off { state = .connecting }
        problem = nil
        generation += 1
        let mine = generation
        do {
            try await audio.start { [weak self] samples in Task { @MainActor in self?.captured(samples) } }
        } catch {
            guard mine == generation else { return }
            problem = switch error as? CallAudioError {
            case .denied: words.micDenied
            case .noMicrophone: words.noMic
            case .failed(let why): words.micFailed(why)
            case nil: words.micFailed(error.localizedDescription)
            }
            wanted = false
            stop(state: .off)
            return
        }
        guard mine == generation, wanted else { return }
        do {
            let socket = try await dialer.dial()
            guard mine == generation, wanted else { socket.close(); return }
            self.socket = socket
            state = .live
            retries = 0
            lastHeard = now()
            talk.reset()
            socket.send(text: Wire.hello(device: device))
            read(socket, generation: mine)
            keepAlive = Task { [weak self, aliveEvery] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: aliveEvery)
                    guard let self, self.generation == mine, self.state == .live, !Task.isCancelled else { return }
                    socket.send(text: Wire.alive(answered: self.answered))
                }
            }
        } catch {
            guard mine == generation else { return }
            dropped(error as? CallClose ?? CallClose(code: 0))
        }
    }

    public func hangUp() {
        guard wanted || state != .off else { return }
        wanted = false
        generation += 1
        let hungUp = hungUp
        Task { await hungUp() }
        stop(state: .off)
    }

    public func toggleMute() { muted.toggle() }

    // MARK: push to talk

    /// The daemon's "microphone" setting. In push to talk the gate decides what is sent, never the mute.
    public func setMicrophone(_ mode: String) {
        guard mode != talk.mode else { return }
        let was = talk.isOpen
        talk.mode = mode
        talk.reset()
        if was { sendTalk(false) }
        if talk.ptt { muted = false }
    }

    public func talkPress(_ input: TalkGate.Input) { changeTalk { $0.press(input, at: now()) } }
    public func talkRelease(_ input: TalkGate.Input) { changeTalk { $0.release(input, at: now()) } }
    public func talkToggle() { changeTalk { $0.toggle(at: now()) } }

    /// A control that is a key or a button: Hold opens on down and closes on up; Tap toggles on down.
    public func talkDown(_ input: TalkGate.Input) { talkStyle == .tap ? talkToggle() : talkPress(input) }
    public func talkUp(_ input: TalkGate.Input) { if talkStyle == .hold { talkRelease(input) } }

    /// The daemon's status: a press it closed by itself closes here too. Returns true when it did, for a sound.
    @discardableResult
    public func follow(_ status: API.PTTStatus?) -> Bool {
        if let mode = status?.mode { setMicrophone(mode) }
        guard let why = talk.follow(status) else { return false }
        talkClosedWhy = why
        return true
    }

    private func changeTalk(_ change: (inout TalkGate) -> Void) {
        let was = talk.isOpen
        change(&talk)
        guard talk.isOpen != was else { return }
        if talk.isOpen {
            talkClosedWhy = nil
            talkNote = nil
            talkOpenedAt = now()
            talkTrace = "open"
        } else {
            let held = talkOpenedAt.map { now().timeIntervalSince($0) } ?? 0
            talkTrace = "held \(Int(held * 1000)) ms"
            let short = talkStyle == .hold && held < TalkStyle.shortPress
            note(short ? TalkStyle.shortPressLine : TalkStyle.sentLine, for: short ? TalkStyle.shortPressFor : TalkStyle.sentFor)
        }
        sendTalk(talk.isOpen)
    }

    private func note(_ line: String, for secs: TimeInterval) {
        talkNotes += 1
        let n = talkNotes
        talkNote = line
        let sleep = sleep
        Task { @MainActor [weak self] in
            await sleep(secs)
            if let self, self.talkNotes == n { self.talkNote = nil }
        }
    }

    private func sendTalk(_ open: Bool) {
        socket?.send(text: TalkGate.message(open: open, at: now()))
    }

    // MARK: audio

    private func captured(_ samples: [Float]) {
        guard state == .live, !muted, talk.sends(at: now()), let socket else {
            if !talk.sends(at: now()) { pending.removeAll() }
            return
        }
        pending += samples
        while pending.count >= Wire.chunk {
            socket.send(audio: Wire.pcm16(Array(pending.prefix(Wire.chunk))))
            pending.removeFirst(Wire.chunk)
        }
    }

    // MARK: link

    private func read(_ socket: any CallSocket, generation mine: Int) {
        reader = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    let frame = try await socket.receive()
                    guard let self, self.generation == mine else { return }
                    self.lastHeard = self.now()
                    switch frame {
                    case .audio(let data): self.audio.play(Wire.floats(data))
                    case .text(let text): self.control(text, on: socket)
                    }
                } catch {
                    guard let self, self.generation == mine, !Task.isCancelled else { return }
                    self.dropped(error as? CallClose ?? CallClose(code: 0))
                    return
                }
            }
        }
    }

    /// Text from the daemon: an interrupt, a heartbeat ping to answer, or a press made by a shortcut on the Mac.
    private func control(_ text: String, on socket: any CallSocket) {
        switch Wire.Control(text) {
        case .interrupt: audio.flush()
        case .ptt(let open): changeTalk { $0.set(open: open, at: now()) }
        case .ping(let id, let rtt):
            rttMs = rtt
            socket.send(text: Wire.pong(id))
            answered = max(answered, id)
        case nil: break
        }
    }

    /// Call every second while a call is wanted: a live call that went quiet is dead, and is redialled.
    public func checkHealth() {
        guard wanted, state == .live, now().timeIntervalSince(lastHeard) > Self.deadAfter else { return }
        dropped(CallClose(code: 1006))
    }

    private func dropped(_ close: CallClose) {
        if let why = Self.refusal(close, firstDial: state == .connecting, retries: retries, place: place, words: words) {
            problem = why
            wanted = false
        }
        generation += 1
        stop(state: wanted ? .reconnecting : .off)
        guard wanted else { return }  // keep trying until the user hangs up: the daemon may be restarting
        retries += 1
        let delay = TimeInterval(min(16, 1 << min(retries, 4)))
        let mine = generation
        let (sleep, idleHangup) = (sleep, idleHangup)
        Task { @MainActor [weak self] in
            await sleep(delay)
            guard let self, self.wanted, self.generation == mine else { return }
            // The daemon's idle timer closes the link like any hang-up: ask before calling back, as the page does.
            if await idleHangup() == true {
                guard self.generation == mine else { return }
                self.wanted = false
                self.problem = self.words.idleHangup
                self.stop(state: .off)
                return
            }
            guard self.wanted, self.generation == mine else { return }
            await self.start()
        }
    }

    /// Why a dropped link is not called back, in the surface's words; nil for a live call that dropped, which is
    /// redialled by itself. The daemon turning this client away (401 or 403 at the upgrade, or a 4401 or 1008 close), a
    /// call already up (4409 on the first try: while redialling it is our own dead call, closed by the daemon within
    /// 12 s), or a first dial that never opened: that one stays off and says why.
    public nonisolated static func refusal(_ close: CallClose, firstDial: Bool, retries: Int, place: String, words: Words) -> String? {
        if close.code == 4401 || close.code == 1008 || close.http == 401 || close.http == 403 { return words.notPaired }
        if close.code == 4409 && retries == 0 { return words.busy }
        guard firstDial else { return nil }
        if close.http == nil && close.code <= 0 { return words.unreachable(place) }  // never answered
        return words.failed(close.reason.isEmpty ? (close.http.map { "HTTP \($0)" } ?? "code \(close.code)") : close.reason)
    }

    private func stop(state: State) {
        reader?.cancel()
        reader = nil
        keepAlive?.cancel()
        keepAlive = nil
        answered = 0
        socket?.close()
        socket = nil
        audio.flush()
        pending.removeAll()
        talk.reset()
        if state == .off { audio.stop() }
        self.state = state
    }
}
