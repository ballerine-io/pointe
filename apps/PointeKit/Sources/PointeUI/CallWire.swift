@preconcurrency import AVFAudio
import Foundation
import PointeKit
import SwiftUI

/// The call's link as decisions, with no I/O: when it opens, drops, goes quiet or the phone changes network, what
/// happens next. Call does the I/O; tests drive this. A link that drops is dialled again almost at once, with the
/// call's token (phone.py, protocol 5), and the Mac puts this phone back on the same call: the conversation, the
/// press and the voice go on, and nothing is said again.
struct LinkMachine: Equatable {
    enum Action: Equatable {
        case none
        /// Dial again after this many seconds.
        case dial(after: TimeInterval)
        /// The call is over: `problem` says why.
        case stop
    }

    private(set) var state: Call.State = .off
    /// The call the Mac holds for this phone: a new link brings it back. Nil before the Mac first answered.
    private(set) var token: String?
    private(set) var problem: String?
    private(set) var redial = Redial()
    /// This dial is the user's own Connect, not a redial: a refusal on it is said, not retried.
    private(set) var dialledByUser = false

    /// Connect was tapped.
    mutating func start() {
        if state == .off {
            state = .connecting
            dialledByUser = true
            token = nil
        }
        problem = nil
    }

    /// The socket opened.
    mutating func opened() { state = .live }

    /// The Mac answered the hello with its call (protocol 5): from here a drop is a redial, not a first dial.
    mutating func answered(token: String) {
        self.token = token
        dialledByUser = false
        redial.reset()
    }

    /// The link ended without a hang-up here. A refusal ends the call with its reason; anything else is dialled again.
    mutating func dropped(code: Int, http: Int?, reason: String, place: String, random: Double) -> Action {
        let first = dialledByUser && token == nil
        if let why = Call.refusal(code: code, http: http, reason: reason, firstDial: first, place: place) {
            return end(why)
        }
        state = .reconnecting
        dialledByUser = false
        return .dial(after: redial.next(random: random))
    }

    /// Nothing from the Mac for Call.deadAfter: this link is given up and a new one dialled.
    mutating func quiet(random: Double) -> Action {
        guard state == .live else { return .none }
        state = .reconnecting
        return .dial(after: redial.next(random: random))
    }

    /// The phone moved to another network: the link on the old one is dead whatever it shows, so dial now.
    mutating func networkChanged() -> Action {
        guard state == .live || state == .reconnecting else { return .none }
        state = .reconnecting
        redial.reset()
        return .dial(after: 0)
    }

    mutating func hungUp() {
        state = .off
        token = nil
        redial.reset()
    }

    mutating func end(_ why: String?) -> Action {
        state = .off
        token = nil
        problem = why
        redial.reset()
        return .stop
    }
}

/// One socket of a call, off the main thread: the bot's voice goes straight to the speaker (Playout), pings are
/// answered where they arrive, and the microphone's chunks are coded and sent. Only what the screen needs (the Mac's
/// call message, a press from the Mac, the round trip, the end) goes to the main actor. A busy screen never delays the
/// voice, and the voice never redraws the screen.
final class CallWire: @unchecked Sendable {
    enum Event: Sendable {
        case control(Wire.Control)
        /// Text the wire format does not know (mute's message): the screen's own to read.
        case text(String)
        case rtt(Int?)
        case ended(code: Int, http: Int?, reason: String)
    }

    let socket: URLSessionWebSocketTask
    private let playout: Playout
    private let events: @Sendable (CallWire, Event) -> Void
    private let lock = NSLock()
    private var heardAt = ProcessInfo.processInfo.systemUptime
    private var answered = 0
    private var coder: ADPCM?  // the microphone's coder once the Mac asked for ADPCM; PCM before
    private var uplink = Uplink()
    private var rtt: TimeInterval = 0
    private var lastRtt: Int?
    private var closed = false

    init(socket: URLSessionWebSocketTask, playout: Playout, events: @escaping @Sendable (CallWire, Event) -> Void) {
        self.socket = socket
        self.playout = playout
        self.events = events
    }

    func start(hello: String) {
        socket.resume()
        send(text: hello)
        receive()
    }

    /// Seconds since anything arrived on this socket.
    var quiet: TimeInterval { lock.withLock { ProcessInfo.processInfo.systemUptime - heardAt } }

    /// Microphone audio the path could not carry in time, dropped rather than sent late (Uplink).
    var droppedUp: TimeInterval { lock.withLock { uplink.dropped } }

    func send(text: String) {
        socket.send(.string(text)) { _ in }
    }

    /// The microphone's chunks, in order. Under the lock so a codec change falls between two chunks, never inside one.
    func send(audio chunks: [[Float]]) {
        lock.withLock {
            guard !closed else { return }
            for chunk in chunks where !chunk.isEmpty {
                guard uplink.admit(Double(chunk.count) / Wire.upRate, rtt: rtt) else { continue }
                let data: Data
                if var c = coder {
                    data = Wire.adpcm(chunk, &c)
                    coder = c
                } else {
                    data = Wire.pcm16(chunk)
                }
                socket.send(.data(data)) { _ in }
            }
        }
    }

