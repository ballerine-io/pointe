import XCTest
@testable import PointeUI

/// The dictionary: the daemon's contract decodes (and an older daemon without it still does), the toast shows each
/// learned name once and never one from before the app was following, a refusal shows the Mac's own reason, and the
/// copy is the page's, word for word.
final class VocabularyTests: XCTestCase {
    private func status(_ json: String) throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testAnOlderDaemonWithoutTheDictionaryStillDecodes() throws {
        XCTAssertNil(try status(#"{"connected": true, "sessions": []}"#).dictionary)
    }

    func testTheStatusContractDecodes() throws {
        let s = try status(#"""
        {"connected": true, "sessions": [],
         "dictionary": {"count": 2, "cap": 400, "full": false, "learn": true, "problem": null,
                        "learned_this_call": [{"term": "Quillfeather", "at": 1762900000.5}]}}
        """#)
        let d = try XCTUnwrap(s.dictionary)
        XCTAssertEqual(d.count, 2)
        XCTAssertEqual(d.learned_this_call?.map(\.term), ["Quillfeather"])
    }

    func testThePageContractDecodes() throws {
        let page = try JSONDecoder().decode(API.DictionaryPage.self, from: Data(#"""
        {"count": 2, "cap": 400, "full": false, "learn": true, "learned_this_call": [], "problem": null,
         "entries": [{"term": "Quillfeather", "lang": "en", "source": "correction", "hits": 3, "added_at": 1762900000, "confirmed": true},
                     {"term": "ליאורה", "lang": "he", "source": "manual", "hits": 0, "added_at": 1762900001, "confirmed": true}],
         "ignored": ["Zentrak"], "suggestions": [{"term": "Kestrelbay", "session": "river-lantern", "lang": "en"}]}
        """#.utf8))
        XCTAssertEqual(page.entries.map(\.term), ["Quillfeather", "ליאורה"])
        XCTAssertEqual(page.suggestions?.first?.session, "river-lantern")
        XCTAssertEqual(page.ignored, ["Zentrak"])
    }

    func testEachLearnedNameIsToastedOnceAndNoneFromBeforeTheAppFollowed() {
        var toasts = LearnedToasts()
        let before = API.DictionaryStatus(count: 1, cap: 400, full: false, learn: true,
                                          learned_this_call: [.init(term: "Marrowind", at: 1)], problem: nil)
        XCTAssertEqual(toasts.fresh(before), [], "the first status only seeds: a relaunch mid-call toasts nothing old")
        let after = API.DictionaryStatus(count: 2, cap: 400, full: false, learn: true,
                                         learned_this_call: [.init(term: "Marrowind", at: 1), .init(term: "Quillfeather", at: 2)], problem: nil)
        XCTAssertEqual(toasts.fresh(after), ["Quillfeather"])
        XCTAssertEqual(toasts.fresh(after), [], "never twice")
        XCTAssertEqual(toasts.fresh(nil), [], "a failed poll is not news")
        let relearned = API.DictionaryStatus(count: 2, cap: 400, full: false, learn: true,
                                             learned_this_call: [.init(term: "Quillfeather", at: 9)], problem: nil)
        XCTAssertEqual(toasts.fresh(relearned), ["Quillfeather"], "undone and learned again is new")
    }

    func testARefusalShowsTheMacsOwnReason() {
        XCTAssertEqual(VocabularyFailure.from(API.Failure.status(400, "a yes, no or stop word: it would bias what counts as an answer")).message,
                       "a yes, no or stop word: it would bias what counts as an answer")
        XCTAssertEqual(VocabularyFailure.from(API.Failure.status(500, "HTTP 500")).message, VocabularyCopy.notSaved)
        XCTAssertEqual(VocabularyFailure.from(URLError(.timedOut)).message, VocabularyCopy.unreachable)
    }

    func testLabels() {
        XCTAssertEqual(VocabularyCopy.lang("both"), "EN + HE")
        XCTAssertEqual(VocabularyCopy.source("correction"), "you fixed it")
        XCTAssertEqual(VocabularyCopy.source("manual"), "you added it")
        XCTAssertEqual(VocabularyCopy.source("session"), "from a session")
        XCTAssertEqual(VocabularyCopy.learned(["Quillfeather", "Marrowind"]), "Learned: Quillfeather, Marrowind")
        XCTAssertEqual(VocabularyCopy.full(400), "Full (400). Delete one to add another.")
    }

    func testTheDemoRefusesAConsentWordAsTheMacDoes() {
        var demo = DemoDictionary()
        if case .success = demo.apply(["action": "add", "term": "okay"]) { XCTFail("a consent word is refused") }
        if case .failure = demo.apply(["action": "add", "term": "Tarnwick"]) { XCTFail("a name is added") }
        XCTAssertTrue(demo.page.entries.contains { $0.term == "Tarnwick" })
    }

    /// The page and the app say the same thing (docs/design/2026-11-feature-plan.md: parity).
    func testTheCopyIsThePagesWordForWord() throws {
        let html = try Repo.text("ui_dictionary.html")
        let page = html.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
        for copy in [VocabularyCopy.title, VocabularyCopy.lede, VocabularyCopy.addPlaceholder, VocabularyCopy.empty,
                     VocabularyCopy.suggestions, VocabularyCopy.learn, VocabularyCopy.learnHelp, VocabularyCopy.appliesNext,
                     VocabularyCopy.undo,
                     "you fixed it", "you added it", "from a session", "EN + HE", "Full (", "Delete one to add another.", "Learned: "] {
            XCTAssertTrue(page.contains(copy), "the page says: \(copy)")
        }
    }
}
