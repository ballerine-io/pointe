import Foundation

/// The daemon's status and actions, over the same pinned HTTPS listener as the call.
struct API {
    let pairing: Pairing
    let session: URLSession

    struct Status: Decodable, Equatable {
        let active: String?
        let connected: Bool
        let sessions: [Session]
        let monologue: Monologue?
        let talk: [Turn]?       // the last turns of the conversation, oldest first
        let hearing: String?    // the user's words while they speak
        let mode: String?       // "orchestrator" or "session"
        let polish: Bool?       // "clean up my words" is on
        let meeting: Meeting?   // on, or ended and not yet discarded; nil otherwise
        let notes: NotesVersion?
        let attention: [Attention]?
        let ptt: PTTStatus?     // push to talk; nil from a Mac without it
    }

    /// The Mac's microphone gate. `open` is the truth the ring shows.
    struct PTTStatus: Decodable, Equatable {
        let mode: String?        // "always" or "ptt"
        let open: Bool?
        let closed_why: String?  // "released", "held too long", "no audio", "switched to push to talk"
    }

    // MARK: meeting mode (docs/plans/next-features.md, "Meeting API (as built)"). Every field optional: an older daemon
    // sends none of them, and the app must still decode its status.

    struct Meeting: Decodable, Equatable {
        let on: Bool?
        let id: String?             // the meeting on now; an ended meeting's status has none
        let ending: Bool?           // the end pass (the summary) is running
        let ended: Bool?
        let mode: String?           // "listening" or "participating"
        let since: Double?          // epoch seconds
        let speakers: [Speaker]?
        let owner_known: Bool?
        let hand: Hand?
        let speaking: Bool?
        let paused: Bool?
        let vendors: Vendors?
        let recording: Bool?
        let sessions: [String]?
        let auto_lookups: Bool?
        let turns: Int?
        let result: MeetingResult?  // after the end

        var isOn: Bool { on == true }
        var isEnding: Bool { on == true && ending == true }
        var isEnded: Bool { on != true && ended == true }
        var participating: Bool { mode == "participating" }
    }

    struct Speaker: Decodable, Equatable, Identifiable, Hashable {
        let label: String
        let name: String?
        let is_owner: Bool?
        let turns: Int?
        var id: String { label }
        var shown: String { is_owner == true ? "You" : (name?.isEmpty == false ? name! : "Speaker \(label)") }
    }

    struct Hand: Decodable, Equatable {
        let line: String
        let at: Double?
        let urgency: String?
    }

    struct Vendors: Decodable, Equatable {
        let room_audio: String?
        let notes: String?
        let speech: String?
        let commands: String?
    }

    struct ActionItem: Decodable, Equatable, Hashable {
        let what: String
        let owner: String?
        let due: String?
    }

    struct MeetingResult: Decodable, Equatable {
        let summary: String?
        let decisions: [String]?
        let action_items: [ActionItem]?
        let open_questions: [String]?
    }

    struct NotesVersion: Decodable, Equatable {
        let version: Int?
        let last_id: Int?
    }

    struct Attention: Decodable, Equatable, Identifiable {
        let id: String
        let kind: String?
        let text: String?
        let session: String?
    }

    struct Note: Decodable, Equatable, Identifiable {
        let id: Int
        let kind: String            // thought, question, answer, action, decision, hand, session_news, brief, summary, speaker
        let at: Double?
        let updated: Double?
        let text: String
        let meta: NoteMeta?
        let speakers: [String]?
        let session: String?
        let state: String?          // open, done, dismissed
        var meeting: String? = nil  // the meeting it was written in; older daemons send none
        var rev: Int? = nil         // the notes version when it last changed
    }

    struct NoteMeta: Decodable, Equatable {
        let why: String?
        let asked_by: String?
        let owner: String?
        let due: String?
        let label: String?          // a suggested speaker name: which label
        let name: String?           // and the name
        let full: String?           // a raised hand's whole point
        let lookup: Lookup?         // a question a linked session can answer
    }

    struct Lookup: Decodable, Equatable {
        let session: String?
        let how: String?
    }

    struct NotesPage: Decodable { let version: Int?; let notes: [Note]? }

    struct TranscriptTurn: Decodable, Equatable, Identifiable {
        let id: Int
        let who: String?
        let speaker: String?
        let at: Double?
        let lang: String?
        let text: String
    }

    struct Transcript: Decodable { let turns: [TranscriptTurn]? }

