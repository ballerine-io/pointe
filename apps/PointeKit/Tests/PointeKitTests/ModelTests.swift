import Foundation
import Testing
@testable import PointeKit

@Suite struct ModelTests {
    @Test func anUnknownHarnessStillGetsAMark() {
        #expect(Harness.name(nil) == "Claude")
        #expect(Harness.name("") == "Claude")
        #expect(Harness.name("aider") == "aider")
    }
}

@Suite struct WireTests {
    @Test func pcmSurvivesTheRoundTrip() {
        let samples: [Float] = [0, 0.5, -0.5, 1, -1, 2]
        let back = Wire.floats(Wire.pcm16(samples))
        #expect(back.count == 6)
        #expect(abs(back[1] - 0.5) < 0.001 && abs(back[5] - 1) < 0.001)  // clipped, never wrapped
        #expect(Wire.floats(Data([1])).isEmpty)  // an odd byte is no sample, and no crash
    }

    @Test func resamplingKeepsTheDuration() {
        let second = [Float](repeating: 0.25, count: 48000)
        #expect(Wire.resample(second, from: 48000, to: 16000).count == 16000)
        #expect(Wire.resample([], from: 48000, to: 16000).isEmpty)
        #expect(Wire.resample(second, from: 0, to: 16000).count == 48000)
    }

    @Test func controlMessagesParseAndUnknownTextIsIgnored() {
        #expect(Wire.Control(#"{"type":"interrupt"}"#) == .interrupt)
        #expect(Wire.Control(#"{"type":"ping","id":7,"rtt_ms":12}"#) == .ping(id: 7, rttMs: 12))  // before protocol 5
        #expect(Wire.Control(#"{"type":"ping","id":7,"rtt_ms":null}"#) == .ping(id: 7, rttMs: nil))
        #expect(Wire.Control(#"{"type":"ptt","open":true,"by":"shortcut"}"#) == .ptt(open: true))
        #expect(Wire.Control(#"{"type":"ptt"}"#) == nil)
        #expect(Wire.Control(#"{"type":"duck","gain":0.3}"#) == .duck(gain: 0.3))
        #expect(Wire.Control(#"{"type":"duck","gain":1}"#) == .duck(gain: 1))
        #expect(Wire.Control(#"{"type":"duck","gain":7}"#) == .duck(gain: 1))  // never louder than the voice itself
        #expect(Wire.Control(#"{"type":"duck"}"#) == nil)
        #expect(Wire.Control("not json") == nil && Wire.Control(#"{"type":"new"}"#) == nil)
    }

    @Test func helloSaysTheProtocolWhatTheClientCanDoAndTheCallItComesBackTo() throws {
        let hello = try #require(try JSONSerialization.jsonObject(with: Data(Wire.hello(device: "Mac").utf8)) as? [String: Any])
        #expect(hello["protocol"] as? Int == 5 && hello["device"] as? String == "Mac")
        #expect(hello["capabilities"] as? [String] == ["ptt", "resume", "adpcm", "duck"])
        #expect(hello["resume"] == nil)  // a first dial names no call
        let back = try #require(try JSONSerialization.jsonObject(with: Data(Wire.hello(device: "iPhone", resume: "tok").utf8)) as? [String: Any])
        #expect(back["resume"] as? String == "tok")
        #expect(Wire.alive(answered: 7) == #"{"alive":true,"id":7,"type":"pong"}"#)
        #expect(Wire.alive(answered: 7, aheadMs: 240) == #"{"ahead_ms":240,"alive":true,"id":7,"type":"pong"}"#)
        #expect(Wire.pong(3, aheadMs: 0) == #"{"ahead_ms":0,"id":3,"type":"pong"}"#)
        #expect(Wire.adpcmUp == #"{"type":"codec","up":"adpcm"}"#)
    }

