import SwiftUI

// Demo screens for people and machines (docs/design/people-and-machines.md): the fields as the contract defines them.
// Every name is made up: avi invited this voice to avi-box, and dana and omer are invited to studio.

extension Demo {
    /// `people`: studio with two people, and Avi's machine with a send grant. `peopleWatch`: the same with a watch grant
    /// and a prompt on Avi's session, which is his to answer. `peopleRemoved`: Avi removed this voice. `peopleAdded`:
    /// the one-time line after avi-box was added.
    static func peopleJSON(_ screen: Screen, now: Double = Date().timeIntervalSince1970) -> String {
        let watch = screen == .peopleWatch, removed = screen == .peopleRemoved
        let caps = #"{"approvals": true, "side_questions": false}"#
        let request = #"Bash: Run the tests\n{\"command\": \"uv run pytest -q\"}"#
        let theirs = removed ? "" : """
        ,
         {"name": "tide", "working": true, "waiting": \(watch), "needs": null, "machine": "avi-box", "online": true, "owner": "avi",
          "capabilities": \(caps), "request": \(watch ? "\"\(request)\"" : "null"), "request_id": \(watch ? "\"r-avi-1\"" : "null"),
          "by": {"name": "dana", "since": \(now - 120)}},
         {"name": "shop on avi-box", "working": false, "waiting": false, "needs": null, "machine": "avi-box", "online": true,
          "owner": "avi", "capabilities": \(caps)}
        """
        let aviBox = removed
            ? #"{"id": "m7c1e22", "name": "avi-box", "here": false, "os": "linux", "online": false, "since": \#(now - 900), "sessions": 0, "need": 0, "owner": "avi", "grant": "send", "notice": "avi-box removed you"}"#
            : #"{"id": "m7c1e22", "name": "avi-box", "here": false, "os": "linux", "online": true, "sessions": 2, "need": 0, "rtt_ms": 31, "key_fp": "7c1e22b04d9a6f13", "owner": "avi", "grant": "\#(watch ? "watch" : "send")"}"#
        let disclosure = screen == .peopleAdded ? #""disclosure": {"machine": "avi-box", "vendors": ["Deepgram", "Gemini"]},"# : ""
        return """
        {"active": "shop", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
         "sessions": [
         {"name": "shop", "working": true, "waiting": false, "needs": null, "machine": "studio", "online": true},
         {"name": "billing", "working": false, "waiting": false, "needs": null, "machine": "studio", "online": true, "private": true}\(theirs)],
         "machines": [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true, "sessions": 2, "need": 0},
                      \(aviBox)],
         "people": [{"name": "dana", "grant": "send", "online": true, "since": \(now - 1500)},
                    {"name": "omer", "grant": "watch", "online": false, "since": \(now - 3600)}],
         \(disclosure)
         "invite": null,
         "talk": [{"id": 1, "who": "user", "text": "what's going on everywhere", "typed": false, "corrected": false},
                  {"id": 2, "who": "assistant", "text": "On studio, shop is running its tests. On avi-box, tide is working on Dana's request."}]}
        """
    }

    /// The People list as `GET /voice/people` answers it: the status's people, with the services each voice uses.
    static func people(_ status: API.Status?) -> [API.Person] {
        let vendors = ["dana": ["Deepgram", "Gemini"], "omer": ["Soniox", "Gemini"]]
        return (status?.people ?? []).map { p in
            var p = p
            p.vendors = vendors[p.name] ?? ["Deepgram", "Gemini"]
            return p
        }
    }

    static let personInviteLink = "pointe://machine?v=1&host=demo.invalid&port=7443&fp=\(String(repeating: "0", count: 64))&code=K7PQ-2MXD&name=studio"
    /// What a demo's Add a machine takes: the line Avi would send.
    static let machineLine = "pointe://machine?v=1&host=avi-box.invalid&port=7443&fp=\(String(repeating: "0", count: 64))&code=M4RT-9WXZ&name=avi-box"

    /// Add a machine in a demo: the machine joins the list as Avi's, with one session. A name this voice already has is
    /// refused as the Mac refuses it (409), so "Call it" shows.
    static func addMachine(_ line: String, name: String?, status: API.Status?) throws -> (API.MachineAdded, API.Status?) {
        guard let invite = MachineLine(line) else { throw API.Failure.status(400, "that is not a machine invite") }
        let called = name ?? invite.name ?? "avi-box"
        if (status?.machines ?? []).contains(where: { $0.name == called }) {
            throw API.Failure.status(409, "a machine called \(called) is already on your voice: give this one another name")
        }
        var status = status
        let machine = #"{"id": "m-demo", "name": "\#(called)", "here": false, "os": "linux", "online": true, "sessions": 1, "need": 0, "rtt_ms": 31, "owner": "avi", "grant": "send"}"#
        let session = #"{"name": "tide", "working": true, "waiting": false, "needs": null, "machine": "\#(called)", "online": true, "owner": "avi"}"#
        if let m = try? JSONDecoder().decode(API.Machine.self, from: Data(machine.utf8)) {
            let before = status?.machines ?? []
            status?.machines = before + [m]
        }
        let known = status?.sessions.map(\.name) ?? []
        if let s = try? JSONDecoder().decode(API.Session.self, from: Data(session.utf8)), !known.contains(s.name) {
            status?.sessions.append(s)
        }
        return (API.MachineAdded(name: called, owner: "avi", grant: "send", vendors: ["Deepgram", "Gemini"]), status)
    }

    /// People in a demo: the invite is taken on its second check, as if the person had scanned it.
    @MainActor static func peopleActions(ownerCheck: @escaping (String) async -> Bool, status: Binding<API.Status?>) -> PeopleActions {
        let state = DemoPeople()
        return PeopleActions(
            ownerCheck: ownerCheck,
            load: { people(status.wrappedValue) },
            invite: { name, grant in
                state.waiting = (name, grant); state.checks = 0
                return API.PeopleInvite(code: "K7PQ-2MXD", link: personInviteLink, expires_in: 600, name: name, grant: grant)
            },
            state: {
                guard let (name, grant) = state.waiting else { return API.PeopleInvite(code: "", paired: false) }
                state.checks += 1
                guard state.checks >= 4 else {
                    return API.PeopleInvite(code: "K7PQ-2MXD", link: personInviteLink, expires_in: 600, name: name, grant: grant)
                }
                state.waiting = nil
                status.wrappedValue?.people = (status.wrappedValue?.people ?? []) + [API.Person(name: name, grant: grant, online: true, since: Date().timeIntervalSince1970)]
                return API.PeopleInvite(code: "K7PQ-2MXD", name: name, grant: grant, paired: true)
            },
            cancel: { state.waiting = nil },
            grant: { name, grant in
                if let i = status.wrappedValue?.people?.firstIndex(where: { $0.name == name }) { status.wrappedValue?.people?[i].grant = grant }
            },
            remove: { name in status.wrappedValue?.people?.removeAll { $0.name == name } })
    }
}

@MainActor private final class DemoPeople {
    var waiting: (String, String)?
    var checks = 0
}
