import Foundation

// People and machines (docs/design/people-and-machines.md): the fields, the calls and the words. A person is somebody
// whose voice the owner of a machine invited to it; a machine can be somebody else's, added to this voice from their
// invite. Every field is optional and nothing here shows for a person with one machine and no people.

/// A field added after the status was first shipped. Missing, or in a form this app does not know, it is nil and the
/// rest of the status still decodes: one new field must never blank the call screen.
@propertyWrapper
struct Tolerant<Value: Decodable & Equatable>: Decodable, Equatable {
    var wrappedValue: Value?

    init(wrappedValue: Value? = nil) { self.wrappedValue = wrappedValue }

    init(from decoder: Decoder) throws {
        wrappedValue = try? decoder.singleValueContainer().decode(Value.self)
    }
}

extension Tolerant: Hashable where Value: Hashable {}
extension Tolerant: Sendable where Value: Sendable {}

extension KeyedDecodingContainer {
    /// A missing key is nil, as for any optional (the synthesized decoder would otherwise require the key).
    func decode<Value>(_ type: Tolerant<Value>.Type, forKey key: Key) throws -> Tolerant<Value> {
        (try? decodeIfPresent(type, forKey: key)) ?? Tolerant()
    }
}

extension API {
    /// Somebody invited to this machine. The status sends the name, the grant and whether they are linked; the list
    /// (`GET /voice/people`) adds the services their voice uses and their key's fingerprint.
    struct Person: Decodable, Equatable, Identifiable, Hashable {
        let name: String
        var grant: String? = nil    // "send" or "watch"
        var online: Bool? = nil
        var since: Double? = nil    // linked since, or last seen (epoch seconds)
        var address: String? = nil
        var key_fp: String? = nil
        var vendors: [String]? = nil
        var added: Double? = nil
        var notice: String? = nil   // one line about their link: their voice runs an older Pointe

        var id: String { name }
        var watchOnly: Bool { grant == "watch" }

        private enum Keys: String, CodingKey { case name, grant, online, since, address, key_fp, vendors, added, notice }

        init(name: String, grant: String? = nil, online: Bool? = nil, since: Double? = nil, vendors: [String]? = nil) {
            self.name = name
            self.grant = grant
            self.online = online
            self.since = since
            self.vendors = vendors
        }

