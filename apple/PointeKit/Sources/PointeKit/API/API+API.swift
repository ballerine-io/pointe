import Foundation

// The daemon's status and replies, as the page and the apps read them. Every field a newer daemon added is optional:
// an older daemon sends none of them and the status must still decode.

extension API {
    /// The Mac keeps itself awake while a call from another device is up, on AC power only.
    public struct KeepAwake: Decodable, Equatable, Sendable {
        public let on: Bool?
        public let why: String?

        public static let line = "Keeping your Mac awake"
        /// The one quiet line under the call's state: only on a live call, only while the Mac says it is on.
        public static func shown(_ status: Status?, live: Bool) -> String? {
            live && status?.keep_awake?.on == true ? line : nil
        }

        public init(on: Bool? = nil, why: String? = nil) {
            self.on = on
            self.why = why
        }
    }

    public struct Status: Decodable, Equatable, Sendable {
        public var version: String?   // the Mac's Pointe; the brand line shows it when it differs from this app
        public var active: String?
        public var connected: Bool
        public var sessions: [Session]
        public var monologue: Monologue?   // the old brainstorm field; brain_dump carries the dump now
        public var brain_dump: BrainDump?  // brain dump (BrainDump.swift); nil from a Mac without it, or when there is none
        public var hold: Hold?        // "don't interrupt me" (Turns.swift): quiet until a release; nil when none, or from an older Mac
        public var talk: [Turn]?       // the last turns of the conversation, oldest first
        public var hearing: String?    // the user's words while they speak
        public var mode: String?       // "orchestrator" or "session"
        public var polish: Bool?       // "clean up my words" is on
        public var meeting: Meeting?   // on, or ended and not yet discarded; nil otherwise
        public var notes: NotesVersion?
        public var attention: [Attention]?
        public var ptt: PTTStatus?     // push to talk; nil from a Mac without it
        public var voice_lock: VoiceLock?  // the owner-voice lock; nil from a Mac without it, and the app hides the feature
        public var conflicts: [Conflict]?  // two sessions that disagree (Conflicts.swift); nil from a Mac without the alarm
        public var briefing: BriefingStatus?  // audio briefings (Briefing.swift); nil from a Mac without them
        public var showing: Showing?       // show while it says: what the voice is reporting on; nil when off on this phone
        public var shown_earlier: [ShownSet]?
        public var show_on_phone: Bool?    // the Mac's setting; nil from a Mac without the feature
        public var drive: DriveStatus?     // drive & walk mode (Drive.swift); nil from a Mac without it
        public var challenge: ChallengeStatus?  // devil's advocate (Challenge.swift): on, or the last one ended; nil from a Mac without it
        public var dictionary: DictionaryStatus?  // the dictionary (Vocabulary.swift); nil from a Mac without it
        public var whisper: WhisperStatus?  // whisper mode (Whisper.swift); nil from a Mac without it
        public var idle_hangup: Bool?      // the Mac's idle timer ended the last call: not redialled
        public var recent: [Dispatch]?     // the last requests and where each went, oldest first; the page's Recent requests
        public var tokens: Tokens?         // the voice model's own count of its context, after its last reply
        public var local: LocalMode?       // local mode, read-only (local.summary); nil from a Mac without it
        public var problem: String?        // the Mac's last error (a refused key, a vendor down), for a while; nil when none
        public var keep_awake: KeepAwake?  // the Mac holds off idle sleep under this call (mac.py); nil from an older Mac
        public var machines: [Machine]?    // every machine with sessions on this voice, this Mac included; nil from a Mac without them
        public var invite: Invite?         // the one-time code to pair another machine, while one is outstanding
        public var invite_ended: String?   // why the last invite ended early: wrong codes, and the addresses they came from