    /// The phone's own keep-alive (protocol 4), with what it holds to play (protocol 5).
    func sendAlive() {
        let id = lock.withLock { answered }
        send(text: Wire.alive(answered: id, aheadMs: playout.aheadMs))
    }

    /// No more events from this socket: it is closed, with 1000 for a hang-up and 1001 for a link given up.
    func close(_ code: URLSessionWebSocketTask.CloseCode) {
        lock.withLock { closed = true }
        socket.cancel(with: code, reason: nil)
    }

    private var isClosed: Bool { lock.withLock { closed } }

    private func receive() {
        socket.receive { [weak self] result in
            guard let self, !self.isClosed else { return }
            switch result {
            case .success(let message):
                self.lock.withLock { self.heardAt = ProcessInfo.processInfo.systemUptime }
                switch message {
                case .data(let data): self.playout.receive(data)
                case .string(let text): self.control(text)
                @unknown default: break
                }
                self.receive()
            case .failure(let error):
                print("pointe: call link ended: \(error) close=\(self.socket.closeCode.rawValue)")
                let http = (self.socket.response as? HTTPURLResponse)?.statusCode
                let reason = self.socket.closeReason.flatMap { String(data: $0, encoding: .utf8) } ?? ""
                self.events(self, .ended(code: self.socket.closeCode.rawValue, http: http, reason: reason))
            }
        }
    }

    private func control(_ text: String) {
        guard let message = Wire.Control(text) else {
            events(self, .text(text))
            return
        }
        switch message {
        case .ping(let id, let rttMs, let heardMs):
            let changed: Bool = lock.withLock {
                answered = max(answered, id)
                rtt = Double(rttMs ?? 0) / 1000
                if let heardMs { uplink.heard(Double(heardMs) / 1000) }
                defer { lastRtt = rttMs }
                return lastRtt != rttMs
            }
            send(text: Wire.pong(id, aheadMs: playout.aheadMs))
            if changed { events(self, .rtt(rttMs)) }
        case .interrupt:
            playout.flush()
        case .call(_, _, let adpcm, _):
            playout.setADPCM(adpcm)
            if adpcm {
                lock.withLock {
                    socket.send(.string(Wire.adpcmUp)) { _ in }  // before the first ADPCM chunk, on the same queue
                    coder = ADPCM()
                }
            }
            events(self, .control(message))
        case .ptt:
            events(self, .control(message))
        }
    }
}

/// The bot's voice on the speaker, off the main thread: decoded, held by the jitter buffer while the speaker is dry,
/// then scheduled on the player. Tells the main actor only when speaking starts or stops.
final class Playout: @unchecked Sendable {
    private let player: AVAudioPlayerNode
    private let format: AVAudioFormat
    private let speaking: @Sendable (Bool) -> Void
    private let queue = DispatchQueue(label: "io.ballerine.pointe.playout", qos: .userInteractive)
    private let lock = NSLock()
    // on `queue`
    private var buffer = JitterBuffer()
    private var held: [AVAudioPCMBuffer] = []
    private var scheduled = 0
    private var generation = 0
    private var isSpeaking = false
    private var timer: DispatchWorkItem?
    // under `lock`: read from other threads
    private var adpcm = false
    private var ahead: TimeInterval = 0
    private var stats = (underruns: 0, gapSecs: 0.0)

    init(player: AVAudioPlayerNode, format: AVAudioFormat, speaking: @escaping @Sendable (Bool) -> Void) {
        self.player = player
        self.format = format
        self.speaking = speaking
    }

    var aheadMs: Int { lock.withLock { Int((ahead * 1000).rounded()) } }
    var underruns: Int { lock.withLock { stats.underruns } }
    var gapMs: Int { lock.withLock { Int(stats.gapSecs * 1000) } }

    func setADPCM(_ on: Bool) { lock.withLock { adpcm = on } }

