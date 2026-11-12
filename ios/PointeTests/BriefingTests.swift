import XCTest
@testable import Pointe

/// Audio briefings: the daemon's contract decodes (and an older daemon without it still does), the copy matches the
/// page's, and the phone's own reminder lands on the chosen weekdays at the chosen time.
final class BriefingTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testAnOlderDaemonWithoutBriefingsStillDecodes() throws {
        XCTAssertNil(try status(#"{"connected": true, "sessions": []}"#).briefing)
    }

    func testTheStatusContractDecodes() throws {
        let s = try status(#"""
        {"connected": true, "sessions": [],
         "attention": [{"id": "briefing:ab12", "kind": "briefing", "text": "Your 08:30 briefing is ready.", "at": 1700000000}],
         "briefing": {"playing": true, "paused": "", "part": 2, "parts": 3, "id": "ab12", "building": false,
                      "latest_id": "ab12", "ready": {"id": "ab12", "at": 1700000000, "slot": "2026-11-12 08:30", "empty": false}}}
        """#)
        let b = try XCTUnwrap(s.briefing)
        XCTAssertTrue(b.isPlaying)
        XCTAssertFalse(b.isPaused)
        XCTAssertEqual(b.ready?.slot, "2026-11-12 08:30")
        XCTAssertEqual(s.briefingAlert?.text, "Your 08:30 briefing is ready.")
    }

    func testTheHistoryContractDecodes() throws {
        let page = try JSONDecoder().decode(API.BriefingsPage.self, from: Data(#"""
        {"briefings": [{"id": "ab12", "at": 1700000000, "since": 1699960000, "since_label": "overnight", "length": "normal",
                        "sections": [{"session": "lantern", "status": "waiting", "text": "Lantern waits for your approval.",
                                      "did": "", "failed": "", "waits": "a permission approval", "clocks": ""},
                                     {"session": "billing", "status": "failed", "text": "Billing: 3 of 42 tests failed."}],
                        "opener": "Two sessions overnight. lantern needs you; billing failed.", "scheduled": true,
                        "slot": "2026-11-12 08:30", "heard": false, "empty": false}],
         "schedule": {"time": "08:30", "days": [0, 1, 2, 3, 4], "length": "short", "speak_on_connect": true, "skip_empty": false},
         "status": {"playing": false, "paused": "", "part": 0, "parts": 0, "id": null, "building": false, "latest_id": "ab12", "ready": null}}
        """#.utf8))
        XCTAssertEqual(page.briefings?.first?.sections?.map(\.session), ["lantern", "billing"])
        XCTAssertEqual(page.schedule?.days, [0, 1, 2, 3, 4])
        XCTAssertEqual(page.schedule?.length, "short")
    }

    func testChipsAndProgressMatchThePage() throws {
        XCTAssertEqual(BriefingCopy.chip("waiting"), "Needs you")
        XCTAssertEqual(BriefingCopy.chip("failed"), "Failed")
        XCTAssertEqual(BriefingCopy.chip("done"), "Done")
        XCTAssertEqual(BriefingCopy.chip("quiet"), "Quiet")
        let playing = try XCTUnwrap(try status(#"{"connected": true, "sessions": [], "briefing": {"playing": true, "paused": "", "part": 2, "parts": 3}}"#).briefing)
        XCTAssertEqual(BriefingCopy.progress(playing), "Part 2 of 3")
        let paused = try XCTUnwrap(try status(#"{"connected": true, "sessions": [], "briefing": {"playing": false, "paused": "question", "part": 1, "parts": 3}}"#).briefing)
        XCTAssertEqual(BriefingCopy.progress(paused), "Paused: part 1 of 3")
        let building = try XCTUnwrap(try status(#"{"connected": true, "sessions": [], "briefing": {"building": true}}"#).briefing)
        XCTAssertEqual(BriefingCopy.progress(building), "Reading your sessions…")
        let idle = try XCTUnwrap(try status(#"{"connected": true, "sessions": [], "briefing": {"playing": false, "paused": ""}}"#).briefing)
        XCTAssertNil(BriefingCopy.progress(idle))
    }

    func testWhyItCannotStart() {
        XCTAssertEqual(BriefingCopy.cannotStart(callUp: false, meetingOn: false), "Connect to hear it.")
        XCTAssertEqual(BriefingCopy.cannotStart(callUp: true, meetingOn: true), "Not during a meeting.")
        XCTAssertNil(BriefingCopy.cannotStart(callUp: true, meetingOn: false))
    }

    func testTheHistoryHeading() {
        var c = DateComponents()
        (c.year, c.month, c.day, c.hour, c.minute) = (2026, 11, 11, 8, 30)  // a Wednesday
        let at = Calendar.current.date(from: c)!.timeIntervalSince1970
        XCTAssertEqual(BriefingCopy.heading(at: at, since: "overnight", scheduled: true), "Wed 08:30 · overnight · scheduled")
        XCTAssertEqual(BriefingCopy.heading(at: at, since: "today", scheduled: false), "Wed 08:30 · today")
    }

    func testTheReminderLandsOnTheChosenWeekdays() {
        let t = BriefingReminder.triggers(time: "08:30", days: [0, 4, 6])  // Monday, Friday, Sunday
        XCTAssertEqual(t.map(\.weekday), [2, 6, 1])  // Apple counts Sunday as 1
        XCTAssertTrue(t.allSatisfy { $0.hour == 8 && $0.minute == 30 })
        XCTAssertEqual(BriefingReminder.triggers(time: "", days: [0, 1]), [])
        XCTAssertEqual(BriefingReminder.triggers(time: "8.30", days: [0]), [])
        XCTAssertEqual(BriefingReminder.triggers(time: "23:05", days: [9, 2]).map(\.weekday), [4])  // a day the Mac never sends is dropped
    }

    func testTheSinceChoicesAreThePages() {
        XCTAssertEqual(BriefingCopy.sinceChoices.map(\.label), ["The night", "Today", "Yesterday"])
        XCTAssertEqual(BriefingCopy.sinceChoices.map(\.since), ["the night", "today", "yesterday"])
        XCTAssertEqual(BriefingCopy.lede, "What each session did, failed and waits on, most urgent first. It reads; it never sends or approves.")
    }
}
