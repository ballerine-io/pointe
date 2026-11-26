import PointeKit
import XCTest
@testable import PointeUI

/// Phase 3 of people and machines (docs/design/people-and-machines.md, "Phase 3"): who answers a prompt and when, who
/// answered, a session started on somebody's machine, and what the people invited to a machine may do. The fixtures are
/// the status as pointe/guests.py and pointe/daemon.py build it.
@MainActor
final class PeopleApproveTests: XCTestCase {
    private func status(_ json: String) -> API.Status {
        try! JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    private let t0 = 1_790_000_000.0
    private var now: Date { Date(timeIntervalSince1970: t0) }

    /// Dana's voice, as the contract's example: Avi is asked first for shop's request on avi-box.
    private func danas(_ shop: String) -> API.Status {
        status("""
        {"connected": true,
         "machines": [{"id": "hub", "name": "studio", "here": true, "online": true},
                      {"id": "m7c1e22", "name": "avi-box", "here": false, "owner": "Avi", "grant": "send", "can_start": true, "online": true}],
         "sessions": [{"name": "shop", "machine": "avi-box", "owner": "Avi", "working": true, "online": true,
                       "capabilities": {"approvals": true}\(shop)},
                      {"name": "tide", "machine": "avi-box", "started_by": "Dana", "working": false, "waiting": false, "online": true}]}
        """)
    }

    private let request = #", "waiting": true, "request_id": "9f2c41aa", "request": "Bash\n{\"command\": \"npm test\"}""#
    private var askedFirst: API.Status { danas(request + #", "asked": {"name": "Avi", "until": 1790000020.4}, "can_answer": false"#) }
    private var open: API.Status { danas(request + #", "can_answer": true"#) }
    private var resolved: API.Status { danas(#", "waiting": false, "resolved_by": {"name": "Dana", "verdict": "allow", "at": 1790000003.5}"#) }

    /// On the machine itself (the contract's second example).
    private var onTheMachine: API.Status {
        status("""
        {"connected": true, "can_invite": true,
         "people_settings": {"approve": "anyone", "start": "on", "sessions_ask": "default", "owner_first_secs": 20.0, "people_hold_secs": 45.0},
         "people": [{"name": "Dana", "grant": "send", "online": true, "since": null, "vendors": []}],
         "machines": [{"id": "hub", "name": "avi-box", "here": true, "online": true}],
         "sessions": [{"name": "shop", "working": true, "waiting": true, "request_id": "9f2c41aa", "request": "Bash\\n{\\"command\\": \\"npm test\\"}",
                       "asked": {"name": "Dana", "until": 1790000020.0}, "can_answer": true, "owner": "Dana", "started_by": "Dana"},
                      {"name": "tide", "owner": "Dana", "started_by": "Dana", "working": false, "waiting": false,
                       "resolved_by": {"name": "Dana", "verdict": "allow", "at": 1790000003.5}}],
         "starting": [{"id": "st-1", "name": "billing", "harness": "claude-code", "state": "starting", "by": "Dana"}]}
        """)
    }

    // MARK: decoding

    func testThePhase3FieldsDecodeAsTheDaemonBuildsThem() {
        let s = askedFirst
        XCTAssertEqual(s.sessions[0].asked, API.Asked(name: "Avi", until: 1790000020.4))
        XCTAssertEqual(s.sessions[0].can_answer, false)
        XCTAssertEqual(s.sessions[1].started_by, "Dana")
        XCTAssertEqual(s.machines?[1].can_start, true)
        XCTAssertEqual(resolved.sessions[0].resolved_by, API.ResolvedBy(name: "Dana", verdict: "allow", at: 1790000003.5))
        let m = onTheMachine
        XCTAssertEqual(m.people_settings, API.PeopleSettings(approve: "anyone", start: "on", sessions_ask: "default", owner_first_secs: 20, people_hold_secs: 45))
        XCTAssertEqual(m.starting?.first?.by, "Dana")
        XCTAssertNil(m.starting?.first?.machine)
        let pending = try? JSONDecoder().decode(NewSession.Pending.self, from: Data(#"{"id": "rb-1", "line": "Start a Claude Code session on avi-box, Avi's machine, in shop?", "machine": "avi-box"}"#.utf8))
        XCTAssertEqual(pending?.machine, "avi-box")
    }

    func testAStatusWithoutThemReadsAsBefore() {
        let s = status("""
        {"connected": true, "machines": [{"id": "hub", "name": "studio", "here": true, "online": true}],
         "sessions": [{"name": "shop", "working": true, "waiting": true, "request_id": "r1", "request": "Bash"}],
         "starting": [{"id": "st-1", "name": "shop-2", "state": "starting"}], "start_pending": {"id": "rb-1", "line": "Start it?"}}
        """)
        XCTAssertNil(s.sessions[0].asked)
        XCTAssertNil(s.sessions[0].can_answer)
        XCTAssertNil(s.sessions[0].resolved_by)
        XCTAssertNil(s.sessions[0].started_by)
        XCTAssertNil(s.machines?[0].can_start)
        XCTAssertNil(s.people_settings)
        XCTAssertNil(s.starting?.first?.machine)
        XCTAssertNil(s.start_pending?.machine)
        let v = MachineView(s)
        XCTAssertNil(v.waitsFor(s.sessions[0]))
        XCTAssertNil(v.askedLine(s.sessions[0]))
        XCTAssertTrue(v.mayAnswer(s.sessions[0]), "an own prompt: Approve and Deny as always")
        XCTAssertNil(v.lastResolved)
        XCTAssertEqual(v.needingYou(), 1)
    }

    func testAFieldInAnotherFormIsDroppedNotTheStatus() {
        let s = status("""
        {"connected": true, "people_settings": "on", "machines": [{"id": "hub", "name": "studio", "here": true, "can_start": "yes"}],
         "sessions": [{"name": "shop", "working": true, "waiting": true, "asked": "Avi", "can_answer": 1, "resolved_by": [], "started_by": {"name": "Dana"}}]}
        """)
        XCTAssertEqual(s.sessions.count, 1)
        XCTAssertNil(s.sessions[0].asked)
        XCTAssertNil(s.sessions[0].can_answer)
        XCTAssertNil(s.sessions[0].resolved_by)
        XCTAssertNil(s.sessions[0].started_by)
        XCTAssertNil(s.people_settings)
        XCTAssertNil(s.machines?[0].can_start)
    }

    // MARK: the card: asked first, open, resolved

    func testWhileTheOwnerIsAskedFirstTheCardSaysWhoAndCountsDownWithNoAnswer() {
        let s = askedFirst, v = MachineView(s), shop = s.sessions[0]
        XCTAssertEqual(v.waitsFor(shop, now: now)?.name, "Avi")
        XCTAssertEqual(v.waitsFor(shop, now: now)?.left, 21, "20.4 s left: the second it ends in")
        XCTAssertEqual(v.askedLine(shop, now: now), "Avi is asked first · 21 s")
        XCTAssertEqual(v.askedLine(shop, now: now.addingTimeInterval(6.4)), "Avi is asked first · 14 s")
        XCTAssertEqual(v.askedLine(shop, now: now.addingTimeInterval(40)), "Avi is asked first", "past its time and not open yet: no count below zero")
        XCTAssertFalse(v.mayAnswer(shop), "no Approve or Deny before it opens")
        XCTAssertEqual(v.needingYou(), 0, "it does not wait for me yet")
        XCTAssertEqual(v.spoken(shop), ", Avi's session, Avi is asked first")
        XCTAssertEqual(PeopleCopy.askedFirst("avi", left: nil), "Avi is asked first")
    }

    func testOnceItOpensApproveAndDenyAreOffered() {
        let s = open, v = MachineView(s), shop = s.sessions[0]
        XCTAssertNil(v.waitsFor(shop))
        XCTAssertNil(v.askedLine(shop))
        XCTAssertTrue(v.mayAnswer(shop))
        XCTAssertEqual(v.needingYou(), 1)
        XCTAssertEqual(v.label(shop), "shop on avi-box")
    }

    func testAnsweredBySomebodyElseIsOneLine() {
        let s = resolved, v = MachineView(s), shop = s.sessions[0]
        XCTAssertFalse(v.mayAnswer(shop))
        XCTAssertEqual(v.resolvedLine(shop), "Dana approved it")
        XCTAssertEqual(v.lastResolved?.line, "Dana approved it")
        XCTAssertEqual(v.lastResolved?.session.name, "shop")
        XCTAssertEqual(PeopleCopy.resolved(API.ResolvedBy(name: "avi", verdict: "deny")), "Avi denied it")
        XCTAssertEqual(PeopleCopy.resolved(API.ResolvedBy(name: "Dana")), "Dana answered it", "only who, from a refused answer of my own")
        let again = danas(request + #", "can_answer": true, "resolved_by": {"name": "Dana", "verdict": "allow", "at": 1790000003.5}"#)
        XCTAssertNil(MachineView(again).resolvedLine(again.sessions[0]), "a new request waits: the card, not the old line")
    }

    func testOnTheMachineItsOwnerMayAnswerAtOnceAndSeesWhoIsAsked() {
        let s = onTheMachine, v = MachineView(s), shop = s.sessions[0]
        XCTAssertNil(v.waitsFor(shop), "can_answer is true there")
        XCTAssertTrue(v.mayAnswer(shop))
        XCTAssertEqual(v.askedLine(shop, now: now), "Dana is asked first · 20 s")
        XCTAssertEqual(v.resolvedLine(s.sessions[1]), "Dana approved it", "the owner's own device says who answered")
        XCTAssertEqual(v.needingYou(), 1)
    }

    func testAWatchOnlyMachineNeverOffersAnAnswer() {
        let s = status("""
        {"connected": true,
         "machines": [{"id": "hub", "name": "studio", "here": true, "online": true},
                      {"id": "m7c1e22", "name": "avi-box", "here": false, "owner": "Avi", "grant": "watch", "online": true}],
         "sessions": [{"name": "shop", "machine": "avi-box", "owner": "Avi", "working": true, "waiting": true, "online": true, "can_answer": true}]}
        """)
        XCTAssertFalse(MachineView(s).mayAnswer(s.sessions[0]))
        XCTAssertEqual(MachineView(s).needingYou(), 0)
    }

    func testTheScreensUseTheTurn() throws {
        let call = try Repo.source("CallView.swift")
        XCTAssertTrue(call.contains("turn: machines, answer: answer"), "the card is told who answers")
        XCTAssertTrue(call.contains("turn.waitsFor(session) != nil"), "and offers no answer while somebody else is asked first")
        XCTAssertTrue(call.contains("machines.mayAnswer(request), !driving"), "nor does the Call menu's Approve")
        XCTAssertTrue(try Repo.source("MacShell.swift").contains("machines.waitsFor(s) == nil"), "nor the Mac's menu bar and bubble")
    }

    // MARK: alerts

    private func attention(_ session: String) -> API.Attention {
        try! JSONDecoder().decode(API.Attention.self, from: Data("""
        {"id": "permission:9f2c41aa", "kind": "permission", "session": "\(session)", "request_id": "9f2c41aa",
         "title": "\(session) needs approval", "body": "run: npm test", "approvable": true}
        """.utf8))
    }

    func testNoAlertWhileItIsTheOwnersTurnThenTheOwnPromptsAlertNamingTheMachine() {
        let waiting = AlertPlan.plan([attention("shop")], posted: [], delivered: [], appActive: false, enabled: true, watchApprove: true,
                                     machines: MachineView(askedFirst))
        XCTAssertEqual(waiting.post, [], "Avi is asked first")
        XCTAssertEqual(waiting.posted, [], "not recorded: it is posted when it opens")
        let opened = AlertPlan.plan([attention("shop")], posted: waiting.posted, delivered: [], appActive: false, enabled: true, watchApprove: true,
                                    machines: MachineView(open))
        XCTAssertEqual(opened.post.map(\.title), ["shop on avi-box needs approval"])
        XCTAssertEqual(opened.post.first?.category, AlertPlan.approveCategory, "its Approve works as a node's prompt's does")
        XCTAssertEqual(opened.post.first?.session, "shop")
        XCTAssertEqual(opened.post.first?.requestId, "9f2c41aa")
        let gone = AlertPlan.plan([], posted: opened.posted, delivered: ["permission:9f2c41aa"], appActive: false, enabled: true, watchApprove: true,
                                  machines: MachineView(resolved))
        XCTAssertEqual(gone.withdraw, ["permission:9f2c41aa"], "Dana answered: it leaves the lock screen")
    }

    // MARK: whose it is

    func testStartedByDanaWhereTheOwnerTagIs() {
        let m = onTheMachine, v = MachineView(m)
        XCTAssertEqual(v.ownerTag(m.sessions[1]), "started by Dana", "on the machine's own device")
        XCTAssertEqual(v.spoken(m.sessions[1]), ", started by Dana, Dana approved it")
        let d = open
        XCTAssertNil(MachineView(d).ownerTag(d.sessions[1]), "on Dana's own voice it is hers: no tag")
        XCTAssertEqual(MachineView(d).ownerTag(d.sessions[0]), "Avi's")
    }

    func testPrivateOnASessionIStartedOnSomebodyElsesMachine() {
        let d = open, v = MachineView(d)
        XCTAssertEqual(v.privacyOffer(d.sessions[1], people: nil), true, "tide is mine, on avi-box")
        XCTAssertNil(v.privacyOffer(d.sessions[0], people: nil), "shop is Avi's")
        let m = onTheMachine
        XCTAssertNil(MachineView(m).privacyOffer(m.sessions[1], people: m.people), "on the machine a person's session is theirs to keep private")
    }

    // MARK: the approvals record

    func testTheRecordSaysWhoAnsweredWhenAPersonDid() throws {
        let page = try JSONDecoder().decode(API.ApprovalsPage.self, from: Data("""
        {"approvals": [
          {"session": "shop", "request_id": "9f2c41aa", "decision": "allow", "by": "tap", "person": "Dana", "link": "100.64.0.7",
           "request": "Bash\\n{\\"command\\": \\"npm test\\"}", "lock": "off", "score": null, "at": "2026-11-20 09:14:02.121"},
          {"session": "shop", "request_id": "77aa0102", "decision": "deny", "by": "voice", "request": "Bash", "lock": "off", "score": null,
           "at": "2026-11-20 09:10:00.000"}]}
        """.utf8))
        XCTAssertEqual(ApprovalsCopy.person(page.approvals[0]), "Dana, from 100.64.0.7")
        XCTAssertTrue(ApprovalsCopy.spoken(page.approvals[0]).hasPrefix("Approved by a tap, Dana, from 100.64.0.7, shop"))
        XCTAssertNil(ApprovalsCopy.person(page.approvals[1]), "the owner's own answer names nobody")
    }

    // MARK: New session on somebody's machine

    private let mine = NewSession.Options(
        harnesses: [.init(name: "claude-code", title: "Claude Code"), .init(name: "opencode", title: "OpenCode")],
        machines: [.init(name: "studio", here: true), .init(name: "avi-box", here: false, owner: "Avi"),
                   .init(name: "devbox", here: false, available: false, why: "devbox is offline.")],
        folders: [.init(path: "/Users/mira/work/shop", name: "shop"), .init(path: "/Users/mira/work/billing", name: "billing")])

    /// `GET /voice/new-session?machine=avi-box`, as daemon.py answers it.
    private func avis() throws -> NewSession.Options {
        try JSONDecoder().decode(NewSession.Options.self, from: Data("""
        {"harnesses": [{"name": "claude-code", "title": "Claude Code", "available": true, "why": null},
                       {"name": "codex", "title": "Codex", "available": true, "why": null}],
         "machines": [{"name": "studio", "here": true, "available": true, "why": null},
                      {"name": "avi-box", "here": false, "available": true, "why": null, "owner": "Avi"}],
         "max_prompt": 4000,
         "folders": [{"path": "/home/avi/work/shop", "name": "shop", "source": "machine"},
                     {"path": "/home/avi/work/tide", "name": "tide", "source": "machine"}],
         "machine": {"name": "avi-box", "owner": "Avi", "permissions": "skip", "account": "avi"}}
        """.utf8))
    }

    private final class Asked: @unchecked Sendable {
        var machines: [String?] = []
        var started: [NewSession.Draft] = []
        var refuse: API.Failure?
    }

    private func sheet(_ asked: Asked, owner: Bool = true) -> NewSessionModel {
        NewSessionModel(actions: NewSessionActions(
            ownerCheck: { _ in owner },
            options: { machine in
                asked.machines.append(machine)
                if machine != nil, let refuse = asked.refuse { throw refuse }
                return try machine == nil ? self.mine : self.avis()
            },
            start: { asked.started.append($0) }))
    }

    func testTheMachinesOwnOptionsDecode() throws {
        let o = try avis()
        XCTAssertEqual(o.machine, NewSession.Options.Target(name: "avi-box", owner: "Avi", permissions: "skip", account: "avi"))
        XCTAssertEqual(o.machines[1].owner, "Avi")
        XCTAssertEqual(o.of, "avi-box")
        XCTAssertEqual(mine.of, "studio")
        XCTAssertNil(mine.machine)
        XCTAssertTrue(mine.needsLoad(for: "avi-box"))
        XCTAssertFalse(mine.needsLoad(for: "studio"))
        XCTAssertTrue(o.needsLoad(for: "studio"), "back to this Mac: its own folders again")
        XCTAssertEqual(o.machine?.startsLine, "avi-box starts sessions that skip permission prompts: it can edit files and run commands as avi without asking.")
        XCTAssertEqual(NewSession.Options.Target(name: "avi-box", permissions: "ask").startsLine, "avi-box starts sessions that ask before actions.")
    }

    func testPickingSomebodysMachineLoadsItsFoldersAndSaysWhoseItIsAndHowItStarts() async {
        let asked = Asked(), model = sheet(asked)
        await model.load()
        XCTAssertEqual(model.draft.machine, "studio")
        XCTAssertNil(model.machineNote, "nothing new on this Mac")
        model.draft.harness = "opencode"
        model.draft.name = "tide-2"
        await model.pick(machine: "avi-box")
        XCTAssertEqual(asked.machines, [nil, "avi-box"])
        XCTAssertEqual(model.draft.machine, "avi-box")
        XCTAssertEqual(model.options?.folders.map(\.name), ["shop", "tide"], "that machine's own list")
        XCTAssertEqual(model.draft.folder, "/home/avi/work/shop", "a folder of this Mac cannot be sent there")
        XCTAssertEqual(model.draft.harness, "claude-code", "avi-box has no OpenCode")
        XCTAssertEqual(model.draft.name, "tide-2", "what was typed stays")
        XCTAssertEqual(model.machineNote, "avi-box is Avi's machine. avi-box starts sessions that skip permission prompts: it can edit files and run commands as avi without asking.")
        XCTAssertTrue(model.canStart)
        let started = await model.start()
        XCTAssertTrue(started)
        XCTAssertEqual(asked.started.first?.body, ["harness": "claude-code", "folder": "/home/avi/work/shop", "machine": "avi-box", "name": "tide-2"])
        await model.pick(machine: "studio")
        XCTAssertEqual(asked.machines, [nil, "avi-box", nil], "back to this Mac's own folders")
        XCTAssertEqual(model.draft.folder, "/Users/mira/work/shop")
        XCTAssertNil(model.machineNote)
    }

    func testAMachineThatRefusesSaysSoAndTheChoiceStays() async {
        let asked = Asked(), model = sheet(asked)
        asked.refuse = .status(409, "Avi turned off starting sessions on avi-box for the people invited to it.")
        await model.load()
        await model.pick(machine: "avi-box")
        XCTAssertEqual(model.problem, "Avi turned off starting sessions on avi-box for the people invited to it.")
        XCTAssertEqual(model.draft.machine, "studio")
        XCTAssertEqual(model.options?.folders.map(\.name), ["shop", "billing"])
        XCTAssertNil(model.loading)
        await model.pick(machine: "devbox")
        XCTAssertEqual(asked.machines.count, 2, "a machine that cannot take a start is not asked")
    }

    func testWithoutFaceIDNothingStarts() async {
        let asked = Asked(), model = sheet(asked, owner: false)
        await model.load()
        let started = await model.start()
        XCTAssertFalse(started)
        XCTAssertEqual(asked.started.count, 0)
    }

    func testTheCallAsksTheMachineByName() async throws {
        HubStub.reply = (200, #"{"harnesses": [], "machines": [], "folders": [], "machine": {"name": "avi-box", "owner": "Avi", "permissions": "ask", "account": ""}}"#)
        HubStub.bodies = []; HubStub.urls = []
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HubStub.self]
        let api = API(pairing: Demo.pairing, session: URLSession(configuration: config))
        let o = try await api.startOptions(machine: "avi-box")
        XCTAssertEqual(o.machine?.name, "avi-box")
        XCTAssertEqual(HubStub.urls.last?.path, "/voice/new-session")
        XCTAssertEqual(HubStub.urls.last?.query, "machine=avi-box")
        _ = try await api.startOptions()
        XCTAssertNil(HubStub.urls.last?.query)
    }

    func testASessionStartingThereSaysItsMachineAndOnTheMachineWhoAsked() {
        let row = NewSession.Starting(id: "st-1", name: "tide-2", state: "starting", machine: "avi-box")
        XCTAssertEqual(row.machine, "avi-box")
        XCTAssertEqual(PeopleCopy.startedBy("dana"), "started by Dana")
    }

    // MARK: what people can do

    private final class Desk: @unchecked Sendable {
        var now = API.PeopleSettings(approve: "anyone", start: "on", sessions_ask: "default", owner_first_secs: 20, people_hold_secs: 45)
        var posts: [[String: String]] = []
        var asked: [String] = []
        var owner = true
        var refuse: API.Failure?
        var has = true
    }

    private func people(_ desk: Desk) -> PeopleModel {
        PeopleModel(actions: PeopleActions(
            ownerCheck: { desk.asked.append($0); return desk.owner }, load: { [] },
            invite: { _, _ in API.PeopleInvite(code: "") }, state: { API.PeopleInvite(code: "") }, cancel: {}, grant: { _, _ in }, remove: { _ in },
            settings: {
                guard desk.has else { throw API.Failure.status(404, "HTTP 404") }
                return desk.now
            },
            setSettings: { changes in
                if let refuse = desk.refuse { throw refuse }
                desk.posts.append(changes)
                if let v = changes["approve"] { desk.now.approve = v }
                if let v = changes["start"] { desk.now.start = v }
                if let v = changes["sessions_ask"] { desk.now.sessions_ask = v }
                return desk.now
            }))
    }

    func testTheSettingsLoadAndEachChangeNeedsFaceIDAndPostsOneKey() async {
        let desk = Desk(), model = people(desk)
        XCTAssertNil(model.settings, "nothing shows until the Mac said")
        await model.loadSettings()
        XCTAssertEqual(model.settings?.mayApprove, true)
        XCTAssertEqual(model.settings?.mayStart, true)
        XCTAssertEqual(model.settings?.alwaysAsk, false)
        await model.set("approve", "off")
        XCTAssertEqual(desk.asked, [PeopleCopy.settingsReason])
        XCTAssertEqual(desk.posts, [["approve": "off"]])
        XCTAssertEqual(model.settings?.mayApprove, false)
        await model.set("approve", "off")
        XCTAssertEqual(desk.posts.count, 1, "the same value sends nothing")
        await model.set("sessions_ask", "ask")
        XCTAssertEqual(desk.posts.last, ["sessions_ask": "ask"])
        XCTAssertEqual(model.settings?.alwaysAsk, true)
        XCTAssertEqual(model.settings?.owner_first_secs, 20, "the times are the Mac's: nothing here changes them")
        await model.set("owner_first_secs", "5")
        XCTAssertEqual(desk.posts.count, 2, "no number is set from this screen")
    }

    func testWithoutFaceIDOrWhenTheMacRefusesTheSwitchStays() async {
        let desk = Desk(), model = people(desk)
        await model.loadSettings()
        desk.owner = false
        await model.set("start", "off")
        XCTAssertEqual(desk.posts.count, 0)
        XCTAssertEqual(model.settings?.mayStart, true)
        desk.owner = true
        desk.refuse = .status(409, "start is on or off")
        await model.set("start", "off")
        XCTAssertEqual(model.settings?.mayStart, true, "back where it was")
        XCTAssertEqual(model.problem, "Start is on or off.")
    }

    func testAnOlderMacHasNoSuchGroupAndTheStatusIsFollowed() async {
        let desk = Desk(), model = people(desk)
        desk.has = false
        await model.loadSettings()
        XCTAssertNil(model.settings)
        model.follow(settings: nil)
        XCTAssertNil(model.settings)
        model.follow(settings: onTheMachine.people_settings)
        XCTAssertEqual(model.settings?.approve, "anyone", "a change made on the page shows here")
    }

    func testTheSettingsRoutes() async throws {
        HubStub.reply = (200, #"{"approve": "off", "start": "on", "sessions_ask": "default", "owner_first_secs": 20.0, "people_hold_secs": 45.0}"#)
        HubStub.bodies = []
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HubStub.self]
        let api = API(pairing: Demo.pairing, session: URLSession(configuration: config))
        let now = try await api.setPeopleSettings(["approve": "off"])
        XCTAssertEqual(now.approve, "off")
        XCTAssertEqual(HubStub.bodies.last?["path"] as? String, "/voice/people/settings")
        XCTAssertEqual((HubStub.bodies.last?["body"] as? [String: Any])?["approve"] as? String, "off")
        _ = try await api.peopleSettings()
        XCTAssertEqual(HubStub.bodies.last?["path"] as? String, "/voice/people/settings")
    }

    // MARK: the demo screens and the words

    func testThePhase3DemoScreensDecode() throws {
        let asked = try XCTUnwrap(Demo.make(.peopleAsked)).status
        XCTAssertEqual(MachineView(asked).waitsFor(asked.sessions[2])?.name, "avi")
        XCTAssertFalse(MachineView(asked).mayAnswer(asked.sessions[2]))
        let open = try XCTUnwrap(Demo.make(.peopleOpen)).status
        XCTAssertTrue(MachineView(open).mayAnswer(open.sessions[2]))
        let resolved = try XCTUnwrap(Demo.make(.peopleResolved)).status
        XCTAssertEqual(MachineView(resolved).lastResolved?.line, "Dana approved it")
        let start = try XCTUnwrap(Demo.make(.peopleStart)).status
        XCTAssertEqual(start.machines?.last?.can_start, true)
        XCTAssertEqual(start.people_settings?.approve, "anyone")
        let options = try XCTUnwrap(Demo.startOptions(machine: "avi-box", status: start))
        XCTAssertEqual(options.machine?.owner, "avi")
        XCTAssertEqual(options.folders.map(\.name), ["shop", "tide"])
        XCTAssertEqual(Demo.startOptions(machine: nil, status: start)?.machines.map(\.name), ["studio", "avi-box"])
        XCTAssertEqual(Demo.startOptions(machine: nil, status: try XCTUnwrap(Demo.make(.call)).status), Demo.startOptions, "other demos keep their list")
        let watch = try XCTUnwrap(Demo.make(.peopleWatch)).status
        XCTAssertEqual(Demo.startOptions(machine: nil, status: watch)?.machines.last?.available, false)
    }

    func testTheWords() {
        XCTAssertEqual([PeopleCopy.askedFirst, PeopleCopy.approvedIt, PeopleCopy.deniedIt, PeopleCopy.canDo, PeopleCopy.approveRequests, PeopleCopy.startSessions,
                        PeopleCopy.sessionsTheyStart, PeopleCopy.followDefault, PeopleCopy.alwaysAsk, PeopleCopy.startedBy],
                       ["is asked first", "approved it", "denied it", "What people can do", "Approve requests", "Start sessions",
                        "Sessions they start", "Follow my default", "Always ask first", "started by"])
    }
}
