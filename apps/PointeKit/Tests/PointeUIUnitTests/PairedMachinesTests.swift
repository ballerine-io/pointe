import XCTest
@testable import PointeUI
import PointeKit

/// A phone that holds several machines (docs/design/multi-machine-clients.md): one entry per machine whatever was
/// stored before, a choice of where calls go, adding beside the others behind Face ID, and one alert per thing across
/// machines.
@MainActor
final class PairedMachinesTests: XCTestCase {
    final class Vault: PairingVault, @unchecked Sendable {
        var stored: [String: Pairing] = [:]
        var failWrites = false
        func rows() -> [VaultRow] { stored.map { VaultRow(account: $0.key, pairing: $0.value, ref: nil) } }
        func put(_ pairing: Pairing, account: String) -> Bool {
            guard !failWrites else { return false }
            stored[account] = pairing
            return true
        }
        func delete(_ row: VaultRow) { stored[row.account] = nil }
    }

    final class Choice: MachineChoice, @unchecked Sendable {
        var current: String?
        var order: [String] = []
    }

    struct Keeper: PairingKeeping {
        let machines: PairedMachines
        func load() -> Pairing? { machines.current }
        func save(_ pairing: Pairing) { machines.only(pairing) }
        func forget() { machines.removeAll() }
        func all() -> [Pairing] { machines.ordered }
        func add(_ pairing: Pairing) { machines.add(pairing) }
        func remove(_ pairing: Pairing) { machines.remove(pairing) }
        func select(_ pairing: Pairing) { machines.select(pairing) }
    }

    private let key = String(repeating: "k", count: 43)
    private func fp(_ c: Character) -> String { String(repeating: c, count: 64) }
    private lazy var mac = Pairing(host: "studio.example.ts.net", port: 7443, fingerprint: fp("a"), key: key, id: "m1", name: "studio", via: "tailscale")
    private lazy var kite = Pairing(host: "kite.example.internal", port: 7443, fingerprint: fp("b"), key: key, id: "m2", name: "kite", via: "host")
    private lazy var avi = Pairing(host: "avi-box.example.internal", port: 7443, fingerprint: fp("c"), key: key, id: "m3", name: "avi-box", via: "host")

    private func list() -> (PairedMachines, Vault, Choice) {
        let vault = Vault(), choice = Choice()
        return (PairedMachines(vault: vault, choice: choice), vault, choice)
    }

    // MARK: the list

    func testTheItemSavedBeforeSeveralMachinesIsOneMachineAndIsReplacedOnlyOnceItsNewEntryIsWritten() {
        let (machines, vault, _) = list()
        let old = Pairing(host: mac.host, port: 7443, fingerprint: mac.fingerprint, key: key)  // no id: saved by an older app
        vault.stored[""] = old
        XCTAssertEqual(machines.ordered, [old])
        XCTAssertEqual(machines.current, old, "the one machine it had is where calls go")
        vault.failWrites = true
        machines.add(mac)
        XCTAssertEqual(vault.stored[""], old, "a write that fails leaves the old pairing in place")
        vault.failWrites = false
        machines.add(mac)
        XCTAssertNil(vault.stored[""])
        XCTAssertEqual(machines.ordered, [mac])
    }

    func testAddingKeepsTheOthersAndTheSameMachinePairedAgainReplacesItsOwnEntry() {
        let (machines, vault, choice) = list()
        machines.add(mac)
        machines.add(kite)
        machines.add(avi)
        XCTAssertEqual(machines.ordered.map(\.label), ["studio", "kite", "avi-box"])
        XCTAssertEqual(machines.current, avi, "the one just added is where calls go")
        let kiteAgain = Pairing(host: "100.64.0.9", port: 7443, fingerprint: kite.fingerprint, key: String(repeating: "n", count: 43), id: "m2", name: "kite", via: "tailscale")
        machines.select(mac)
        machines.add(kiteAgain, current: false)
        XCTAssertEqual(machines.ordered.map(\.host), ["studio.example.ts.net", "100.64.0.9", "avi-box.example.internal"], "in its place")
        XCTAssertEqual(vault.stored.count, 3)
        XCTAssertEqual(choice.current, mac.storeKey)
    }