    /// The text tests/test_calllink.py has the daemon send, read back here: the two ends must not drift.
    @Test func theMacsCallMessageAndPingCarryProtocolFive() {
        #expect(Wire.Control(#"{"type":"call","resume":"abc","resumed":true,"codec":"adpcm","grace":30.0}"#)
                == .call(resume: "abc", resumed: true, adpcm: true, grace: 30))
        #expect(Wire.Control(#"{"type":"call","resume":"abc","resumed":false,"codec":"pcm16","grace":0}"#)
                == .call(resume: "abc", resumed: false, adpcm: false, grace: 0))
        #expect(Wire.Control(#"{"type":"call"}"#) == nil)
        #expect(Wire.Control(#"{"type":"ping","id":4,"rtt_ms":80,"heard_ms":1960}"#) == .ping(id: 4, rttMs: 80, heardMs: 1960))
    }
}

/// IMA ADPCM, against Python's audioop on the same samples (the daemon's coder, phone.adpcm_encode).
@Suite struct ADPCMTests {
    static let samples: [Int16] = [-900, 1276, 3369, 5302, 7001, 8406, 9468, 8054, 8346, 8245, 7768, 6951, 5840, 4500, 902,
                                   -675, -2250, -3738, -5063, -6152, -6944, -9491, -9561, -9237, -8521, -7430, -5999, -4279,
                                   -4431, -2327, -148, 2023, 4107, 6023, 7701, 6981, 8013, 8668, 8928, 8796]

    @Test func encodesAsAudioopDoesCarryingTheStateInEachHeader() {
        var coder = ADPCM()
        let first = coder.encode(Array(Self.samples[..<20]))
        #expect(first == Data([0, 0, 0, 0]) + Data(hex: "f777777738899af99a99"))
        #expect(coder.predictor == -6125 && coder.index == 61)
        let second = coder.encode(Array(Self.samples[20...]))
        #expect(second.prefix(4) == Data([0x13, 0xe8, 61, 0]))  // -6125 little-endian, then the step index
        #expect(second.dropFirst(4) == Data(hex: "9c000224844233392108"))
        #expect(coder.predictor == 8774 && coder.index == 53)
    }

    @Test func aMessageDecodesOnItsOwnAsAudioopDoes() {
        var coder = ADPCM()
        _ = coder.encode(Array(Self.samples[..<20]))
        let second = coder.encode(Array(Self.samples[20...]))
        #expect(ADPCM.decode(second) == [-7061, -9617, -9274, -8962, -8678, -7387, -6214, -4294, -4552, -2440, 116, 1833,
                                         4018, 6006, 7813, 7110, 8176, 8758, 8934, 8774])
        #expect(ADPCM.decode(Data([1, 2, 3])) == nil)
        #expect(ADPCM.decode(Data([0, 0, 89, 0, 0x77])) == nil)  // no such step index
    }

    @Test func aQuarterOfPCMAndCloseToIt() {
        let tone = (0..<480).map { Float(sin(Double($0) * 0.13)) * 0.5 }
        var coder = ADPCM()
        _ = Wire.adpcm(tone, &coder)  // the state warms up, as it has mid-call
        let message = Wire.adpcm(tone, &coder)
        #expect(message.count == 4 + 240)
        #expect(Wire.pcm16(tone).count == 960)
        let back = Wire.floats(adpcm: message)
        #expect(back.count == 480)
        let rms = (zip(tone, back).map { ($0 - $1) * ($0 - $1) }.reduce(0, +) / Float(tone.count)).squareRoot()
        #expect(rms < 0.02)  // about 33 dB under a tone at half scale
    }
}

@Suite struct RedialTests {
    @Test func soonThenBackingOffToEightSecondsWithJitter() {
        var r = Redial()
        let low = (0..<7).map { _ in r.next(random: 0) }
        #expect(low == [0.125, 0.25, 0.5, 1, 2, 4, 4])
        r.reset()
        let high = (0..<7).map { _ in r.next(random: 1) }
        #expect(high == [0.25, 0.5, 1, 2, 4, 8, 8])
        #expect(r.attempt == 7)
    }

    /// The Mac holds a dropped call 30 s (calllink.GRACE_SECS): a phone backing off still dials several times in it.
    @Test func severalDialsFallInsideTheMacsGrace() {
        var r = Redial()
        var at: TimeInterval = 0, dials = 0
        while true {
            at += r.next(random: 1)
            if at > 30 { break }
            dials += 1
        }
        #expect(dials >= 7)
    }
}

