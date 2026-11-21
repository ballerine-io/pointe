import Foundation

/// A stand-in for the daemon, with made-up sessions: for the tests, the UI tests and screenshots. It keeps the same
/// promises the screens rely on (a request answered once is gone and a second answer is a 409; typed words become a
/// turn; a dump goes dumping → review → sent), and records every call.
public actor StubDaemon: DaemonAPI {
    public var current: API.Status
    public var currentPrefs: [String: JSONValue]
    public private(set) var calls: [String] = []
    /// When set, every request fails with it: the daemon away, or refusing the key.
    public var failure: API.Failure?
    public var down = false

    public init(status: API.Status = StubDaemon.busy(), prefs: [String: JSONValue] = ["microphone": "always", "turns.patience": "normal"]) {
        current = status
        currentPrefs = prefs
    }

    public func set(_ change: @Sendable (inout API.Status) -> Void) { change(&current) }
    public func fail(_ failure: API.Failure?) { self.failure = failure }
    public func setDown(_ down: Bool) { self.down = down }

    private func record(_ call: String) throws {
        calls.append(call)
        if down { throw URLError(.cannotConnectToHost) }
        if let failure { throw failure }
    }

    public func status() async throws -> API.Status {
        if down { throw URLError(.cannotConnectToHost) }
        if let failure { throw failure }
        return current
    }

    public func prefs() async throws -> API.Prefs {
        if down { throw URLError(.cannotConnectToHost) }  // a read: not recorded, as status is not
        if let failure { throw failure }
        let data = try JSONSerialization.data(withJSONObject: currentPrefs.mapValues(\.any))
        return try JSONDecoder().decode(API.Prefs.self, from: data)
    }

    public func setPrefs(_ changes: [String: JSONValue]) async throws {
        try record("setPrefs \(changes.keys.sorted().joined(separator: ","))")
        currentPrefs.merge(changes) { _, new in new }
        if case .string(let mode)? = changes["microphone"] {
            current.ptt = API.PTTStatus(mode: mode, open: false)
        }
    }

    public func answer(session: String, requestId: String, allow: Bool, viaNotification: Bool) async throws {
        try record("answer \(session) \(requestId) \(allow ? "allow" : "deny")\(viaNotification ? " notification" : "")")
        guard let i = current.sessions.firstIndex(where: { $0.name == session }), current.sessions[i].request_id == requestId else {
            throw API.Failure.status(409, "that request is no longer pending")
        }
        if viaNotification, allow, current.sessions[i].voice_can_approve != true {
            throw API.Failure.status(403, "approve this one in the app or on the page")
        }
        let s = current.sessions[i]
        current.sessions[i] = API.Session(name: s.name, working: allow, waiting: false, harness: s.harness, capabilities: s.capabilities,
                                          machine: s.machine, online: s.online)
        current.attention = current.attention?.filter { $0.request_id != requestId }
    }

    public func switchTo(_ name: String) async throws {
        try record("switch \(name)")
        guard current.sessions.contains(where: { $0.name == name }) else { throw API.Failure.status(404, "no session called \(name)") }
        current.active = name
    }

    public func disconnect(_ name: String) async throws {
        try record("disconnect \(name)")
        current.sessions.removeAll { $0.name == name }
    }

    public func say(_ text: String) async throws {
        try record("say \(text)")
        let next = (current.talk?.map(\.id).max() ?? 0) + 1
        current.talk = (current.talk ?? []) + [API.Turn(id: next, who: "user", text: text, typed: true),
                                               API.Turn(id: next + 1, who: "assistant", text: "Noted: \(text)")]
    }

    public func correct(turn: Int, to text: String) async throws {
        try record("correct \(turn) \(text)")
        current.talk = current.talk?.map { $0.id == turn ? API.Turn(id: $0.id, who: $0.who, text: text, corrected: true) : $0 }
    }

    public func hungUp() async throws { try record("hung-up") }

    public func dump(_ action: String, text: String?, session: String?, to: String?) async throws {
        try record("dump \(action)\(session.map { " session=\($0)" } ?? "")\(to.map { " to=\($0)" } ?? "")")
        switch action {
        case "start":
            current.brain_dump = API.BrainDump(id: "dump-1", state: "dumping", thoughts: [], send_to: API.DumpSendTo(orchestrator: true))
        case "done":
            guard var dump = current.brain_dump else { throw API.Failure.status(409, "no brain dump is on") }
            dump.state = "review"
            let said = dump.thoughts.map(\.text).joined(separator: " ")
            dump.prompt = API.DumpPrompt(goal: "Ship the retry fix", context: ["Tests pass locally"], text: said.isEmpty ? "Ship the retry fix. Tests pass locally." : said)
            current.brain_dump = dump
        case "more":
            current.brain_dump?.state = "dumping"
        case "edit":
            current.brain_dump?.prompt?.text = text ?? ""
        case "discard", "send":
            guard current.brain_dump != nil else { throw API.Failure.status(409, "no brain dump is on") }
            current.brain_dump = nil
        case "read": break
        default: throw API.Failure.status(400, "unknown action")
        }
    }

    public func voiceLock(level: String) async throws {
        try record("voiceLock \(level)")
        if level != "off", current.voice_lock?.isEnrolled != true { throw API.Failure.status(409, "Enrol your voice to use the other levels.") }
        current.voice_lock?.level = level
    }

    public func talk(_ action: String) async throws { try record("talk \(action)") }

    public func dismissAttention(_ id: String) async throws {
        try record("attention \(id)")
        current.attention = current.attention?.filter { $0.id != id }
    }

    // MARK: made-up statuses

    /// Five sessions on two machines, one waiting on an approval, one with a question, and a short conversation.
    public static func busy(connected: Bool = true) -> API.Status {
        let caps = API.Capabilities(approvals: true)
        let sessions = [
            API.Session(name: "payments", working: true, waiting: false, harness: "claude-code", capabilities: caps),
            API.Session(name: "docs", working: false, waiting: true, request: "Bash(git push origin retry-fix)", request_id: "perm-1",
                        voice_can_approve: true, harness: "claude-code", capabilities: caps),
            API.Session(name: "billing", working: false, waiting: false, needs: "Which branch should it target?", harness: "codex", capabilities: caps),
            API.Session(name: "search devbox", working: true, waiting: false, harness: "opencode", capabilities: caps, machine: "devbox", online: true),
            API.Session(name: "infra devbox", working: false, waiting: false, harness: "claude-code", capabilities: caps, machine: "devbox", online: true),
        ]
        let talk = [
            API.Turn(id: 1, who: "user", text: "What is the payments session doing?"),
            API.Turn(id: 2, who: "assistant", text: "It finished the retry fix. Tests pass. It wants to know if it should open the pull request."),
            API.Turn(id: 3, who: "user", text: "Yes. And tell the docs session to update the changelog."),
            API.Turn(id: 4, who: "assistant", text: "Docs is on it. It asks to push the branch: git push to origin, branch retry-fix. Should it?"),
        ]
        let machines = [
            API.Machine(id: "studio", name: "studio", here: true, os: "macos", online: true, sessions: 3, need: 2),
            API.Machine(id: "devbox", name: "devbox", here: false, os: "linux", online: true, sessions: 2, need: 0, rtt_ms: 23),
        ]
        let attention = [API.Attention(id: "perm-1", kind: "permission", text: "docs needs approval", session: "docs", request_id: "perm-1",
                                       title: "docs needs approval", body: "git push to origin, branch retry-fix", approvable: true)]
        return API.Status(version: "1.15.0", active: "payments", connected: connected, sessions: sessions, talk: talk, hearing: "",
                          mode: "orchestrator", attention: attention, ptt: API.PTTStatus(mode: "always", open: false),
                          voice_lock: API.VoiceLock(level: "off", enrolled: false),
                          tokens: API.Tokens(context: 48210, at: "15:04"),
                          local: API.LocalMode(line: "Cloud voice: Soniox + ElevenLabs"), machines: machines)
    }

    public static func empty() -> API.Status {
        API.Status(version: "1.15.0", connected: false, sessions: [], talk: [], hearing: "", mode: "orchestrator",
                   ptt: API.PTTStatus(mode: "always", open: false))
    }
}
