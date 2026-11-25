import Foundation

/// The daemon's status and actions, over the same pinned HTTPS listener as the call.
struct API {
    let link: DaemonLink
    let session: URLSession

    /// The pinned connection was offered a certificate other than the paired one: the Mac's changed (PinnedDelegate).
    var pinRefused: Bool { (session.delegate as? PinnedDelegate)?.refused ?? false }

    init(link: DaemonLink, session: URLSession) {
        self.link = link
        self.session = session
    }

    init(pairing: Pairing, session: URLSession) { self.init(link: DaemonLink(pairing), session: session) }

    /// The Mac keeps itself awake while a call from another device is up, on AC power only.
    struct KeepAwake: Decodable, Equatable {
        let on: Bool?
        let why: String?

        static let line = "Keeping your Mac awake"
        /// The one quiet line under the call's state: only on a live call, only while the Mac says it is on.
        static func shown(_ status: Status?, live: Bool) -> String? {
            live && status?.keep_awake?.on == true ? line : nil
        }
    }

    /// The key a vendor refused, and whether the call's ears run on it (then nothing is heard).
    struct KeyRefused: Decodable, Equatable {
        let vendor: String
        let ears: Bool
    }

    struct Status: Decodable, Equatable {
        let version: String?   // the Mac's Pointe; the brand line shows it when it differs from this app
        /// The call protocol the Mac speaks, and the oldest app protocol it still serves: either side can be too old
        /// for the other (ConnectionCause.of(macProtocol:oldestApp:)). Nil from a Mac before them.
        var phone_protocol: Int? = nil
        var oldest_phone_protocol: Int? = nil
        var active: String?
        let connected: Bool
        var sessions: [Session]
        let monologue: Monologue?   // the old brainstorm field; brain_dump carries the dump now
        var brain_dump: BrainDump?  // brain dump (BrainDump.swift); nil from a Mac without it, or when there is none
        let hold: Hold?        // "don't interrupt me" (Turns.swift): quiet until a release; nil when none, or from an older Mac
        var talk: [Turn]?       // the last turns of the conversation, oldest first
        let hearing: String?    // the user's words while they speak
        var mode: String?       // "orchestrator" or "session"
        var polish: Bool?       // "clean up my words" is on
        let meeting: Meeting?   // on, or ended and not yet discarded; nil otherwise
        let notes: NotesVersion?
        let attention: [Attention]?
        let ptt: PTTStatus?     // push to talk; nil from a Mac without it
        var voice_lock: VoiceLock?  // the owner-voice lock; nil from a Mac without it, and the app hides the feature
        var conflicts: [Conflict]?  // two sessions that disagree (Conflicts.swift); nil from a Mac without the alarm
        var briefing: BriefingStatus?  // audio briefings (Briefing.swift); nil from a Mac without them
        var showing: Showing?       // show while it says: what the voice is reporting on; nil when off on this phone
        let shown_earlier: [ShownSet]?
        var show_on_phone: Bool?    // the Mac's setting; nil from a Mac without the feature
        var drive: DriveStatus?     // drive & walk mode (Drive.swift); nil from a Mac without it
        var challenge: ChallengeStatus?  // devil's advocate (Challenge.swift): on, or the last one ended; nil from a Mac without it
        var dictionary: DictionaryStatus?  // the dictionary (Vocabulary.swift); nil from a Mac without it
        var whisper: WhisperStatus?  // whisper mode (Whisper.swift); nil from a Mac without it
        var reading: ReadingStatus?  // mute, the call's (Mute.swift; the wire's name is reading mode's); nil from a Mac without it
        var phase: Phase?            // thinking, or a session working on a request (Thinking.swift); nil when neither, or from an older Mac
        var held: HeldStatus?        // session mode: the other sessions' news, held and not spoken; nil from an older Mac
        var idle_hangup: Bool?      // the Mac's idle timer ended the last call: not redialled
        var recent: [Dispatch]?     // the last requests and where each went, oldest first; the page's Recent requests
        var tokens: Tokens?         // the voice model's own count of its context, after its last reply
        var local: LocalMode?       // local mode, read-only (local.summary); nil from a Mac without it
        var problem: String?        // the Mac's last error (a refused key, a vendor down), for a while; nil when none
        var key_refused: KeyRefused?  // a refused key while its problem shows: the title says so, never Listening
        var vendor_fault: KeyRefused?  // a vendor out of quota, failing, or gone for the call: the same, Cannot hear you
        var keep_awake: KeepAwake?  // the Mac holds off idle sleep under this call (mac.py); nil from an older Mac
        var machines: [Machine]?    // every machine with sessions on this voice, this Mac included; nil from a Mac without them
        var invite: Invite?         // the one-time code to pair another machine, while one is outstanding
        var invite_ended: String?   // why the last invite ended early: wrong codes, and the addresses they came from
        var starting: [NewSession.Starting]?    // sessions Pointe is starting, or that just failed to; nil from an older Mac
        var start_pending: NewSession.Pending?  // a read-back that waits for a yes or a tap; nil when none
        var attach_pending: AddSessions.Pending?  // sessions read back to add, waiting for a yes, a pick or a tap; nil when none
        var night_shift: NightShift.Summary?    // the running or the last night shift; nil when there was none, or from an older Mac
        var shift_pending: NightShift.Pending?  // a night shift's read-back that waits for a yes or a tap; nil when none
        #if os(macOS)
        var phones: Phones?         // Settings → Phone: the paired phones; the Mac sends them to its own page and app only
        #endif
    }

