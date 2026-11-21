import Foundation
import Testing
@testable import PointeKit

func fixture(_ name: String) throws -> Data {
    let url = try #require(Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Fixtures"))
    return try Data(contentsOf: url)
}

@Suite struct ModelTests {
    @Test func aBusyStatusDecodesAsThePageRigMakesIt() throws {
        let status = try JSONDecoder().decode(API.Status.self, from: fixture("status-busy"))
        #expect(status.connected)
        #expect(status.sessions.count == 5)
        #expect(status.sessions[1].waiting && status.sessions[1].request == "Bash(rm -rf build && make test)")
        #expect(status.talk?.count == 4)
        #expect(status.ptt?.mode == "always")
        #expect(status.machines?.count == 2)
    }

    /// Captured from the daemon's own /voice/status (tests/test_orchestrator.py's client), names replaced: the shape a
    /// real daemon sends, which the page rig's stub does not match field for field.
    @Test func theDaemonsOwnStatusAndPrefsDecode() throws {
        let status = try JSONDecoder().decode(API.Status.self, from: fixture("status-daemon"))
        #expect(status.version == "1.15.0" && !status.connected && status.sessions.isEmpty)
        #expect(status.machines?.first?.isHere == true && status.keep_awake?.on == false)
        let prefs = try JSONDecoder().decode(API.Prefs.self, from: fixture("prefs-daemon"))
        #expect(prefs.microphone == "always" && prefs.patience == "normal")
    }

