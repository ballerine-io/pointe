import Foundation
import Testing
@testable import PointeKit

final class FakeAuth: Authenticating, @unchecked Sendable {
    private let lock = NSLock()
    private var answer: Bool, reasonsAsked: [String] = []
    init(_ answer: Bool) { self.answer = answer }
    var reasons: [String] { lock.withLock { reasonsAsked } }
    func confirm(reason: String) async -> Bool { lock.withLock { reasonsAsked.append(reason); return answer } }
}

@MainActor @Suite struct StoreTests {
    func store(_ daemon: StubDaemon, auth: FakeAuth = FakeAuth(true)) -> PointeStore {
        PointeStore(api: daemon, authenticator: auth, appVersion: "1.15.0")
    }

    @Test func theMenuBarCountsWhoNeedsYou() async {
        let daemon = StubDaemon()
        let s = store(daemon)
        #expect(s.menuBar.kind == .down)  // nothing heard from the daemon yet
        await s.refresh()
        #expect(s.menuBar == MenuBarState(kind: .needsYou, count: 2, title: "2 sessions need you"))
        #expect(s.menuBar.accessibilityLabel == "Pointe: 2 sessions need you")
        await daemon.set { $0.sessions = [] }
        await s.refresh()
        #expect(s.menuBar.kind == .off && s.menuBar.count == 0)
    }

    @Test func sessionsAreGroupedByMachineWithThePagesTags() async {
        let s = store(StubDaemon())
        await s.refresh()
        #expect(s.groups.map(\.name) == ["studio", "devbox"])
        #expect(s.groups[0].header == "studio · this Mac" && s.groups[1].header == "devbox · Linux · 23 ms")
        #expect(s.groups[0].sessions.map(PointeStore.tag) == ["working", "approve", "needs you"])
        #expect(s.groups[1].sessions.map(PointeStore.tag) == ["working", "idle"])
    }

    @Test func approveAsksWhoIsThereAndCarriesTheExactRequest() async throws {
        let daemon = StubDaemon(), auth = FakeAuth(true)
        let s = store(daemon, auth: auth)
        await s.refresh()
        let approval = try #require(s.pending.first)
        #expect(approval.request == "Bash(git push origin retry-fix)" && approval.requestId == "perm-1")
        #expect(await s.approve(approval))
        #expect(auth.reasons == [MacCopy.approveReason])
        #expect(await daemon.calls.contains("answer docs perm-1 allow"))
        #expect(s.pending.isEmpty)
    }

    @Test func withoutTouchIDNothingIsApproved() async throws {
        let daemon = StubDaemon()
        let s = store(daemon, auth: FakeAuth(false))
        await s.refresh()
        #expect(!(await s.approve(try #require(s.pending.first))))
        let calls = await daemon.calls
        #expect(calls.isEmpty && s.pending.count == 1)
    }

    @Test func denyNeverAsks() async throws {
        let daemon = StubDaemon(), auth = FakeAuth(false)
        let s = store(daemon, auth: auth)
        await s.refresh()
        #expect(await s.deny(try #require(s.pending.first)))
        #expect(auth.reasons.isEmpty)
        #expect(await daemon.calls == ["answer docs perm-1 deny"])
    }

    @Test func aRequestAnsweredElsewhereSaysSo() async throws {
        let daemon = StubDaemon()
        let s = store(daemon)
        await s.refresh()
        let approval = try #require(s.pending.first)
        try await daemon.answer(session: "docs", requestId: "perm-1", allow: false, viaNotification: false)
        _ = await s.approve(approval)
        #expect(s.notice == MacCopy.alreadyAnswered)
    }

    @Test func anOfflineSessionsRequestCannotBeAnsweredHere() async throws {
        let daemon = StubDaemon()
        await daemon.set { $0.sessions[1].online = false }
        let s = store(daemon)
        await s.refresh()
        let approval = try #require(s.pending.first)
        #expect(approval.offline)
        let approved = await s.approve(approval), denied = await s.deny(approval)
        #expect(!approved && !denied)
        #expect(await daemon.calls.isEmpty)
    }

    @Test func aNotificationsApproveIsTheDaemonsToRefuse() async {
        let daemon = StubDaemon()
        await daemon.set { $0.sessions[1] = API.Session(name: "docs", working: false, waiting: true, request: "Bash(python3 -c …)", request_id: "perm-1", voice_can_approve: false) }
        let s = store(daemon)
        await s.refresh()
        let said = await s.answerFromNotification(.init(session: "docs", requestId: "perm-1", allow: true))
        #expect(said == MacCopy.approveOnPage)
        #expect(await s.answerFromNotification(.init(session: "docs", requestId: "gone", allow: false)) == MacCopy.alreadyAnswered)
        #expect(await s.answerFromNotification(.init(session: "docs", requestId: "perm-1", allow: false)) == nil)
    }