        public init(version: String? = nil, active: String? = nil, connected: Bool, sessions: [Session], monologue: Monologue? = nil, brain_dump: BrainDump? = nil, hold: Hold? = nil, talk: [Turn]? = nil, hearing: String? = nil, mode: String? = nil, polish: Bool? = nil, meeting: Meeting? = nil, notes: NotesVersion? = nil, attention: [Attention]? = nil, ptt: PTTStatus? = nil, voice_lock: VoiceLock? = nil, conflicts: [Conflict]? = nil, briefing: BriefingStatus? = nil, showing: Showing? = nil, shown_earlier: [ShownSet]? = nil, show_on_phone: Bool? = nil, drive: DriveStatus? = nil, challenge: ChallengeStatus? = nil, dictionary: DictionaryStatus? = nil, whisper: WhisperStatus? = nil, idle_hangup: Bool? = nil, recent: [Dispatch]? = nil, tokens: Tokens? = nil, local: LocalMode? = nil, problem: String? = nil, keep_awake: KeepAwake? = nil, machines: [Machine]? = nil, invite: Invite? = nil, invite_ended: String? = nil) {
            self.version = version
            self.active = active
            self.connected = connected
            self.sessions = sessions
            self.monologue = monologue
            self.brain_dump = brain_dump
            self.hold = hold
            self.talk = talk
            self.hearing = hearing
            self.mode = mode
            self.polish = polish
            self.meeting = meeting
            self.notes = notes
            self.attention = attention
            self.ptt = ptt
            self.voice_lock = voice_lock
            self.conflicts = conflicts
            self.briefing = briefing
            self.showing = showing
            self.shown_earlier = shown_earlier
            self.show_on_phone = show_on_phone
            self.drive = drive
            self.challenge = challenge
            self.dictionary = dictionary
            self.whisper = whisper
            self.idle_hangup = idle_hangup
            self.recent = recent
            self.tokens = tokens
            self.local = local
            self.problem = problem
            self.keep_awake = keep_awake
            self.machines = machines
            self.invite = invite
            self.invite_ended = invite_ended
        }
    }

    public struct Machine: Decodable, Equatable, Identifiable, Hashable, Sendable {
        public let id: String
        public let name: String
        public let here: Bool?             // this Mac, the one with the call
        public let os: String?             // "macos", "linux"
        public let online: Bool?
        public let since: Double?          // offline since (epoch seconds)
        public let sessions: Int?
        public let need: Int?
        public let rtt_ms: Int?
        public let key_fp: String?         // the first hex of the node key's SHA-256, as `pointe node status` prints it
        public let notice: String?         // one line about its link, e.g. a takeover from another address

        public var isHere: Bool { here == true }
        public var isOffline: Bool { online == false }
        public var osName: String {
            switch os ?? "" {
            case "macos": "macOS"
            case "linux": "Linux"
            case let other: other
            }
        }

        public init(id: String, name: String, here: Bool? = nil, os: String? = nil, online: Bool? = nil, since: Double? = nil, sessions: Int? = nil, need: Int? = nil, rtt_ms: Int? = nil, key_fp: String? = nil, notice: String? = nil) {
            self.id = id
            self.name = name
            self.here = here
            self.os = os
            self.online = online
            self.since = since
            self.sessions = sessions
            self.need = need
            self.rtt_ms = rtt_ms
            self.key_fp = key_fp
            self.notice = notice
        }
    }

    public struct Invite: Decodable, Equatable, Sendable {
        public let code: String
        public let expires_in: Double?     // seconds left when the status was made
        public let link: String?           // the whole pointe://hub?… line, when the Mac sends it

        public init(code: String, expires_in: Double? = nil, link: String? = nil) {
            self.code = code
            self.expires_in = expires_in
            self.link = link
        }
    }

    public struct Dispatch: Decodable, Equatable, Hashable, Sendable {
        public let at: String?
        public let said: String?
        public let to: [String]?
        public let how: String?

        public init(at: String? = nil, said: String? = nil, to: [String]? = nil, how: String? = nil) {
            self.at = at
            self.said = said
            self.to = to
            self.how = how
        }
    }

    public struct Tokens: Decodable, Equatable, Sendable {
        public let context: Int?
        public let at: String?

        public init(context: Int? = nil, at: String? = nil) {
            self.context = context
            self.at = at
        }
    }