    // MARK: machines (docs/multi-machine.md). With one machine, `machines` has only this Mac and nothing changes on screen.

    struct Machine: Decodable, Equatable, Identifiable, Hashable {
        let id: String
        let name: String
        let here: Bool?             // this Mac, the one with the call
        let os: String?             // "macos", "linux"
        let online: Bool?
        let since: Double?          // offline since (epoch seconds)
        let sessions: Int?
        let need: Int?
        let rtt_ms: Int?
        let key_fp: String?         // the first hex of the node key's SHA-256, as `pointe node status` prints it
        let notice: String?         // one line about its link, e.g. a takeover from another address

        var isHere: Bool { here == true }
        var isOffline: Bool { online == false }
        var osName: String {
            switch os ?? "" {
            case "macos": "macOS"
            case "linux": "Linux"
            case let other: other
            }
        }
    }

    struct Invite: Decodable, Equatable {
        let code: String
        let expires_in: Double?     // seconds left when the status was made
        let link: String?           // the whole pointe://hub?… line, when the Mac sends it
    }

    // MARK: show while it says (docs/features/show-while-it-says.md). Paths only in status; the
    // content comes from /voice/artifact, which the Mac refuses (403) until this phone turned the feature on.

    struct Dispatch: Decodable, Equatable, Hashable {
        let at: String?
        let said: String?
        let to: [String]?
        let how: String?
    }

    struct Tokens: Decodable, Equatable {
        let context: Int?
        let at: String?
    }

    struct LocalMode: Decodable, Equatable {
        let mode: String?           // full, voice, off
        let models: String?         // ready, missing; nil when off
        let line: String            // the page's Settings line, written by the Mac

        /// A menu item holds about three short lines: the same facts as `line`, shorter.
        var short: String {
            let models = models == "ready" ? "models here" : "models missing"
            switch mode {
            case "full": return "Fully local · \(models)"
            case "voice": return "Voice stays on your Mac · \(models)"
            case "off": return "Local mode: off"
            default: return line
            }
        }
    }

    struct ShownArtifact: Decodable, Equatable, Identifiable, Hashable {
        let id: String
        let kind: String        // test, edit, read
        let name: String?
        let path: String?
        let range: [Int]?
        let failed: Bool?
        let refused: String?    // why the Mac never shows it ("outside the project: not shown")
    }

    struct Showing: Decodable, Equatable {
        let id: String
        let session: String?
        let since: Double?
        let summary: String?
        let current: String?
        let artifacts: [ShownArtifact]
    }