    func testRemovingOneKeepsTheRestAndMovesCallsToTheFirstLeft() {
        let (machines, _, _) = list()
        machines.add(mac)
        machines.add(kite)
        machines.remove(kite)
        XCTAssertEqual(machines.ordered, [mac])
        XCTAssertEqual(machines.current, mac)
        machines.removeAll()
        XCTAssertNil(machines.current)
    }

    func testOneMachineReplacesEveryOtherAsBefore() {
        let (machines, vault, _) = list()
        machines.add(mac)
        machines.add(kite)
        machines.only(avi)
        XCTAssertEqual(machines.ordered, [avi])
        XCTAssertEqual(vault.stored.count, 1)
    }

    // MARK: the flow

    private struct Refused: Error {}

    private func flow(_ keeper: Keeper, several: Bool, owner: Bool = true, asked: @escaping () -> Void = {},
                      redeem: @escaping (PairingInvite) async throws -> (Pairing, String) = { _ in throw Refused() }) -> PairingFlow {
        PairingFlow(keeper: keeper, ownerCheck: { _ in asked(); return owner }, redeem: redeem, answers: { _ in nil }, several: { several })
    }

    func testWithSeveralMachinesAScanAddsBesideTheMacAfterFaceIDAndCallsGoToTheNewOne() async {
        let (machines, _, _) = list()
        machines.add(mac)
        var asked = 0
        let flow = flow(Keeper(machines: machines), several: true, asked: { asked += 1 }, redeem: { _ in (self.kite, "kite") })
        flow.scanned("pointe://pair?v=2&host=kite.example.internal&port=7443&fp=\(fp("b"))&code=ABCD-EFGH&via=host")
        XCTAssertEqual(flow.offer?.title, "Add kite.example.internal to this phone?")
        XCTAssertEqual(flow.offer?.action, "Add")
        XCTAssertTrue(flow.offer?.message.contains("The machines you have stay") == true)
        await flow.confirm()
        XCTAssertEqual(asked, 1, "a second machine needs Face ID")
        XCTAssertEqual(flow.pairings.map(\.label), ["studio", "kite"])
        XCTAssertEqual(flow.pairing, kite)
        XCTAssertEqual(flow.note?.text, "Added kite.")
    }

    func testFaceIDRefusedAddsNothing() async {
        let (machines, _, _) = list()
        machines.add(mac)
        let flow = flow(Keeper(machines: machines), several: true, owner: false, redeem: { _ in XCTFail("not redeemed"); throw Refused() })
        flow.scanned("pointe://pair?v=2&host=kite.example.internal&port=7443&fp=\(fp("b"))&code=ABCD-EFGH")
        await flow.confirm()
        XCTAssertEqual(flow.pairings, [mac])
    }

    func testWithTheFlagOffAScanStillReplacesTheMac() async {
        let (machines, _, _) = list()
        machines.add(mac)
        let flow = flow(Keeper(machines: machines), several: false, redeem: { _ in (self.kite, "kite") })
        flow.scanned("pointe://pair?v=2&host=kite.example.internal&port=7443&fp=\(fp("b"))&code=ABCD-EFGH")
        XCTAssertEqual(flow.offer?.title, "Replace your Mac studio.example.ts.net with kite.example.internal?")
        await flow.confirm()
        XCTAssertEqual(flow.pairings, [kite])
    }

    func testATapSelectsAMachineAndItsStatusNamesItWithoutMovingTheCall() {
        let (machines, _, _) = list()
        machines.add(mac)
        machines.add(Pairing(host: kite.host, port: 7443, fingerprint: kite.fingerprint, key: key))
        let flow = flow(Keeper(machines: machines), several: true)
        flow.select(mac)
        XCTAssertEqual(flow.pairing, mac)
        flow.learned(flow.pairings[1], id: "m2", name: "kite")
        XCTAssertEqual(flow.pairings.map(\.label), ["studio", "kite"])
        XCTAssertEqual(flow.pairing, mac, "learning a name is not a switch")
        flow.remove(mac)
        XCTAssertEqual(flow.pairing?.label, "kite")
    }

    // MARK: lines and answers

