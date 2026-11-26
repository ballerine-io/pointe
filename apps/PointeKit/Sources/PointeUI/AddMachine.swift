import Observation
import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// What Add a machine asks of the call: Face ID as for a machine invite, and the Mac's add.
struct AddMachineActions {
    let ownerCheck: (String) async -> Bool
    /// The invite line, and this voice's own name for the machine once the Mac said the machine's name is taken.
    let add: (String, String?) async throws -> API.MachineAdded
}

/// Settings → Machines → Add a machine (docs/design/people-and-machines.md): somebody's invite line, scanned or pasted,
/// goes to the Mac, which checks the certificate, trades the code and links. A refusal is the Mac's one sentence and the
/// line stays, to try again. A name is asked for only when the Mac says the machine's own is taken.
@MainActor @Observable
final class AddMachineModel {
    var line = ""
    /// "Call it": this voice's own name for the machine. Shown only after the Mac said the name is taken.
    var name = ""
    private(set) var working = false
    private(set) var problem: String?
    private(set) var needsName = false
    private(set) var added: API.MachineAdded?
    /// The line came with a link that opened the app: nothing is sent until the owner chooses Add.
    private(set) var fromOutside = false
    /// Changes when the camera read something that is not an invite: it reads again.
    private(set) var attempt = 0

    private let actions: AddMachineActions

    init(actions: AddMachineActions, line: String = "", fromOutside: Bool = false) {
        self.actions = actions
        self.line = line
        self.fromOutside = fromOutside && !line.isEmpty
    }

    var canAdd: Bool {
        !working && !line.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (!needsName || !name.trimmingCharacters(in: .whitespaces).isEmpty)
    }

    /// A code the camera read: an invite is added at once, anything else says what it is not and the camera reads on.
    func scanned(_ code: String) async {
        guard !working, added == nil else { return }
        guard MachineLine(code) != nil else { problem = PeopleCopy.notAnInvite; attempt += 1; return }
        line = code
        fromOutside = false
        await add()
    }

    /// Paste instead: the clipboard's line, added at once when it is an invite.
    func pasted(_ text: String?) async {
        guard !working else { return }
        guard let text, MachineLine(text) != nil else { problem = PeopleCopy.nothingToPaste; return }
        line = text
        fromOutside = false
        await add()
    }

    /// Scan again: the line is dropped and the camera reads.
    func clear() {
        guard !working else { return }
        line = ""; name = ""; problem = nil; needsName = false; fromOutside = false
    }

    func add() async {
        guard canAdd else { return }
        guard let invite = MachineLine(line) else { problem = PeopleCopy.notAnInvite; return }
        problem = nil
        guard await actions.ownerCheck(PeopleCopy.addReason) else { return }
        working = true
        defer { working = false }
        do {
            let called = name.trimmingCharacters(in: .whitespaces)
            added = try await actions.add(invite.line, needsName && !called.isEmpty ? called : nil)
        } catch {
            // 409 is also "already in your voice" and "this is your own machine": a name is asked for only when the
            // sentence is about the name.
            if case API.Failure.status(409, let detail) = error, detail.localizedCaseInsensitiveContains("name") {
                needsName = true
                if name.isEmpty { name = invite.name ?? "" }
            }
            problem = PeopleCopy.refusal(error)
        }
    }
}

/// The one-time line after a machine is added: which services this voice sends its transcripts to. It shows from the
/// answer to Add at once, then from the status until OK; OK hides it here before the Mac's next status says so.
struct DisclosureGate: Equatable {
    private(set) var added: API.Disclosure?
    private(set) var seen: Set<String> = []

    mutating func machineAdded(_ m: API.MachineAdded) {
        added = API.Disclosure(machine: m.name, vendors: m.vendors)
    }

    func pending(_ status: API.Status?) -> API.Disclosure? {
        guard let d = status?.disclosure ?? added, !seen.contains(d.machine) else { return nil }
        return d
    }

    /// OK: returns the machine to tell the Mac about (`POST /voice/machines/add {seen}`).
    mutating func dismiss(_ d: API.Disclosure) -> String {
        seen.insert(d.machine)
        if added?.machine == d.machine { added = nil }
        return d.machine
    }
}

/// The disclosure, as a card with its one OK.
struct DisclosureCard: View {
    let disclosure: API.Disclosure
    var owner: String? = nil
    let ok: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(PeopleCopy.disclosure(disclosure, owner: owner)).font(.brand(.subheadline))
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("disclosureText")
            Button(PeopleCopy.ok, action: ok).buttonStyle(.brandPrimary).controlSize(.small)
                .accessibilityIdentifier("disclosureOK")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("disclosure.\(disclosure.machine)")
    }
}

