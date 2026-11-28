import Observation
import SwiftUI

// Settings → Agents (docs/design/agents.md): agents built on agent frameworks (OpenClaw, Hermes Agent, any A2A or
// OpenAI-compatible agent), talked to like sessions. The list with whether each answers, Connect an agent (its credential
// goes to the Mac's Keychain and is never shown again), Remove after a confirm and Face ID, and the one line, once after
// an agent is added, about which services hear what it says. Shown only while the Mac runs agents: Settings, Labs,
// Agents turns them on or off (POINTE_AGENTS=on|off on the Mac decides instead, and the switch says so).

extension API {
    struct AgentKind: Decodable, Equatable, Identifiable, Hashable {
        let kind: String
        let title: String
        var approvals: Bool? = nil
        var id: String { kind }
    }

    struct Agent: Decodable, Equatable, Identifiable {
        let name: String
        let kind: String
        let url: String
        let title: String
        var state: String? = nil   // "online", "offline", "unknown"
        var why: String? = nil     // why it is offline, in the Mac's fixed words
        var approvals: Bool? = nil
        var vendors_line: String? = nil  // only in the answer to Connect: where its words go
        var id: String { name }
    }

    struct AgentsPage: Decodable, Equatable {
        let enabled: Bool
        let agents: [Agent]
        let kinds: [AgentKind]
    }

    /// In the status while the Mac runs agents; nil from a Mac without them or with them off.
    struct AgentsFlag: Decodable, Equatable {
        var count: Int? = nil
    }

    /// The Labs switch, for the owner's screens: whether agents run, and whether POINTE_AGENTS decides instead of the
    /// saved setting. Nil from an older Mac, or on a screen that is not the owner's.
    struct AgentsSetting: Decodable, Equatable, Sendable {
        var on: Bool = false
        var forced: Bool = false
    }

    /// Once after an agent is added on another screen: where its words go, until OK.
    struct AgentDisclosure: Decodable, Equatable {
        let agent: String
        var line: String? = nil
    }

    /// The agents routes answer a refusal as plain text, the Mac's one sentence.
    private func agentsCall(_ path: String, method: String, body: [String: Any]? = nil, timeout: TimeInterval = 15) async throws -> Data {
        var r = request(path, method: method, body: body)
        r.timeoutInterval = timeout
        let (data, response) = try await send(r)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let text = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            throw Failure.status(code, text.isEmpty || text.hasPrefix("{") || text.hasPrefix("<") ? "HTTP \(code)" : text)
        }
        return data
    }

    func agents() async throws -> AgentsPage {
        try JSONDecoder().decode(AgentsPage.self, from: try await agentsCall("voice/agents", method: "GET"))
    }

    /// Connect an agent. The Mac checks the credential with one call that costs no model turn, then keeps it in its
    /// Keychain; the answer never holds it.
    func addAgent(kind: String, name: String, url: String, secret: String, agent: String) async throws -> Agent {
        try JSONDecoder().decode(Agent.self, from: try await agentsCall(
            "voice/agents", method: "POST", body: ["kind": kind, "name": name, "url": url, "secret": secret, "agent": agent], timeout: 45))
    }

    func removeAgent(_ name: String) async throws {
        let escaped = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? name
        _ = try await agentsCall("voice/agents/\(escaped)", method: "DELETE")
    }

    func agentSeen(_ name: String) async throws { _ = try await agentsCall("voice/agents/seen", method: "POST", body: ["name": name]) }

    /// What a tap on "<agent> replied" opens (AgentReply.swift): the replies not heard yet, or the last one when none
    /// waits. The Mac counts them as heard once read.
    func agentReplies(_ name: String) async throws -> AgentReplies {
        let escaped = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? name
        return try JSONDecoder().decode(AgentReplies.self, from: try await agentsCall("voice/agents/\(escaped)/replies", method: "POST", body: [:]))
    }
}

