import Foundation
import Testing
@testable import PointeKit

final class FakeSocket: CallSocket, @unchecked Sendable {
    private let lock = NSLock()
    private var texts: [String] = [], audio: [Data] = [], closedFlag = false
    private let frames: AsyncThrowingStream<CallFrame, Error>
    private let feed: AsyncThrowingStream<CallFrame, Error>.Continuation

    init() { (frames, feed) = AsyncThrowingStream.makeStream() }

    var sentTexts: [String] { lock.withLock { texts } }
    var sentAudio: [Data] { lock.withLock { audio } }
    var closed: Bool { lock.withLock { closedFlag } }
    func send(text: String) { lock.withLock { texts.append(text) } }
    func send(audio data: Data) { lock.withLock { audio.append(data) } }
    func close() { lock.withLock { closedFlag = true }; feed.finish(throwing: CallClose(code: 1000)) }
    func push(_ frame: CallFrame) { feed.yield(frame) }
    func drop(_ close: CallClose) { feed.finish(throwing: close) }

    func receive() async throws -> CallFrame {
        for try await frame in frames { return frame }
        throw CallClose(code: 1000)
    }
}

final class FakeDialer: CallDialer, @unchecked Sendable {
    private let lock = NSLock()
    private var queue: [Result<FakeSocket, CallClose>] = []
    private var count = 0
    var dials: Int { lock.withLock { count } }
    func next(_ result: Result<FakeSocket, CallClose>) { lock.withLock { queue.append(result) } }

    func dial() async throws -> any CallSocket {
        let result: Result<FakeSocket, CallClose> = lock.withLock {
            count += 1
            return queue.isEmpty ? .failure(CallClose(code: 0)) : queue.removeFirst()
        }
        return try result.get()
    }
}

@MainActor final class FakeAudio: CallAudio {
    var onSpeaking: ((Bool) -> Void)?
    var deliver: (@Sendable ([Float]) -> Void)?
    var played = 0, flushes = 0, starts = 0, stops = 0
    var failure: CallAudioError?

    func start(deliver: @escaping @Sendable ([Float]) -> Void) async throws {
        if let failure { throw failure }
        starts += 1
        self.deliver = deliver
    }
    func stop() { stops += 1 }
    func play(_ samples: [Float]) { played += samples.count }
    func flush() { flushes += 1 }
}

let words = CallLink.Words(notPaired: "not paired", busy: "busy", idleHangup: "idle", micDenied: "mic denied", noMic: "no mic",
                           micFailed: { "mic failed: \($0)" }, unreachable: { "unreachable \($0)" }, failed: { "failed: \($0)" })

/// Lets the link's tasks run: its work hops through the main actor.
@MainActor func settle(_ until: @MainActor () -> Bool = { false }) async {
    for _ in 0..<200 {
        if until() { return }
        try? await Task.sleep(for: .milliseconds(5))
    }
}

@MainActor @Suite struct CallLinkTests {
    let dialer = FakeDialer(), audio = FakeAudio()

    func link(idle: Bool? = nil, hungUp: @escaping @Sendable () async -> Void = {}) -> CallLink {
        CallLink(dialer: dialer, audio: audio, device: "Mac", place: "127.0.0.1:7999", words: words,
                 idleHangup: { idle }, hungUp: hungUp, sleep: { _ in })
    }

    @Test func aDialThatOpensSaysHelloAndGoesLive() async {
        let socket = FakeSocket()
        dialer.next(.success(socket))
        let call = link()
        await call.start()
        #expect(call.state == .live && audio.starts == 1)
        #expect(socket.sentTexts.first?.contains(#""type":"hello""#) == true)
    }

