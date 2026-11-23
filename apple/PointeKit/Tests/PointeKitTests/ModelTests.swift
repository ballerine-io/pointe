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