@Suite struct JitterBufferTests {
    @Test func theFirstAudioWaitsForTheTargetThenPlaysStraightOn() {
        var b = JitterBuffer()
        for k in 0..<7 {  // the Mac's lead comes in a burst: 280 ms, short of the 300 ms target
            let r = b.arrived(0.04, at: Double(k) * 0.01)
            #expect(!r)
        }
        let r8 = b.arrived(0.04, at: 0.07)
        #expect(r8)  // 320 ms in hand
        #expect(abs(b.ahead(at: 0.07) - 0.32) < 1e-9)
        let r9 = b.arrived(0.04, at: 0.08)
        #expect(r9)  // playing: straight on
        #expect(b.underruns == 0)
    }

    @Test func aShortReplyStillPlaysOnceItHasWaitedTheTarget() {
        var b = JitterBuffer()
        let r5 = b.arrived(0.04, at: 10)
        #expect(!r5)
        #expect(b.due() == 10.3)
        let r6 = b.tick(at: 10.2)
        #expect(!r6)
        let r7 = b.tick(at: 10.3)
        #expect(r7)
        #expect(b.due() == nil)
    }

    @Test func runningDryMidReplyIsAnUnderrunAndTheNextWaitIsLonger() {
        var b = JitterBuffer()
        _ = b.arrived(0.4, at: 0)  // plays until 0.4
        let held = b.arrived(0.04, at: 0.7)  // dry since 0.4: 300 ms of silence in the middle of the reply
        #expect(!held)
        #expect(b.underruns == 1)
        #expect(abs(b.gapSecs - 0.3) < 1e-9)
        #expect(b.target > JitterBuffer.startTarget)
        for k in 1...10 {  // one bad path after another: the wait grows to its ceiling and no further
            let t = Double(k) * 100
            _ = b.arrived(1.0, at: t)  // a new reply, enough in hand to start at once
            _ = b.arrived(0.04, at: t + 1.3)  // dry since t + 1
        }
        #expect(b.underruns == 11)
        #expect(b.target == JitterBuffer.maxTarget)
    }

    @Test func aPauseBetweenRepliesIsNoUnderrunAndCalmBringsTheWaitDown() {
        var b = JitterBuffer()
        _ = b.arrived(0.4, at: 0)
        _ = b.arrived(0.4, at: 0.6)  // underrun: the target goes up
        let raised = b.target
        _ = b.tick(at: 2)
        let r9 = b.arrived(0.04, at: 30)
        #expect(!r9)  // a new reply, long after: no underrun, and calm: down a step
        #expect(b.underruns == 1)
        #expect(b.target < raised)
    }

    @Test func aBargeInFlushesAndTheSilenceAfterIsNoUnderrun() {
        var b = JitterBuffer()
        _ = b.arrived(1, at: 0)
        b.flush()
        #expect(b.ahead(at: 0.1) == 0)
        _ = b.arrived(0.04, at: 0.3)
        #expect(b.underruns == 0)
    }

    /// The voice on a relayed VPN path (tests/netshaper.py's "relay": 70 ms, up to 80 ms of jitter, a segment in 200
    /// lost for a 300 ms retransmission), on a fake clock: the Mac's half-second lead (phone.SEND_LEAD_SECS) against
    /// pipecat's own pacing, one chunk ahead. tests/test_playout_gaps.py measures the same with the page.
    @Test func withTheMacsLeadTheVoiceAlmostNeverBreaksOnAJitteryLossyPath() {
        let before = Self.gaps(lead: 0.04), after = Self.gaps(lead: 0.5)
        #expect(after.perMinute <= 0.5, "\(after)")
        #expect(after.msPerMinute <= 60, "\(after)")
        #expect(before.perMinute >= 2 * max(after.perMinute, 0.25), "before \(before), after \(after)")
    }