    struct VendorsReply: Decodable { let vendors: Vendors?; let soniox: Bool? }

    struct Prefs: Decodable, Equatable {
        var defaultMode: String
        var autoLookups: Bool
        var notesLanguage: String
        var consented: Bool
        var microphone: String  // "always" or "ptt"

        enum CodingKeys: String, CodingKey {
            case defaultMode = "meeting.default_mode", autoLookups = "meeting.auto_lookups"
            case notesLanguage = "meeting.notes_language", consented = "meeting.consented", microphone
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            defaultMode = (try? c.decode(String.self, forKey: .defaultMode)) ?? "listening"
            autoLookups = (try? c.decode(Bool.self, forKey: .autoLookups)) ?? false
            notesLanguage = (try? c.decode(String.self, forKey: .notesLanguage)) ?? "auto"
            consented = (try? c.decode(Bool.self, forKey: .consented)) ?? false
            microphone = (try? c.decode(String.self, forKey: .microphone)) ?? "always"
        }
    }

    struct Turn: Decodable, Equatable, Hashable, Identifiable {
        let id: Int             // stable while the turn is in the window
        let who: String         // "user" or "assistant"
        let text: String
        let understood: String? // the cleaned-up wording, when "clean up my words" is on
        let typed: Bool?
        let corrected: Bool?
        var mine: Bool { who == "user" }
    }

    struct Monologue: Decodable, Equatable {
        let said: String
    }

    struct Session: Decodable, Identifiable, Equatable {
        let name: String
        let working: Bool
        let waiting: Bool
        let request: String?       // the exact request: what a tap approves
        let request_id: String?
        let voice_can_approve: Bool?
        let needs: String?
        /// Which coding agent runs it: "claude-code", "opencode", "codex"... Older daemons send nothing: Claude Code.
        let harness: String?
        let capabilities: Capabilities?
        var id: String { name }

        var agent: String {
            switch harness ?? "claude-code" {
            case "claude-code": "Claude"
            case "opencode": "OpenCode"
            case "codex": "Codex"
            case "pi": "Pi"
            case let other: other
            }
        }
        /// An agent without approvals (Pi, for one) never gets Approve or Deny.
        var canApprove: Bool { capabilities?.approvals != false }
    }

    struct Capabilities: Decodable, Equatable {
        let approvals: Bool?
        let side_questions: Bool?
        let attach: Bool?
        let spawn: Bool?
    }

    enum Failure: Error { case status(Int, String) }

    private func request(_ path: String, method: String = "GET", body: [String: Any]? = nil,
                         query: [URLQueryItem] = []) -> URLRequest {
        var url = pairing.base.appendingPathComponent(path)
        if !query.isEmpty, var parts = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            parts.queryItems = query
            url = parts.url ?? url
        }
        var r = URLRequest(url: url)
        r.httpMethod = method
        r.setValue("Bearer \(pairing.key)", forHTTPHeaderField: "Authorization")
        if let body {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        r.timeoutInterval = 10
        return r
    }

