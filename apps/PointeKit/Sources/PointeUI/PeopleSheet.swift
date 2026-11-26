import CoreImage.CIFilterBuiltins
import Observation
import SwiftUI

/// What the People sheet asks of the call; a test or the demo gives its own.
struct PeopleActions {
    let ownerCheck: (String) async -> Bool
    let load: () async throws -> [API.Person]
    /// A name and a grant ("send" or "watch"): the line that person adds this machine with.
    let invite: (String, String) async throws -> API.PeopleInvite
    let state: () async throws -> API.PeopleInvite
    let cancel: () async throws -> Void
    let grant: (String, String) async throws -> Void
    let remove: (String) async throws -> Void
}

/// Settings → Machines → People (docs/design/people-and-machines.md): who is invited to this machine, what each may do,
/// and the invite for one more. An invite's line lets its holder make this machine's agents run commands, so it shows
/// only after Face ID; Remove asks first, then Face ID.
@MainActor @Observable
final class PeopleModel {
    private(set) var people: [API.Person] = []
    private(set) var loaded = false
    var name = ""
    var grant = "send"
    private(set) var invite: API.PeopleInvite?
    private(set) var until: Date?
    private(set) var problem: String?
    private(set) var done: String?
    private(set) var busy = false

    private let actions: PeopleActions

    init(actions: PeopleActions) { self.actions = actions }

    var canInvite: Bool { !busy && !name.trimmingCharacters(in: .whitespaces).isEmpty }

    func load() async {
        do { people = try await actions.load(); loaded = true } catch { if !loaded { problem = PeopleCopy.refusal(error) } }
    }

    /// The status carries who is linked and each grant, on every poll: the rows follow it. A name the list does not have
    /// (somebody just paired), or one that left, reads the list again.
    func follow(_ live: [API.Person]?) async {
        let live = live ?? []
        if Set(live.map(\.name)) != Set(people.map(\.name)) { await load(); return }
        for now in live {
            guard let i = people.firstIndex(where: { $0.name == now.name }) else { continue }
            people[i].grant = now.grant ?? people[i].grant
            people[i].online = now.online
            people[i].since = now.since ?? people[i].since
            people[i].vendors = now.vendors ?? people[i].vendors
            people[i].notice = now.notice
        }
    }

    /// Face ID, then the line. `waiting` is an invite made elsewhere (the page) that the status says is out: it is shown,
    /// not replaced.
    func makeInvite(waiting: API.PeopleInvite? = nil, now: Date = Date()) async {
        guard !busy, waiting != nil || canInvite else { return }
        busy = true; problem = nil; done = nil
        defer { busy = false }
        guard await actions.ownerCheck(PeopleCopy.inviteReason) else { return }
        do {
            let made = try await (waiting == nil ? actions.invite(name.trimmingCharacters(in: .whitespaces), grant) : actions.state())
            invite = made
            until = now.addingTimeInterval(made.expires_in ?? 600)
        } catch { problem = PeopleCopy.refusal(error) }
    }

    /// While the line shows: has the person paired, or did the invite end? True once the line is gone.
    @discardableResult
    func poll() async -> Bool {
        guard let shown = invite, let state = try? await actions.state() else { return false }
        if state.paired {
            done = PeopleCopy.joined(state.pairedName ?? state.name ?? shown.name ?? name)
            close()
            await load()
            return true
        }
        if let ended = state.ended, !ended.isEmpty {
            problem = ended.prefix(1).uppercased() + ended.dropFirst() + (ended.hasSuffix(".") ? "" : ".")
            close()
            return true
        }
        return false
    }

    func cancel() async {
        do { try await actions.cancel(); close() } catch { problem = PeopleCopy.refusal(error) }
    }

    /// The countdown reached zero.
    func expired() { if invite != nil { close(); problem = PeopleCopy.expired } }

    private func close() {
        invite = nil; until = nil; name = ""; grant = "send"
    }