enum AgentsCopy {
    static let title = "Agents"
    static let labs = "Agents"
    static let labsHelp = "Talk to OpenClaw, Hermes and other agents in your call. Connect one in Settings, Agents."
    static func forced(_ on: Bool) -> String { "POINTE_AGENTS=\(on ? "on" : "off") decides until Pointe restarts without it." }
    static let switchFailed = "The Mac did not change the agents setting."
    static let add = "Connect an agent"
    static let connect = "Connect"
    static let kind = "Kind"
    static let name = "Name"
    static let address = "Address"
    static let credential = "Token or key"
    static let agentID = "Agent (optional)"
    static let connecting = "Checking the agent…"
    static let remove = "Remove"
    static let removeReason = "Remove an agent"
    static let addReason = "Connect an agent"
    static let ok = "OK"
    static let none = "No agents yet. Connect OpenClaw, Hermes, or any agent that speaks A2A or the OpenAI chat API."
    static let help = "Talk to an agent like a session: \"talk to hermes\", or \"ask openclaw to …\". Its replies come in when it is done, and wait in \"what needs me\" if you are busy."
    static let credentialHelp = "OpenClaw: the gateway token. Hermes: the API server key. It goes to the Mac's Keychain and is never shown again."
    static func removeAsk(_ name: String) -> String { "Remove \(name)? Its saved credential is deleted from the Mac." }
    static func removed(_ name: String) -> String { "\(name) is no longer in your voice." }
    static func added(_ name: String) -> String { "\(name) is in your voice." }
    static func state(_ a: API.Agent) -> String {
        switch a.state {
        case "online": return "answers"
        case "offline": return a.why.map { "offline: \($0)" } ?? "offline"
        default: return "not checked yet"
        }
    }
    static func facts(_ a: API.Agent) -> String {
        [a.title, a.url, state(a), a.approvals == true ? "approvals come to you" : ""].filter { !$0.isEmpty }.joined(separator: " · ")
    }
    static func refusal(_ error: Error) -> String {
        guard case API.Failure.status(let code, let detail) = error else { return "The Mac did not answer." }
        if detail.hasPrefix("HTTP ") { return code == 404 ? "Pointe on the Mac has no agents yet: update it." : "The Mac did not do it." }
        return detail
    }
}

/// What the Agents sheet asks of the call.
struct AgentsActions {
    let ownerCheck: (String) async -> Bool
    let load: () async throws -> API.AgentsPage
    let add: (String, String, String, String, String) async throws -> API.Agent
    let remove: (String) async throws -> Void
    let seen: (String) async -> Void
}

@MainActor @Observable
final class AgentsModel {
    private(set) var page: API.AgentsPage?
    private(set) var problem: String?
    private(set) var done: String?
    /// The one line after Connect: which services hear the agent, until OK.
    private(set) var disclosure: (name: String, line: String)?
    let actions: AgentsActions

    init(actions: AgentsActions, elsewhere: API.AgentDisclosure? = nil) {
        self.actions = actions
        if let d = elsewhere, let line = d.line, !line.isEmpty { disclosure = (d.agent, line) }  // added on the page or in a terminal
    }

    func load() async {
        do { page = try await actions.load(); problem = nil } catch { problem = AgentsCopy.refusal(error) }
    }

    func added(_ agent: API.Agent) async {
        done = AgentsCopy.added(agent.name)
        if let line = agent.vendors_line, !line.isEmpty { disclosure = (agent.name, line) }
        await load()
    }

    func ok() async {
        guard let d = disclosure else { return }
        disclosure = nil
        await actions.seen(d.name)
    }

    func remove(_ name: String) async {
        problem = nil; done = nil
        guard await actions.ownerCheck("\(AgentsCopy.removeReason): \(name)") else { return }
        do { try await actions.remove(name); done = AgentsCopy.removed(name) } catch { problem = AgentsCopy.refusal(error) }
        await load()
    }
}

struct AgentsSheet: View {
    @State private var model: AgentsModel
    @State private var adding = false
    @State private var removing: String?
    @Environment(\.dismiss) private var dismiss

    init(actions: AgentsActions, elsewhere: API.AgentDisclosure? = nil) {
        _model = State(initialValue: AgentsModel(actions: actions, elsewhere: elsewhere))
    }