    @Test func aDaemonThatIsAwayOrRefusesIsToldApart() async {
        let daemon = StubDaemon()
        let s = store(daemon)
        await daemon.fail(.status(403, "forbidden"))
        await s.refresh()
        #expect(s.reach == .rejected && s.connectWhy.line == MacCopy.keyRefused && s.connectWhy.bad)
        await daemon.fail(nil)
        await daemon.setDown(true)
        await s.refresh()
        #expect(s.reach == .unreachable && s.connectWhy.line == MacCopy.daemonDown)
        await daemon.setDown(false)
        await s.refresh()
        #expect(s.reach == .ok && s.connectWhy == (MacCopy.elsewhereWhy, false))  // the stub says a call is up, and it is not ours
    }

    @Test func typedWordsBecomeATurnAndEmptyOnesAreNotSent() async {
        let daemon = StubDaemon()
        let s = store(daemon)
        await s.refresh()
        #expect(!(await s.say("   ")))
        #expect(await s.say(" ship it "))
        #expect(await daemon.calls == ["say ship it"])
        #expect(s.status?.talk?.last?.text == "Noted: ship it")
    }

    @Test func aBrainDumpIsReviewedThenSentOnTheSecondClick() async {
        let daemon = StubDaemon()
        let s = store(daemon)
        await s.refresh()
        await s.dumpAction("start")
        #expect(s.dump?.isDumping == true && s.status?.dumping == true)
        await s.dumpAction("done")
        #expect(s.dump?.inReview == true && s.dumpTarget == .orchestrator)
        #expect(s.dumpChoices.first == .orchestrator && s.dumpChoices.count == 6)
        s.dumpPicked = .session("payments")
        await s.dumpSend()
        #expect(s.dumpSendArmed && s.dump != nil)
        await s.dumpSend()
        #expect(s.dump == nil && !s.dumpSendArmed)
        #expect(await daemon.calls.last == "dump send session=payments")
    }

    @Test func loweringTheVoiceLockAsksWhoIsThere() async {
        let daemon = StubDaemon()
        await daemon.set { $0.voice_lock = API.VoiceLock(level: "commands", enrolled: true) }
        let auth = FakeAuth(true)
        let s = store(daemon, auth: auth)
        await s.refresh()
        await s.setVoiceLock(.everything)
        #expect(auth.reasons.isEmpty)
        await s.setVoiceLock(.off)
        #expect(auth.reasons == [MacCopy.lowerLockReason])
        #expect(s.status?.voice_lock?.lockLevel == .off)
    }

    @Test func raisingTheLockWithoutAVoiceprintSaysTheDaemonsReason() async {
        let s = store(StubDaemon())
        await s.refresh()
        await s.setVoiceLock(.approvals)
        #expect(s.notice == "Enrol your voice to use the other levels.")
    }

    @Test func aVersionDifferenceIsSaid() async {
        let daemon = StubDaemon()
        await daemon.set { $0.version = "1.14.8" }
        let s = store(daemon)
        await s.refresh()
        #expect(s.versionNote?.line == "Pointe on this Mac is 1.14.8; this app is 1.15.0.")
    }

    @Test func theStateLineFollowsTheCall() async {
        let daemon = StubDaemon()
        let dialer = FakeDialer(), audio = FakeAudio(), socket = FakeSocket()
        dialer.next(.success(socket))
        let call = CallLink(dialer: dialer, audio: audio, device: "Mac", place: "p", words: words, sleep: { _ in })
        let s = PointeStore(api: daemon, authenticator: FakeAuth(true), appVersion: "1.15.0", call: call)
        await s.refresh()
        #expect(s.stateTitle == MacCopy.elsewhere)
        await call.start()
        #expect(s.stateTitle == MacCopy.listening && s.mine)
        call.toggleMute()
        #expect(s.stateTitle == MacCopy.muted)
        await daemon.set { $0.ptt = API.PTTStatus(mode: "ptt", open: false) }
        await s.refresh()
        #expect(s.stateTitle == "Hold to talk")
        call.talkDown(.shortcut)
        #expect(s.stateTitle == "Talking" && s.menuBar.kind == .needsYou)
        await daemon.set { $0.sessions = [] }
        await s.refresh()
        #expect(s.menuBar.kind == .talking)
    }
}
