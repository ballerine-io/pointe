import SwiftUI

// Self-learning vocabulary (docs/features/vocabulary.md): names Pointe learned from your fixes, or that you added,
// so the ears hear them right. The dictionary lives only on the Mac (vocabulary.py); the phone shows it, edits it and
// deletes from it through /voice/dictionary, and shows "Learned: …" with Undo when a fix taught a name.

extension API {
    struct DictionaryLearned: Decodable, Equatable, Hashable {
        let term: String
        let at: Double
    }

    /// In every status poll: enough for the toast and the count.
    struct DictionaryStatus: Decodable, Equatable {
        let count: Int?
        let cap: Int?
        let full: Bool?
        let learn: Bool?
        let learned_this_call: [DictionaryLearned]?
        let problem: String?
    }

    struct DictionaryEntry: Decodable, Equatable, Identifiable, Hashable {
        let term: String
        let lang: String        // en, he, both
        let source: String      // correction, manual, session
        let hits: Int?
        var id: String { term }
    }

    struct DictionarySuggestion: Decodable, Equatable, Identifiable, Hashable {
        let term: String
        let session: String
        let lang: String?
        var id: String { term }
    }

    struct DictionaryPage: Decodable, Equatable {
        let entries: [DictionaryEntry]
        let suggestions: [DictionarySuggestion]?
        let ignored: [String]?
        let count: Int?
        let cap: Int?
        let full: Bool?
        let learn: Bool?
        let problem: String?
    }

    // The Mac's own words on a refusal ("a yes, no or stop word…"), so the sheet can show why.
    private func dictionaryRequest(_ method: String, body: [String: any Sendable]? = nil, term: String? = nil) async throws -> DictionaryPage {
        let query = term.map { [URLQueryItem(name: "term", value: $0)] } ?? []
        let (data, response) = try await send(request("voice/dictionary", method: method, body: body, query: query))
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw Failure.status(code, detail ?? "HTTP \(code)")
        }
        return try JSONDecoder().decode(DictionaryPage.self, from: data)
    }

    func dictionary() async throws -> DictionaryPage { try await dictionaryRequest("GET") }
    func changeDictionary(_ body: [String: any Sendable]) async throws -> DictionaryPage { try await dictionaryRequest("POST", body: body) }
    func deleteFromDictionary(_ term: String) async throws -> DictionaryPage { try await dictionaryRequest("DELETE", term: term) }
}

/// Word for word the page's copy (ui_dictionary.html): the two must not drift.
enum VocabularyCopy {
    static let title = "Dictionary"
    static let menuItem = "Dictionary"
    static let lede = "Names Pointe should hear right. Stored only on your Mac, and sent to the speech recognizer as hints."
    static let addPlaceholder = "Add a name, repo or word"
    static let add = "Add"
    static let empty = "No names yet. Fix a word Pointe misheard, or add one here."
    static let suggestions = "From your sessions"
    static let ignore = "Ignore"
    static let delete = "Delete"
    static let learn = "Learn from my fixes"
    static let learnHelp = "When you fix what Pointe heard, it learns the name you typed. It never learns yes, no or stop words, "
        + "anything that looks like a password or key, or words from a meeting."
    static let appliesNext = "Applies on the next call."
    static let undo = "Undo"
    static let edit = "Edit"
    static let notSaved = "Not saved"
    static let unreachable = "The Mac did not answer."
    static let langs: [(String, String)] = [("en", "EN"), ("he", "HE"), ("both", "EN + HE")]

    static func full(_ cap: Int) -> String { "Full (\(cap)). Delete one to add another." }
    static func learned(_ terms: [String]) -> String { "Learned: " + terms.joined(separator: ", ") }

    static func lang(_ code: String) -> String { langs.first { $0.0 == code }?.1 ?? code }

    static func source(_ code: String) -> String {
        switch code {
        case "correction": "you fixed it"
        case "session": "from a session"
        default: "you added it"
        }
    }
}

/// Which learned terms to toast: each once, and none from before the app started following (a relaunch mid-call does
/// not toast old ones). Pure, so it is tested without a screen.
struct LearnedToasts: Equatable {
    var seen: Set<String> = []
    var seeded = false

    mutating func fresh(_ status: API.DictionaryStatus?) -> [String] {
        guard let status else { return [] }
        let learned = status.learned_this_call ?? []
        let new = learned.filter { !seen.contains(Self.key($0)) }
        seen.formUnion(learned.map(Self.key))
        if !seeded { seeded = true; return [] }
        return new.map(\.term)
    }

    private static func key(_ l: API.DictionaryLearned) -> String { "\(l.term)@\(l.at)" }
}

