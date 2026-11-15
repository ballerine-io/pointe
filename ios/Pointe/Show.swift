import SwiftUI

/// Word for word the page's copy (ui.html): the two must not drift.
enum ShowCopy {
    static let title = "Showing"
    static let file = "File"
    static let diff = "Diff"
    static let test = "Test"
    static let earlier = "Shown earlier"
    static let pin = "Pin"
    static let pinned = "Pinned"
    static let setting = "Show while it says"
    static let help = "Show the files and test output the voice talks about. Code stays on your Mac unless you turn this on."
    static let changed = "changed since it was spoken about"
    static let gone = "Shown too long ago: the Mac no longer has it."
    static let off = "Show while it says is off on this phone. Turn it on in Settings."
    static let unreachable = "The Mac did not send it."
    static let enableReason = "Show code from your Mac on this phone"

    static func card(_ summary: String) -> String { "\(title): \(summary)" }
    static func range(_ r: [Int]?) -> String? {
        guard let r, r.count == 2 else { return nil }
        return r[1] > r[0] ? "lines \(r[0])–\(r[1])" : "line \(r[0])"
    }
}

/// Which artifact the sheet shows: a pinned one wins, then the one you tapped, then the one the voice names now.
/// A new report forgets your tap but keeps the pin.
struct ShowFollow: Equatable {
    var picked: String?
    var pinned: ShownPin?
    private var setId: String?

    struct ShownPin: Equatable { let artifact: API.ShownArtifact; let session: String? }

    mutating func follow(_ showing: API.Showing?) {
        guard let showing, showing.id != setId else { return }
        setId = showing.id
        picked = nil
    }

    func selected(_ showing: API.Showing?) -> String? {
        if let pinned { return pinned.artifact.id }
        let ids = showing?.artifacts.map(\.id) ?? []
        if let picked, ids.contains(picked) { return picked }
        if let current = showing?.current, ids.contains(current) { return current }
        return ids.first
    }

    /// The tabs: this report's artifacts, plus the pinned one when it came from an earlier report.
    func tabs(_ showing: API.Showing?) -> [API.ShownArtifact] {
        let now = showing?.artifacts ?? []
        guard let pinned, !now.contains(where: { $0.id == pinned.artifact.id }) else { return now }
        return [pinned.artifact] + now
    }

    mutating func togglePin(_ a: API.ShownArtifact, session: String?) {
        pinned = pinned?.artifact.id == a.id ? nil : ShownPin(artifact: a, session: session)
    }
}

/// The card above the conversation while the voice reports: one line, tap for the sheet.
struct ShowCard: View {
    let showing: API.Showing
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            HStack(spacing: 10) {
                Image(systemName: "doc.text.magnifyingglass").foregroundStyle(Brand.accent)
                Text(ShowCopy.card(showing.summary ?? showing.artifacts.first?.name ?? ""))
                    .font(.brand(.subheadline, .semibold)).lineLimit(2).multilineTextAlignment(.leading)
                Spacer(minLength: 4)
                Image(systemName: "chevron.up").font(.brand(.caption, .bold)).foregroundStyle(Brand.muted)
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            .background(Brand.raised, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Brand.orangeLine))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("showCard")
    }
}