    /// The row moves at the tap; a refusal puts it back.
    func setGrant(_ person: String, _ grant: String) async {
        guard let i = people.firstIndex(where: { $0.name == person }), people[i].grant != grant else { return }
        let before = people[i].grant
        people[i].grant = grant
        problem = nil; done = nil
        do { try await actions.grant(person, grant) } catch {
            if let j = people.firstIndex(where: { $0.name == person }) { people[j].grant = before }
            problem = PeopleCopy.refusal(error)
        }
    }

    /// After the confirm: Face ID, then the machine deletes that person's key.
    func remove(_ person: String) async {
        problem = nil; done = nil
        guard await actions.ownerCheck("\(PeopleCopy.removeReason): \(PeopleCopy.shown(person))") else { return }
        do {
            try await actions.remove(person)
            people.removeAll { $0.name == person }
            done = PeopleCopy.removed(person)
        } catch { problem = PeopleCopy.refusal(error) }
    }
}

struct PeopleSheet: View {
    let status: API.Status?
    @State private var model: PeopleModel
    @State private var removing: String?
    @Environment(\.dismiss) private var dismiss

    init(status: API.Status?, actions: PeopleActions) {
        self.status = status
        _model = State(initialValue: PeopleModel(actions: actions))
    }

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    if model.people.isEmpty && model.loaded {
                        Text(PeopleCopy.none).foregroundStyle(Brand.muted).accessibilityIdentifier("peopleNone")
                    }
                    ForEach(model.people) { row($0) }
                    if let problem = model.problem {
                        Text(problem).foregroundStyle(Brand.accent).fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("peopleProblem")
                    }
                    if let done = model.done {
                        Text(done).foregroundStyle(Brand.muted).accessibilityIdentifier("peopleDone")
                    }
                } footer: {
                    Group { Text(PeopleCopy.trust(account: status?.account)).accessibilityIdentifier("peopleTrust") }.brandFootnote()
                }
                Section { inviteSection }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle(PeopleCopy.people)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .confirmationDialog(removing.map(PeopleCopy.removeAsk) ?? "", isPresented: Binding(
                get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible, presenting: removing) { name in
                Button("\(PeopleCopy.remove) \(PeopleCopy.shown(name))", role: .destructive) { Task { await model.remove(name) } }
                    .accessibilityIdentifier("confirmRemovePerson")
                Button("Cancel", role: .cancel) {}
            }
            .task { await model.load() }
            .task(id: status?.people) { await model.follow(status?.people) }
            .task(id: model.invite?.code) {  // while the line shows: closes by itself when they pair
                while model.invite != nil, !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(1.5))
                    if await model.poll() { break }
                }
            }
        }
    }

    private func row(_ p: API.Person) -> some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(PeopleCopy.shown(p.name)).font(.brand(.body, .semibold))
                Text(PeopleCopy.facts(p)).font(.brand(.caption)).foregroundStyle(Brand.muted)
                if let services = PeopleCopy.services(p) {
                    Text(services).font(.brand(.caption)).foregroundStyle(Brand.muted)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("personServices.\(p.name)")
                }
                if let notice = p.notice, !notice.isEmpty {
                    Text(notice).font(.brand(.caption)).foregroundStyle(Brand.accent)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("personNotice.\(p.name)")
                }
            }
            Spacer(minLength: 8)
            Menu {
                Picker(PeopleCopy.shown(p.name), selection: Binding(get: { p.watchOnly ? "watch" : "send" },
                                                                   set: { grant in Task { await model.setGrant(p.name, grant) } })) {
                    Text(PeopleCopy.send).tag("send")
                    Text(PeopleCopy.watch).tag("watch")
                }
                .pickerStyle(.inline)
                Button(PeopleCopy.remove, systemImage: "person.badge.minus", role: .destructive) { removing = p.name }
                    .accessibilityIdentifier("removePerson.\(p.name)")
            } label: {
                Image(systemName: "ellipsis.circle").font(.brand(.title3)).foregroundStyle(Brand.muted)
                    .frame(minWidth: 44, minHeight: 44).contentShape(Rectangle())
            }
            .fieldMenu()
            .accessibilityLabel("\(PeopleCopy.shown(p.name)): change what they can do, or remove them")
            .accessibilityIdentifier("personMenu.\(p.name)")
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("person.\(p.name)")
    }

    @ViewBuilder
    private var inviteSection: some View {
        if let invite = model.invite, let until = model.until {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                if let left = MachinesCopy.countdown(until.timeIntervalSince(context.date)) {
                    InviteLine(invite: invite, left: left, until: until) { Task { await model.cancel() } }
                } else {
                    Text(PeopleCopy.expired).foregroundStyle(Brand.muted).accessibilityIdentifier("personInviteExpired")
                        .task { model.expired() }
                }
            }
        } else if let waiting = status?.people_invite, !waiting.code.isEmpty {
            Button { Task { await model.makeInvite(waiting: waiting) } } label: {
                Label("Show the invite", systemImage: Surface.ownerSymbol)
            }
            .disabled(model.busy)
            .accessibilityIdentifier("showPersonInvite")
        } else {
            TextField(PeopleCopy.name, text: $model.name).plainEntry()
                .submitLabel(.done)
                .accessibilityIdentifier("personName")
            Picker(selection: $model.grant) {
                Text(PeopleCopy.send).tag("send")
                Text(PeopleCopy.watch).tag("watch")
            } label: { EmptyView() }
                .pickerStyle(.inline).labelsHidden()
                .accessibilityIdentifier("personGrant")
            Button { Task { await model.makeInvite() } } label: {
                Label(PeopleCopy.invite, systemImage: Surface.ownerSymbol)
            }
            .disabled(!model.canInvite)
            .accessibilityIdentifier("invitePerson")
        }
    }
}