/// "Learned: bluebell" with Undo, over the call screen for a few seconds.
struct LearnedToast: View {
    let terms: [String]
    let undo: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "text.book.closed").foregroundStyle(Brand.accent)
            Text(VocabularyCopy.learned(terms)).font(.brand(.subheadline, .semibold)).lineLimit(2)
            Button(VocabularyCopy.undo, action: undo).font(.brand(.subheadline, .semibold)).tint(Brand.orange)
                .accessibilityIdentifier("dictionaryUndo")
        }
        .padding(.horizontal, 16).padding(.vertical, 11)
        .background(Brand.card, in: Capsule())
        .overlay(Capsule().stroke(Brand.orangeLine))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("dictionaryToast")
    }
}

struct VocabularySheet: View {
    let load: () async -> Result<API.DictionaryPage, VocabularyFailure>
    let change: ([String: any Sendable]) async -> Result<API.DictionaryPage, VocabularyFailure>
    let delete: (String) async -> Result<API.DictionaryPage, VocabularyFailure>
    let setLearn: (Bool) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var page: API.DictionaryPage?
    @State private var newTerm = ""
    @State private var error: String?
    @State private var editing: API.DictionaryEntry?
    @State private var editText = ""
    @State private var editOriginal = ""  // kept apart: the alert clears `editing` as it closes, before Save runs

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    HStack {
                        TextField(VocabularyCopy.addPlaceholder, text: $newTerm)
                            .plainEntry()
                            .submitLabel(.done).onSubmit(add)
                            .accessibilityIdentifier("dictionaryNew")
                        Button(VocabularyCopy.add, action: add).disabled(newTerm.trimmingCharacters(in: .whitespaces).isEmpty)
                            .accessibilityIdentifier("dictionaryAdd")
                    }
                    if let error {
                        Text(error).font(.brand(.footnote)).foregroundStyle(Brand.accent).accessibilityIdentifier("dictionaryError")
                    }
                    if let problem = page?.problem {
                        Text(problem).font(.brand(.footnote)).foregroundStyle(Brand.accent)
                    }
                } header: {
                    Group {
                        Text(VocabularyCopy.lede).textCase(nil)
                    }.brandFootnote()
                }
                if let page {
                    Section {
                        if page.entries.isEmpty {
                            Text(VocabularyCopy.empty).foregroundStyle(Brand.muted).accessibilityIdentifier("dictionaryEmpty")
                        }
                        ForEach(page.entries) { entry in row(entry) }
                    } footer: {
                        Group {
                            if page.full == true { Text(VocabularyCopy.full(page.cap ?? 400)) }
                        }.brandFootnote()
                    }
                    if let suggestions = page.suggestions, !suggestions.isEmpty {
                        KickerSection(VocabularyCopy.suggestions) {
                            ForEach(suggestions) { s in
                                HStack {
                                    VStack(alignment: .leading) {
                                        Text(s.term).fontWeight(.semibold)
                                        Text(s.session).font(.brand(.caption)).foregroundStyle(Brand.muted)
                                    }
                                    Spacer()
                                    Button(VocabularyCopy.add) { run { await change(["action": "add", "term": s.term, "session": s.session]) } }
                                        .buttonStyle(.brandQuiet)
                                        .accessibilityIdentifier("suggestAdd-\(s.term)")
                                    Button(VocabularyCopy.ignore) { run { await change(["action": "ignore", "term": s.term]) } }
                                        .buttonStyle(.brandQuiet)
                                        .accessibilityIdentifier("suggestIgnore-\(s.term)")
                                }
                            }
                        }
                    }
                    Section {
                        Toggle(VocabularyCopy.learn, isOn: Binding(get: { page.learn ?? true }, set: { on in
                            Task {
                                if await setLearn(on) { await reload() } else { error = VocabularyCopy.notSaved }
                            }
                        }))
                        .tint(Brand.orange)
                        .accessibilityIdentifier("dictionaryLearn")
                    } footer: {
                        Group {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(VocabularyCopy.learnHelp)
                                Text(VocabularyCopy.appliesNext)
                                    .accessibilityIdentifier("dictionaryApplies")
                            }
                        }.brandFootnote()
                    }
                } else {
                    ProgressView()
                }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle(VocabularyCopy.title)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task { await reload() }
            .alert(VocabularyCopy.edit, isPresented: Binding(get: { editing != nil }, set: { if !$0 { editing = nil } })) {
                TextField(VocabularyCopy.addPlaceholder, text: $editText)
                    .plainEntry()
                    .accessibilityIdentifier("dictionaryEditField")
                Button("Save") {
                    let original = editOriginal, to = editText.trimmingCharacters(in: .whitespaces)
                    if !to.isEmpty, to != original {
                        run { await change(["action": "edit", "term": original, "to": to]) }
                    }
                }
                .accessibilityIdentifier("dictionaryEditSave")
                Button("Cancel", role: .cancel) {}
            }
        }
    }

    private func row(_ entry: API.DictionaryEntry) -> some View {
        HStack(spacing: 10) {
            Button { editText = entry.term; editOriginal = entry.term; editing = entry } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text(entry.term).fontWeight(.semibold).foregroundStyle(.primary)
                    Text(VocabularyCopy.source(entry.source)).font(.brand(.caption)).foregroundStyle(Brand.muted)
                }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(VocabularyCopy.edit) \(entry.term)")
            .accessibilityIdentifier("dictionaryTerm-\(entry.term)")
            Spacer()
            Menu {
                ForEach(VocabularyCopy.langs, id: \.0) { code, label in
                    Button(label) { run { await change(["action": "edit", "term": entry.term, "lang": code]) } }
                }
            } label: {
                Text(VocabularyCopy.lang(entry.lang)).font(.brand(.caption, .semibold))
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Brand.card, in: Capsule())
            }
            .accessibilityLabel("Language of \(entry.term): \(VocabularyCopy.lang(entry.lang))")
            .accessibilityIdentifier("dictionaryLang-\(entry.term)")
            Button(role: .destructive) { run { await delete(entry.term) } } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.borderless)
            .accessibilityLabel("\(VocabularyCopy.delete) \(entry.term)")
            .accessibilityIdentifier("dictionaryDelete-\(entry.term)")
        }
    }

    private func add() {
        let term = newTerm.trimmingCharacters(in: .whitespaces)
        guard !term.isEmpty else { return }
        run { await change(["action": "add", "term": term]) } then: { newTerm = "" }
    }

    private func reload() async {
        switch await load() {
        case .success(let p): page = p
        case .failure(let f): error = f.message
        }
    }

    private func run(_ work: @escaping () async -> Result<API.DictionaryPage, VocabularyFailure>, then done: @escaping () -> Void = {}) {
        error = nil
        Task {
            switch await work() {
            case .success(let p): page = p; done()
            case .failure(let f): error = f.message
            }
        }
    }
}

