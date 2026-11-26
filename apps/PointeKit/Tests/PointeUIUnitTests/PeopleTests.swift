import XCTest
@testable import PointeUI

/// People and machines (docs/design/people-and-machines.md): the status's new fields, whose a session is, watch only,
/// Private, the Mine chip, Add a machine and the People list. No network and no screen: the calls are given.
@MainActor
final class PeopleTests: XCTestCase {
    private func status(_ json: String) -> API.Status {
        try! JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    private let now = 1_794_400_000.0

    /// studio is mine and has two people; avi-box is Avi's, and I may send to it (or only watch).
    private func shared(grant: String = "send", waiting: Bool = false) -> API.Status {
        status("""
        {"connected": true, "mode": "orchestrator",
         "sessions": [{"name": "shop", "working": true, "waiting": false, "machine": "studio", "online": true},
                      {"name": "billing", "working": false, "waiting": false, "machine": "studio", "online": true, "private": true},
                      {"name": "tide", "working": true, "waiting": \(waiting), "request_id": "r1", "machine": "avi-box", "online": true,
                       "owner": "avi", "by": {"name": "dana", "since": \(now - 120)}},
                      {"name": "shop on avi-box", "working": false, "waiting": false, "machine": "avi-box", "online": true, "owner": "avi"}],
         "machines": [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true, "sessions": 2},
                      {"id": "m7c1e22", "name": "avi-box", "here": false, "os": "linux", "online": true, "sessions": 2, "rtt_ms": 31,
                       "owner": "avi", "grant": "\(grant)"}],
         "people": [{"name": "dana", "grant": "send", "online": true, "since": \(now - 1500)},
                    {"name": "omer", "grant": "watch", "online": false, "since": \(now - 3600)}],
         "people_invite": {"code": "K7PQ-2MXD", "expires_in": 540, "name": "noa", "grant": "watch"},
         "disclosure": {"machine": "avi-box", "vendors": ["Deepgram", "Gemini"]}}
        """)
    }

    private var alone: API.Status {
        status("""
        {"connected": true, "sessions": [{"name": "shop", "working": true, "waiting": false, "machine": "studio", "online": true},
                                         {"name": "api", "working": false, "waiting": false, "machine": "devbox", "online": true}],
         "machines": [{"id": "hub", "name": "studio", "here": true, "online": true},
                      {"id": "n3f2a1", "name": "devbox", "here": false, "os": "linux", "online": true, "rtt_ms": 23}]}
        """)
    }

    // MARK: the status

    func testEveryNewFieldDecodes() {
        let s = shared()
        XCTAssertEqual(s.machines?[1].owner, "avi")
        XCTAssertEqual(s.machines?[1].grant, "send")
        XCTAssertEqual(s.sessions[2].owner, "avi")
        XCTAssertEqual(s.sessions[2].by, API.By(name: "dana", since: now - 120))
        XCTAssertEqual(s.sessions[1].private, true)
        XCTAssertEqual(s.people?.map(\.name), ["dana", "omer"])
        XCTAssertEqual(s.people?[1].watchOnly, true)
        XCTAssertEqual(s.people_invite?.name, "noa")
        XCTAssertEqual(s.people_invite?.paired, false)
        XCTAssertEqual(s.disclosure, API.Disclosure(machine: "avi-box", vendors: ["Deepgram", "Gemini"]))
    }

    func testAStatusWithoutThemDecodesAndShowsNothingNew() {
        let s = alone
        XCTAssertNil(s.machines?[1].owner)
        XCTAssertNil(s.machines?[1].grant)
        XCTAssertNil(s.sessions[0].owner)
        XCTAssertNil(s.sessions[0].private)
        XCTAssertNil(s.sessions[0].by)
        XCTAssertNil(s.people)
        XCTAssertNil(s.people_invite)
        XCTAssertNil(s.disclosure)
        let v = MachineView(s)
        XCTAssertFalse(v.hasOwners)
        XCTAssertNil(v.ownerTag(s.sessions[1]))
        XCTAssertNil(v.ownerTag(machine: "devbox"))
        XCTAssertFalse(v.watchOnly(s.sessions[1]))
        XCTAssertNil(v.privacyOffer(s.sessions[0], people: s.people), "no people: no Private")
        XCTAssertEqual(v.header("devbox"), "devbox · Linux · 23 ms")
        XCTAssertEqual(v.label(s.sessions[1]), "api · devbox")
        XCTAssertEqual(v.spoken(s.sessions[1]), "")
        let old = status(#"{"connected": true, "sessions": [{"name": "docs", "working": false, "waiting": false}]}"#)
        XCTAssertNil(old.people)
        XCTAssertNil(MachineView(old).valid(MachineView.mineFilter), "a Mac before machines has no Mine chip")
    }

    /// A field in a form this app does not know is dropped: the call screen never goes blank over it.
    func testANewFieldInAnotherFormLeavesTheRestOfTheStatus() {
        let s = status("""
        {"connected": true,
         "sessions": [{"name": "shop", "working": true, "waiting": false, "owner": 7, "private": "yes", "by": "dana"},
                      {"name": "tide", "working": false, "waiting": false, "by": {"name": "dana", "since": "14:02"}}],
         "machines": [{"id": "hub", "name": "studio", "here": true, "owner": {"name": "avi"}, "grant": 3}],
         "people": {"dana": {}}, "people_invite": [], "disclosure": "avi-box"}
        """)
        XCTAssertEqual(s.sessions.map(\.name), ["shop", "tide"])
        XCTAssertNil(s.sessions[0].owner)
        XCTAssertNil(s.sessions[0].private)
        XCTAssertNil(s.sessions[0].by)
        XCTAssertEqual(s.sessions[1].by?.name, "dana")
        XCTAssertEqual(s.sessions[1].by?.sinceText, "14:02", "a clock time already written is kept as it is")
        XCTAssertNil(s.machines?[0].owner)
        XCTAssertNil(s.machines?[0].grant)
        XCTAssertNil(s.people)
        XCTAssertNil(s.people_invite)
        XCTAssertNil(s.disclosure)
    }

    func testAPersonNeedsOnlyAName() throws {
        let page = try JSONDecoder().decode(API.PeoplePage.self, from: Data("""
        {"people": [{"id": "p1", "name": "dana", "grant": "send", "online": true, "since": \(now), "address": "100.64.0.7",
                     "key_fp": "9a41", "vendors": ["Deepgram", "Gemini"], "added": \(now - 86_400)},
                    {"name": "omer", "vendors": "none", "online": "no"}]}
        """.utf8))
        XCTAssertEqual(page.people[0].vendors, ["Deepgram", "Gemini"])
        XCTAssertEqual(page.people[1].name, "omer")
        XCTAssertNil(page.people[1].vendors)
        XCTAssertNil(page.people[1].online)
    }

    func testAnInviteIsPairedByATrueOrByWhoPaired() throws {
        func invite(_ json: String) throws -> API.PeopleInvite { try JSONDecoder().decode(API.PeopleInvite.self, from: Data(json.utf8)) }
        XCTAssertFalse(try invite(#"{"code": "K7PQ-2MXD", "expires_in": 600, "link": "pointe://machine?code=K7PQ-2MXD"}"#).paired)
        XCTAssertFalse(try invite(#"{"code": "K7PQ-2MXD", "paired": false}"#).paired)
        XCTAssertFalse(try invite(#"{"code": "K7PQ-2MXD", "paired": null}"#).paired)
        XCTAssertTrue(try invite(#"{"code": "K7PQ-2MXD", "paired": true, "name": "dana"}"#).paired)
        XCTAssertTrue(try invite(#"{"paired": {"name": "dana"}}"#).paired, "as the phone's invite says it")
        XCTAssertEqual(try invite(#"{"ended": "the invite was cancelled after 20 wrong codes"}"#).ended, "the invite was cancelled after 20 wrong codes")
    }

    // MARK: whose it is

    func testAnOwnerTagOnlyOnWhatIsSomebodyElses() {
        let s = shared(), v = MachineView(s)
        XCTAssertNil(v.ownerTag(s.sessions[0]), "mine")
        XCTAssertEqual(v.ownerTag(s.sessions[2]), "Avi's")
        XCTAssertNil(v.ownerTag(machine: "studio"))
        XCTAssertEqual(v.ownerTag(machine: "avi-box"), "Avi's")
        XCTAssertEqual(v.header("avi-box"), "avi-box · Avi's · Linux · 31 ms")
        XCTAssertEqual(v.header("studio"), "studio · this Mac")
        XCTAssertEqual(PeopleCopy.owned("Dana Levi"), "Dana Levi's", "a name with a capital is left as it was written")
    }

    func testASessionOnSomebodyElsesMachineReadsShopOnAviBox() {
        let s = shared(), v = MachineView(s)
        XCTAssertEqual(v.label(s.sessions[2]), "tide on avi-box")
        XCTAssertEqual(v.label(s.sessions[3]), "shop on avi-box", "the machine is not said twice")
        XCTAssertEqual(v.label(s.sessions[0]), "shop · studio", "my own, while machines mix, as before")
        XCTAssertEqual(v.short(s.sessions[3]), "shop", "under avi-box's own heading the machine is not said again")
        XCTAssertEqual(v.short(s.sessions[2]), "tide")
        XCTAssertEqual(v.short(s.sessions[0]), "shop")
    }

    func testWatchOnlyIsSaidAndNothingWaitsForMe() {
        let send = shared(waiting: true), watch = shared(grant: "watch", waiting: true)
        XCTAssertFalse(MachineView(send).watchOnly(send.sessions[2]))
        XCTAssertEqual(MachineView(send).needingYou(), 1)
        let v = MachineView(watch)
        XCTAssertTrue(v.watchOnly(watch.sessions[2]))
        XCTAssertTrue(v.watchOnly(machine: "avi-box"))
        XCTAssertFalse(v.watchOnly(watch.sessions[0]), "my own machine")
        XCTAssertEqual(v.header("avi-box"), "avi-box · Avi's · Linux · 31 ms · watch only")
        XCTAssertEqual(v.needingYou(), 0, "a prompt on a session I only watch is its owner's")
    }

    func testDanaIsUsingItWhileTheSessionWorksOnHerRequest() {
        let s = shared(), v = MachineView(s)
        XCTAssertEqual(v.usedBy(s.sessions[2]), "Dana is using it")
        XCTAssertNil(v.usedBy(s.sessions[3]))
        XCTAssertEqual(v.spoken(s.sessions[2]), ", Avi's session, Dana is using it")
        XCTAssertEqual(v.spoken(s.sessions[1]), ", private")
    }

    func testPrivateIsOfferedOnMySessionsOfThisMachineOnceItHasPeople() {
        let s = shared(), v = MachineView(s)
        XCTAssertEqual(v.privacyOffer(s.sessions[0], people: s.people), true, "shared now: the item says Private")
        XCTAssertEqual(v.privacyOffer(s.sessions[1], people: s.people), false, "private now: the item says Shared with people")
        XCTAssertTrue(s.sessions[1].isPrivate)
        XCTAssertNil(v.privacyOffer(s.sessions[2], people: s.people), "not mine")
        XCTAssertNil(v.privacyOffer(s.sessions[0], people: nil), "a machine with no people has nobody to keep it from")
        let mineElsewhere = alone
        XCTAssertNil(MachineView(mineElsewhere).privacyOffer(mineElsewhere.sessions[1], people: []), "a session on my other machine")
    }

    func testAMachineThatRemovedMeOffersRemove() {
        let s = status("""
        {"connected": true, "sessions": [{"name": "shop", "working": false, "waiting": false}],
         "machines": [{"id": "hub", "name": "studio", "here": true, "online": true},
                      {"id": "m7c1e22", "name": "avi-box", "here": false, "online": false, "owner": "avi", "notice": "avi-box removed you"},
                      {"id": "n3f2a1", "name": "devbox", "here": false, "online": true, "notice": "devbox runs an older Pointe (0.9.0). Update it there."}]}
        """)
        let v = MachineView(s)
        XCTAssertEqual(v.removable("avi-box"), "avi-box removed you")
        XCTAssertNil(v.removable("devbox"), "my own machine with an older Pointe: the line shows, with no Remove")
        XCTAssertNil(v.removable("studio"))
        XCTAssertEqual(PeopleCopy.removeMachineAsk("avi-box", owner: "avi"),
                       "Remove avi-box? Its sessions leave your voice. To add it again, Avi must invite you again.")
    }

    // MARK: the Mine chip

    func testMineShowsOnlyWhenSomeSessionIsSomebodyElses() {
        XCTAssertFalse(MachineView(alone).hasOwners)
        XCTAssertNil(MachineView(alone).valid(MachineView.mineFilter), "Mine left over falls back to All")
        XCTAssertEqual(MachineView(alone).shown(MachineView.mineFilter).count, 2)
        let v = MachineView(shared())
        XCTAssertTrue(v.hasOwners)
        XCTAssertEqual(v.valid(MachineView.mineFilter), MachineView.mineFilter)
        XCTAssertNil(v.machine(MachineView.mineFilter), "Mine is not a machine")
        XCTAssertEqual(v.shown(MachineView.mineFilter).map(\.name), ["shop", "billing"])
        XCTAssertEqual(v.groups(MachineView.mineFilter).map(\.machine), ["studio"], "a machine with none of mine has no section")
        XCTAssertEqual(v.groups(nil).map(\.machine), ["studio", "avi-box"])
        XCTAssertEqual(v.groups("avi-box").map { $0.sessions.map(\.name) }, [["tide", "shop on avi-box"]])
        XCTAssertEqual(v.machine("avi-box"), "avi-box")
    }

    // MARK: alerts

    private func attention(_ session: String, _ id: String, title: String? = nil) -> API.Attention {
        try! JSONDecoder().decode(API.Attention.self, from: Data("""
        {"id": "permission:\(id)", "kind": "permission", "session": "\(session)", "request_id": "\(id)",
         "title": "\(title ?? "\(session) needs approval")", "body": "run the tests", "approvable": true}
        """.utf8))
    }

    func testAnAlertForASessionOnSomebodyElsesMachineNamesTheMachine() {
        let v = MachineView(shared(waiting: true))
        XCTAssertEqual(AlertPlan.note(attention("tide", "r1"), watchApprove: true, machines: v)?.title, "tide on avi-box needs approval")
        XCTAssertEqual(AlertPlan.note(attention("shop on avi-box", "r2"), watchApprove: true, machines: v)?.title,
                       "shop on avi-box needs approval", "named already: not twice")
        XCTAssertEqual(AlertPlan.note(attention("tide", "r1", title: "tide · avi-box needs approval"), watchApprove: true, machines: v)?.title,
                       "tide · avi-box needs approval", "the Mac's own title names it")
        XCTAssertEqual(AlertPlan.note(attention("shop", "r3"), watchApprove: true, machines: v)?.title, "shop needs approval", "my own")
        XCTAssertEqual(AlertPlan.note(attention("tide", "r1"), watchApprove: true, machines: v)?.session, "tide",
                       "the answer still goes to the session by its real name")
    }

    func testASessionIOnlyWatchRaisesNoApprovalAlert() {
        let v = MachineView(shared(grant: "watch", waiting: true))
        XCTAssertNil(AlertPlan.note(attention("tide", "r1"), watchApprove: true, machines: v))
        let r = AlertPlan.plan([attention("tide", "r1")], posted: [], delivered: [], appActive: false, enabled: true,
                               watchApprove: true, machines: v)
        XCTAssertEqual(r.post, [])
        XCTAssertNotNil(AlertPlan.note(attention("shop", "r3"), watchApprove: true, machines: v), "my own sessions still do")
    }

    func testTheCallScreenOffersNoApproveForASessionIOnlyWatch() throws {
        let source = try Repo.source("CallView.swift")
        XCTAssertTrue(source.contains("$0.waiting && $0.canApprove && !machines.watchOnly($0)"), "the request card's list")
        XCTAssertTrue(try Repo.source("MacShell.swift").contains("s.waiting, s.canApprove, !machines.watchOnly(s)"), "the Mac's menu and bubble")
    }

    // MARK: Add a machine

    private let line = "pointe://machine?v=1&host=avi-box.example&port=7443&fp=\(String(repeating: "ab", count: 32))&code=K7PQ-2MXD&name=avi-box"
    private let avis = API.MachineAdded(name: "avi-box", owner: "avi", grant: "send", vendors: ["Deepgram", "Gemini"])

    private final class Calls: @unchecked Sendable {
        var adds: [(line: String, name: String?)] = []
        var asked: [String] = []
    }

    private func adder(_ calls: Calls, owner: Bool = true, reply: @escaping (String?) throws -> API.MachineAdded) -> AddMachineModel {
        AddMachineModel(actions: AddMachineActions(ownerCheck: { calls.asked.append($0); return owner },
                                                   add: { line, name in calls.adds.append((line, name)); return try reply(name) }))
    }

    func testTheInviteLineIsReadFromALinkOrAWholeCommand() {
        XCTAssertEqual(MachineLine(line)?.line, line)
        XCTAssertEqual(MachineLine(line)?.host, "avi-box.example")
        XCTAssertEqual(MachineLine(line)?.name, "avi-box")
        XCTAssertEqual(MachineLine("  pointe machine add '\(line)'\n")?.line, line, "a pasted command: the link inside it")
        XCTAssertNil(MachineLine("pointe://pair?v=2&host=studio.example&port=7443&fp=ab&code=ABCD-EFGH"), "a phone's pairing code")
        XCTAssertNil(MachineLine("pointe://hub?v=1&host=h&port=1&fp=f&code=K7PQ-2MXD"), "an invite for a machine of your own")
        XCTAssertNil(MachineLine("pointe://machine?v=1&host=avi-box.example"), "no code")
        XCTAssertNil(MachineLine("hello"))
    }

    func testAScannedInviteIsAddedAfterFaceIDAndTheSheetGetsTheMachine() async {
        let calls = Calls()
        let model = adder(calls) { _ in self.avis }
        await model.scanned(line)
        XCTAssertEqual(calls.asked, [PeopleCopy.addReason], "Face ID, as a machine invite asks")
        XCTAssertEqual(calls.adds.map(\.line), [line])
        XCTAssertNil(calls.adds.first?.name, "no name unless the Mac asks for one")
        XCTAssertEqual(model.added, avis)
        XCTAssertNil(model.problem)
        XCTAssertFalse(model.working)
        XCTAssertEqual(PeopleCopy.added("avi-box", owner: "avi"), "Added avi-box, Avi's machine.")
    }

    func testWithoutFaceIDNothingIsSentAndTheLineStays() async {
        let calls = Calls()
        let model = adder(calls, owner: false) { _ in XCTFail("not sent"); return self.avis }
        await model.pasted(line)
        XCTAssertEqual(calls.adds.count, 0)
        XCTAssertNil(model.added)
        XCTAssertEqual(model.line, line)
        XCTAssertNil(model.problem, "they cancelled: they know why nothing happened")
    }

    func testARefusalShowsTheMacsSentenceAndKeepsTheLine() async {
        let calls = Calls()
        let model = adder(calls) { _ in throw API.Failure.status(403, "the code is wrong or was used") }
        await model.pasted(line)
        XCTAssertEqual(model.problem, "The code is wrong or was used.")
        XCTAssertEqual(model.line, line, "kept, to try again")
        XCTAssertFalse(model.needsName)
        XCTAssertNil(model.added)
        XCTAssertTrue(model.canAdd)
        await model.add()
        XCTAssertEqual(calls.adds.count, 2, "Add sends the kept line again")
    }

    func testANameIsAskedOnlyWhenTheMacSaysItIsTaken() async {
        let calls = Calls()
        let model = adder(calls) { name in
            guard let name else { throw API.Failure.status(409, "A machine called avi-box is already paired. Give the machine another name and add it again.") }
            return API.MachineAdded(name: name, owner: "avi", grant: "send", vendors: [])
        }
        XCTAssertFalse(model.needsName)
        await model.scanned(line)
        XCTAssertTrue(model.needsName)
        XCTAssertEqual(model.problem, "A machine called avi-box is already paired. Give the machine another name and add it again.")
        XCTAssertEqual(model.name, "avi-box", "the machine's own name, to change")
        model.name = "  "
        XCTAssertFalse(model.canAdd, "Call it needs a name")
        model.name = "avis laptop"
        await model.add()
        XCTAssertEqual(calls.adds.last?.name, "avis laptop")
        XCTAssertEqual(calls.adds.last?.line, line)
        XCTAssertEqual(model.added?.name, "avis laptop")
    }

    func testWhatIsNotAnInviteIsNeverSent() async {
        let calls = Calls()
        let model = adder(calls) { _ in XCTFail("not sent"); return self.avis }
        await model.scanned("pointe://pair?v=2&host=studio.example&port=7443&fp=ab&code=ABCD-EFGH")
        XCTAssertEqual(model.problem, PeopleCopy.notAnInvite)
        XCTAssertEqual(model.attempt, 1, "the camera reads again")
        XCTAssertEqual(model.line, "")
        await model.pasted("git push origin main")
        XCTAssertEqual(model.problem, PeopleCopy.nothingToPaste)
        await model.pasted(nil)
        model.line = "something typed"
        await model.add()
        XCTAssertEqual(model.problem, PeopleCopy.notAnInvite)
        XCTAssertEqual(calls.asked, [], "no Face ID for a line that is not an invite")
        XCTAssertEqual(calls.adds.count, 0)
    }

    func testAnInviteThatOpenedTheAppWaitsForAdd() async {
        let calls = Calls()
        let model = AddMachineModel(actions: AddMachineActions(ownerCheck: { calls.asked.append($0); return true },
                                                               add: { line, name in calls.adds.append((line, name)); return self.avis }),
                                    line: line, fromOutside: true)
        XCTAssertTrue(model.fromOutside)
        XCTAssertEqual(calls.adds.count, 0, "a link from outside sends nothing by itself")
        XCTAssertEqual(PeopleCopy.fromOutside("avi-box.example"),
                       "This invite opened Pointe from outside the app. It adds the machine at avi-box.example. Add it only if you asked for it.")
        await model.add()
        XCTAssertEqual(calls.asked.count, 1)
        XCTAssertEqual(model.added, avis)
    }

    #if os(iOS)
    func testOnlyAMachineInviteOnAPairedPhoneOpensAddAMachine() {
        XCTAssertEqual(PointeRoot.machineInvite(URL(string: line)!, paired: true), line)
        XCTAssertNil(PointeRoot.machineInvite(URL(string: line)!, paired: false), "no Mac to add it to: the pairing sheet")
        XCTAssertNil(PointeRoot.machineInvite(URL(string: "pointe://pair?v=2&host=evil.example&port=443&fp=ab&code=ABCD-EFGH")!, paired: true),
                     "a pairing link from outside still pairs nothing")
    }
    #endif

    // MARK: what the daemon builds (pointe/guests.py and pointe/machines.py on main)

    /// guests.py `status` and `session_status`, daemon.py's machines and `can_invite`, machines.py `disclosure`.
    func testTheStatusAsTheDaemonBuildsItDecodes() {
        let s = status("""
        {"connected": true, "can_invite": true, "account": "sam",
         "sessions": [{"name": "shop", "working": true, "waiting": false, "private": true,
                       "by": {"name": "dana", "since": 1794399880.5}}],
         "machines": [{"id": "hub", "name": "studio", "here": true, "online": true},
                      {"id": "m7c1e22", "name": "avi-box", "here": false, "online": false, "owner": "avi", "grant": "watch",
                       "notice": "avi-box removed you", "removed": true}],
         "people": [{"name": "dana", "grant": "send", "online": true, "since": null, "vendors": ["Soniox", "ElevenLabs"]},
                    {"name": "omer", "grant": "watch", "online": false, "since": 1794396400, "vendors": [],
                     "notice": "omer's voice runs an older Pointe (0.9.0)."}],
         "people_invite": {"code": "K7PQ-2MXD", "expires_in": 540, "wrong_codes": 0, "link": "pointe://machine?code=K7PQ-2MXD",
                           "svg": "<svg/>", "name": "noa", "grant": "watch"},
         "disclosure": {"machine": "avi-box", "vendors": ["Soniox", "ElevenLabs"]}}
        """)
        XCTAssertEqual(s.can_invite, true)
        XCTAssertEqual(s.account, "sam")
        XCTAssertEqual(s.sessions[0].by, API.By(name: "dana", since: 1794399880.5))
        XCTAssertEqual(s.machines?[1].removed, true)
        XCTAssertNil(s.people?[0].since, "linked: no last seen")
        XCTAssertEqual(s.people?[0].vendors, ["Soniox", "ElevenLabs"])
        XCTAssertEqual(s.people?[1].notice, "omer's voice runs an older Pointe (0.9.0).")
        XCTAssertEqual(s.people_invite?.link, "pointe://machine?code=K7PQ-2MXD")
        XCTAssertEqual(PeopleCopy.trust(account: s.account), "People you invite can make these agents run commands as sam. Keep a session to yourself with Private.")
        XCTAssertEqual(PeopleCopy.trust(account: nil), PeopleCopy.trust, "a Mac that does not say the account")
        XCTAssertEqual(PeopleCopy.disclosure(s.disclosure!, owner: MachineView(s).info("avi-box")?.owner),
                       "Your voice sends the transcripts of the sessions on avi-box, with credentials masked, to: Soniox, ElevenLabs. Avi sees this list next to your name.")
        let old = status(#"{"connected": true, "sessions": [], "machines": []}"#)
        XCTAssertNil(old.can_invite, "an older Mac: People stays hidden")
        XCTAssertNil(old.account)
    }

    func testPeopleShowsOnlyWhereTheMacWouldShowAnInvite() throws {
        XCTAssertTrue(try Repo.source("Settings.swift").contains("if people != nil, status?.can_invite == true {"))
    }

    func testRemovedIsReadFromTheFlagAndFromTheNoticeOnlyWithoutIt() {
        func view(_ more: String) -> MachineView {
            MachineView(status("""
            {"connected": true, "sessions": [], "machines": [{"id": "hub", "name": "studio", "here": true, "online": true},
              {"id": "m7c1e22", "name": "avi-box", "here": false, "owner": "avi"\(more)}]}
            """))
        }
        XCTAssertEqual(view(#", "online": false, "removed": true, "notice": "avi-box removed you""#).removable("avi-box"), "avi-box removed you")
        XCTAssertEqual(view(#", "online": false, "removed": true"#).removable("avi-box"), "avi-box removed you", "the flag alone is enough")
        XCTAssertNil(view(#", "online": false, "removed": false, "notice": "avi-box runs an older Pointe (0.9.0).""#).removable("avi-box"),
                     "the flag says no: an offline machine with something to say keeps its line and offers no Remove")
        XCTAssertEqual(view(#", "online": false, "notice": "avi-box removed you""#).removable("avi-box"), "avi-box removed you",
                       "a Mac before the flag: offline, somebody else's, with a notice")
    }

    /// guests.py: POST answers {code, link, svg, expires_in, name, grant}; GET adds `paired` (null, or who paired) and
    /// `ended`, and has a null code once nothing is out.
    func testTheInviteAnswersAsTheMachineBuildsThemDecode() throws {
        func invite(_ json: String) throws -> API.PeopleInvite { try JSONDecoder().decode(API.PeopleInvite.self, from: Data(json.utf8)) }
        let made = try invite(#"{"code": "K7PQ-2MXD", "link": "pointe://machine?code=K7PQ-2MXD", "svg": "<svg/>", "expires_in": 600, "name": "dana", "grant": "send"}"#)
        XCTAssertEqual(made.link, "pointe://machine?code=K7PQ-2MXD")
        XCTAssertEqual(made.expires_in, 600)
        let waiting = try invite(#"{"code": "K7PQ-2MXD", "expires_in": 512, "wrong_codes": 0, "link": "pointe://machine?code=K7PQ-2MXD", "svg": "<svg/>", "name": "dana", "grant": "send", "paired": null, "ended": null}"#)
        XCTAssertFalse(waiting.paired)
        XCTAssertNil(waiting.ended)
        let done = try invite(#"{"code": null, "expires_in": 0, "name": null, "paired": {"name": "dana", "address": "100.64.0.7", "network": "Tailscale", "grant": "send", "key_fp": "9a41", "vendors": ["Soniox"]}, "ended": null}"#)
        XCTAssertTrue(done.paired)
        XCTAssertEqual(done.pairedName, "dana")
        XCTAssertEqual(done.code, "")
    }

    func testANameIsNotAskedForARefusalThatIsNotAboutTheName() async {
        for said in ["This is your own machine: its sessions are already in your voice.",
                     "avi-box is already in your voice. To add it again, remove it first: pointe machine remove avi-box"] {
            let calls = Calls()
            let model = adder(calls) { _ in throw API.Failure.status(400, said) }  // machines.py: 409 is only a name problem
            await model.pasted(line)
            XCTAssertFalse(model.needsName, said)
            XCTAssertEqual(model.problem?.lowercased().hasPrefix(said.prefix(20).lowercased()), true, "the Mac's sentence, kept")
        }
    }

    func testAPersonsNoticeFollowsTheStatus() async {
        let desk = Desk(), model = people(desk)
        await model.load()
        var omer = API.Person(name: "omer", grant: "watch", online: false, vendors: ["Soniox"])
        omer.notice = "omer's voice runs an older Pointe (0.9.0)."
        await model.follow([API.Person(name: "dana"), omer])
        XCTAssertEqual(model.people[1].notice, "omer's voice runs an older Pointe (0.9.0).")
        XCTAssertEqual(model.people[1].vendors, ["Soniox"])
        await model.follow([API.Person(name: "dana"), API.Person(name: "omer")])
        XCTAssertNil(model.people[1].notice, "gone once their voice is updated")
    }

    // MARK: the disclosure

    func testTheDisclosureShowsOnceFromTheAnswerThenTheStatusUntilOK() {
        var gate = DisclosureGate()
        XCTAssertNil(gate.pending(alone))
        gate.machineAdded(avis)
        let first = gate.pending(alone)
        XCTAssertEqual(first, API.Disclosure(machine: "avi-box", vendors: ["Deepgram", "Gemini"]), "at once, before the next status")
        XCTAssertEqual(PeopleCopy.disclosure(first!, owner: "avi"),
                       "Your voice sends the transcripts of the sessions on avi-box, with credentials masked, to: Deepgram, Gemini. Avi sees this list next to your name.")
        XCTAssertEqual(gate.pending(shared())?.machine, "avi-box", "the status says the same")
        XCTAssertEqual(gate.dismiss(first!), "avi-box", "OK tells the Mac which machine")
        XCTAssertNil(gate.pending(shared()), "gone at the tap, before the Mac's next status drops it")
        XCTAssertNil(gate.pending(alone))
        XCTAssertEqual(PeopleCopy.disclosure(API.Disclosure(machine: "avi-box", vendors: [])),
                       "Your voice sends the transcripts of the sessions on avi-box to no outside service. Its owner sees this list next to your name.")
        XCTAssertEqual(PeopleCopy.list(["Deepgram", "Gemini", "ElevenLabs"]), "Deepgram, Gemini and ElevenLabs")
    }

    // MARK: People

    private final class Desk: @unchecked Sendable {
        var people = [API.Person(name: "dana", grant: "send", online: true, since: 1_794_398_500, vendors: ["Deepgram", "Gemini"]),
                      API.Person(name: "omer", grant: "watch", online: false, since: 1_794_396_400)]
        var invited: [(String, String)] = []
        var paired = false
        var ended: String?
        var cancelled = 0
        var grants: [(String, String)] = []
        var removed: [String] = []
        var asked: [String] = []
        var owner = true
        var refuse: API.Failure?
    }

    private func people(_ desk: Desk) -> PeopleModel {
        PeopleModel(actions: PeopleActions(
            ownerCheck: { desk.asked.append($0); return desk.owner },
            load: { desk.people },
            invite: { name, grant in
                if let refuse = desk.refuse { throw refuse }
                desk.invited.append((name, grant))
                return API.PeopleInvite(code: "K7PQ-2MXD", link: "pointe://machine?code=K7PQ-2MXD", expires_in: 600, name: name, grant: grant)
            },
            state: {
                if desk.paired, let (name, grant) = desk.invited.last {
                    desk.people.append(API.Person(name: name, grant: grant, online: true))
                    return API.PeopleInvite(code: "K7PQ-2MXD", name: name, grant: grant, paired: true)
                }
                return API.PeopleInvite(code: "K7PQ-2MXD", expires_in: 500, ended: desk.ended)
            },
            cancel: { desk.cancelled += 1 },
            grant: { name, grant in
                if let refuse = desk.refuse { throw refuse }
                desk.grants.append((name, grant))
            },
            remove: { name in
                if let refuse = desk.refuse { throw refuse }
                desk.removed.append(name); desk.people.removeAll { $0.name == name }
            }))
    }

    func testInvitingAPersonShowsTheLineAfterFaceIDAndClosesWhenTheyPair() async {
        let desk = Desk(), model = people(desk)
        await model.load()
        XCTAssertEqual(model.people.map(\.name), ["dana", "omer"])
        XCTAssertFalse(model.canInvite, "a name first")
        model.name = " noa "
        XCTAssertEqual(model.grant, "send", "Can talk to the sessions is the default")
        model.grant = "watch"
        let t0 = Date(timeIntervalSince1970: now)
        await model.makeInvite(now: t0)
        XCTAssertEqual(desk.asked, [PeopleCopy.inviteReason])
        XCTAssertEqual(desk.invited.first?.0, "noa")
        XCTAssertEqual(desk.invited.first?.1, "watch")
        XCTAssertEqual(model.invite?.link, "pointe://machine?code=K7PQ-2MXD")
        XCTAssertEqual(model.until, t0.addingTimeInterval(600))
        let waiting = await model.poll()
        XCTAssertFalse(waiting, "nobody paired yet: the line stays")
        XCTAssertNotNil(model.invite)
        desk.paired = true
        let closed = await model.poll()
        XCTAssertTrue(closed)
        XCTAssertNil(model.invite, "it closes by itself")
        XCTAssertEqual(model.people.map(\.name), ["dana", "omer", "noa"], "and the person is in the list")
        XCTAssertEqual(model.done, "Noa can reach this machine now.")
        XCTAssertEqual(model.name, "", "ready for the next one")
    }

    func testWithoutFaceIDNoInviteIsMade() async {
        let desk = Desk(), model = people(desk)
        desk.owner = false
        model.name = "noa"
        await model.makeInvite()
        XCTAssertEqual(desk.invited.count, 0)
        XCTAssertNil(model.invite)
    }

    func testATakenNameIsTheMachinesSentenceAndCancelWithdrawsTheLine() async {
        let desk = Desk(), model = people(desk)
        desk.refuse = .status(409, "somebody called dana is already invited")
        model.name = "dana"
        await model.makeInvite()
        XCTAssertEqual(model.problem, "Somebody called dana is already invited.")
        XCTAssertEqual(model.name, "dana", "the name stays, to change")
        desk.refuse = nil
        model.name = "noa"
        await model.makeInvite()
        XCTAssertNil(model.problem)
        await model.cancel()
        XCTAssertEqual(desk.cancelled, 1)
        XCTAssertNil(model.invite)
    }

    func testAnInviteThatEndedEarlySaysWhy() async {
        let desk = Desk(), model = people(desk)
        model.name = "noa"
        await model.makeInvite()
        desk.ended = "the invite was cancelled after 20 wrong codes"
        let closed = await model.poll()
        XCTAssertTrue(closed)
        XCTAssertNil(model.invite)
        XCTAssertEqual(model.problem, "The invite was cancelled after 20 wrong codes.")
    }

    func testAnInviteMadeOnThePageIsShownNotReplaced() async {
        let desk = Desk(), model = people(desk)
        await model.makeInvite(waiting: API.PeopleInvite(code: "K7PQ-2MXD", expires_in: 500))
        XCTAssertEqual(desk.asked.count, 1, "still behind Face ID")
        XCTAssertEqual(desk.invited.count, 0, "no second invite")
        XCTAssertEqual(model.invite?.code, "K7PQ-2MXD")
    }

    func testAGrantChangeMovesAtTheTapAndGoesBackWhenRefused() async {
        let desk = Desk(), model = people(desk)
        await model.load()
        await model.setGrant("dana", "watch")
        XCTAssertEqual(desk.grants.first?.0, "dana")
        XCTAssertEqual(desk.grants.first?.1, "watch")
        XCTAssertEqual(model.people[0].grant, "watch")
        await model.setGrant("dana", "watch")
        XCTAssertEqual(desk.grants.count, 1, "the same grant sends nothing")
        desk.refuse = .status(404, "nobody called dana is invited")
        await model.setGrant("dana", "send")
        XCTAssertEqual(model.people[0].grant, "watch", "refused: as it was")
        XCTAssertEqual(model.problem, "Nobody called dana is invited.")
    }

    func testRemovingAPersonNeedsFaceID() async {
        let desk = Desk(), model = people(desk)
        await model.load()
        desk.owner = false
        await model.remove("omer")
        XCTAssertEqual(desk.removed, [], "nothing removed before Face ID")
        XCTAssertEqual(model.people.count, 2)
        desk.owner = true
        await model.remove("omer")
        XCTAssertEqual(desk.asked.last, "Remove a person: Omer")
        XCTAssertEqual(desk.removed, ["omer"])
        XCTAssertEqual(model.people.map(\.name), ["dana"])
        XCTAssertEqual(model.done, "Omer is removed.")
        XCTAssertEqual(PeopleCopy.removeAsk("omer"), "Remove Omer? Their voice loses this machine's sessions now. To bring them back, invite them again.")
    }

    func testTheRowsFollowTheStatusAndANewNameReadsTheListAgain() async {
        let desk = Desk(), model = people(desk)
        await model.load()
        await model.follow([API.Person(name: "dana", grant: "watch", online: false, since: now), API.Person(name: "omer", grant: "watch", online: true)])
        XCTAssertEqual(model.people[0].grant, "watch")
        XCTAssertEqual(model.people[0].online, false)
        XCTAssertEqual(model.people[0].vendors, ["Deepgram", "Gemini"], "the list's own fields stay")
        XCTAssertEqual(model.people[1].online, true)
        desk.people.append(API.Person(name: "noa", grant: "send", online: true))
        await model.follow([API.Person(name: "dana"), API.Person(name: "omer"), API.Person(name: "noa")])
        XCTAssertEqual(model.people.map(\.name), ["dana", "omer", "noa"])
    }

    func testAPersonsRowSaysTheGrantTheStateAndTheServices() {
        let today = Date(timeIntervalSince1970: now)
        let dana = API.Person(name: "dana", grant: "send", online: true, since: now - 1500, vendors: ["Deepgram", "Gemini"])
        let omer = API.Person(name: "omer", grant: "watch", online: false, since: now - 3600)
        XCTAssertEqual(PeopleCopy.facts(dana, now: today), "can talk · online")
        XCTAssertEqual(PeopleCopy.facts(omer, now: today), "watch only · last seen \(MachinesCopy.since(now - 3600, now: today))")
        XCTAssertEqual(PeopleCopy.facts(API.Person(name: "noa")), "can talk · not linked yet")
        XCTAssertEqual(PeopleCopy.services(dana), "Their voice uses: Deepgram, Gemini")
        XCTAssertNil(PeopleCopy.services(omer))
        XCTAssertEqual(MachinesCopy.peopleCount(shared().people), "2")
        XCTAssertEqual(MachinesCopy.peopleCount(nil), "")
    }

    func testAMacWithoutTheRoutesSaysToUpdate() {
        XCTAssertEqual(PeopleCopy.refusal(API.Failure.status(404, "HTTP 404")), PeopleCopy.tooOld)
        XCTAssertEqual(PeopleCopy.refusal(API.Failure.status(500, "HTTP 500")), "The Mac did not do it.")
        XCTAssertEqual(PeopleCopy.refusal(URLError(.timedOut)), PeopleCopy.noAnswer)
    }

    // MARK: what the app sends (the contract's routes)

    private func api(_ code: Int, _ reply: String) -> API {
        HubStub.reply = (code, reply); HubStub.bodies = []
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [HubStub.self]
        return API(pairing: Demo.pairing, session: URLSession(configuration: config))
    }

    private func sent() -> (path: String?, body: [String: Any]?) {
        (HubStub.bodies.last?["path"] as? String, HubStub.bodies.last?["body"] as? [String: Any])
    }

    func testEachCallSendsWhatTheContractSays() async throws {
        let added = try await api(200, #"{"name": "avi-box", "owner": "avi", "grant": "send", "vendors": ["Deepgram"]}"#).addMachine(line: line)
        XCTAssertEqual(added, API.MachineAdded(name: "avi-box", owner: "avi", grant: "send", vendors: ["Deepgram"]))
        XCTAssertEqual(sent().path, "/voice/machines/add")
        XCTAssertEqual(sent().body?["line"] as? String, line)
        XCTAssertNil(sent().body?["name"], "no name unless one was asked for")
        _ = try await api(200, #"{"name": "avis laptop"}"#).addMachine(line: line, name: "avis laptop")
        XCTAssertEqual(sent().body?["name"] as? String, "avis laptop")
        try await api(200, #"{"ok": true}"#).disclosureSeen("avi-box")
        XCTAssertEqual(sent().path, "/voice/machines/add")
        XCTAssertEqual(sent().body?["seen"] as? String, "avi-box")
        XCTAssertNil(sent().body?["line"])

        let invite = try await api(200, #"{"code": "K7PQ-2MXD", "link": "pointe://machine?code=K7PQ-2MXD", "expires_in": 600, "name": "dana", "grant": "watch"}"#)
            .invitePerson(name: "dana", grant: "watch")
        XCTAssertEqual(invite.link, "pointe://machine?code=K7PQ-2MXD")
        XCTAssertEqual(sent().path, "/voice/people/invite")
        XCTAssertEqual(sent().body?["name"] as? String, "dana")
        XCTAssertEqual(sent().body?["grant"] as? String, "watch")
        try await api(200, #"{"ok": true}"#).cancelPersonInvite()
        XCTAssertEqual(sent().body?["cancel"] as? Bool, true)
        let state = try await api(200, #"{"code": "K7PQ-2MXD", "expires_in": 410, "name": "dana", "paired": true}"#).personInviteState()
        XCTAssertTrue(state.paired)
        XCTAssertEqual(sent().path, "/voice/people/invite")

        let list = try await api(200, #"{"people": [{"id": "p1", "name": "dana", "grant": "send", "online": true, "vendors": ["Deepgram"]}]}"#).people()
        XCTAssertEqual(list.map(\.name), ["dana"])
        XCTAssertEqual(sent().path, "/voice/people")
        try await api(200, #"{"ok": true}"#).setGrant("dana", "watch")
        XCTAssertEqual(sent().path, "/voice/people/grant")
        XCTAssertEqual(sent().body?["grant"] as? String, "watch")
        try await api(200, #"{"ok": true}"#).removePerson("dana")
        XCTAssertEqual(sent().path, "/voice/people/remove")
        XCTAssertEqual(sent().body?["name"] as? String, "dana")
        try await api(200, #"{"ok": true, "private": true}"#).share("billing", private: true)
        XCTAssertEqual(sent().path, "/voice/share")
        XCTAssertEqual(sent().body?["session"] as? String, "billing")
        XCTAssertEqual(sent().body?["private"] as? Bool, true)
    }

    func testARefusalIsTheMachinesOneSentenceAsJSONOrAsText() async {
        do { _ = try await api(409, "A machine called avi-box is already paired. Give the machine another name and add it again.").addMachine(line: line); XCTFail() } catch {
            XCTAssertEqual(PeopleCopy.refusal(error), "A machine called avi-box is already paired. Give the machine another name and add it again.", "plain text, as machines.py answers")
        }
        do { try await api(404, "nobody called dana is invited").removePerson("dana"); XCTFail() } catch {
            XCTAssertEqual(PeopleCopy.refusal(error), "Nobody called dana is invited.")
        }
        do { _ = try await api(404, "").people(); XCTFail() } catch {
            XCTAssertEqual(PeopleCopy.refusal(error), PeopleCopy.tooOld, "an older Pointe has no such route")
        }
    }

    // MARK: the demo screens

    func testEveryPeopleDemoScreenDecodesWithItsFields() throws {
        for screen in [Demo.Screen.people, .peopleWatch, .peopleRemoved, .peopleAdded] {
            let s = try XCTUnwrap(Demo.make(screen), "\(screen)").status
            XCTAssertEqual(s.people?.map(\.name), ["dana", "omer"], "\(screen)")
            XCTAssertEqual(s.machines?.last?.owner, "avi", "\(screen)")
        }
        let people = try XCTUnwrap(Demo.make(.people)).status
        XCTAssertEqual(MachineView(people).ownerTag(people.sessions[2]), "Avi's")
        XCTAssertEqual(MachineView(people).usedBy(people.sessions[2]), "Dana is using it")
        XCTAssertTrue(people.sessions[1].isPrivate)
        let watch = try XCTUnwrap(Demo.make(.peopleWatch)).status
        XCTAssertTrue(watch.sessions[2].waiting && MachineView(watch).watchOnly(watch.sessions[2]))
        let removed = try XCTUnwrap(Demo.make(.peopleRemoved)).status
        XCTAssertEqual(MachineView(removed).removable("avi-box"), "avi-box removed you")
        XCTAssertEqual(try XCTUnwrap(Demo.make(.peopleAdded)).status.disclosure?.machine, "avi-box")
        XCTAssertEqual(Demo.people(people).map(\.vendors), [["Deepgram", "Gemini"], ["Soniox", "Gemini"]])
    }

    func testTheDemoAddsAvisMachineAndRefusesANameItHas() throws {
        let before = try XCTUnwrap(Demo.make(.machines)).status
        let (added, after) = try Demo.addMachine(Demo.machineLine, name: nil, status: before)
        XCTAssertEqual(added.name, "avi-box")
        XCTAssertEqual(after?.machines?.last?.owner, "avi")
        XCTAssertEqual(after?.sessions.last?.owner, "avi")
        XCTAssertThrowsError(try Demo.addMachine(Demo.machineLine, name: nil, status: after)) { error in
            guard case API.Failure.status(409, _) = error else { return XCTFail("\(error)") }
        }
        XCTAssertEqual(try Demo.addMachine(Demo.machineLine, name: "avis laptop", status: after).0.name, "avis laptop")
    }

    // MARK: the words

    func testTheScreensSayMachinesAndPeopleNeverHubNodeOrGuest() throws {
        let said = [PeopleCopy.trust, PeopleCopy.lineHelp, PeopleCopy.scanHelp, PeopleCopy.lineHelpMac, PeopleCopy.notAnInvite,
                    PeopleCopy.none, PeopleCopy.tooOld, MachinesCopy.help, PeopleCopy.removeAsk("dana"),
                    PeopleCopy.removeMachineAsk("avi-box", owner: "avi"), PeopleCopy.fromOutside("avi-box.example")]
        for line in said {
            for word in ["hub", "node", "guest", "—"] {
                XCTAssertFalse(line.lowercased().split(whereSeparator: { !$0.isLetter && $0 != "—" }).contains(Substring(word)), "\(word) in: \(line)")
            }
        }
        XCTAssertEqual(PeopleCopy.trust, "People you invite can make these agents run commands as this machine's account. Keep a session to yourself with Private.")
    }
}