    struct ShownSet: Decodable, Equatable, Identifiable {
        let id: String
        let session: String?
        let at: Double?
        let summary: String?
        let artifacts: [ShownArtifact]?
    }

    struct ArtifactLine: Decodable, Equatable, Hashable {
        let n: Int
        let text: String
        let hl: Bool?
    }

    struct ArtifactView: Decodable, Equatable {
        let id: String
        let kind: String
        let name: String?
        let path: String?
        let range: [Int]?
        let failed: Bool?
        let problem: String?
        let lines: [ArtifactLine]?
        let total: Int?
        let truncated: Bool?
        let changed_since: Bool?
        let diff: String?
        let command: String?
        let output: String?
        let focus: Int?
    }

    // MARK: owner-voice lock (docs/features/voice-lock.md). Every field optional, like the meeting's.

    struct VoiceLock: Decodable, Equatable {
        var level: String?              // off, approvals, commands, everything
        let enrolled: Bool?
        let devices: [VoiceDevice]?
        let enrolling: Enrolling?
        let lines: [String]?
        let model: String?              // missing, downloading, ready, failed
        let problem: String?
        let ignored: Ignored?
        let speaker: Verdict?
        let unsure_streak: Int?

        var isEnrolled: Bool { enrolled == true }
        var lockLevel: VoiceLockLevel { VoiceLockLevel(rawValue: level ?? "off") ?? .off }
    }

    struct VoiceDevice: Decodable, Equatable, Identifiable {
        let device: String
        let seconds: Double?
        let segments: Int?
        let enrolled_at: Double?
        var id: String { device }
    }

    struct Enrolling: Decodable, Equatable {
        let device: String?
        let progress: Double?           // 0...1
        let line: Int?
        let text: String?               // the line to read aloud
        let seconds: Double?
        let segments: Int?
        let rejected: Int?
        let last_reason: String?        // why the last segment did not count; empty when it did
    }

    struct Ignored: Decodable, Equatable {
        let count: Int?
        let last_at: Double?
        let recent: [IgnoredSpeech]?
    }

    struct IgnoredSpeech: Decodable, Equatable, Hashable {
        let at: Double
        let secs: Double?
        let text: String?               // only at the Commands level
    }

    struct Verdict: Decodable, Equatable {
        let owner: Bool?
        let score: Double?
        let at: Double?
    }

    /// The Mac's microphone gate. `open` is the truth the ring shows.
    struct PTTStatus: Decodable, Equatable {
        let mode: String?        // "always" or "ptt"
        let open: Bool?
        let closed_why: String?  // "released", "held too long", "no audio", "switched to push to talk"
        let room_heard: Bool?    // a meeting is on: the room reaches the meeting without a press; talking to Pointe still needs one
        let draft: Bool?         // `hearing` is a press's words, sent as one message when it closes; nil from an older Mac
    }

    // MARK: meeting mode (docs/features/meeting-mode.md). Every field optional: an older daemon
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
        let send_pending: SendPending?  // after the end: a spoken "send the action items to X", read back, waiting for a yes
        let sent_to: String?        // after the end: the session asked to take the action items, by a tap or a spoken yes

        struct SendPending: Decodable, Equatable {
            let session: String
            let line: String        // the read-back, word for word
        }

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
        // What a notification may show and do (alerts.py); an older Mac sends none, and gets no notifications.
        var request_id: String? = nil
        var title: String? = nil
        var body: String? = nil
        var approvable: Bool? = nil
        // The user is at the Mac: post nothing for it yet (the Mac decides; an older Mac sends none).
        var quiet: Bool? = nil
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
        var conflictsOn: Bool
        var conflictsSpoken: Bool
        var watchApprove: Bool  // Approve on a notification, without Face ID
        var showOnPhone: Bool   // show while it says on this phone: off until turned on
        var patience: String    // "turns.patience": quick, normal or patient (Turns.swift)
        var waitCue: Bool?      // "thinking.cue": the waiting sound (Thinking.swift); nil from a Mac without it
        var progressSpoken: Bool?  // "progress.spoken": say how a session is doing while it works; nil from a Mac without it