        /// Only the name is required: a field in another form is dropped, never the person.
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            name = try c.decode(String.self, forKey: .name)
            grant = try? c.decode(String.self, forKey: .grant)
            online = try? c.decode(Bool.self, forKey: .online)
            since = try? c.decode(Double.self, forKey: .since)
            address = try? c.decode(String.self, forKey: .address)
            key_fp = try? c.decode(String.self, forKey: .key_fp)
            vendors = try? c.decode([String].self, forKey: .vendors)
            added = try? c.decode(Double.self, forKey: .added)
            notice = try? c.decode(String.self, forKey: .notice)
        }
    }

    struct PeoplePage: Decodable, Equatable { let people: [Person] }

    /// The line a person adds this machine with: one use, ten minutes. `paired` once they did; `ended` when it stopped
    /// early (wrong codes), in the machine's words.
    struct PeopleInvite: Decodable, Equatable {
        let code: String
        var link: String? = nil
        var expires_in: Double? = nil
        var name: String? = nil
        var grant: String? = nil
        var paired = false
        /// Who paired, as the machine names them ({name, grant, address, network, key_fp, vendors}).
        var pairedName: String? = nil
        var ended: String? = nil

        private struct Who: Decodable { let name: String? }

        private enum Keys: String, CodingKey { case code, link, expires_in, name, grant, paired, ended }

        init(code: String, link: String? = nil, expires_in: Double? = nil, name: String? = nil, grant: String? = nil,
             paired: Bool = false, ended: String? = nil) {
            self.code = code
            self.link = link
            self.expires_in = expires_in
            self.name = name
            self.grant = grant
            self.paired = paired
            self.ended = ended
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            code = (try? c.decode(String.self, forKey: .code)) ?? ""
            link = try? c.decode(String.self, forKey: .link)
            expires_in = try? c.decode(Double.self, forKey: .expires_in)
            name = try? c.decode(String.self, forKey: .name)
            grant = try? c.decode(String.self, forKey: .grant)
            // true, or who paired ({"name": ...}), as the phone's invite says it
            if let yes = try? c.decode(Bool.self, forKey: .paired) { paired = yes }
            else { paired = c.contains(.paired) && (try? c.decodeNil(forKey: .paired)) == false }
            if let who = try? c.decode(Who.self, forKey: .paired) { pairedName = who.name }
            ended = try? c.decode(String.self, forKey: .ended)
        }
    }

    /// Shown once after a machine is added: the services this voice sends that machine's transcripts to.
    struct Disclosure: Decodable, Equatable {
        let machine: String
        var vendors: [String]? = nil
    }

    /// The answer to Add a machine, once paired and linking.
    struct MachineAdded: Decodable, Equatable {
        let name: String
        var owner: String? = nil
        var grant: String? = nil
        var vendors: [String]? = nil
    }

    // MARK: the calls

    /// The machine's refusal is one sentence: JSON's `detail`, or plain text as the machine routes answer it.
    private func people(_ path: String, _ body: [String: Any]? = nil, timeout: TimeInterval? = nil) async throws -> Data {
        var r = request(path, method: body == nil ? "GET" : "POST", body: body)
        if let timeout { r.timeoutInterval = timeout }
        let (data, response) = try await send(r)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let text = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw Failure.status(code, detail ?? (text.isEmpty || text.hasPrefix("{") || text.hasPrefix("<") ? "HTTP \(code)" : text))
        }
        return data
    }

    /// Adds somebody's machine to this voice from their invite line. `name` only after the machine said its own is
    /// taken. It checks the certificate, trades the code and links before it answers: a longer wait than a status.
    func addMachine(line: String, name: String? = nil) async throws -> MachineAdded {
        var body: [String: Any] = ["line": line]
        if let name, !name.isEmpty { body["name"] = name }
        return try JSONDecoder().decode(MachineAdded.self, from: try await people("voice/machines/add", body, timeout: 30))
    }

    /// OK on the one-time disclosure: the status stops sending it.
    func disclosureSeen(_ machine: String) async throws { _ = try await people("voice/machines/add", ["seen": machine]) }

    func people() async throws -> [Person] {
        try JSONDecoder().decode(PeoplePage.self, from: try await people("voice/people")).people
    }

    func invitePerson(name: String, grant: String) async throws -> PeopleInvite {
        try JSONDecoder().decode(PeopleInvite.self, from: try await people("voice/people/invite", ["name": name, "grant": grant]))
    }

    func personInviteState() async throws -> PeopleInvite {
        try JSONDecoder().decode(PeopleInvite.self, from: try await people("voice/people/invite"))
    }

    func cancelPersonInvite() async throws { _ = try await people("voice/people/invite", ["cancel": true]) }

    func setGrant(_ name: String, _ grant: String) async throws { _ = try await people("voice/people/grant", ["name": name, "grant": grant]) }

    func removePerson(_ name: String) async throws { _ = try await people("voice/people/remove", ["name": name]) }

    /// Private keeps a session of this machine to its owner; shared shows it to the people invited again.
    func share(_ session: String, private isPrivate: Bool) async throws {
        _ = try await people("voice/share", ["session": session, "private": isPrivate])
    }
}

/// The words of people and machines. The page says the same ones (ui.html PEOPLE_COPY; tests/test_copy_parity.py).
enum PeopleCopy {
    static let people = "People"
    static let addMachine = "Add a machine"
    static let trust = "People you invite can make these agents run commands as this machine's account. Keep a session to yourself with Private."
    static let invite = "Invite a person"
    static let name = "Name"
    static let send = "Can talk to the sessions"
    static let watch = "Can only watch"
    static let none = "Nobody is invited to this machine yet."
    static let lineHelp = "Send them this line. They add it in Settings, Machines, Add a machine. It works once."
    static let copy = "Copy the line"
    static let share = "Share"
    static let cancelInvite = "Cancel the invite"
    static let expired = "The invite expired."
    static let remove = "Remove"
    static let watchOnly = "watch only"
    static let mine = "Mine"
    static let makePrivate = "Private"
    static let makeShared = "Shared with people"
    static let privateMark = "private"
    static let ok = "OK"
    static let add = "Add"
    static let pasteInstead = "Paste instead"
    static let scanHelp = "Scan the code on their screen, or paste the line they sent you."
    static let lineField = "pointe://machine?… line"
    static let lineHelpMac = "Paste the line they sent you, or drop it here."
    static let adding = "Adding the machine…"
    static let callIt = "Call it"
    static let notAnInvite = "That is not a machine invite. Ask for the line from Settings, Machines, People."
    static let nothingToPaste = "The clipboard has no machine invite."
    /// Over Add, when a link from another app or a web page opened the sheet: the machine it names, to check first.
    static func fromOutside(_ host: String) -> String {
        "This invite opened Pointe from outside the app. It adds the machine at \(host). Add it only if you asked for it."
    }
    static let noAnswer = "The Mac is not answering."
    static let tooOld = "This Mac's Pointe cannot do this yet: update it."