/// Full screen: a tab per artifact, the file at its range, the diff, or the test output at the failing line.
struct ShowSheet: View {
    let showing: API.Showing?
    let earlier: [API.ShownSet]
    @Binding var follow: ShowFollow
    /// The artifact's view from the Mac, or the reason it could not be had.
    let load: (String) async -> Result<API.ArtifactView, ShowFailure>
    @Environment(\.dismiss) private var dismiss
    @State private var views: [String: Result<API.ArtifactView, ShowFailure>] = [:]
    @State private var face: [String: String] = [:]  // per artifact: "File" or "Diff"

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                tabStrip
                Divider()
                if let id = follow.selected(showing), let a = follow.tabs(showing).first(where: { $0.id == id }) {
                    pane(a)
                } else {
                    Spacer()
                    Text(ShowCopy.gone).foregroundStyle(Brand.muted).padding()
                    Spacer()
                }
                if !earlier.isEmpty { earlierList }
            }
            .navigationTitle(ShowCopy.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .onChange(of: showing?.id) { follow.follow(showing) }
    }

    private var tabStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(follow.tabs(showing)) { a in
                    let on = a.id == follow.selected(showing)
                    Button { follow.picked = a.id } label: {
                        HStack(spacing: 4) {
                            if follow.pinned?.artifact.id == a.id { Image(systemName: "pin.fill").font(.brand(.caption2)) }
                            if a.kind == "test" { Image(systemName: a.failed == true ? "xmark.octagon.fill" : "checkmark.circle") }
                            Text(a.kind == "test" ? ShowCopy.test : a.name ?? "")
                        }
                        .font(.brand(.subheadline, on ? .semibold : .regular))
                        .padding(.horizontal, 12).padding(.vertical, 7)
                        .background(on ? Brand.tint : Brand.raised, in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("showTab-\(a.kind)-\(a.name ?? a.id)")
                    .accessibilityAddTraits(on ? .isSelected : [])
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
        }
    }

    @ViewBuilder private func pane(_ a: API.ShownArtifact) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(a.path?.isEmpty == false ? a.path! : (a.name ?? "")).font(.footnote.monospaced()).lineLimit(1)
                        .truncationMode(.head)
                    if let r = ShowCopy.range(a.range) { Text(r).font(.brand(.caption)).foregroundStyle(Brand.muted) }
                }
                Spacer()
                if a.kind == "edit" {
                    Picker("", selection: Binding(get: { face[a.id] ?? ShowCopy.file }, set: { face[a.id] = $0 })) {
                        Text(ShowCopy.file).tag(ShowCopy.file)
                        Text(ShowCopy.diff).tag(ShowCopy.diff)
                    }
                    .pickerStyle(.segmented).fixedSize()
                    .accessibilityIdentifier("showFace")
                }
                let isPinned = follow.pinned?.artifact.id == a.id
                Button { follow.togglePin(a, session: showing?.session) } label: {
                    Label(isPinned ? ShowCopy.pinned : ShowCopy.pin, systemImage: isPinned ? "pin.fill" : "pin")
                        .font(.brand(.caption, .semibold))
                }
                .buttonStyle(.brandQuiet)
                .accessibilityIdentifier("showPin")
            }
            .padding(.horizontal, 14)
            content(a)
        }
        .padding(.top, 8)
        .task(id: a.id) { if views[a.id] == nil { views[a.id] = await load(a.id) } }
    }

    @ViewBuilder private func content(_ a: API.ShownArtifact) -> some View {
        if let refused = a.refused {
            message(refused)
        } else {
            switch views[a.id] {
            case .none: ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            case .failure(let f): message(f.text)
            case .success(let v):
                if let problem = v.problem {
                    message(problem)
                } else {
                    if v.changed_since == true {
                        Text(ShowCopy.changed).font(.brand(.caption)).foregroundStyle(Brand.accent).padding(.horizontal, 14)
                            .accessibilityIdentifier("showChanged")
                    }
                    if a.kind == "test" {
                        if let command = v.command, !command.isEmpty {
                            Text(command).font(.caption.monospaced()).foregroundStyle(Brand.muted).padding(.horizontal, 14)
                        }
                        CodeLines(rows: (v.output ?? "").components(separatedBy: "\n").enumerated().map {
                            CodeRow(id: $0.offset, number: nil, text: $0.element, tone: $0.offset == v.focus ? .focus : .plain)
                        }, scrollTo: v.focus)
                    } else if (face[a.id] ?? ShowCopy.file) == ShowCopy.diff {
                        if let diff = v.diff {
                            CodeLines(rows: diff.components(separatedBy: "\n").enumerated().map { i, line in
                                CodeRow(id: i, number: nil, text: line,
                                        tone: line.hasPrefix("+") && !line.hasPrefix("+++") ? .added
                                            : line.hasPrefix("-") && !line.hasPrefix("---") ? .removed : .plain)
                            }, scrollTo: nil)
                        } else {
                            message("Not in a git repository: no diff.")
                        }
                    } else {
                        let lines = v.lines ?? []
                        CodeLines(rows: lines.map { CodeRow(id: $0.n, number: $0.n, text: $0.text, tone: $0.hl == true ? .highlight : .plain) },
                                  scrollTo: lines.first(where: { $0.hl == true })?.n)
                    }
                }
            }
        }
    }

    private func message(_ text: String) -> some View {
        Text(text).foregroundStyle(Brand.muted).padding(14).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .accessibilityIdentifier("showProblem")
    }

    private var earlierList: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(ShowCopy.earlier).font(.brand(.caption, .semibold)).foregroundStyle(Brand.muted)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(earlier.filter { $0.id != showing?.id }) { set in
                        Menu {
                            ForEach(set.artifacts ?? []) { a in
                                Button(a.kind == "test" ? ShowCopy.test : a.name ?? "") {
                                    follow.pinned = .init(artifact: a, session: set.session)
                                }
                            }
                        } label: {
                            Text(set.summary ?? set.session ?? "").font(.brand(.caption)).lineLimit(1)
                                .padding(.horizontal, 10).padding(.vertical, 6)
                                .background(Brand.raised, in: Capsule())
                        }
                    }
                }
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(Brand.bg)
        .accessibilityIdentifier("showEarlier")
    }
}