    public struct LocalMode: Decodable, Equatable, Sendable {
        public let mode: String?           // full, voice, off
        public let models: String?         // ready, missing; nil when off
        public let line: String            // the page's Settings line, written by the Mac

        /// A menu item holds about three short lines: the same facts as `line`, shorter.
        public var short: String {
            let models = models == "ready" ? "models here" : "models missing"
            switch mode {
            case "full": return "Fully local · \(models)"
            case "voice": return "Voice stays on your Mac · \(models)"
            case "off": return "Local mode: off"
            default: return line
            }
        }

        public init(mode: String? = nil, models: String? = nil, line: String) {
            self.mode = mode
            self.models = models
            self.line = line
        }
    }

    public struct ShownArtifact: Decodable, Equatable, Identifiable, Hashable, Sendable {
        public let id: String
        public let kind: String        // test, edit, read
        public let name: String?
        public let path: String?
        public let range: [Int]?
        public let failed: Bool?
        public let refused: String?    // why the Mac never shows it ("outside the project: not shown")

        public init(id: String, kind: String, name: String? = nil, path: String? = nil, range: [Int]? = nil, failed: Bool? = nil, refused: String? = nil) {
            self.id = id
            self.kind = kind
            self.name = name
            self.path = path
            self.range = range
            self.failed = failed
            self.refused = refused
        }
    }

    public struct Showing: Decodable, Equatable, Sendable {
        public let id: String
        public let session: String?
        public let since: Double?
        public let summary: String?
        public let current: String?
        public let artifacts: [ShownArtifact]

        public init(id: String, session: String? = nil, since: Double? = nil, summary: String? = nil, current: String? = nil, artifacts: [ShownArtifact]) {
            self.id = id
            self.session = session
            self.since = since
            self.summary = summary
            self.current = current
            self.artifacts = artifacts
        }
    }

    public struct ShownSet: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let session: String?
        public let at: Double?
        public let summary: String?
        public let artifacts: [ShownArtifact]?