/// The sheet. The iPhone opens on its camera, with Paste instead under it; the Mac has one field to paste or drop the
/// line into. Both close when the machine is added: the Machines list behind shows it, with whose it is.
struct AddMachineSheet: View {
    @State private var model: AddMachineModel
    let done: (API.MachineAdded) -> Void
    @Environment(\.dismiss) private var dismiss

    init(actions: AddMachineActions, line: String = "", fromOutside: Bool = false, done: @escaping (API.MachineAdded) -> Void) {
        _model = State(initialValue: AddMachineModel(actions: actions, line: line, fromOutside: fromOutside))
        self.done = done
    }

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    entry
                    if model.fromOutside, let invite = MachineLine(model.line) {
                        Text(PeopleCopy.fromOutside(invite.host)).font(.brand(.footnote)).foregroundStyle(Brand.accent)
                            .accessibilityIdentifier("addMachineOutside")
                    }
                    if model.working {
                        HStack(spacing: 10) {
                            ProgressView().controlSize(.small)
                            Text(PeopleCopy.adding).foregroundStyle(Brand.muted)
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("addMachineWorking")
                    }
                    if let problem = model.problem {
                        Text(problem).foregroundStyle(Brand.accent).fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("addMachineProblem")
                    }
                    if model.needsName {
                        LabeledContent(PeopleCopy.callIt) {
                            TextField(PeopleCopy.callIt, text: $model.name).plainEntry().multilineTextAlignment(.trailing)
                                .onSubmit { Task { await model.add() } }
                                .accessibilityIdentifier("addMachineName")
                        }
                    }
                } footer: {
                    Group { Text(Surface.isMac ? PeopleCopy.lineHelpMac : PeopleCopy.scanHelp) }.brandFootnote()
                }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle(PeopleCopy.addMachine)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.accessibilityIdentifier("addMachineCancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(PeopleCopy.add) { Task { await model.add() } }
                        .disabled(!model.canAdd)
                        .accessibilityIdentifier("addMachineAdd")
                }
            }
            .onChange(of: model.added) { _, added in
                if let added { done(added); dismiss() }
            }
        }
    }

    @ViewBuilder
    private var entry: some View {
        #if os(iOS)
        if model.line.isEmpty {
            ZStack {
                VStack(spacing: 8) {  // under the camera: what shows before it starts, without one, or when it was not allowed
                    Image(systemName: "qrcode.viewfinder").font(.system(size: 36, weight: .light)).foregroundStyle(Brand.dim)
                    Text("Point the camera at the code").font(.brand(.footnote)).foregroundStyle(Brand.dim)
                }
                .accessibilityHidden(true)
                Scanner { code in Task { await model.scanned(code) } }
                    .id(model.attempt)  // not an invite: the camera reads again
            }
            .frame(maxWidth: .infinity).frame(height: 260)
            .background(Brand.raised, in: RoundedRectangle(cornerRadius: 16))
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.line))
            .padding(.vertical, 4)  // inside the card, with Paste under it: on a clear row it floated over the sheet
            .listRowSeparator(.hidden)
            .accessibilityIdentifier("addMachineScanner")
        } else {
            kept
            Button("Scan again", systemImage: "qrcode.viewfinder") { model.clear() }
                .disabled(model.working)
                .accessibilityIdentifier("addMachineScanAgain")
        }
        // The system's own paste control: one tap, and iOS does not ask whether Pointe may read the clipboard.
        PasteButton(payloadType: String.self) { strings in
            Task { await model.pasted(strings.first) }
        }
        .labelStyle(.titleAndIcon)
        .disabled(model.working)
        .accessibilityLabel(PeopleCopy.pasteInstead)
        .accessibilityIdentifier("addMachinePaste")
        #else
        TextField(PeopleCopy.lineField, text: $model.line, axis: .vertical)
            .lineLimit(2...4)
            .font(.system(.footnote, design: .monospaced))
            .plainEntry()
            .disabled(model.working)
            .onSubmit { Task { await model.add() } }
            .dropDestination(for: String.self) { items, _ in
                guard let text = items.first, !model.working else { return false }
                model.line = text
                return true
            }
            .accessibilityLabel(PeopleCopy.lineField)
            .accessibilityIdentifier("addMachineLine")
        #endif
    }

    /// The line that was read, kept while it is added and after a refusal.
    private var kept: some View {
        Text(model.line).font(.system(.caption, design: .monospaced)).foregroundStyle(Brand.muted)
            .lineLimit(3).truncationMode(.middle)
            .environment(\.layoutDirection, .leftToRight)
            .accessibilityIdentifier("addMachineLine")
    }
}