    var body: some View {
        NavigationStack {
            BrandForm {
                if let d = model.disclosure {
                    Section {
                        VStack(alignment: .leading, spacing: 10) {
                            Text(d.line).font(.brand(.subheadline)).fixedSize(horizontal: false, vertical: true)
                                .accessibilityIdentifier("agentDisclosureText")
                            Button(AgentsCopy.ok) { Task { await model.ok() } }.buttonStyle(.brandPrimary).controlSize(.small)
                                .accessibilityIdentifier("agentDisclosureOK")
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                Section {
                    if let agents = model.page?.agents, !agents.isEmpty {
                        ForEach(agents) { row($0) }
                    } else if model.page != nil {
                        Text(AgentsCopy.none).foregroundStyle(Brand.muted).accessibilityIdentifier("agentsNone")
                    }
                    if let problem = model.problem {
                        Text(problem).foregroundStyle(Brand.accent).accessibilityIdentifier("agentsProblem")
                    }
                    if let done = model.done {
                        Text(done).foregroundStyle(Brand.muted).accessibilityIdentifier("agentsDone")
                    }
                } footer: { Group { Text(AgentsCopy.help) }.brandFootnote() }
                Section {
                    Button { adding = true } label: { Label(AgentsCopy.add, systemImage: "plus") }
                        .disabled(model.page?.kinds.isEmpty ?? true)
                        .accessibilityIdentifier("agentAdd")
                }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle(AgentsCopy.title)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task { await model.load() }
            .sheet(isPresented: $adding) {
                AddAgentSheet(kinds: model.page?.kinds ?? [], actions: model.actions) { agent in
                    Task { await model.added(agent) }
                }
                .presentationDetents([.large])
                .sheetSurface()
            }
            .confirmationDialog(removing.map(AgentsCopy.removeAsk) ?? "", isPresented: Binding(
                get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible, presenting: removing) { name in
                Button("\(AgentsCopy.remove) \(name)", role: .destructive) { Task { await model.remove(name) } }
                    .accessibilityIdentifier("agentRemoveConfirm")
                Button("Cancel", role: .cancel) {}
            }
        }
    }

    private func row(_ a: API.Agent) -> some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(a.name).font(.brand(.body, .semibold))
                Text(AgentsCopy.facts(a)).font(.brand(.caption))
                    .foregroundStyle(a.state == "offline" ? Brand.accent : Brand.muted)
                    .environment(\.layoutDirection, .leftToRight)  // an address reads left to right
            }
            Spacer()
            Button(AgentsCopy.remove, role: .destructive) { removing = a.name }
                .buttonStyle(.brandQuiet).controlSize(.small)
                .accessibilityIdentifier("agentRemove.\(a.name)")
                .accessibilityLabel("\(AgentsCopy.remove) \(a.name)")
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("agent.\(a.name)")
    }
}

@MainActor @Observable
final class AddAgentModel {
    var kind: String
    var name: String
    var url = ""
    var secret = ""
    var agent = ""
    private(set) var working = false
    private(set) var problem: String?
    private(set) var added: API.Agent?
    let actions: AgentsActions

    init(kinds: [API.AgentKind], actions: AgentsActions) {
        self.actions = actions
        kind = kinds.first?.kind ?? "openclaw"
        name = kinds.first?.kind ?? "openclaw"
    }

    var canAdd: Bool {
        !working && !name.trimmingCharacters(in: .whitespaces).isEmpty && !url.trimmingCharacters(in: .whitespaces).isEmpty
            && !secret.isEmpty
    }

    /// The kind picked: the name follows it until the person typed their own.
    func picked(_ new: String, from old: String) {
        if name.isEmpty || name == old { name = new }
    }

    func add() async {
        guard canAdd else { return }
        problem = nil
        guard await actions.ownerCheck(AgentsCopy.addReason) else { return }
        working = true
        defer { working = false }
        do {
            added = try await actions.add(kind, name.trimmingCharacters(in: .whitespaces), url.trimmingCharacters(in: .whitespaces),
                                          secret, agent.trimmingCharacters(in: .whitespaces))
            secret = ""
        } catch { problem = AgentsCopy.refusal(error) }
    }
}

struct AddAgentSheet: View {
    let kinds: [API.AgentKind]
    let done: (API.Agent) -> Void
    @State private var model: AddAgentModel
    @Environment(\.dismiss) private var dismiss

    init(kinds: [API.AgentKind], actions: AgentsActions, done: @escaping (API.Agent) -> Void) {
        self.kinds = kinds
        self.done = done
        _model = State(initialValue: AddAgentModel(kinds: kinds, actions: actions))
    }

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    Picker(AgentsCopy.kind, selection: Binding(get: { model.kind }, set: { new in
                        let old = model.kind; model.kind = new; model.picked(new, from: old) })) {
                        ForEach(kinds) { Text($0.title).tag($0.kind) }
                    }
                    .accessibilityIdentifier("agentKind")
                    LabeledContent(AgentsCopy.name) {
                        TextField(AgentsCopy.name, text: $model.name).plainEntry().multilineTextAlignment(.trailing)
                            .accessibilityIdentifier("agentName")
                    }
                    LabeledContent(AgentsCopy.address) {
                        TextField("127.0.0.1:18789", text: $model.url).plainEntry().multilineTextAlignment(.trailing)
                            .environment(\.layoutDirection, .leftToRight)
                            .accessibilityIdentifier("agentURL")
                    }
                    LabeledContent(AgentsCopy.credential) {
                        SecureField(AgentsCopy.credential, text: $model.secret).multilineTextAlignment(.trailing)
                            .accessibilityIdentifier("agentSecret")
                    }
                    if model.kind == "openclaw" || model.kind == "openai" {
                        LabeledContent(AgentsCopy.agentID) {
                            TextField(model.kind == "openclaw" ? "main" : "model", text: $model.agent).plainEntry()
                                .multilineTextAlignment(.trailing)
                                .accessibilityIdentifier("agentID")
                        }
                    }
                    if model.working {
                        HStack(spacing: 10) {
                            ProgressView().controlSize(.small)
                            Text(AgentsCopy.connecting).foregroundStyle(Brand.muted)
                        }
                        .accessibilityIdentifier("agentWorking")
                    }
                    if let problem = model.problem {
                        Text(problem).foregroundStyle(Brand.accent).fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("agentProblem")
                    }
                } footer: { Group { Text(AgentsCopy.credentialHelp) }.brandFootnote() }
            }
            .scrollContentBackground(.hidden)
            .sheetTitle(AgentsCopy.add)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }.accessibilityIdentifier("agentAddCancel")
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(AgentsCopy.connect) { Task { await model.add() } }
                        .disabled(!model.canAdd)
                        .accessibilityIdentifier("agentConnect")
                }
            }
            .onChange(of: model.added) { _, added in
                if let added { done(added); dismiss() }
            }
        }
    }
}