    func receive(_ data: Data) {
        let samples = lock.withLock { adpcm } ? Wire.floats(adpcm: data) : Wire.floats(data)
        guard !samples.isEmpty,
              let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(samples.count)) else { return }
        pcm.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { pcm.floatChannelData![0].update(from: $0.baseAddress!, count: samples.count) }
        let secs = Double(samples.count) / format.sampleRate
        nonisolated(unsafe) let made = pcm  // made here, used only on `queue` from now on
        queue.async { [self] in
            held.append(made)
            if buffer.arrived(secs, at: Self.now) { release() } else { arm() }
            publish()
        }
    }

    /// The user cut the bot off: drop what is queued at once, or it keeps talking over them.
    func flush() {
        queue.sync {
            generation += 1
            held = []
            scheduled = 0
            buffer.flush()
            timer?.cancel()
            timer = nil
            publish()
        }
        player.stop()  // outside the queue: stopping calls the completions of what was scheduled
        if player.engine?.isRunning == true { player.play() }  // play() on a stopped engine raises
        setSpeaking(false)
    }

    private func release() {
        timer?.cancel()
        timer = nil
        let gen = generation
        for pcm in held {
            scheduled += 1
            player.scheduleBuffer(pcm) { [self] in queue.async { self.played(gen) } }
        }
        held = []
        if scheduled > 0 { setSpeaking(true) }
    }

    private func arm() {
        guard timer == nil, let due = buffer.due() else { return }
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.timer = nil
            if self.buffer.tick(at: Self.now) { self.release() } else { self.arm() }
            self.publish()
        }
        timer = work
        queue.asyncAfter(deadline: .now() + max(0, due - Self.now), execute: work)
    }

    private func played(_ gen: Int) {
        guard gen == generation else { return }
        scheduled = max(0, scheduled - 1)
        if scheduled == 0 && held.isEmpty { setSpeaking(false) }
        publish()
    }

    private func publish() {
        let a = buffer.ahead(at: Self.now), u = buffer.underruns, g = buffer.gapSecs
        lock.withLock {
            ahead = a
            stats = (u, g)
        }
    }

    private func setSpeaking(_ on: Bool) {
        let changed: Bool = lock.withLock {
            defer { isSpeaking = on }
            return isSpeaking != on
        }
        if changed { speaking(on) }
    }

    private static var now: TimeInterval { ProcessInfo.processInfo.systemUptime }
}

#if DEBUG
/// Debug builds: the link's trace (Call.netTrace) where a UI test can read it. A view of its own, so its changes
/// redraw only it.
struct NetTraceProbe: View {
    let call: Call

    var body: some View {
        Color.clear.frame(width: 1, height: 1)
            .accessibilityElement()
            .accessibilityIdentifier("netTrace")
            .accessibilityValue(call.netTrace)
    }
}

/// Debug builds: typed lines timed from the moment they were sent (CallView.say) to the moment their bubble first
/// showed (Bubble), for apps/ios/e2e/bad_network.py.
enum NetProbe {
    nonisolated(unsafe) private static var sentAt: [String: TimeInterval] = [:]
    nonisolated(unsafe) private static var shownMs: [String: Int] = [:]
    private static let lock = NSLock()

    nonisolated(unsafe) private static var sentWall: [Double] = []

    static func sent(_ text: String) {
        lock.withLock {
            sentAt[text] = ProcessInfo.processInfo.systemUptime
            sentWall.append(Date().timeIntervalSince1970)
        }
    }

    /// When each line was sent, by the wall clock the daemon's log uses: "1795…/1795…".
    static var sentLine: String { lock.withLock { sentWall.map { String(format: "%.3f", $0) }.joined(separator: "/") } }

    static func shown(_ text: String) {
        lock.withLock {
            guard let at = sentAt[text], shownMs[text] == nil else { return }
            shownMs[text] = Int((ProcessInfo.processInfo.systemUptime - at) * 1000)
        }
    }

    /// "a/b/c": each line's milliseconds to its bubble, in the order sent; "-" for one not shown yet.
    static var shownLine: String {
        lock.withLock { sentAt.sorted { $0.value < $1.value }.map { shownMs[$0.key].map(String.init) ?? "-" }.joined(separator: "/") }
    }
}


/// Debug builds: how long the main thread was late to a tick every 50 ms, for the UI tests' bad-network run. A stall
/// is a tick more than 100 ms late: a tap or a frame waiting that long is felt.
final class MainStall: @unchecked Sendable {
    static let shared = MainStall()
    private let lock = NSLock()
    private var stalls = 0
    private var worst = 0.0

    private init() {
        let thread = Thread { [weak self] in
            while true {
                let asked = ProcessInfo.processInfo.systemUptime
                let answered = DispatchSemaphore(value: 0)
                DispatchQueue.main.async { answered.signal() }
                answered.wait()
                let late = ProcessInfo.processInfo.systemUptime - asked
                self?.lock.withLock {
                    if late > 0.1 { self?.stalls += 1 }
                    self?.worst = max(self?.worst ?? 0, late)
                }
                Thread.sleep(forTimeInterval: 0.05)
            }
        }
        thread.qualityOfService = .utility
        thread.start()
    }

    var count: Int { lock.withLock { stalls } }
    var maxMs: Int { lock.withLock { Int(worst * 1000) } }
}
#endif

extension View {
    /// Debug builds: the bubble of a typed line tells NetProbe when it first showed. Release builds: nothing. A modifier
    /// in both, so the view's chain carries no `#if` (a postfix `#if` is slow for the type checker).
    @ViewBuilder func netProbe(_ text: String) -> some View {
        #if DEBUG
        onAppear { NetProbe.shown(text) }
        #else
        self
        #endif
    }
}
