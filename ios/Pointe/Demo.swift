import SwiftUI

/// Sample calls for looking at the screens without a Mac. Every name and word here is made up. Two ways in:
/// `-demo [call|sessions|edit|typing|request]` at launch (Debug builds only, for tests and screenshots), and
/// "Try a demo" on the pairing screen (every build: App Review has no Mac to pair with), which shows the Demo badge.
struct Demo {
    enum Screen: String { case call, sessions, edit, typing, request, brainstorm, meetingStart, meeting, meetingHand, meetingEnd, talking,
                       voiceLock, voiceLockEnrolling, voiceLockEnrolled, briefing, briefingPaused,
                       showing, showingOff, challenge, challengeEnded, conflict, conflictMeeting, dictionary, dictionaryLearned, drive,
                       whisper, whisperOff, rtl, machines, machinesOne, machinesOffline, machinesDrive }
    let screen: Screen
    let status: API.Status
    var notes: [API.Note] = []
    /// Entered from "Try a demo": the header says Demo and offers the way out.
    var tried = false

    static func fromLaunch() -> Demo? {
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        guard let i = args.firstIndex(of: "-demo") else { return nil }
        return make(args.indices.contains(i + 1) ? Screen(rawValue: args[i + 1]) ?? .call : .call)
        #else
        return nil
        #endif
    }

    /// "Try a demo": a call with a request waiting, so the approval card, the conversation and the sessions all show.
    static var tryIt: Demo? {
        guard var demo = make(.request) else { return nil }
        demo.tried = true
        return demo
    }