    @Test func anEmptyStatusAndAnOlderDaemonDecode() throws {
        _ = try JSONDecoder().decode(API.Status.self, from: fixture("status-empty"))
        let old = try JSONDecoder().decode(API.Status.self, from: Data(#"{"connected": false, "sessions": []}"#.utf8))
        #expect(old.version == nil && old.ptt == nil && old.machines == nil)
    }

    @Test func sessionsAreGroupedByMachineThisMacFirst() throws {
        let view = MachineView(try JSONDecoder().decode(API.Status.self, from: fixture("status-busy")))
        #expect(view.names == ["studio", "devbox"])
        #expect(view.onMachine("studio").count == 3 && view.onMachine("devbox").count == 2)
        #expect(view.header("studio") == "studio · this Mac")
        #expect(view.header("devbox").hasPrefix("devbox · Linux · "))
    }

    @Test func prefsFallBackToTheDaemonsDefaults() throws {
        let prefs = try JSONDecoder().decode(API.Prefs.self, from: Data("{}".utf8))
        #expect(prefs.microphone == "always" && prefs.patience == "normal" && !prefs.watchApprove)
    }

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

@Suite struct TalkGateTests {
    let t0 = Date(timeIntervalSince1970: 1000)

    @Test func alwaysOnSendsAndIgnoresPresses() {
        var gate = TalkGate()
        gate.press(.shortcut)
        #expect(!gate.isOpen && gate.sends())
    }

    @Test func aHoldOpensAndTheReleaseLeavesATail() {
        var gate = TalkGate()
        gate.mode = "ptt"
        #expect(!gate.sends(at: t0))
        gate.press(.shortcut, at: t0)
        gate.press(.ring, at: t0)  // a second control is not a new press
        gate.release(.shortcut, at: t0.addingTimeInterval(1))
        #expect(gate.isOpen)
        gate.release(.ring, at: t0.addingTimeInterval(2))
        #expect(!gate.isOpen)
        #expect(gate.sends(at: t0.addingTimeInterval(2.3)) && !gate.sends(at: t0.addingTimeInterval(2.5)))
    }

    @Test func aToggleOpensAndTheNextCloses() {
        var gate = TalkGate()
        gate.mode = "ptt"
        gate.toggle(at: t0)
        #expect(gate.isOpen)
        gate.set(open: true, at: t0)  // said again for the state it is in: nothing changes
        #expect(gate.isOpen)
        gate.set(open: false, at: t0)
        #expect(!gate.isOpen)
    }

    @Test func aPressTheDaemonClosedClosesHereOnlyOnceItWasSeenOpen() {
        var gate = TalkGate()
        gate.mode = "ptt"
        gate.press(.shortcut, at: t0)
        #expect(gate.follow(API.PTTStatus(mode: "ptt", open: false, closed_why: "held too long")) == nil)  // about an earlier press
        #expect(gate.follow(API.PTTStatus(mode: "ptt", open: true)) == nil)
        #expect(gate.follow(API.PTTStatus(mode: "ptt", open: false, closed_why: "held too long")) == "held too long")
        #expect(!gate.isOpen && !gate.sends(at: t0))
        #expect(TalkGate.closedLine("held too long", style: .tap) == "Talk closed after 90 s: tap again")
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

    @Test func aRefusalIsSaidInTheDaemonsWords() {
        #expect(DaemonClient.reason(Data(#"{"detail": "that request is no longer pending"}"#.utf8), code: 409) == "that request is no longer pending")
        #expect(DaemonClient.reason(Data("forbidden".utf8), code: 403) == "forbidden")
        #expect(DaemonClient.reason(Data("<html>".utf8), code: 500) == "HTTP 500")
        #expect(DaemonClient.reason(Data(), code: 502) == "HTTP 502")
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

@Suite struct AlertPlanTests {
    let items = [API.Attention(id: "perm-1", kind: "permission", session: "docs", request_id: "perm-1", title: "docs needs approval",
                               body: "git push to origin", approvable: true),
                 API.Attention(id: "q-1", kind: "question", session: "billing", title: "billing asks", body: "Which branch?")]

    @Test func nothingIsPostedWhileTheWindowIsInFront() {
        let plan = AlertPlan.plan(items, posted: [], delivered: [], appActive: true, enabled: true, watchApprove: true)
        #expect(plan.post.isEmpty)
    }

    @Test func approveIsOfferedOnlyWithTheSettingAndAReadableRequest() {
        let on = AlertPlan.plan(items, posted: [], delivered: [], appActive: false, enabled: true, watchApprove: true)
        #expect(on.post.map(\.category) == [AlertPlan.approveCategory, AlertPlan.openCategory])
        let off = AlertPlan.plan(items, posted: [], delivered: [], appActive: false, enabled: true, watchApprove: false)
        #expect(off.post.first?.category == AlertPlan.denyCategory)
        let unreadable = [API.Attention(id: "p", kind: "permission", session: "docs", request_id: "p", title: "t", body: "b", approvable: false)]
        #expect(AlertPlan.plan(unreadable, posted: [], delivered: [], appActive: false, enabled: true, watchApprove: true).post.first?.category == AlertPlan.denyCategory)
    }

    @Test func eachItemIsPostedOnceAndWithdrawnWhenAnswered() {
        let first = AlertPlan.plan(items, posted: [], delivered: [], appActive: false, enabled: true, watchApprove: false)
        let again = AlertPlan.plan(items, posted: first.posted, delivered: ["perm-1", "q-1"], appActive: false, enabled: true, watchApprove: false)
        #expect(again.post.isEmpty && again.withdraw.isEmpty)
        let answered = AlertPlan.plan([items[1]], posted: first.posted, delivered: ["perm-1", "q-1"], appActive: false, enabled: true, watchApprove: false)
        #expect(answered.withdraw == ["perm-1"])
    }

    @Test func anActionIsBoundToItsRequest() {
        let info: [AnyHashable: Any] = ["session": "docs", "request_id": "perm-1"]
        #expect(AlertAnswer.decision(action: AlertAnswer.approve, userInfo: info) == .init(session: "docs", requestId: "perm-1", allow: true))
        #expect(AlertAnswer.decision(action: AlertAnswer.deny, userInfo: info)?.allow == false)
        #expect(AlertAnswer.decision(action: AlertAnswer.approve, userInfo: [:]) == nil)
        #expect(AlertAnswer.outcome(API.Failure.status(409, "")) == .alreadyAnswered)
        #expect(AlertAnswer.outcome(API.Failure.status(403, "")) == .approveInApp)
        #expect(AlertAnswer.outcome(URLError(.timedOut)) == .unreachable)
    }
}