    @Test func pingsAreAnsweredAndTheRoundTripKept() async {
        let socket = FakeSocket()
        dialer.next(.success(socket))
        let call = link()
        await call.start()
        socket.push(.text(#"{"type":"ping","id":4,"rtt_ms":18}"#))
        await settle { call.rttMs == 18 }
        #expect(call.rttMs == 18)
        #expect(socket.sentTexts.contains(Wire.pong(4)))
    }

    @Test func theBotsVoiceIsPlayedAndAnInterruptDropsIt() async {
        let socket = FakeSocket()
        dialer.next(.success(socket))
        let call = link()
        await call.start()
        socket.push(.audio(Wire.pcm16([0.1, 0.2, 0.3])))
        await settle { audio.played == 3 }
        #expect(audio.played == 3)
        let before = audio.flushes
        socket.push(.text(#"{"type":"interrupt"}"#))
        await settle { audio.flushes > before }
        #expect(audio.flushes == before + 1)
    }

    @Test func theMicrophoneIsSentInTwentyMillisecondChunksUnlessMuted() async {
        let socket = FakeSocket()
        dialer.next(.success(socket))
        let call = link()
        await call.start()
        audio.deliver?([Float](repeating: 0.1, count: 800))
        await settle { socket.sentAudio.count == 2 }
        #expect(socket.sentAudio.count == 2 && socket.sentAudio[0].count == 640)
        call.toggleMute()
        audio.deliver?([Float](repeating: 0.1, count: 800))
        await settle()
        #expect(socket.sentAudio.count == 2)
    }

    @Test func inPushToTalkNothingIsSentUntilAPressAndThePressIsToldToTheDaemon() async {
        let socket = FakeSocket()
        dialer.next(.success(socket))
        let call = link()
        await call.start()
        call.follow(API.PTTStatus(mode: "ptt", open: false))
        audio.deliver?([Float](repeating: 0.1, count: 640))
        await settle()
        #expect(socket.sentAudio.isEmpty)
        call.talkDown(.shortcut)
        #expect(call.talk.isOpen && socket.sentTexts.contains { $0.contains(#""open":true"#) })
        audio.deliver?([Float](repeating: 0.1, count: 640))
        await settle { socket.sentAudio.count == 2 }
        #expect(socket.sentAudio.count == 2)
        call.talkUp(.shortcut)
        #expect(!call.talk.isOpen && socket.sentTexts.contains { $0.contains(#""open":false"#) })
        #expect(call.talkTrace.hasPrefix("held "))
    }

    @Test func tapStyleTogglesOnThePressAndIgnoresTheRelease() async {
        let socket = FakeSocket()
        dialer.next(.success(socket))
        let call = link()
        call.talkStyle = .tap
        await call.start()
        call.follow(API.PTTStatus(mode: "ptt", open: false))
        call.talkDown(.shortcut); call.talkUp(.shortcut)
        #expect(call.talk.isOpen)
        call.talkDown(.shortcut); call.talkUp(.shortcut)
        #expect(!call.talk.isOpen)
    }

    @Test func aShortcutPressedOnTheDaemonOpensThisSide() async {
        let socket = FakeSocket()
        dialer.next(.success(socket))
        let call = link()
        await call.start()
        call.follow(API.PTTStatus(mode: "ptt", open: false))
        socket.push(.text(#"{"type":"ptt","open":true,"by":"shortcut"}"#))
        await settle { call.talk.isOpen }
        #expect(call.talk.isOpen)
    }

    @Test func aLiveCallThatDropsIsRedialled() async {
        let first = FakeSocket(), second = FakeSocket()
        dialer.next(.success(first)); dialer.next(.success(second))
        let call = link()
        await call.start()
        first.drop(CallClose(code: 1006))
        await settle { dialer.dials == 2 && call.state == .live }
        #expect(dialer.dials == 2 && call.state == .live && call.problem == nil)
    }

    @Test func aCallTheIdleTimerEndedIsNotRedialled() async {
        let first = FakeSocket()
        dialer.next(.success(first))
        let call = link(idle: true)
        await call.start()
        first.drop(CallClose(code: 1000))
        await settle { call.state == .off }
        #expect(call.state == .off && call.problem == "idle" && dialer.dials == 1)
    }

    @Test func aQuietLinkIsTreatedAsDead() async {
        let first = FakeSocket()
        dialer.next(.success(first))
        let clock = Clock()
        let call = CallLink(dialer: dialer, audio: audio, device: "Mac", place: "p", words: words, sleep: { _ in }, now: { clock.now })
        await call.start()
        clock.advance(CallLink.deadAfter + 1)
        call.checkHealth()
        #expect(call.state == .reconnecting && first.closed)
    }

    @Test func refusalsStayOffAndSayWhy() async {
        dialer.next(.failure(CallClose(code: 0, http: 403)))
        let refused = link()
        await refused.start()
        #expect(refused.state == .off && refused.problem == "not paired" && audio.stops == 1)

        #expect(CallLink.refusal(CallClose(code: 4409), firstDial: true, retries: 0, place: "p", words: words) == "busy")
        #expect(CallLink.refusal(CallClose(code: 4409), firstDial: false, retries: 2, place: "p", words: words) == nil)
        #expect(CallLink.refusal(CallClose(code: 0), firstDial: true, retries: 0, place: "p", words: words) == "unreachable p")
        #expect(CallLink.refusal(CallClose(code: 1011, reason: "boom"), firstDial: true, retries: 0, place: "p", words: words) == "failed: boom")
        #expect(CallLink.refusal(CallClose(code: 1006), firstDial: false, retries: 0, place: "p", words: words) == nil)
    }

    @Test func aMicrophoneThatIsDeniedNeverDials() async {
        audio.failure = .denied
        let call = link()
        await call.start()
        #expect(call.state == .off && call.problem == "mic denied" && dialer.dials == 0)
    }

    @Test func hangingUpTellsTheDaemonAndStopsTheAudio() async {
        let socket = FakeSocket()
        dialer.next(.success(socket))
        let told = Flag()
        let call = link(hungUp: { told.set() })
        await call.start()
        call.hangUp()
        await settle { told.isSet }
        #expect(call.state == .off && socket.closed && audio.stops == 1 && told.isSet)
        #expect(dialer.dials == 1)
    }
}

final class Clock: @unchecked Sendable {
    private let lock = NSLock()
    private var value = Date(timeIntervalSince1970: 5000)
    var now: Date { lock.withLock { value } }
    func advance(_ by: TimeInterval) { lock.withLock { value += by } }
}

final class Flag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false
    var isSet: Bool { lock.withLock { value } }
    func set() { lock.withLock { value = true } }
}