// MARK: demo: made-up agents, nothing sent

extension Demo {
    @MainActor static func agentsActions(ownerCheck: @escaping (String) async -> Bool) -> AgentsActions {
        let kinds = [API.AgentKind(kind: "openclaw", title: "OpenClaw", approvals: true),
                     API.AgentKind(kind: "hermes", title: "Hermes Agent", approvals: true),
                     API.AgentKind(kind: "a2a", title: "Any A2A agent", approvals: false),
                     API.AgentKind(kind: "openai", title: "Any OpenAI-compatible agent", approvals: false)]
        let list = DemoAgents(agents: [
            API.Agent(name: "juniper", kind: "openclaw", url: "127.0.0.1:18789", title: "OpenClaw", state: "online", approvals: true),
            API.Agent(name: "hermes", kind: "hermes", url: "127.0.0.1:8642", title: "Hermes Agent", state: "offline",
                      why: "hermes is not reachable: is it running?", approvals: true)])
        return AgentsActions(ownerCheck: ownerCheck, load: { API.AgentsPage(enabled: true, agents: list.agents, kinds: kinds) },
                             add: { kind, name, url, _, _ in
                                 let added = API.Agent(name: name, kind: kind, url: url, title: kinds.first { $0.kind == kind }?.title ?? kind,
                                                       state: "online", vendors_line: "What \(name) says is transcribed into your call like a session's: it reaches Anthropic and ElevenLabs, the services your voice uses.")
                                 list.agents.append(added)
                                 return added
                             },
                             remove: { name in list.agents.removeAll { $0.name == name } }, seen: { _ in })
    }
}

/// The demo's list, kept between loads of the sheet.
@MainActor final class DemoAgents {
    var agents: [API.Agent]
    init(agents: [API.Agent]) { self.agents = agents }
}