    func testALineNamesItsRouteAndTheAnswerTheMachine() {
        let invite = PairingInvite(link: "pointe://pair?v=2&host=kite.example.internal&port=7443&fp=\(fp("b"))&code=ABCD-EFGH&via=host")
        XCTAssertEqual(invite?.via, "host")
        XCTAssertNil(PairingInvite(link: "pointe://pair?v=2&host=k.example&port=7443&fp=\(fp("b"))&code=ABCD-EFGH&via=carrier-pigeon")?.via)
        let p = invite?.pairing(from: ["key": key, "id": "a3f9c2d1", "name": "kite", "mac": "kite"])
        XCTAssertEqual(p?.id, "a3f9c2d1")
        XCTAssertEqual(p?.label, "kite")
        XCTAssertEqual(p?.via, "host")
        XCTAssertNil(invite?.pairing(from: ["key": key, "id": "../../etc"])?.id, "an id is a plain word or nothing")
        XCTAssertEqual(MachineCopy.route("host"), "Twingate or VPN")
    }

    func testAPairingSavedByAnOlderAppStillDecodes() throws {
        let old = try JSONEncoder().encode(["host": "studio.example.ts.net", "port": "7443", "fingerprint": fp("a"), "key": key])
        let fixed = String(data: old, encoding: .utf8)!.replacingOccurrences(of: "\"7443\"", with: "7443")
        let p = try JSONDecoder().decode(Pairing.self, from: Data(fixed.utf8))
        XCTAssertNil(p.id)
        XCTAssertEqual(p.storeKey, "fp:\(fp("a"))")
    }

    // MARK: alerts across machines

    private func attention(_ id: String, origin: String?, session: String = "shop", title: String = "shop needs approval") -> API.Attention {
        API.Attention(id: id, kind: "permission", text: nil, session: session, request_id: "r1", title: title, body: "run: npm test",
                      approvable: true, quiet: false, origin: origin)
    }

    func testOneMachineKeepsItsIds() {
        let items = [attention("perm:s1:r1", origin: "m2/s1")]
        XCTAssertEqual(AlertMerge.merge([.init(key: "id:m2", name: "kite", machineId: "m2", items: items)]), items)
    }

    func testAPromptTwoMachinesListIsOneAlertAnsweredThroughTheMachineItRunsOn() {
        let viaMac = attention("perm:n2-s1:r1", origin: "m2/s1", session: "shop kite")
        let onKite = attention("perm:s1:r1", origin: "m2/s1")
        let merged = AlertMerge.merge([.init(key: "id:m1", name: "studio", machineId: "m1", items: [viaMac]),
                                      .init(key: "id:m2", name: "kite", machineId: "m2", items: [onKite])])
        XCTAssertEqual(merged.count, 1)
        XCTAssertEqual(merged[0].via, "id:m2", "kite runs it: the answer goes there")
        XCTAssertEqual(merged[0].session, "shop", "with kite's name for it")
        XCTAssertEqual(merged[0].title, "shop needs approval · kite")
    }

    func testTwoMachinesWithTheSameSessionNameAreTwoAlerts() {
        let merged = AlertMerge.merge([.init(key: "id:m1", name: "studio", machineId: "m1", items: [attention("perm:s1:r1", origin: "m1/s1")]),
                                      .init(key: "id:m2", name: "kite", machineId: "m2", items: [attention("perm:s1:r1", origin: "m2/s1")])])
        XCTAssertEqual(merged.count, 2)
        XCTAssertEqual(Set(merged.map(\.via)), ["id:m1", "id:m2"])
    }

    func testAnOlderMachineWithNoOriginIsKeptApartByItsPairing() {
        let merged = AlertMerge.merge([.init(key: "id:m1", name: "studio", machineId: nil, items: [attention("perm:s1:r1", origin: nil)]),
                                      .init(key: "id:m2", name: "kite", machineId: nil, items: [attention("perm:s1:r1", origin: nil)])])
        XCTAssertEqual(merged.map(\.id), ["id:m1|perm:s1:r1", "id:m2|perm:s1:r1"])
    }

