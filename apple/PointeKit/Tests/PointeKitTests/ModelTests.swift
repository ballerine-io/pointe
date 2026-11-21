import Foundation
import Testing
@testable import PointeKit

@Suite struct ModelTests {
    @Test func anUnknownHarnessStillGetsAMark() {
        #expect(Harness.mark(nil).name == "Claude")
        #expect(Harness.mark("").glyph == "C")
        #expect(Harness.mark("aider").glyph == "A")
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
        #expect(Wire.Control(#"{"type":"ping","id":7,"rtt_ms":12}"#) == .ping(id: 7, rttMs: 12))
        #expect(Wire.Control(#"{"type":"ping","id":7,"rtt_ms":null}"#) == .ping(id: 7, rttMs: nil))
        #expect(Wire.Control(#"{"type":"ptt","open":true,"by":"shortcut"}"#) == .ptt(open: true))
        #expect(Wire.Control(#"{"type":"ptt"}"#) == nil)
        #expect(Wire.Control("not json") == nil && Wire.Control(#"{"type":"new"}"#) == nil)
    }

    @Test func helloSaysTheProtocolAndPushToTalk() throws {
        let hello = try #require(try JSONSerialization.jsonObject(with: Data(Wire.hello(device: "Mac").utf8)) as? [String: Any])
        #expect(hello["protocol"] as? Int == 4 && hello["device"] as? String == "Mac")
        #expect(hello["capabilities"] as? [String] == ["ptt"])
        #expect(Wire.alive(answered: 7) == #"{"alive":true,"id":7,"type":"pong"}"#)
    }
}

@Suite struct ClientTests {
    let endpoint = DaemonEndpoint(port: 7999, credential: .pageKey("k3y"))

    @Test func aRequestCarriesThePageCookieOnLoopbackAndNoOrigin() throws {
        let r = endpoint.request("voice/approve", method: "POST", body: ["session": "docs", "decision": "allow"])
        #expect(r.url?.absoluteString == "http://127.0.0.1:7999/voice/approve")
        #expect(r.value(forHTTPHeaderField: "Cookie") == "pointe_local=k3y")
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
        #expect(endpoint.callRequest.value(forHTTPHeaderField: "Cookie") == "pointe_local=k3y")
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
