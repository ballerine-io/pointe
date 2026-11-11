import Foundation

/// Sample calls for looking at the screens without a Mac: `-demo [call|sessions|edit|typing|request]` at launch,
/// Debug builds only. Every name and word here is made up.
struct Demo {
    enum Screen: String { case call, sessions, edit, typing, request, brainstorm, meetingStart, meeting, meetingHand, meetingEnd }
    let screen: Screen
    let status: API.Status
    var notes: [API.Note] = []

    static func fromLaunch() -> Demo? {
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        guard let i = args.firstIndex(of: "-demo") else { return nil }
        let screen = args.indices.contains(i + 1) ? Screen(rawValue: args[i + 1]) ?? .call : .call
        let json = switch screen {
        case .request: requestJSON
        case .brainstorm: brainstormJSON
        case .meeting: meetingJSON(hand: false)
        case .meetingHand: meetingJSON(hand: true)
        case .meetingEnd: meetingEndJSON
        default: callJSON
        }
        guard let status = try? JSONDecoder().decode(API.Status.self, from: Data(json.utf8)) else { return nil }
        let notes = (try? JSONDecoder().decode([API.Note].self, from: Data(notesJSON.utf8))) ?? []
        return Demo(screen: screen, status: status, notes: [.meeting, .meetingHand, .meetingEnd].contains(screen) ? notes : [])
        #else
        return nil
        #endif
    }

    static let pairing = Pairing(host: "demo.invalid", port: 7443, fingerprint: String(repeating: "0", count: 64),
                                 key: String(repeating: "x", count: 32))

    private static let sessions = """
    [{"name": "billing/main", "working": true, "waiting": false, "needs": null, "harness": "claude-code"},
     {"name": "docs", "working": false, "waiting": false, "needs": null, "harness": "opencode"},
     {"name": "river-lantern", "working": false, "waiting": false, "needs": "a decision on the retry budget", "harness": "codex"}]
    """

    private static let talk = """
    [{"id": 40, "who": "user", "text": "what's billing doing", "typed": false, "corrected": false,
      "understood": "What is the billing session doing?"},
     {"id": 41, "who": "assistant", "text": "It finished the retry fix. Tests pass. It wants to know if it should open the PR."},
     {"id": 42, "who": "user", "text": "yes and tell docs to update the change log", "typed": false, "corrected": false,
      "understood": "Yes. And tell docs to update the changelog."},
     {"id": 43, "who": "assistant", "text": "Docs is on it. Billing is opening the PR."},
     {"id": 44, "who": "user", "text": "by the way why did billing drop the queue idea", "typed": true, "corrected": false},
     {"id": 45, "who": "assistant", "text": "Duplicate charges during failover. It decided that an hour ago."},
     {"id": 46, "who": "user", "text": "tell building to bump the timeout to 30 seconds", "typed": false, "corrected": true,
      "understood": "Tell billing to raise the timeout to 30 seconds."}]
    """

    private static let callJSON = """
    {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": true,
     "hearing": "and after that ask river lantern whether the retry", "sessions": \(sessions), "talk": \(talk)}
    """

    private static let brainstormJSON = """
    {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false,
     "hearing": "and maybe the cache should live per merchant", "sessions": \(sessions), "talk": \(talk),
     "monologue": {"said": "So the checkout keeps timing out for some customers. I think it's the retry loop, it retries five times with no backoff."}}
    """

    private static let requestJSON = """
    {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
     "sessions": [{"name": "billing/main", "working": true, "waiting": true, "needs": null,
                   "request": "git push --force-with-lease origin retry-fix", "request_id": "ab12cd34", "voice_can_approve": true},
                  {"name": "docs", "working": false, "waiting": false, "needs": null}],
     "talk": \(talk)}
    """

    private static let speakers = """
    [{"label": "1", "name": null, "is_owner": true, "turns": 9}, {"label": "2", "name": "Dana", "is_owner": false, "turns": 14},
     {"label": "3", "name": null, "is_owner": false, "turns": 6}]
    """

    private static func meetingJSON(hand: Bool) -> String {
        let since = Date().timeIntervalSince1970 - 1_712
        return """
        {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
         "sessions": \(sessions), "talk": [], "notes": {"version": 7, "last_id": 9},
         "meeting": {"on": true, "mode": "\(hand ? "participating" : "listening")", "since": \(since), "speakers": \(speakers),
                     "owner_known": true, "speaking": false, "paused": false, "recording": true, "turns": 29,
                     "vendors": {"room_audio": "soniox", "notes": "anthropic", "speech": "elevenlabs", "commands": "anthropic"},
                     "sessions": ["billing/main"], "auto_lookups": false,
                     "hand": \(hand ? #"{"line": "The retry fix already shipped in billing an hour ago.", "at": \#(since + 1_600), "urgency": "now"}"# : "null")}}
        """
    }

    private static let meetingEndJSON = """
    {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
     "sessions": \(sessions), "talk": [],
     "meeting": {"on": false, "ended": true, "since": 1700000000,
       "result": {"summary": "The team agreed to ship the retry fix behind a flag on Thursday. The queue idea stays shelved.",
                  "decisions": ["Ship the retry fix behind a flag", "No queue for now"],
                  "action_items": [{"what": "Open the PR for the retry fix", "owner": "You", "due": "Thursday"},
                                   {"what": "Draft the rollout note", "owner": "Dana", "due": null}],
                  "open_questions": ["What timeout does the partner gateway use?"]}}}
    """

    private static let notesJSON = """
    [{"id": 1, "kind": "brief", "at": 1700000000, "text": "Weekly sync: retry fix rollout, queue idea, partner timeouts.", "state": "open"},
     {"id": 2, "kind": "decision", "at": 1700000300, "text": "Ship the retry fix behind a flag.", "meta": {"why": "Dana and You agreed"}, "state": "open"},
     {"id": 3, "kind": "question", "at": 1700000400, "text": "What timeout does the partner gateway use?",
      "meta": {"asked_by": "Dana", "lookup": {"session": "billing/main", "how": "read-only"}}, "state": "open"},
     {"id": 4, "kind": "speaker", "at": 1700000450, "text": "Speaker 3 may be Sam", "meta": {"label": "3", "name": "Sam"}, "state": "open"},
     {"id": 5, "kind": "thought", "at": 1700000500, "text": "Nobody named who watches the error rate after the rollout.", "state": "open"},
     {"id": 6, "kind": "answer", "at": 1700000600, "text": "The billing session set the timeout to 30 seconds yesterday.", "session": "billing/main", "state": "open"},
     {"id": 7, "kind": "action", "at": 1700000700, "text": "Open the PR for the retry fix", "meta": {"owner": "You", "due": "Thursday"}, "state": "open"},
     {"id": 8, "kind": "action", "at": 1700000800, "text": "Draft the rollout note", "meta": {"owner": "Dana"}, "state": "done"}]
    """
}