/// Why the Mac refused, in its own words ("a yes, no or stop word: …"), or that it did not answer.
struct VocabularyFailure: Error, Equatable {
    let message: String

    static func from(_ error: Error) -> VocabularyFailure {
        if case API.Failure.status(_, let detail) = error, !detail.hasPrefix("HTTP") { return VocabularyFailure(message: detail) }
        if case API.Failure.status = error { return VocabularyFailure(message: VocabularyCopy.notSaved) }
        return VocabularyFailure(message: VocabularyCopy.unreachable)
    }
}

/// The demo's dictionary (`-demo dictionary`): the sheet works against it as against a Mac, made-up names only.
struct DemoDictionary {
    var page = API.DictionaryPage(
        entries: [API.DictionaryEntry(term: "Quillfeather", lang: "en", source: "correction", hits: 3),
                  API.DictionaryEntry(term: "Marrowind", lang: "both", source: "manual", hits: 1)],
        suggestions: [API.DictionarySuggestion(term: "Kestrelbay", session: "river-lantern", lang: "en")],
        ignored: [], count: 2, cap: 400, full: false, learn: true, problem: nil)

    mutating func apply(_ body: [String: any Sendable]) -> Result<API.DictionaryPage, VocabularyFailure> {
        let term = (body["term"] as? String ?? "").trimmingCharacters(in: .whitespaces)
        var entries = page.entries, suggestions = page.suggestions ?? []
        switch body["action"] as? String {
        case "add":
            if ["yes", "okay", "ok", "sure", "go ahead", "כן"].contains(term.lowercased()) {
                return .failure(VocabularyFailure(message: "a yes, no or stop word: it would bias what counts as an answer"))
            }
            guard !entries.contains(where: { $0.term.lowercased() == term.lowercased() }) else {
                return .failure(VocabularyFailure(message: "already in the dictionary"))
            }
            entries.append(API.DictionaryEntry(term: term, lang: "en", source: body["session"] == nil ? "manual" : "session", hits: 0))
            suggestions.removeAll { $0.term == term }
        case "edit":
            guard let i = entries.firstIndex(where: { $0.term == term }) else { return .failure(VocabularyFailure(message: "not in the dictionary")) }
            let e = entries[i]
            entries[i] = API.DictionaryEntry(term: body["to"] as? String ?? e.term, lang: body["lang"] as? String ?? e.lang, source: e.source, hits: e.hits)
        case "ignore": suggestions.removeAll { $0.term == term }
        default: break
        }
        page = API.DictionaryPage(entries: entries, suggestions: suggestions, ignored: page.ignored, count: entries.count, cap: 400,
                                  full: false, learn: page.learn, problem: nil)
        return .success(page)
    }

    mutating func delete(_ term: String) -> Result<API.DictionaryPage, VocabularyFailure> {
        let entries = page.entries.filter { $0.term != term }
        page = API.DictionaryPage(entries: entries, suggestions: page.suggestions, ignored: page.ignored, count: entries.count, cap: 400,
                                  full: false, learn: page.learn, problem: nil)
        return .success(page)
    }
}
