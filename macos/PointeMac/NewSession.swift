import PointeKit
import SwiftUI

// MARK: new session (docs/design/new-session.md)

/// Start a coding agent in a folder you already work in. Everything offered comes from the daemon; Start asks for
/// Touch ID or the password, as Approve does, and a refusal stays here in the daemon's words.
struct NewSessionSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var options: NewSession.Options?
    @State private var draft = NewSession.Draft()

    var body: some View {
        let store = model.store
        VStack(alignment: .leading, spacing: 10) {
            Text(NewSessionCopy.title).font(.headline)
            Text(NewSessionCopy.lede).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if let options {
                fields(options)
            } else if store.startProblem == nil {
                ProgressView().controlSize(.small)
            }
            if let problem = store.startProblem {
                Text(problem).font(.callout).foregroundStyle(Brand.accent).fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled).accessibilityIdentifier("newSession.problem")
            }
            HStack {
                Spacer()
                Button(NewSessionCopy.cancel, role: .cancel) { dismiss() }.keyboardShortcut(.cancelAction)
                    .accessibilityIdentifier("newSession.cancel")
                Button(NewSessionCopy.start) { Task { if await store.start(draft) { dismiss() } } }
                    .keyboardShortcut(.defaultAction)
                    .disabled(store.busy || options.map(draft.canStart) != true)
                    .accessibilityIdentifier("newSession.start")
                    .accessibilityHint("Starts the session, after Touch ID or your password.")
            }
        }
        .padding(20)
        .frame(width: 460)
        .task {
            options = await store.startOptions()
            if let options { draft = NewSession.Draft(options) }
        }
        .accessibilityIdentifier("newSession.sheet")
    }

    @ViewBuilder private func fields(_ options: NewSession.Options) -> some View {
        kicker(NewSessionCopy.agent)
        ForEach(options.harnesses) { agent in
            choice(agent.title, detail: agent.available ? nil : agent.why, on: draft.harness == agent.name, available: agent.available,
                   id: "newSession.agent.\(agent.name)") { draft.harness = agent.name }
        }
        if draft.harness == "claude-code" { Text(NewSessionCopy.claudeNote).font(.footnote).foregroundStyle(.secondary) }
        if options.showsMachines {
            kicker(NewSessionCopy.machine)
            ForEach(options.machines) { machine in
                choice(machine.name, detail: machine.available ? nil : machine.why, on: draft.machine == machine.name, available: machine.available,
                       id: "newSession.machine.\(machine.name)") { draft.machine = machine.name }
            }
        }
        kicker(NewSessionCopy.folder)
        if options.folders.isEmpty {
            Text(NewSessionCopy.noFolders).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("newSession.noFolders")
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(options.folders) { folder in
                        choice(folder.name, detail: folder.path, on: draft.folder == folder.path, id: "newSession.folder.\(folder.name)") { draft.folder = folder.path }
                    }
                }
            }
            .frame(maxHeight: 132)
        }
        kicker(NewSessionCopy.name)
        TextField(NewSessionCopy.namePlaceholder, text: $draft.name).textFieldStyle(.roundedBorder)
            .accessibilityLabel(NewSessionCopy.name).accessibilityIdentifier("newSession.name")
        kicker(NewSessionCopy.prompt)
        TextField(NewSessionCopy.promptPlaceholder, text: $draft.prompt, axis: .vertical).lineLimit(2...6).textFieldStyle(.roundedBorder)
            .accessibilityLabel(NewSessionCopy.prompt).accessibilityIdentifier("newSession.prompt")
    }

    private func kicker(_ text: String) -> some View {
        Text(text).font(.caption).foregroundStyle(.secondary).padding(.top, 4)
    }

    /// One of a few: a radio mark, the name, and under it the path, or why it cannot be picked.
    private func choice(_ title: String, detail: String?, on: Bool, available: Bool = true, id: String, pick: @escaping () -> Void) -> some View {
        Button(action: pick) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: on ? "largecircle.fill.circle" : "circle").foregroundStyle(on ? Brand.accent : Color.secondary)
                VStack(alignment: .leading, spacing: 1) {
                    Text(title)
                    if let detail { Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(2).truncationMode(.middle) }
                }
                Spacer(minLength: 0)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!available)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(on ? .isSelected : [])
        .accessibilityIdentifier(id)
    }
}

/// A session Pointe is starting, or one that did not start, under the sessions: no actions, it becomes a session by itself.
struct StartingRow: View {
    let row: NewSession.Starting

    var body: some View {
        HStack(spacing: 8) {
            Text(Harness.mark(row.harness).glyph)
                .font(.system(size: 10, weight: .semibold))
                .frame(width: 16, height: 16)
                .overlay(RoundedRectangle(cornerRadius: 3).stroke(Brand.lineStrong))
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 1) {
                Text(row.name).lineLimit(1)
                Text(row.agent).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                if let why = row.why { Text(why).font(.caption).foregroundStyle(Brand.accent).fixedSize(horizontal: false, vertical: true) }
            }
            Spacer(minLength: 4)
            Text(row.tag)
                .font(.caption2.weight(row.failed ? .semibold : .regular))
                .foregroundStyle(row.failed ? Brand.accent : .secondary)
                .padding(.horizontal, 6).padding(.vertical, 2)
                .overlay(Capsule().stroke(row.failed ? Brand.orangeLine : Brand.line))
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel([row.name, row.agent, row.tag, row.why].compactMap { $0 }.joined(separator: ", "))
        .accessibilityIdentifier("starting.\(row.name)")
    }
}

/// What the voice read back and waits to start: its exact words, Cancel, and Start, which asks for Touch ID or the password.
struct StartCard: View {
    @Environment(AppModel.self) private var model
    let pending: NewSession.Pending

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(NewSessionCopy.confirmTitle).font(.callout.weight(.semibold))
                Text(pending.line).font(.callout).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("startCard.line")
            }
            Spacer(minLength: 8)
            Button(NewSessionCopy.cancel) { Task { await model.store.cancelStart(pending) } }
                .accessibilityIdentifier("startCard.cancel")
                .accessibilityHint("Starts nothing. No authentication needed.")
            Button(NewSessionCopy.start) { Task { await model.store.confirmStart(pending) } }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("startCard.start")
                .accessibilityHint("Starts exactly this session, after Touch ID or your password.")
        }
        .padding(12)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(Brand.orangeLine))
        .disabled(model.store.busy)
        .padding(.horizontal, 16).padding(.vertical, 10)
        .background(Brand.tint)
        .accessibilityElement(children: .contain)
        .accessibilityLabel(NewSessionCopy.confirmTitle)
        .accessibilityIdentifier("startCard")
    }
}