        enum CodingKeys: String, CodingKey {
            case defaultMode = "meeting.default_mode", autoLookups = "meeting.auto_lookups"
            case notesLanguage = "meeting.notes_language", consented = "meeting.consented", microphone
            case conflictsOn = "conflicts.on", conflictsSpoken = "conflicts.spoken"
            case watchApprove = "alerts.watch_approve"
            case showOnPhone = "show.on_phone"
            case patience = "turns.patience"
            case waitCue = "thinking.cue", progressSpoken = "progress.spoken"
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            defaultMode = (try? c.decode(String.self, forKey: .defaultMode)) ?? "listening"
            autoLookups = (try? c.decode(Bool.self, forKey: .autoLookups)) ?? false
            notesLanguage = (try? c.decode(String.self, forKey: .notesLanguage)) ?? "auto"
            consented = (try? c.decode(Bool.self, forKey: .consented)) ?? false
            microphone = (try? c.decode(String.self, forKey: .microphone)) ?? "always"
            conflictsOn = (try? c.decode(Bool.self, forKey: .conflictsOn)) ?? true
            conflictsSpoken = (try? c.decode(Bool.self, forKey: .conflictsSpoken)) ?? true
            watchApprove = (try? c.decode(Bool.self, forKey: .watchApprove)) ?? false
            showOnPhone = (try? c.decode(Bool.self, forKey: .showOnPhone)) ?? false
            patience = (try? c.decode(String.self, forKey: .patience)) ?? TurnsCopy.defaultLevel  // an older Mac: Normal
            waitCue = try? c.decode(Bool.self, forKey: .waitCue)
            progressSpoken = try? c.decode(Bool.self, forKey: .progressSpoken)
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

    struct Hold: Decodable, Equatable {
        let since: Double?
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
        /// The machine it runs on; nil or empty is this Mac. Older Macs send neither field.
        var machine: String? = nil
        /// False while its machine is offline: sends are refused and its prompt is back in its terminal.
        var online: Bool? = nil
        var id: String { name }
        var isOffline: Bool { online == false }

        var agent: String { Harness.mark(harness).name }
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

    /// This phone's name for the Mac's list, percent-encoded: a header is ASCII, and a name is often "Mira’s iPhone".
    static func header(for name: String) -> String {
        name.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "iPhone"
    }
    nonisolated(unsafe) static var deviceHeader = "iPhone"  // set once at launch, on the main actor (PointeApp)

    func request(_ path: String, method: String = "GET", body: [String: Any]? = nil,
                 query: [URLQueryItem] = []) -> URLRequest {
        link.request(path, method: method, body: body, query: query)
    }

    /// The reply, whatever its status. On the Mac nothing is sent until the listener is verified, and a request nobody
    /// answered has the listener checked again before the key goes out once more.
    func send(_ r: URLRequest) async throws -> (Data, URLResponse) {
        guard link.ready else { throw URLError(.cannotConnectToHost) }
        do {
            return try await session.data(for: r)
        } catch {
            link.unreachable()
            throw error
        }
    }