enum ShowFailure: Error, Equatable {
    case off, gone, unreachable
    var text: String {
        switch self {
        case .off: ShowCopy.off
        case .gone: ShowCopy.gone
        case .unreachable: ShowCopy.unreachable
        }
    }
}

struct CodeRow: Identifiable, Hashable {
    enum Tone { case plain, highlight, added, removed, focus }
    let id: Int
    let number: Int?
    let text: String
    let tone: Tone
}

/// Monospaced lines, both ways scrollable, pinch to zoom on top of Dynamic Type, scrolled to the line that matters.
struct CodeLines: View {
    let rows: [CodeRow]
    let scrollTo: Int?
    @ScaledMetric(relativeTo: .footnote) private var base: CGFloat = 13
    @State private var zoom: CGFloat = 1
    @GestureState private var pinch: CGFloat = 1

    private var size: CGFloat { min(40, max(8, base * zoom * pinch)) }

    var body: some View {
        ScrollViewReader { scroller in
            ScrollView([.horizontal, .vertical]) {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(rows) { row in
                        HStack(alignment: .top, spacing: 10) {
                            if let n = row.number {
                                Text(String(n)).foregroundStyle(Brand.muted).frame(minWidth: size * 2.4, alignment: .trailing)
                            }
                            Text(row.text.isEmpty ? " " : row.text).foregroundStyle(color(row.tone)).fixedSize()
                        }
                        .font(.system(size: size, design: .monospaced))
                        .padding(.horizontal, 14).padding(.vertical, 1)
                        .background(background(row.tone))
                        .id(row.id)
                    }
                }
                .padding(.vertical, 8)
            }
            .gesture(MagnifyGesture().updating($pinch) { value, state, _ in state = value.magnification }
                .onEnded { zoom = min(3, max(0.6, zoom * $0.magnification)) })
            .onAppear { if let scrollTo { scroller.scrollTo(scrollTo, anchor: .center) } }
            .onChange(of: scrollTo) { if let scrollTo { scroller.scrollTo(scrollTo, anchor: .center) } }
            .accessibilityIdentifier("showCode")
        }
    }

    private func color(_ tone: CodeRow.Tone) -> Color {
        switch tone {
        case .added: Brand.successText
        case .removed: Brand.dangerText
        default: .primary
        }
    }

    private func background(_ tone: CodeRow.Tone) -> Color {
        switch tone {
        case .highlight, .focus: Brand.tint
        case .added: Brand.success.opacity(0.12)
        case .removed: Brand.danger.opacity(0.12)
        case .plain: .clear
        }
    }
}

/// Settings → Show while it says. Turning it on asks Face ID or the passcode; off needs nothing.
struct ShowSettingsSheet: View {
    let on: Bool
    /// Nil when the Mac took it; otherwise its reason.
    let set: (Bool) async -> String?
    let ownerCheck: (String) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var wanted: Bool?
    @State private var refused: String?

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    Toggle(ShowCopy.setting, isOn: Binding(get: { wanted ?? on }, set: { change($0) }))
                        .tint(Brand.orange)
                        .accessibilityIdentifier("showSetting")
                } footer: { Text(ShowCopy.help) }
                if let refused {
                    Label(refused, systemImage: "exclamationmark.triangle.fill").foregroundStyle(Brand.accent)
                }
            }
            .scrollContentBackground(.hidden)
            .navigationTitle(ShowCopy.setting)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }

    private func change(_ value: Bool) {
        Task {
            if value, !(await ownerCheck(ShowCopy.enableReason)) { return }  // turning it on sends code here: the owner only
            wanted = value
            refused = await set(value)
            if refused != nil { wanted = nil }
        }
    }
}