    static func make(_ screen: Screen) -> Demo? {
        let json = switch screen {
        case .request: requestJSON
        case .drive: driveJSON
        case .brainstorm: brainstormJSON
        case .meeting: meetingJSON(hand: false)
        case .meetingHand: meetingJSON(hand: true)
        case .meetingEnd: meetingEndJSON
        case .talking: talkingJSON
        case .voiceLock: voiceLockJSON(lockNew)
        case .voiceLockEnrolling: voiceLockJSON(lockEnrolling)
        case .voiceLockEnrolled: voiceLockJSON(lockEnrolled, request: true)
        case .conflict: conflictJSON
        case .conflictMeeting: conflictMeetingJSON
        case .briefing: briefingJSON(paused: false)
        case .briefingPaused: briefingJSON(paused: true)
        case .showing: showingJSON(on: true)
        case .showingOff: showingJSON(on: false)
        case .challenge: challengeJSON(on: true)
        case .challengeEnded: challengeJSON(on: false)
        case .dictionary, .dictionaryLearned: dictionaryJSON(learned: screen == .dictionaryLearned)
        case .whisper, .whisperOff: whisperJSON(on: screen == .whisper)
        case .rtl: rtlJSON
        case .machines, .machinesOne, .machinesOffline, .machinesDrive: machinesJSON(screen)  // Settings.swift
        default: callJSON
        }
        guard let status = try? JSONDecoder().decode(API.Status.self, from: Data(json.utf8)) else { return nil }
        let notes = (try? JSONDecoder().decode([API.Note].self, from: Data(notesJSON.utf8))) ?? []
        return Demo(screen: screen, status: status, notes: [.meeting, .meetingHand, .meetingEnd].contains(screen) ? notes : [])
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

    /// The dictionary in status: the menu item shows; with `learned`, a fix just taught "Quillfeather" (the toast).
    private static func dictionaryJSON(learned: Bool) -> String {
        """
        {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false,
         "sessions": \(sessions), "talk": \(talk),
         "dictionary": {"count": 2, "cap": 400, "full": false, "learn": true, "problem": null,
                        "learned_this_call": \(learned ? "[{\"term\": \"Quillfeather\", \"at\": 1}]" : "[]")}}
        """
    }

    /// Whisper mode from the Mac: on (with the voice lock at Approvals, and push to talk off, so both notes show), or off.
    private static func whisperJSON(on: Bool) -> String {
        let note = "Your voiceprint was learned from your normal voice. A whispered yes may not match it: then tap to approve."
        let whisper = on ? "{\"on\": true, \"output_gain\": 0.5, \"max_words\": 20, \"suggest_ptt\": true, \"lock_note\": \"\(note)\"}"
                         : "{\"on\": false, \"output_gain\": 1.0, \"max_words\": null, \"suggest_ptt\": false, \"lock_note\": null}"
        return """
        {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false,
         "hearing": "ask billing whether the retry fix landed", "sessions": \(sessions), "talk": \(talk),
         "whisper": \(whisper)}
        """
    }

    /// Right-to-left messages: Hebrew, Arabic, a sentence that starts in Hebrew with English inside, and English.
    private static let rtlJSON = """
    {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false,
     "hearing": "תבדוק את ה-retry ב-billing.", "sessions": \(sessions),
     "talk": [{"id": 1, "who": "user", "text": "מה המצב של billing?", "typed": false, "corrected": false},
              {"id": 2, "who": "assistant", "text": "הוא סיים את התיקון. הבדיקות עוברות."},
              {"id": 3, "who": "user", "text": "أرسل الإصلاح للمراجعة.", "typed": false, "corrected": false},
              {"id": 4, "who": "assistant", "text": "פתחתי PR חדש ל-billing. הוא מעלה את ה-timeout לשלושים שניות ומוסיף בדיקה לכפל חיובים בזמן failover."},
              {"id": 5, "who": "user", "text": "And tell docs to update the changelog.", "typed": false, "corrected": false}]}
    """

    private static let callJSON = """
    {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": true,
     "hearing": "and after that ask river lantern whether the retry", "sessions": \(sessions), "talk": \(talk),
     "local": {"mode": "voice", "models": "ready", "line": "Voice stays on your Mac: on · models on this Mac"},
     "tokens": {"context": 12480, "at": "10:42:07"},
     "recent": [{"at": "10:41:50", "said": "tell docs to update the change log", "to": ["docs"], "how": "(named)"},
                {"at": "10:42:01", "said": "push it", "to": [], "how": "blocked: ambiguous between billing/main and docs"}]}
    """

    /// Push to talk, held open on the Mac: the ring and the state line show the Mac's gate.
    private static let talkingJSON = """
    {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false,
     "hearing": "ask docs whether the changelog", "sessions": \(sessions), "talk": \(talk),
     "ptt": {"mode": "ptt", "open": true, "closed_why": ""}}
    """

    // MARK: conflict alarm

    private static let conflicts = """
    [{"id": "c0ffee01", "a": "river-lantern", "b": "billing/main", "agent_a": "Codex", "agent_b": "Claude",
      "claim_a": "The migration adding the refund_reason column ran on staging and passed.",
      "claim_b": "The refunds test that reads refund_reason failed on staging: the column does not exist.",
      "at_a": 1700000000, "at_b": 1700000720, "at": 1700000725, "why": "The column cannot both exist and be missing.",
      "severity": "high", "questions": {"a": "Which database did the migration run against?", "b": "Which database did the test use?"},
      "branches": null, "asked": [], "state": "open"}]
    """

    private static let conflictJSON = """
    {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
     "sessions": \(sessions), "talk": \(talk), "conflicts": \(conflicts),
     "attention": [{"id": "conflict:c0ffee01", "kind": "conflict", "text": "river-lantern and billing/main disagree"}]}
    """

    private static var conflictMeetingJSON: String {
        meetingJSON(hand: false).replacingOccurrences(of: #""notes": {"#, with: #""conflicts": \#(conflicts), "notes": {"#)
    }

    // MARK: audio briefings

    /// A scheduled briefing waits (the banner), or one is paused after its first part.
    private static func briefingJSON(paused: Bool) -> String {
        let briefing = paused
            ? #"{"playing": false, "paused": "question", "part": 1, "parts": 3, "id": "b7c1", "building": false, "latest_id": "b7c1", "ready": null}"#
            : #"{"playing": false, "paused": "", "part": 0, "parts": 0, "id": null, "building": false, "latest_id": "b7c1", "ready": {"id": "b7c1", "at": 1700000000, "slot": "2026-11-12 08:30", "empty": false}}"#
        let attention = paused ? "[]" : #"[{"id": "briefing:b7c1", "kind": "briefing", "text": "Your 08:30 briefing is ready."}]"#
        return """
        {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
         "sessions": \(sessions), "talk": \(talk), "attention": \(attention), "briefing": \(briefing)}
        """
    }

    static let briefingsPage = try? JSONDecoder().decode(API.BriefingsPage.self, from: Data(briefingsJSON.utf8))

    private static let briefingsJSON = """
    {"briefings": [
      {"id": "b7c1", "at": 1700000000, "since": 1699970000, "since_label": "overnight", "length": "normal", "scheduled": true,
       "slot": "2026-11-12 08:30", "heard": false, "empty": false,
       "opener": "Three sessions overnight. river-lantern needs you; billing/main failed; docs is done.",
       "sections": [{"session": "river-lantern", "status": "waiting", "text": "river-lantern waits for your answer on the retry budget."},
                    {"session": "billing/main", "status": "failed", "text": "billing/main: 2 of 40 checkout tests failed after the retry change."},
                    {"session": "docs", "status": "done", "text": "docs updated the changelog and opened a PR."}]},
      {"id": "a1f0", "at": 1699900000, "since": 1699880000, "since_label": "today", "length": "short", "scheduled": false,
       "slot": "", "heard": true, "empty": true, "opener": "Quiet today. Nothing waits on you.", "sections": []}],
     "schedule": {"time": "08:30", "days": [0, 1, 2, 3, 4], "length": "normal", "speak_on_connect": true, "skip_empty": false},
     "status": null}
    """

    // MARK: owner-voice lock

    private static func voiceLockJSON(_ lock: String, request: Bool = false) -> String {
        let billing = request
            ? #"{"name": "billing/main", "working": true, "waiting": true, "needs": null, "request": "git push origin retry-fix", "request_id": "ef56ab78", "voice_can_approve": true}"#
            : #"{"name": "billing/main", "working": true, "waiting": false, "needs": null}"#
        return """
        {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
         "sessions": [\(billing), {"name": "docs", "working": false, "waiting": false, "needs": null}], "talk": \(talk),
         "voice_lock": \(lock)}
        """
    }

    private static let lockLines = #"["The quick brown fox jumps over the lazy dog.", "Pack my box with five dozen jugs.", "Bright vixens jump; dozy fowl quack.", "שלום, זה הקול שלי.", "היום יום יפה לתכנת.", "אני מדבר בקצב רגיל."]"#

    private static let lockNew = """
    {"level": "off", "enrolled": false, "devices": [], "enrolling": null, "lines": \(lockLines), "model": "ready",
     "problem": null, "ignored": {"count": 0, "last_at": null, "recent": []}, "speaker": null, "unsure_streak": 0}
    """

    private static let lockEnrolling = """
    {"level": "off", "enrolled": false, "devices": [], "lines": \(lockLines), "model": "downloading", "problem": null,
     "enrolling": {"device": "iPhone", "progress": 0.42, "line": 2, "text": "Pack my box with five dozen jugs.",
                   "seconds": 10.5, "segments": 2, "rejected": 1, "last_reason": "too quiet"},
     "ignored": {"count": 0, "last_at": null, "recent": []}, "speaker": null, "unsure_streak": 0}
    """

    private static let lockEnrolled = """
    {"level": "approvals", "enrolled": true, "enrolling": null, "lines": \(lockLines), "model": "ready", "problem": null,
     "devices": [{"device": "iPhone", "seconds": 31.2, "segments": 6, "enrolled_at": 1700000000},
                 {"device": "iPhone · AirPods Pro", "seconds": 28.4, "segments": 5, "enrolled_at": 1700003600}],
     "ignored": {"count": 2, "last_at": 1700007300, "recent": [{"at": 1700007200, "secs": 1.8},
                 {"at": 1700007300, "secs": 2.4, "text": "tell docs to delete the branch"}]},
     "speaker": {"owner": false, "score": 0.31, "at": 1700007300}, "unsure_streak": 3}
    """

    // MARK: show while it says

    private static let shownArtifacts = """
    [{"id": "s3a0", "kind": "test", "name": "test output", "path": "", "range": null, "failed": true},
     {"id": "s3a1", "kind": "edit", "name": "pricing.py", "path": "billing/pricing.py", "range": [40, 42], "failed": false},
     {"id": "s3a2", "kind": "read", "name": "test_pricing.py", "path": "tests/test_pricing.py", "range": null, "failed": false},
     {"id": "s3a3", "kind": "edit", "name": ".env", "path": ".env", "range": null, "failed": false, "refused": "a hidden file: not shown"}]
    """

    /// The Mac's own gate: off, it sends no showing at all.
    private static func showingJSON(on: Bool) -> String {
        let showing = on ? """
        {"id": "s3", "session": "billing/main", "since": 1700000000, "summary": "pricing.py · edited 40–42 · 1 failing test",
         "current": "s3a1", "artifacts": \(shownArtifacts)}
        """ : "null"
        let earlier = on ? """
        [{"id": "s3", "session": "billing/main", "at": 1700000000, "summary": "pricing.py · edited 40–42 · 1 failing test", "artifacts": \(shownArtifacts)},
         {"id": "s2", "session": "docs", "at": 1699999000, "summary": "changelog.md · edited 3–9",
          "artifacts": [{"id": "s2a0", "kind": "edit", "name": "changelog.md", "path": "changelog.md", "range": [3, 9], "failed": false}]}]
        """ : "[]"
        return """
        {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
         "sessions": \(sessions), "talk": \(talk), "showing": \(showing), "shown_earlier": \(earlier), "show_on_phone": \(on)}
        """
    }

    static func artifact(_ id: String) -> API.ArtifactView? {
        let lines = (20...62).map { n -> String in
            let text = n == 40 ? "    for attempt in range(retries):" : n == 41 ? "        delay = backoff(attempt)" : n == 42 ? "        await sleep(delay)" : "    # step \(n)"
            return #"{"n": \#(n), "text": "\#(text)", "hl": \#((40...42).contains(n))}"#
        }.joined(separator: ",")
        let json: String? = switch id {
        case "s3a0": #"{"id": "s3a0", "kind": "test", "name": "test output", "failed": true, "command": "uv run pytest -q tests/test_pricing.py", "output": "tests/test_pricing.py::test_discount FAILED\n    assert price(100, 'GOLD') == 80\nE   AssertionError: assert 90 == 80\n=========== 1 failed, 4 passed in 0.31s ===========", "focus": 1}"#
        case "s3a1": #"{"id": "s3a1", "kind": "edit", "name": "pricing.py", "path": "billing/pricing.py", "range": [40, 42], "lines": [\#(lines)], "total": 100, "changed_since": false, "diff": "--- a/billing/pricing.py\n+++ b/billing/pricing.py\n@@ -38,5 +38,5 @@\n     # step 38\n-    for attempt in range(5):\n+    for attempt in range(retries):\n         delay = backoff(attempt)"}"#
        case "s3a2": #"{"id": "s3a2", "kind": "read", "name": "test_pricing.py", "path": "tests/test_pricing.py", "lines": [{"n": 1, "text": "def test_discount():", "hl": false}, {"n": 2, "text": "    assert price(100, 'GOLD') == 80", "hl": false}], "changed_since": true}"#
        case "s2a0": #"{"id": "s2a0", "kind": "edit", "name": "changelog.md", "path": "changelog.md", "range": [3, 9], "problem": "no longer there"}"#
        default: nil
        }
        return json.flatMap { try? JSONDecoder().decode(API.ArtifactView.self, from: Data($0.utf8)) }
    }

    // MARK: challenge me

    /// A challenge on, two objections and an answer in Hebrew; or ended, with its verdict, until closed.
    private static func challengeJSON(on: Bool) -> String {
        let verdict = on ? "" : #", {"kind": "verdict", "text": "Ship the retry fix behind a flag; keep the queue idea shelved.", "at": 1700000300}"#
        return """
        {"active": "billing/main", "connected": true, "mode": "\(on ? "challenge" : "orchestrator")", "polish": false, "hearing": "",
         "sessions": \(sessions), "talk": \(talk),
         "challenge": {"id": "c7", "on": \(on), "since": 1700000000, "ended_at": \(on ? "null" : "1700000300"),
                       "plan": "Move the checkout retries into a queue so a slow gateway never blocks the customer.",
                       "sessions": ["billing/main"], "objections": 2, "evidence": 3,
                       "verdict": \(on ? "null" : #""Ship the retry fix behind a flag; keep the queue idea shelved.""#),
                       "items": [{"kind": "objection", "text": "A queue replays the charge on failover: billing dropped it for duplicate charges.", "at": 1700000100},
                                 {"kind": "rebuttal", "text": "נשתמש במפתח אידמפוטנטי לכל חיוב.", "at": 1700000150},
                                 {"kind": "objection", "text": "The gateway ignores that key on refunds.", "at": 1700000200}\(verdict)]}}
        """
    }

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

    /// Drive mode on, with a request a spoken yes may not answer from the road: no buttons, "I've stopped" instead.
    private static let driveJSON = """
    {"active": "billing/main", "connected": true, "mode": "orchestrator", "polish": false, "hearing": "",
     "sessions": [{"name": "billing/main", "working": true, "waiting": true, "needs": null,
                   "request": "Bash: Clean the build\\n{\\"command\\": \\"rm -rf build\\"}", "request_id": "ab12cd34", "voice_can_approve": true},
                  {"name": "docs", "working": false, "waiting": false, "needs": null}],
     "talk": \(talk),
     "drive": {"on": true, "since": 1794400000, "how": "voice",
               "pending": [{"session": "billing/main", "request_id": "ab12cd34", "voice": false}]}}
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

/// The header's mark while "Try a demo" runs: nothing here is a real Mac, and a tap goes back to pairing.
struct DemoBadge: View {
    static let label = "Demo"
    static let exit = "Exit demo"
    let tap: () -> Void

    var body: some View {
        Button(action: tap) {
            HStack(spacing: 4) {
                Text(Self.label).font(.caption.weight(.bold))
                Image(systemName: "xmark").font(.caption2.weight(.bold))
            }
            .foregroundStyle(Brand.orange)
            .padding(.horizontal, 10).frame(height: 26)
            .background(Brand.orange.opacity(0.18), in: Capsule())
            .overlay(Capsule().stroke(Brand.orange.opacity(0.6)))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Self.exit)
        .accessibilityIdentifier("demoBadge")
    }
}