        public init(id: String, session: String? = nil, at: Double? = nil, summary: String? = nil, artifacts: [ShownArtifact]? = nil) {
            self.id = id
            self.session = session
            self.at = at
            self.summary = summary
            self.artifacts = artifacts
        }
    }

    public struct ArtifactLine: Decodable, Equatable, Hashable, Sendable {
        public let n: Int
        public let text: String
        public let hl: Bool?

        public init(n: Int, text: String, hl: Bool? = nil) {
            self.n = n
            self.text = text
            self.hl = hl
        }
    }

    public struct ArtifactView: Decodable, Equatable, Sendable {
        public let id: String
        public let kind: String
        public let name: String?
        public let path: String?
        public let range: [Int]?
        public let failed: Bool?
        public let problem: String?
        public let lines: [ArtifactLine]?
        public let total: Int?
        public let truncated: Bool?
        public let changed_since: Bool?
        public let diff: String?
        public let command: String?
        public let output: String?
        public let focus: Int?

        public init(id: String, kind: String, name: String? = nil, path: String? = nil, range: [Int]? = nil, failed: Bool? = nil, problem: String? = nil, lines: [ArtifactLine]? = nil, total: Int? = nil, truncated: Bool? = nil, changed_since: Bool? = nil, diff: String? = nil, command: String? = nil, output: String? = nil, focus: Int? = nil) {
            self.id = id
            self.kind = kind
            self.name = name
            self.path = path
            self.range = range
            self.failed = failed
            self.problem = problem
            self.lines = lines
            self.total = total
            self.truncated = truncated
            self.changed_since = changed_since
            self.diff = diff
            self.command = command
            self.output = output
            self.focus = focus
        }
    }

    public struct VoiceLock: Decodable, Equatable, Sendable {
        public var level: String?              // off, approvals, commands, everything
        public let enrolled: Bool?
        public let devices: [VoiceDevice]?
        public let enrolling: Enrolling?
        public let lines: [String]?
        public let model: String?              // missing, downloading, ready, failed
        public let problem: String?
        public let ignored: Ignored?
        public let speaker: Verdict?
        public let unsure_streak: Int?

        public var isEnrolled: Bool { enrolled == true }
        public var lockLevel: VoiceLockLevel { VoiceLockLevel(rawValue: level ?? "off") ?? .off }

        public init(level: String? = nil, enrolled: Bool? = nil, devices: [VoiceDevice]? = nil, enrolling: Enrolling? = nil, lines: [String]? = nil, model: String? = nil, problem: String? = nil, ignored: Ignored? = nil, speaker: Verdict? = nil, unsure_streak: Int? = nil) {
            self.level = level
            self.enrolled = enrolled
            self.devices = devices
            self.enrolling = enrolling
            self.lines = lines
            self.model = model
            self.problem = problem
            self.ignored = ignored
            self.speaker = speaker
            self.unsure_streak = unsure_streak
        }
    }

    public struct VoiceDevice: Decodable, Equatable, Identifiable, Sendable {
        public let device: String
        public let seconds: Double?
        public let segments: Int?
        public let enrolled_at: Double?
        public var id: String { device }

        public init(device: String, seconds: Double? = nil, segments: Int? = nil, enrolled_at: Double? = nil) {
            self.device = device
            self.seconds = seconds
            self.segments = segments
            self.enrolled_at = enrolled_at
        }
    }

    public struct Enrolling: Decodable, Equatable, Sendable {
        public let device: String?
        public let progress: Double?           // 0...1
        public let line: Int?
        public let text: String?               // the line to read aloud
        public let seconds: Double?
        public let segments: Int?
        public let rejected: Int?
        public let last_reason: String?        // why the last segment did not count; empty when it did

        public init(device: String? = nil, progress: Double? = nil, line: Int? = nil, text: String? = nil, seconds: Double? = nil, segments: Int? = nil, rejected: Int? = nil, last_reason: String? = nil) {
            self.device = device
            self.progress = progress
            self.line = line
            self.text = text
            self.seconds = seconds
            self.segments = segments
            self.rejected = rejected
            self.last_reason = last_reason
        }
    }

    public struct Ignored: Decodable, Equatable, Sendable {
        public let count: Int?
        public let last_at: Double?
        public let recent: [IgnoredSpeech]?

        public init(count: Int? = nil, last_at: Double? = nil, recent: [IgnoredSpeech]? = nil) {
            self.count = count
            self.last_at = last_at
            self.recent = recent
        }
    }

    public struct IgnoredSpeech: Decodable, Equatable, Hashable, Sendable {
        public let at: Double
        public let secs: Double?
        public let text: String?               // only at the Commands level

        public init(at: Double, secs: Double? = nil, text: String? = nil) {
            self.at = at
            self.secs = secs
            self.text = text
        }
    }

    public struct Verdict: Decodable, Equatable, Sendable {
        public let owner: Bool?
        public let score: Double?
        public let at: Double?

        public init(owner: Bool? = nil, score: Double? = nil, at: Double? = nil) {
            self.owner = owner
            self.score = score
            self.at = at
        }
    }

    /// The Mac's microphone gate. `open` is the truth the ring shows.
    public struct PTTStatus: Decodable, Equatable, Sendable {
        public let mode: String?        // "always" or "ptt"
        public let open: Bool?
        public let closed_why: String?  // "released", "held too long", "no audio", "switched to push to talk"
        public let room_heard: Bool?    // a meeting is on: the room reaches the meeting without a press; talking to Pointe still needs one
        public let draft: Bool?         // `hearing` is a press's words, sent as one message when it closes; nil from an older Mac

        public init(mode: String? = nil, open: Bool? = nil, closed_why: String? = nil, room_heard: Bool? = nil, draft: Bool? = nil) {
            self.mode = mode
            self.open = open
            self.closed_why = closed_why
            self.room_heard = room_heard
            self.draft = draft
        }
    }

    public struct Meeting: Decodable, Equatable, Sendable {
        public let on: Bool?
        public let id: String?             // the meeting on now; an ended meeting's status has none
        public let ending: Bool?           // the end pass (the summary) is running
        public let ended: Bool?
        public let mode: String?           // "listening" or "participating"
        public let since: Double?          // epoch seconds
        public let speakers: [Speaker]?
        public let owner_known: Bool?
        public let hand: Hand?
        public let speaking: Bool?
        public let paused: Bool?
        public let vendors: Vendors?
        public let recording: Bool?
        public let sessions: [String]?
        public let auto_lookups: Bool?
        public let turns: Int?
        public let result: MeetingResult?  // after the end

        public var isOn: Bool { on == true }
        public var isEnding: Bool { on == true && ending == true }
        public var isEnded: Bool { on != true && ended == true }
        public var participating: Bool { mode == "participating" }

        public init(on: Bool? = nil, id: String? = nil, ending: Bool? = nil, ended: Bool? = nil, mode: String? = nil, since: Double? = nil, speakers: [Speaker]? = nil, owner_known: Bool? = nil, hand: Hand? = nil, speaking: Bool? = nil, paused: Bool? = nil, vendors: Vendors? = nil, recording: Bool? = nil, sessions: [String]? = nil, auto_lookups: Bool? = nil, turns: Int? = nil, result: MeetingResult? = nil) {
            self.on = on
            self.id = id
            self.ending = ending
            self.ended = ended
            self.mode = mode
            self.since = since
            self.speakers = speakers
            self.owner_known = owner_known
            self.hand = hand
            self.speaking = speaking
            self.paused = paused
            self.vendors = vendors
            self.recording = recording
            self.sessions = sessions
            self.auto_lookups = auto_lookups
            self.turns = turns
            self.result = result
        }
    }

    public struct Speaker: Decodable, Equatable, Identifiable, Hashable, Sendable {
        public let label: String
        public let name: String?
        public let is_owner: Bool?
        public let turns: Int?
        public var id: String { label }
        public var shown: String { is_owner == true ? "You" : (name.flatMap { $0.isEmpty ? nil : $0 } ?? "Speaker \(label)") }

        public init(label: String, name: String? = nil, is_owner: Bool? = nil, turns: Int? = nil) {
            self.label = label
            self.name = name
            self.is_owner = is_owner
            self.turns = turns
        }
    }

    public struct Hand: Decodable, Equatable, Sendable {
        public let line: String
        public let at: Double?
        public let urgency: String?

        public init(line: String, at: Double? = nil, urgency: String? = nil) {
            self.line = line
            self.at = at
            self.urgency = urgency
        }
    }

    public struct Vendors: Decodable, Equatable, Sendable {
        public let room_audio: String?
        public let notes: String?
        public let speech: String?
        public let commands: String?

        public init(room_audio: String? = nil, notes: String? = nil, speech: String? = nil, commands: String? = nil) {
            self.room_audio = room_audio
            self.notes = notes
            self.speech = speech
            self.commands = commands
        }
    }

    public struct ActionItem: Decodable, Equatable, Hashable, Sendable {
        public let what: String
        public let owner: String?
        public let due: String?

        public init(what: String, owner: String? = nil, due: String? = nil) {
            self.what = what
            self.owner = owner
            self.due = due
        }
    }

    public struct MeetingResult: Decodable, Equatable, Sendable {
        public let summary: String?
        public let decisions: [String]?
        public let action_items: [ActionItem]?
        public let open_questions: [String]?

        public init(summary: String? = nil, decisions: [String]? = nil, action_items: [ActionItem]? = nil, open_questions: [String]? = nil) {
            self.summary = summary
            self.decisions = decisions
            self.action_items = action_items
            self.open_questions = open_questions
        }
    }

    public struct NotesVersion: Decodable, Equatable, Sendable {
        public let version: Int?
        public let last_id: Int?

        public init(version: Int? = nil, last_id: Int? = nil) {
            self.version = version
            self.last_id = last_id
        }
    }

    public struct Attention: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let kind: String?
        public let text: String?
        public let session: String?
        // What a notification may show and do (alerts.py); an older Mac sends none, and gets no notifications.
        public var request_id: String? = nil
        public var title: String? = nil
        public var body: String? = nil
        public var approvable: Bool? = nil
        // The user is at the Mac: post nothing for it yet (the Mac decides; an older Mac sends none).
        public var quiet: Bool? = nil

        public init(id: String, kind: String? = nil, text: String? = nil, session: String? = nil, request_id: String? = nil, title: String? = nil, body: String? = nil, approvable: Bool? = nil, quiet: Bool? = nil) {
            self.id = id
            self.kind = kind
            self.text = text
            self.session = session
            self.request_id = request_id
            self.title = title
            self.body = body
            self.approvable = approvable
            self.quiet = quiet
        }
    }

    public struct Note: Decodable, Equatable, Identifiable, Sendable {
        public let id: Int
        public let kind: String            // thought, question, answer, action, decision, hand, session_news, brief, summary, speaker
        public let at: Double?
        public let updated: Double?
        public let text: String
        public let meta: NoteMeta?
        public let speakers: [String]?
        public let session: String?
        public let state: String?          // open, done, dismissed
        public var meeting: String? = nil  // the meeting it was written in; older daemons send none
        public var rev: Int? = nil         // the notes version when it last changed

        public init(id: Int, kind: String, at: Double? = nil, updated: Double? = nil, text: String, meta: NoteMeta? = nil, speakers: [String]? = nil, session: String? = nil, state: String? = nil, meeting: String? = nil, rev: Int? = nil) {
            self.id = id
            self.kind = kind
            self.at = at
            self.updated = updated
            self.text = text
            self.meta = meta
            self.speakers = speakers
            self.session = session
            self.state = state
            self.meeting = meeting
            self.rev = rev
        }
    }

    public struct NoteMeta: Decodable, Equatable, Sendable {
        public let why: String?
        public let asked_by: String?
        public let owner: String?
        public let due: String?
        public let label: String?          // a suggested speaker name: which label
        public let name: String?           // and the name
        public let full: String?           // a raised hand's whole point
        public let lookup: Lookup?         // a question a linked session can answer

        public init(why: String? = nil, asked_by: String? = nil, owner: String? = nil, due: String? = nil, label: String? = nil, name: String? = nil, full: String? = nil, lookup: Lookup? = nil) {
            self.why = why
            self.asked_by = asked_by
            self.owner = owner
            self.due = due
            self.label = label
            self.name = name
            self.full = full
            self.lookup = lookup
        }
    }

    public struct Lookup: Decodable, Equatable, Sendable {
        public let session: String?
        public let how: String?

        public init(session: String? = nil, how: String? = nil) {
            self.session = session
            self.how = how
        }
    }

    public struct NotesPage: Decodable, Sendable {
        public let version: Int?
        public let notes: [Note]?

        public init(version: Int? = nil, notes: [Note]? = nil) {
            self.version = version
            self.notes = notes
        }
    }

    public struct TranscriptTurn: Decodable, Equatable, Identifiable, Sendable {
        public let id: Int
        public let who: String?
        public let speaker: String?
        public let at: Double?
        public let lang: String?
        public let text: String

        public init(id: Int, who: String? = nil, speaker: String? = nil, at: Double? = nil, lang: String? = nil, text: String) {
            self.id = id
            self.who = who
            self.speaker = speaker
            self.at = at
            self.lang = lang
            self.text = text
        }
    }

    public struct Transcript: Decodable, Sendable {
        public let turns: [TranscriptTurn]?

        public init(turns: [TranscriptTurn]? = nil) {
            self.turns = turns
        }
    }

    public struct VendorsReply: Decodable, Sendable {
        public let vendors: Vendors?
        public let soniox: Bool?

        public init(vendors: Vendors? = nil, soniox: Bool? = nil) {
            self.vendors = vendors
            self.soniox = soniox
        }
    }

    public struct Prefs: Decodable, Equatable, Sendable {
        public var defaultMode: String
        public var autoLookups: Bool
        public var notesLanguage: String
        public var consented: Bool
        public var microphone: String  // "always" or "ptt"
        public var conflictsOn: Bool
        public var conflictsSpoken: Bool
        public var watchApprove: Bool  // Approve on a notification, without Face ID
        public var showOnPhone: Bool   // show while it says on this phone: off until turned on
        public var patience: String    // "turns.patience": quick, normal or patient (Turns.swift)

        enum CodingKeys: String, CodingKey {
            case defaultMode = "meeting.default_mode", autoLookups = "meeting.auto_lookups"
            case notesLanguage = "meeting.notes_language", consented = "meeting.consented", microphone
            case conflictsOn = "conflicts.on", conflictsSpoken = "conflicts.spoken"
            case watchApprove = "alerts.watch_approve"
            case showOnPhone = "show.on_phone"
            case patience = "turns.patience"
        }

        public init(from decoder: Decoder) throws {
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
        }
    }

    public struct Turn: Decodable, Equatable, Hashable, Identifiable, Sendable {
        public let id: Int             // stable while the turn is in the window
        public let who: String         // "user" or "assistant"
        public let text: String
        public let understood: String? // the cleaned-up wording, when "clean up my words" is on
        public let typed: Bool?
        public let corrected: Bool?
        public var mine: Bool { who == "user" }

        public init(id: Int, who: String, text: String, understood: String? = nil, typed: Bool? = nil, corrected: Bool? = nil) {
            self.id = id
            self.who = who
            self.text = text
            self.understood = understood
            self.typed = typed
            self.corrected = corrected
        }
    }

    public struct Monologue: Decodable, Equatable, Sendable {
        public let said: String

        public init(said: String) {
            self.said = said
        }
    }

    public struct Hold: Decodable, Equatable, Sendable {
        public let since: Double?
        public let said: String

        public init(since: Double? = nil, said: String) {
            self.since = since
            self.said = said
        }
    }

    public struct Session: Decodable, Identifiable, Equatable, Sendable {
        public let name: String
        public let working: Bool
        public let waiting: Bool
        public let request: String?       // the exact request: what a tap approves
        public let request_id: String?
        public let voice_can_approve: Bool?
        public let needs: String?
        /// Which coding agent runs it: "claude-code", "opencode", "codex"... Older daemons send nothing: Claude Code.
        public let harness: String?
        public let capabilities: Capabilities?
        /// The machine it runs on; nil or empty is this Mac. Older Macs send neither field.
        public var machine: String? = nil
        /// False while its machine is offline: sends are refused and its prompt is back in its terminal.
        public var online: Bool? = nil
        public var id: String { name }
        public var isOffline: Bool { online == false }

        public var agent: String { Harness.mark(harness).name }
        /// An agent without approvals (Pi, for one) never gets Approve or Deny.
        public var canApprove: Bool { capabilities?.approvals != false }

        public init(name: String, working: Bool, waiting: Bool, request: String? = nil, request_id: String? = nil, voice_can_approve: Bool? = nil, needs: String? = nil, harness: String? = nil, capabilities: Capabilities? = nil, machine: String? = nil, online: Bool? = nil) {
            self.name = name
            self.working = working
            self.waiting = waiting
            self.request = request
            self.request_id = request_id
            self.voice_can_approve = voice_can_approve
            self.needs = needs
            self.harness = harness
            self.capabilities = capabilities
            self.machine = machine
            self.online = online
        }
    }

    public struct Capabilities: Decodable, Equatable, Sendable {
        public let approvals: Bool?
        public let side_questions: Bool?
        public let attach: Bool?
        public let spawn: Bool?

        public init(approvals: Bool? = nil, side_questions: Bool? = nil, attach: Bool? = nil, spawn: Bool? = nil) {
            self.approvals = approvals
            self.side_questions = side_questions
            self.attach = attach
            self.spawn = spawn
        }
    }

    /// A reply that was not a success: the HTTP status and the daemon's own reason (`detail`), or "HTTP <code>".
    public enum Failure: Error, Equatable, Sendable { case status(Int, String) }
}