    static let inviteReason = "Invite a person to this machine"
    static let addReason = "Add a machine to your voice"
    static let removeReason = "Remove a person"

    /// "Avi", for a name typed as "avi": a person's name starts with a capital on screen. A name with a capital
    /// anywhere is left as its owner wrote it.
    static func shown(_ name: String) -> String {
        guard name == name.lowercased(), let first = name.first else { return name }
        return first.uppercased() + name.dropFirst()
    }

    /// "Avi's": whose a session or a machine is.
    static func owned(_ name: String) -> String { "\(shown(name))'s" }

    /// "Dana is using it": the session works on another person's request.
    static func using(_ name: String) -> String { "\(shown(name)) is using it" }

    static func removeAsk(_ name: String) -> String {
        "Remove \(shown(name))? Their voice loses this machine's sessions now. To bring them back, invite them again."
    }
    static func removed(_ name: String) -> String { "\(shown(name)) is removed." }
    static func joined(_ name: String) -> String { "\(shown(name)) can reach this machine now." }
    static func added(_ machine: String, owner: String?) -> String {
        owner.map { "Added \(machine), \(owned($0)) machine." } ?? "Added \(machine)."
    }

    /// Removing a machine this voice was invited to, from this voice.
    static func removeMachineAsk(_ machine: String, owner: String?) -> String {
        "Remove \(machine)? Its sessions leave your voice. To add it again, \(owner.map(shown) ?? "its owner") must invite you again."
    }
    static func machineRemoved(_ machine: String) -> String { "\(machine) is removed." }

    /// "Deepgram, Gemini and ElevenLabs"
    static func list(_ names: [String]) -> String {
        switch names.count {
        case 0: ""
        case 1: names[0]
        default: names.dropLast().joined(separator: ", ") + " and " + names[names.count - 1]
        }
    }

    /// The one-time line after a machine is added: where this voice sends that machine's transcripts.
    /// The page's sentence (ui.html PEOPLE_SAYS.disclosure).
    static func disclosure(_ d: API.Disclosure, owner: String? = nil) -> String {
        let vendors = (d.vendors ?? []).filter { !$0.isEmpty }
        let sent = vendors.isEmpty ? "Your voice sends the transcripts of the sessions on \(d.machine) to no outside service."
            : "Your voice sends the transcripts of the sessions on \(d.machine), with credentials masked, to: \(vendors.joined(separator: ", "))."
        return "\(sent) \(owner.flatMap { $0.isEmpty ? nil : shown($0) } ?? "Its owner") sees this list next to your name."
    }

    /// The trust model in one line, naming the account when the Mac says it (ui.html PEOPLE_SAYS.trust).
    static func trust(account: String?) -> String {
        guard let account, !account.isEmpty else { return trust }
        return "People you invite can make these agents run commands as \(account). Keep a session to yourself with Private."
    }

    /// Under a person's name: the services their voice sends this machine's transcripts to.
    static func services(_ p: API.Person) -> String? {
        let vendors = (p.vendors ?? []).filter { !$0.isEmpty }
        return vendors.isEmpty ? nil : "Their voice uses: \(vendors.joined(separator: ", "))"  // ui.html PEOPLE_SAYS.uses
    }

    /// "can talk · online", "watch only · last seen 14:02"
    static func facts(_ p: API.Person, now: Date = Date()) -> String {
        let grant = p.watchOnly ? watchOnly : "can talk"
        let state = p.online == true ? "online" : p.since.map { "last seen \(MachinesCopy.since($0, now: now))" } ?? "not linked yet"
        return "\(grant) · \(state)"
    }

    /// The Mac's refusal as a sentence; a route an older Pointe does not have says to update it.
    @MainActor static func refusal(_ error: Error) -> String {
        if case API.Failure.status(let code, let detail) = error {
            if detail.hasPrefix("HTTP ") { return code == 404 || code == 405 ? tooOld : "The Mac did not do it." }
            return CallView.sentence(detail)
        }
        return noAnswer
    }
}