    private func checked(_ r: URLRequest) async throws -> Data {
        let (data, response) = try await send(r)
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

    /// An action on a notification, bound to the request it was posted for. The Mac refuses an Approve (403) unless the
    /// request could be read out and "Approve from notifications" is on, and a request no longer pending (409).
    func answerFromNotification(session: String, requestId: String, allow: Bool) async throws {
        try await post("voice/approve", ["session": session, "request_id": requestId, "decision": allow ? "allow" : "deny",
                                         "via": "notification"])
    }

    /// Make this session the one the voice talks to. Switching sends nothing to it.
    func switchTo(_ name: String) async throws { try await post("voice/switch", ["name": name]) }

    /// Take a session off the voice. It keeps running in its terminal.
    func disconnect(_ name: String) async throws { try await post("voice/disconnect", ["name": name]) }

    /// The page's rename: the Mac checks the name (letters, a word voice can pick) and that no session has it.
    func rename(_ name: String, to newName: String) async throws { try await post("voice/rename", ["name": name, "new_name": newName]) }

    /// Typed instead of spoken. It never answers a permission prompt: Approve asks for Face ID. `id` is the line's own:
    /// sent again after no answer, the Mac takes it once. Returns the turn the Mac made of it (nil in a meeting, or from
    /// a Mac before 1.26).
    @discardableResult
    func say(_ text: String, id: String? = nil) async throws -> Int? {
        var body: [String: Any] = ["text": text]
        if let id { body["client_id"] = id }
        let data = try await checked(link.request("voice/say", method: "POST", body: body, timeout: API.sayTimeout))
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["id"] as? Int
    }

    /// A typed line not answered in this long is sent again (Outbox): a request lost on a weak link fails fast.
    static let sayTimeout: TimeInterval = 8

    /// Mute for the call (this device keeps its own choice either way).
    func reading(_ on: Bool) async throws { try await post("voice/reading", ["on": on]) }

    /// Skip what Pointe is saying; it goes on to the next line that waits (Skip.swift).
    func skip() async throws { try await post("voice/skip") }

    /// Session mode's held news, said now (the badge's Tell me).
    func tellHeld() async throws { try await post("voice/held", ["action": "tell"]) }

    /// The transcript of one of the user's turns was wrong: this is what they meant.
    func correct(_ turn: Turn, to text: String) async throws { try await post("voice/correct", ["id": turn.id, "text": text]) }

    /// Show a cleaned-up wording under each thing the user says.
    func polish(_ on: Bool) async throws { try await post("voice/polish", ["on": on]) }

    /// "orchestrator" routes each request to the right session; "session" sends everything to the active one.
    func mode(_ mode: String) async throws { try await post("voice/mode", ["mode": mode]) }

    func hungUp() async throws { try await post("voice/hung-up") }

    // MARK: new session (NewSession.swift)

    /// What a new session may start as: the agents, the machines and the folders. The folders come from here only.
    func startOptions() async throws -> NewSession.Options {
        try JSONDecoder().decode(NewSession.Options.self, from: try await checked(request("voice/new-session")))
    }

    /// The sheet's Start (`NewSession.Draft.body`), or a tap on a read-back: `confirm` or `cancel` with its id. A refusal
    /// carries the Mac's own words.
    func newSession(_ body: [String: String]) async throws { try await post("voice/new-session", body) }

    // MARK: adding sessions (AddSessions.swift)

    /// The sessions here and on the paired machines that are not on the voice: open ones and this week's.
    func addSessionsListing() async throws -> AddSessions.Listing {
        try JSONDecoder().decode(AddSessions.Listing.self, from: try await checked(request("voice/add-sessions")))
    }

    /// The sheet's Join with the listed keys ticked.
    func joinSessions(_ keys: [String]) async throws { try await post("voice/add-sessions", ["join": keys]) }

    /// The sheet's Reopen, `reopen` with a listed key, or a tap on a read-back: `confirm` or `cancel` with its id.
    func addSessions(_ body: [String: String]) async throws { try await post("voice/add-sessions", body) }

    // MARK: night shift (NightShift.swift)

    /// The running or the last shift with its ledger (or the one from the history with this id), the last seven, the
    /// caps, and the sessions a task may go to.
    func nightShift(id: String? = nil) async throws -> NightShift.Options {
        let query = id.map { [URLQueryItem(name: "id", value: $0)] } ?? []
        return try JSONDecoder().decode(NightShift.Options.self, from: try await checked(request("voice/night-shift", query: query)))
    }

    /// The sheet's Start (`NightShift.Draft.body`). A refusal carries the Mac's own words.
    func startShift(_ draft: NightShift.Draft) async throws { try await post("voice/night-shift", draft.body) }

    /// `stop`, or a tap on a read-back: `confirm` or `cancel` with its id.
    func shiftAction(_ action: String, id: String? = nil) async throws {
        try await post("voice/night-shift", id.map { ["action": action, "id": $0] } ?? ["action": action])
    }

    // MARK: machines

    /// The hub's routes (hub_nodes.py) answer a refusal as plain text ("no machine called x is paired"), not JSON.
    private func hub(_ path: String, _ body: [String: Any]) async throws -> Data {
        let (data, response) = try await send(request(path, method: "POST", body: body))
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let text = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw Failure.status(code, detail ?? (text.isEmpty || text.hasPrefix("{") ? "HTTP \(code)" : text))
        }
        return data
    }