    private func checked(_ r: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: r)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw Failure.status(code, detail ?? "HTTP \(code)")
        }
        return data
    }

    private func post(_ path: String, _ body: [String: Any] = [:]) async throws {
        _ = try await checked(request(path, method: "POST", body: body))
    }

    func status() async throws -> Status {
        try JSONDecoder().decode(Status.self, from: try await checked(request("voice/status")))
    }

    func answer(_ s: Session, allow: Bool) async throws {
        guard let id = s.request_id else { return }
        try await post("voice/approve", ["session": s.name, "request_id": id, "decision": allow ? "allow" : "deny"])
    }

    /// "Just listen": the bot stays quiet until handed the turn; off hands it over.
    func listen(_ on: Bool) async throws { try await post("voice/listen", ["on": on]) }

    /// Make this session the one the voice talks to. Switching sends nothing to it.
    func switchTo(_ name: String) async throws { try await post("voice/switch", ["name": name]) }

    /// Take a session off the voice. It keeps running in its terminal.
    func disconnect(_ name: String) async throws { try await post("voice/disconnect", ["name": name]) }

    /// Typed instead of spoken. It never answers a permission prompt: Approve asks for Face ID.
    func say(_ text: String) async throws { try await post("voice/say", ["text": text]) }

    /// The transcript of one of the user's turns was wrong: this is what they meant.
    func correct(_ turn: Turn, to text: String) async throws { try await post("voice/correct", ["id": turn.id, "text": text]) }

    /// Show a cleaned-up wording under each thing the user says.
    func polish(_ on: Bool) async throws { try await post("voice/polish", ["on": on]) }

    /// "orchestrator" routes each request to the right session; "session" sends everything to the active one.
    func mode(_ mode: String) async throws { try await post("voice/mode", ["mode": mode]) }

    func hungUp() async throws { try await post("voice/hung-up") }

    // MARK: meeting

    @discardableResult
    private func meeting(_ body: [String: Any], timeout: TimeInterval = 10) async throws -> Data {
        var r = request("voice/meeting", method: "POST", body: body)
        r.timeoutInterval = timeout
        return try await checked(r)
    }

    /// Who receives what, shown in the consent step before a meeting starts.
    func meetingVendors() async throws -> VendorsReply {
        try JSONDecoder().decode(VendorsReply.self, from: try await meeting(["action": "vendors"]))
    }

    func startMeeting(mode: String, brief: String, sessions: [String], autoLookups: Bool) async throws {
        try await meeting(["action": "start", "mode": mode, "consent": true, "brief": brief, "sessions": sessions,
                           "auto_lookups": autoLookups])
    }

    func meetingMode(_ mode: String) async throws { try await meeting(["action": "mode", "mode": mode]) }
    /// "speak" lets a raised hand talk (participating only), "type" turns it into a note, "later" puts it down.
    func hand(_ decision: String) async throws { try await meeting(["action": "hand", "decision": decision]) }
    func nameSpeaker(_ label: String, _ name: String) async throws { try await meeting(["action": "speaker", "label": label, "name": name]) }
    func thatWasMe(_ turnId: Int) async throws { try await meeting(["action": "owner", "turn_id": turnId]) }
    func addBrief(_ text: String) async throws { try await meeting(["action": "brief", "text": text]) }
    /// The operator's okay for one look-up in a linked session (a read-only copy; the session itself is never touched).
    func lookUp(_ note: Note) async throws { try await meeting(["action": "lookup", "note_id": note.id]) }
    /// A typed "Pointe, …" from the owner.
    func ask(_ text: String) async throws { try await meeting(["action": "ask", "text": text]) }

    func endMeeting() async throws -> MeetingResult {
        try JSONDecoder().decode(MeetingResult.self, from: try await meeting(["action": "end"], timeout: 120))  // the summary is written now
    }

    /// Saves the meeting as Markdown on the Mac (0600); the transcript only when asked. Returns the path.
    func exportMeeting(transcript: Bool) async throws -> String {
        let data = try await meeting(["action": "export", "transcript": transcript])
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["exported"] as? String ?? ""
    }

    /// The action items, as the owner's own request, through the normal send path and its checks.
    func sendActions(to session: String) async throws { try await meeting(["action": "send_actions", "session": session], timeout: 30) }
    func discardMeeting() async throws { try await meeting(["action": "discard"]) }
    /// A new stream for the room's audio. Speakers are labelled afresh: the owner says "Pointe, that's me" again.
    func reconnectMeeting() async throws { try await meeting(["action": "reconnect"]) }

    /// New notes after the id `since`, and older ones changed after the version `changedSince` (every changed one without it).
    func notes(since: Int, changedSince: Int? = nil) async throws -> NotesPage {
        var query = [URLQueryItem(name: "since", value: String(since))]
        if let changedSince { query.append(URLQueryItem(name: "changed_since", value: String(changedSince))) }
        return try JSONDecoder().decode(NotesPage.self, from: try await checked(request("voice/notes", query: query)))
    }

    /// state: open, done or dismissed; accept applies a suggested speaker name.
    func setNote(_ id: Int, state: String? = nil, accept: Bool = false) async throws {
        var body: [String: Any] = ["id": id]
        if let state { body["state"] = state }
        if accept { body["accept"] = true }
        try await post("voice/notes", body)
    }

    func transcript() async throws -> [TranscriptTurn] {
        (try JSONDecoder().decode(Transcript.self, from: try await checked(request("voice/meeting/transcript")))).turns ?? []
    }

    func prefs() async throws -> Prefs {
        try JSONDecoder().decode(Prefs.self, from: try await checked(request("voice/prefs")))
    }

    func setPrefs(_ changes: [String: any Sendable]) async throws { try await post("voice/prefs", changes) }
}