/// A `pointe://machine?…` line, as an invite to a machine carries it. The app only reads it to tell an invite from
/// anything else and to say whose machine it names: the Mac checks the certificate and trades the code.
struct MachineLine: Equatable {
    let line: String
    let host: String
    let name: String?

    init?(_ text: String) {
        // A whole pasted command (`pointe machine add '<line>'`) or a line in quotes: the link inside it.
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let start = trimmed.range(of: "pointe://machine?") else { return nil }
        let rest = trimmed[start.lowerBound...]
        let link = String(rest.prefix { !$0.isWhitespace && $0 != "'" && $0 != "\"" })
        guard let c = URLComponents(string: link), c.scheme == "pointe", c.host == "machine" else { return nil }
        func item(_ name: String) -> String? { c.queryItems?.first { $0.name == name }?.value }
        guard let host = item("host"), !host.isEmpty, let code = item("code"), !code.isEmpty,
              let fp = item("fp"), !fp.isEmpty else { return nil }
        self.line = link
        self.host = host
        self.name = item("name").flatMap { $0.isEmpty ? nil : $0 }
    }
}

// MARK: whose it is (pure, so it is unit tested)

extension MachineView {
    /// The Mine chip's value in the machine filter: no machine can have this name.
    static let mineFilter = "\u{1F}mine"

    /// Some session is somebody else's: only then is there a Mine chip, and an owner on anything.
    var hasOwners: Bool { sessions.contains { !$0.isMine } }

    /// "Avi's" on a session that is not this person's; nil on their own.
    func ownerTag(_ s: API.Session) -> String? {
        s.isMine ? nil : PeopleCopy.owned(s.owner ?? "")
    }

    /// "Avi's" on a machine this person was invited to; nil on their own.
    func ownerTag(machine name: String) -> String? {
        info(name)?.owner.flatMap { $0.isEmpty ? nil : PeopleCopy.owned($0) }
    }

    /// This person may only watch the session's machine: nothing offers to send to it, or to answer its prompt.
    func watchOnly(_ s: API.Session) -> Bool { info(of(s))?.isWatchOnly == true }
    func watchOnly(machine name: String) -> Bool { info(name)?.isWatchOnly == true }

    /// Under its machine's name a session of somebody else's machine drops " on avi-box": the heading says it.
    func short(_ s: API.Session) -> String {
        let m = of(s), suffix = " on " + m
        return multi && m != here && s.name.hasSuffix(suffix) && s.name.count > suffix.count ? String(s.name.dropLast(suffix.count)) : s.name
    }

    /// "Dana is using it", while the session works on another person's request.
    func usedBy(_ s: API.Session) -> String? {
        s.by.flatMap { $0.name.isEmpty ? nil : PeopleCopy.using($0.name) }
    }

    /// Private or Shared with people is offered on a session this person owns, on this machine, once the machine has
    /// people. The value is what a tap asks for: true makes it private.
    func privacyOffer(_ s: API.Session, people: [API.Person]?) -> Bool? {
        guard people != nil, s.isMine, of(s) == here || here.isEmpty, !s.isOffline else { return nil }
        return !s.isPrivate
    }

    /// A machine this voice was invited to that has something to say and is gone: "avi-box removed you". Its section
    /// offers Remove.
    func removable(_ name: String) -> String? {
        guard let m = info(name), !m.isHere else { return nil }
        if let removed = m.removed {  // the Mac says so itself; an older one does not, and the notice is read instead
            return removed ? ((m.notice ?? "").isEmpty ? "\(name) removed you" : m.notice) : nil
        }
        guard m.isOffline, (m.owner ?? "").isEmpty == false, let notice = m.notice, !notice.isEmpty else { return nil }
        return notice
    }

    /// What VoiceOver says of a session beyond its name and state: whose it is, who uses it, that it is private.
    func spoken(_ s: API.Session) -> String {
        var parts: [String] = []
        if let owner = ownerTag(s) { parts.append("\(owner) session") }
        if watchOnly(s) { parts.append(PeopleCopy.watchOnly) }
        if let by = usedBy(s) { parts.append(by) }
        if s.isPrivate { parts.append(PeopleCopy.privateMark) }
        return parts.map { ", \($0)" }.joined()
    }
}