    /// Gaps heard per minute of speech: silence inside a reply, the speaker given what JitterBuffer releases.
    static func gaps(lead: TimeInterval) -> (perMinute: Double, msPerMinute: Double) {
        var seed: UInt64 = 7
        func random() -> Double {  // a fixed sequence: the same path every run
            seed = seed &* 6364136223846793005 &+ 1442695040888963407
            return Double(seed >> 11) / Double(1 << 53)
        }
        let chunk = 0.04
        var buffer = JitterBuffer(), held = 0, speakerUntil = 0.0, replyEnd: Double?, gaps = 0, gapSecs = 0.0
        var last = 0.0, speech = 0.0, start = 1.0
        func play(_ now: Double) {
            for _ in 0..<held {
                let at = max(now, speakerUntil)
                if let end = replyEnd, at > end + 1e-9 { gaps += 1; gapSecs += at - end }
                speakerUntil = at + chunk
                replyEnd = speakerUntil
            }
            held = 0
        }
        for _ in 0..<40 {
            let secs = (2 + 12 * random()).rounded() , count = Int(secs / chunk)
            replyEnd = nil
            var clock = 0.0, awake = start
            for k in 0..<count {
                let sent = max(start + Double(k + 1) * chunk / 4, awake)  // the voice service makes it 4x as fast
                clock = max(clock, sent - lead) + chunk  // phone.next_send_at
                awake = max(sent, clock)
                var due = sent + 0.07 + 0.08 * random()
                if random() < 0.005 { due += 0.3 }
                last = max(last, due)
                while let tick = buffer.due(), tick <= last, buffer.tick(at: tick) { play(tick) }
                held += 1
                if buffer.arrived(chunk, at: last) { play(last) }
            }
            if let tick = buffer.due(), buffer.tick(at: tick) { play(tick) }
            speech += secs
            start += secs + 4 + 6 * random()
        }
        return (Double(gaps) * 60 / speech, gapSecs * 1000 * 60 / speech)
    }
}

