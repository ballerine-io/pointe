import SwiftUI

/// What the Add sessions sheet asks of the call: Face ID as for Approve, the Mac's listing, and the join or reopen.
struct AddSessionsActions {
    let ownerCheck: (String) async -> Bool
    let listing: () async throws -> AddSessions.Listing
    let join: ([String]) async throws -> Void
    let reopen: (String) async throws -> Void
}

/// Sessions the user runs now, and ones from this week, not on the voice yet: grouped by state, then machine, each with
/// its agent's mark. Open ones are ticked and joined together; a recent one is reopened on its own. Every row comes from
/// the Mac; Join and Reopen ask for Face ID, as Start does, and a refusal stays here in the Mac's words.
struct AddSessionsSheet: View {
    static let faceIDReason = "Add sessions to the voice"

    let actions: AddSessionsActions
    @Environment(\.dismiss) private var dismiss
    @State private var listing: AddSessions.Listing?
    @State private var query = ""
    @State private var picked: Set<String> = []
    @State private var problem: String?
    @State private var busy = false

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    Text(AddSessionsCopy.lede).brandFootnote()
                        .listRowBackground(Color.clear).listRowInsets(EdgeInsets())
                }
                if let listing { rows(listing) } else if problem == nil {
                    Section { Text(AddSessionsCopy.loading).foregroundStyle(Brand.muted) }
                }
                if let problem {
                    Section { Text(problem).foregroundStyle(Brand.accent).accessibilityIdentifier("addSessionsProblem") }
                }
            }
            .searchable(text: $query, prompt: AddSessionsCopy.searchPlaceholder)
            .sheetTitle(AddSessionsCopy.title)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AddSessionsCopy.cancel) { dismiss() }.accessibilityIdentifier("addSessionsCancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(picked.count > 1 ? "\(AddSessionsCopy.join) \(picked.count)" : AddSessionsCopy.join) {
                        Task { await run { try await actions.join(Array(picked)) } }
                    }
                    .disabled(busy || picked.isEmpty)
                    .accessibilityIdentifier("addSessionsJoin")
                }
            }
            .task {
                do { listing = try await actions.listing() } catch { problem = NewSessionSheet.refusal(error) }
            }
        }
    }

    @ViewBuilder
    private func rows(_ listing: AddSessions.Listing) -> some View {
        let sections = listing.sections(query)
        if sections.isEmpty {
            Section { Text(query.isEmpty ? AddSessionsCopy.none : AddSessionsCopy.noMatch).foregroundStyle(Brand.muted) }
        }
        ForEach(sections, id: \.title) { section in
            let several = section.machines.count > 1
            ForEach(section.machines, id: \.name) { machine in
                KickerSection(several ? "\(section.title) · \(machine.name)" : section.title) {
                    ForEach(machine.items) { item in row(item) }
                }
            }
        }
        if listing.recent.contains(where: { $0.harness == "claude-code" && $0.joinable }) {
            Section { Text(AddSessionsCopy.reopenNote).brandFootnote() }
        }
    }

    private func row(_ item: AddSessions.Item) -> some View {
        HStack(alignment: .top, spacing: 10) {
            if item.isOpen {
                Image(systemName: picked.contains(item.key) ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(picked.contains(item.key) ? Brand.accent : Brand.dim)
            }
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(item.name).font(.brand(.body, .semibold)).lineLimit(1)
                    HarnessMark(harness: item.harness)
                }
                Text(item.detail).font(.brand(.caption)).foregroundStyle(Brand.muted).lineLimit(1)
                if let first = item.first, !first.isEmpty {
                    Text(first).font(.brand(.caption)).foregroundStyle(Brand.muted).lineLimit(2)
                }
                if let why = item.why {
                    Text(why).font(.brand(.caption)).foregroundStyle(Brand.accent)
                } else if !item.approvals {
                    Text(AddSessionsCopy.approvalsTerminal).font(.brand(.caption)).foregroundStyle(Brand.muted)
                }
            }
            Spacer(minLength: 0)
            if !item.isOpen {
                Button(AddSessionsCopy.reopen) { Task { await run { try await actions.reopen(item.key) } } }
                    .buttonStyle(.brandQuiet).controlSize(.small).disabled(busy || !item.joinable)
                    .accessibilityIdentifier("addSessionsReopen.\(item.name)")
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            guard item.isOpen, item.joinable else { return }
            if picked.contains(item.key) { picked.remove(item.key) } else { picked.insert(item.key) }
        }
        .opacity(item.joinable ? 1 : 0.55)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(picked.contains(item.key) ? .isSelected : [])
        .accessibilityIdentifier("addSessionsRow.\(item.name)")
    }

    private func run(_ work: () async throws -> Void) async {
        busy = true
        defer { busy = false }
        guard await actions.ownerCheck(Self.faceIDReason) else { return }
        do {
            try await work()
            dismiss()
        } catch { problem = NewSessionSheet.refusal(error) }
    }
}

/// What the voice read back and waits on: its exact words, Cancel, and Join (or Reopen), which asks for Face ID as Start
/// does. A "which one?" has no Join here: the user says which, or picks it in the sheet.
struct AttachCard: View {
    let pending: AddSessions.Pending
    let answer: (AddSessions.Pending, Bool, String?) async -> Void
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label { Text(AddSessionsCopy.confirmTitle) } icon: { Image(systemName: "rectangle.stack.badge.plus").foregroundStyle(Brand.accent) }
                .font(.brand(.headline))
            Text(pending.line).font(.brand(.subheadline)).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("attachLine")
            HStack(spacing: 10) {
                Button { act(false) } label: { Text(AddSessionsCopy.cancel).frame(maxWidth: .infinity) }
                    .buttonStyle(.brandQuiet).controlSize(.large)
                    .accessibilityIdentifier("attachCancel")
                if !pending.choose {
                    Button { act(true) } label: { Label(pending.button, systemImage: Surface.ownerSymbol).frame(maxWidth: .infinity) }
                        .buttonStyle(.brandPrimary).controlSize(.large)
                        .accessibilityIdentifier("attachConfirm")
                }
            }
            .disabled(busy)
            ForEach(pending.choices, id: \.key) { choice in  // "which one?": a tap on one answers it
                Button { act(true, choice.key) } label: { Label(choice.label, systemImage: Surface.ownerSymbol).frame(maxWidth: .infinity) }
                    .buttonStyle(.brandPrimary).controlSize(.large)
                    .accessibilityIdentifier("attachPick")
                    .disabled(busy)
            }
        }
        .padding(16)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
        .sensoryFeedback(.warning, trigger: pending.id)
    }

    private func act(_ yes: Bool, _ pick: String? = nil) {
        busy = true
        Task { await answer(pending, yes, pick); busy = false }
    }
}