/// The invite: its QR code, the line, the time left, and Copy, Share and Cancel.
private struct InviteLine: View {
    let invite: API.PeopleInvite
    let left: String
    let until: Date
    let cancel: () -> Void

    private var line: String { invite.link ?? invite.code }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(PeopleCopy.lineHelp).font(.brand(.footnote)).foregroundStyle(Brand.muted)
                .fixedSize(horizontal: false, vertical: true)
                .environment(\.layoutDirection, .leftToRight)
            if let code = QRCode.image(line) {
                code.interpolation(.none).resizable().scaledToFit()
                    .frame(maxWidth: 200, maxHeight: 200)
                    .padding(8).background(Color.white, in: RoundedRectangle(cornerRadius: 8))
                    .frame(maxWidth: .infinity)
                    .accessibilityLabel("The invite as a code to scan")
                    .accessibilityIdentifier("personInviteQR")
            }
            Text(line)
                .font(.system(.caption, design: .monospaced)).foregroundStyle(Brand.muted)
                .textSelection(.enabled)
                .accessibilityIdentifier("personInviteLine")
            Text("Expires in \(left)").font(.brand(.subheadline).monospacedDigit())
                .accessibilityIdentifier("personInviteCountdown")
            ViewThatFits(in: .horizontal) {
                HStack { copy; share; Spacer(); stop }
                VStack(alignment: .leading, spacing: 10) { copy; share; stop }
            }
            .buttonStyle(.borderless)
        }
        .environment(\.layoutDirection, .leftToRight)  // a link reads left to right
    }

    private var copy: some View {
        Button(PeopleCopy.copy, systemImage: "doc.on.doc") { Clipboard.copy(line, until: until) }
            .accessibilityIdentifier("copyPersonInvite")
    }

    private var share: some View {
        ShareLink(item: line) { Label(PeopleCopy.share, systemImage: "square.and.arrow.up") }
            .accessibilityIdentifier("sharePersonInvite")
    }

    private var stop: some View {
        Button(PeopleCopy.cancelInvite, role: .destructive, action: cancel)
            .accessibilityIdentifier("cancelPersonInvite")
    }
}

/// A QR code drawn on this device: no image service sees the line.
enum QRCode {
    static func cgImage(_ text: String) -> CGImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: 8, y: 8)) else { return nil }
        return CIContext().createCGImage(output, from: output.extent)
    }

    static func image(_ text: String) -> Image? {
        cgImage(text).map { Image(decorative: $0, scale: 1) }
    }
}