    /// A one-time code another machine pairs with: single use, 10 minutes. `{}` makes one (replacing any other).
    func invite() async throws -> Invite {
        try JSONDecoder().decode(Invite.self, from: try await hub("voice/hub/invite", [:]))
    }

    /// `{"cancel": true}`: anything else would make a new code.
    func cancelInvite() async throws { _ = try await hub("voice/hub/invite", ["cancel": true]) }

    /// Unpairs a machine: its sessions leave the voice, and it needs a new code to come back. 404 names an unknown one.
    func revoke(_ name: String) async throws { _ = try await hub("voice/hub/revoke", ["name": name]) }

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
    /// A new stream for the room's audio. Speakers are labelled afresh: the owner taps "That was me" again (or, with a voiceprint, is matched by voice).
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

    // MARK: owner-voice lock

    /// enrol (with a device label), cancel, delete (one device, or all without one), level. 409 carries the Mac's reason.
    func voiceprint(_ body: [String: any Sendable]) async throws {
        try await post("voice/voiceprint", body)
    }

    func setPrefs(_ changes: [String: any Sendable]) async throws { try await post("voice/prefs", changes) }

    // MARK: audio briefings

    func briefings() async throws -> BriefingsPage {
        try JSONDecoder().decode(BriefingsPage.self, from: try await checked(request("voice/briefings")))
    }

    /// start (since, length), skip, stop, continue. 409 carries the Mac's reason: no call, a meeting on, nothing playing.
    func briefing(_ body: [String: any Sendable]) async throws { try await post("voice/briefings", body) }

    func setBriefingSchedule(_ changes: [String: any Sendable]) async throws -> BriefingSchedule? {
        let data = try await checked(request("voice/briefings/schedule", method: "POST", body: changes))
        struct Reply: Decodable { let schedule: BriefingSchedule? }
        return try JSONDecoder().decode(Reply.self, from: data).schedule
    }

    func dismissAttention(_ id: String) async throws { try await post("voice/attention", ["id": id]) }

    // MARK: challenge me

    /// start or end. 409 carries the Mac's reason: no call, a meeting on, one already on, none on. Starting reads the
    /// sessions' record first, so it may take a while.
    func challenge(_ action: String) async throws {
        var r = request("voice/challenge", method: "POST", body: ["action": action])
        r.timeoutInterval = 30
        _ = try await checked(r)
    }

    // MARK: brain dump (BrainDump.swift)

    /// The dump's buttons, the same as the words: start, done, more, edit (with text), discard, send (to a session, or
    /// to = "orchestrator"), read. 409 carries the Mac's reason; done waits for the reading model.
    func dump(_ action: String, text: String? = nil, session: String? = nil, to: String? = nil) async throws {
        var body: [String: Any] = ["action": action]
        if let text { body["text"] = text }
        if let session { body["session"] = session }
        if let to { body["to"] = to }
        var r = request("voice/dump", method: "POST", body: body)
        r.timeoutInterval = 30
        _ = try await checked(r)
    }

    // MARK: show while it says

    /// One shown artifact, by the id the status gave: never a path. 403 while off on this phone, 404 once forgotten.
    func artifact(_ id: String) async throws -> ArtifactView {
        try JSONDecoder().decode(ArtifactView.self, from: try await checked(request("voice/artifact",
                                                                                     query: [URLQueryItem(name: "id", value: id)])))
    }
}