    func testAnAlertFromAnotherMachineGoesBackToItAndIsApprovableOnlyAsThatMachineSays() {
        var a = attention("perm:s1:r1", origin: "m2/s1")
        a.via = "id:m2"
        let off = AlertPlan.plan([a], posted: [], delivered: [], appActive: false, enabled: true, watchApprove: true, current: "id:m1")
        XCTAssertEqual(off.post.first?.category, AlertPlan.denyCategory, "the current machine's setting is not kite's")
        XCTAssertEqual(off.post.first?.machine, "id:m2")
        let on = AlertPlan.plan([a], posted: [], delivered: [], appActive: false, enabled: true, watchApprove: false, current: "id:m1",
                                watchApproveBy: ["id:m2": true])
        XCTAssertEqual(on.post.first?.category, AlertPlan.approveCategory)
        XCTAssertEqual(AlertAnswer.decision(action: AlertAnswer.approve, userInfo: ["session": "shop", "request_id": "r1", "machine": "id:m2"])?.machine, "id:m2")
    }

    // MARK: "call kite"

    func testTheHelloListsTheMachinesAndAHandoffNamesWhereToDial() throws {
        let hello = Wire.hello(device: "iPhone", machines: [["id": "m2", "name": "kite"]])
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(hello.utf8)) as? [String: Any])
        XCTAssertEqual(body["machines"] as? [[String: String]], [["id": "m2", "name": "kite"]])
        XCTAssertNil((try JSONSerialization.jsonObject(with: Data(Wire.hello(device: "iPhone").utf8)) as? [String: Any])?["machines"],
                     "one machine: the hello is as before")
        XCTAssertEqual(Call.handoff(["type": "handoff", "machine": ["id": "m2", "name": "kite"]]), "m2")
        XCTAssertEqual(Call.handoff(["type": "handoff", "machine": ["id": "", "name": "kite"]]), "kite")
        XCTAssertNil(Call.handoff(["type": "reading", "on": true]))
    }

    // MARK: routes

    func testAMachineLearnsItsOtherRoutesAndTriesThemInOrderNeverSSHOnThePhone() {
        var p = kite
        p = p.learning([.init(kind: "host", host: "kite.example.internal", port: 7443), .init(kind: "wifi", host: "192.168.1.20", port: 7443),
                        .init(kind: "ssh", host: "alon@kite.example.com", port: 7443), .init(kind: "carrier", host: "x", port: 1)])
        XCTAssertEqual(p.allRoutes.map(\.kind), ["host", "wifi", "ssh"], "its own route first, once; an unknown kind is dropped")
        XCTAssertEqual(RouteOrder.alternatives(p, ssh: false).map(\.host), ["192.168.1.20"])
        XCTAssertEqual(RouteOrder.alternatives(p, ssh: true).map(\.kind), ["wifi", "ssh"])
        let moved = p.using(.init(kind: "wifi", host: "192.168.1.20", port: 7443))
        XCTAssertEqual(moved.host, "192.168.1.20")
        XCTAssertEqual(moved.via, "wifi")
        XCTAssertEqual(moved.fingerprint, p.fingerprint, "every route ends at the same pinned certificate")
        XCTAssertEqual(moved.key, p.key)
        XCTAssertEqual(moved.allRoutes.count, 3, "the route it left stays known")
        XCTAssertEqual(MachineCopy.route("public"), "Public address")
        XCTAssertEqual(MachineCopy.route("ssh"), "SSH tunnel")
    }

    func testTheFlowKeepsLearntRoutesAndMovesAMachineToOneThatAnswersWithoutMovingTheCall() {
        let (machines, _, _) = list()
        machines.add(mac)
        machines.add(kite)
        let flow = flow(Keeper(machines: machines), several: true)
        flow.select(mac)
        flow.learned(kite, routes: [.init(kind: "wifi", host: "192.168.1.20", port: 7443)])
        XCTAssertEqual(flow.pairings[1].allRoutes.count, 2)
        flow.reroute(flow.pairings[1], to: .init(kind: "wifi", host: "192.168.1.20", port: 7443))
        XCTAssertEqual(flow.pairings[1].host, "192.168.1.20")
        XCTAssertEqual(flow.pairing, mac)
    }
}