@Suite struct UplinkTests {
    @Test func sendsWhileTheMacKeepsUpAndDropsOnceAudioPilesUpOnTheWay() {
        var u = Uplink()
        for _ in 0..<100 { let ok = u.admit(0.02, rtt: 0.2); #expect(ok) }  // 2 s sent; the Mac has not said anything yet
        u.heard(1.8)  // 0.2 s on the way: fine
        let r10 = u.admit(0.02, rtt: 0.2)
        #expect(r10)
        u.heard(0.2)  // 1.82 s on the way, over 1.5 + 0.2: the path is behind
        let r11 = u.admit(0.02, rtt: 0.2)
        #expect(!r11)
        #expect(u.dropping && u.dropped == 0.02)
        u.heard(1.0)  // 0.82 s: still over the 0.5 + 0.2 it must come down to
        let r12 = u.admit(0.02, rtt: 0.2)
        #expect(!r12)
        u.heard(1.5)
        let r13 = u.admit(0.02, rtt: 0.2)
        #expect(r13)
    }

    @Test func aMacThatSaysNothingIsNeverDroppedFor() {
        var u = Uplink()
        for _ in 0..<1000 { let ok = u.admit(0.02, rtt: 0); #expect(ok) }
        #expect(u.dropped == 0)
    }
}

extension Data {
    init(hex: String) {
        var bytes = [UInt8]()
        var i = hex.startIndex
        while i < hex.endIndex {
            let j = hex.index(i, offsetBy: 2)
            bytes.append(UInt8(hex[i..<j], radix: 16)!)
            i = j
        }
        self.init(bytes)
    }
}

@Suite struct ClientTests {
    let endpoint = DaemonEndpoint(port: 7999, credential: .pageKey("k3y", token: "t0k"))

    /// The proof a request carries is the one `LocalProof` makes for that method, address and body.
    static func proves(_ r: URLRequest, key: String = "k3y", token: String = "t0k") -> Bool {
        guard let value = r.value(forHTTPHeaderField: LocalProof.header), let url = r.url else { return false }
        let parts = value.split(separator: ".").map(String.init)
        guard parts.count == 5, let ts = TimeInterval(parts[1]) else { return false }
        return value == LocalProof.value(pageKey: key, token: token, method: r.httpMethod ?? "GET", url: url, body: r.httpBody,
                                         time: Date(timeIntervalSince1970: ts), nonce: parts[2])
    }

    @Test func aRequestCarriesAProofOnLoopbackAndNoCookieOrOrigin() throws {
        let r = endpoint.request("voice/approve", method: "POST", body: ["session": "docs", "decision": "allow"])
        #expect(r.url?.absoluteString == "http://127.0.0.1:7999/voice/approve")
        #expect(Self.proves(r))
        #expect(!Self.proves(r, token: "the-last-start"))
        #expect(r.value(forHTTPHeaderField: "Cookie") == nil)
        #expect(r.value(forHTTPHeaderField: "Origin") == nil && r.value(forHTTPHeaderField: "Authorization") == nil)
        #expect(!r.httpShouldHandleCookies)
        let data = try #require(r.httpBody)
        let body = try #require(try JSONSerialization.jsonObject(with: data) as? [String: String])
        #expect(body == ["session": "docs", "decision": "allow"])
    }

    @Test func theKeyIsNeverInAURL() {
        for url in [endpoint.base, endpoint.callURL, endpoint.pageURL, endpoint.callRequest.url].compactMap({ $0 }) {
            #expect(!url.absoluteString.contains("k3y"))
        }
        #expect(endpoint.callURL.absoluteString == "ws://127.0.0.1:7999/voice/call")
        #expect(Self.proves(endpoint.callRequest) && endpoint.callRequest.value(forHTTPHeaderField: "Cookie") == nil)
    }

    /// SECURITY.md, "The Mac app": whoever holds the port gets no key, on a request or on the call's socket.
    @Test func thePageKeyIsInNoHeader() {
        for r in [endpoint.request("voice/status"), endpoint.request("voice/approve", method: "POST", body: ["decision": "allow"]),
                  endpoint.callRequest] {
            #expect(!(r.allHTTPHeaderFields ?? [:]).values.contains { $0.contains("k3y") }, "\(r.allHTTPHeaderFields ?? [:])")
        }
    }

    @Test func eachRequestHasItsOwnNonce() {
        let a = endpoint.request("voice/status").value(forHTTPHeaderField: LocalProof.header)?.split(separator: ".")[2]
        let b = endpoint.request("voice/status").value(forHTTPHeaderField: LocalProof.header)?.split(separator: ".")[2]
        #expect(a != nil && a != b)
    }

    /// The same inputs as tests/test_local_proof.py's test_the_swift_builder_and_this_check_agree: one wire format.
    @Test func theProofMatchesTheDaemons() throws {
        let url = try #require(URL(string: "http://127.0.0.1:7999/voice/approve?term=Quillfeather"))
        let value = LocalProof.value(pageKey: "k3y", token: "t0k", method: "POST", url: url, body: Data(#"{"decision":"allow"}"#.utf8),
                                     time: Date(timeIntervalSince1970: 1_800_000_000), nonce: "00112233445566778899aabbccddeeff")
        #expect(value == "v1.1800000000.00112233445566778899aabbccddeeff."
                + "6b838faadcc5ae20ac196a2be7bdcf932f9589a14d7ecbcd9d61e5b94c80d03a."
                + "dd260863ec4e79d883e572ec444bb0263a82bda16d05f73f35b41415fc3984ff")
    }

    @Test func aTokenGoesAsABearer() {
        let r = DaemonEndpoint(port: 7999, credential: .token("t0k")).request("voice/status")
        #expect(r.value(forHTTPHeaderField: "Authorization") == "Bearer t0k" && r.value(forHTTPHeaderField: "Cookie") == nil)
    }

    @Test func versionsAreComparedByNumber() {
        #expect(VersionCheck.compare(app: "1.15.0", daemon: "1.15.0") == .same)
        #expect(VersionCheck.compare(app: "1.15.0", daemon: "1.14.8") == .daemonOlder)
        #expect(VersionCheck.compare(app: "1.9.0", daemon: "1.10.0") == .appOlder)
        #expect(VersionCheck.compare(app: "1.15.0", daemon: "dev") == .unknown)
        #expect(VersionCheck.compare(app: "1.15.0", daemon: nil) == .unknown)
        #expect(VersionCheck.note(app: "1.15.0", daemon: "1.14.8")?.fix == MacCopy.updatePlugin)
        #expect(VersionCheck.note(app: "1.15.0", daemon: "1.15.0") == nil)
    }
}
