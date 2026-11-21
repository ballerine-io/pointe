// Pair a phone, from the Mac app: the page's Settings → Phone (ui.html, phone_pairing.py). The Mac is the side that
// shows the code, so this sheet is the Mac's alone; the phone's side is PairView.
#if os(macOS)
import CoreImage.CIFilterBuiltins
import SwiftUI

/// The words are the page's (ui.html, Settings → Phone): tests/test_macos_parity.py holds them to it.
enum PhoneCopy {
    static let title = "Phone"
    static let none = "No phone paired yet."
    static let connect = "Connect your phone"
    static let connectAnother = "Connect another phone"
    static let unpair = "Unpair"
    static let unpairAll = "Unpair all"
    static let unpairAllSure = "Unpair every phone?"
    static let rule = "Each phone has its own key. Connecting another phone keeps the ones already paired; Unpair signs out only that phone."
    static let how = "How should your phone reach this Mac?"
    static let looking = "Looking for ways your phone can reach this Mac…"
    static let hostHint = "Or a name you set up (Twingate, a VPN)"
    static let check = "Check"
    static let show = "Show the code"
    static let cancel = "Cancel"
    static let scan = "Scan with your iPhone's Camera, or in the Pointe app."
    static let copyLink = "Can't scan? Copy the link"
    static let copied = "Copied"
    static let expired = "The code expired. Connect your phone again to make a new one."
    static let noAnswer = "The Mac did not answer."
    static let newCertificate = "Choosing this makes a new certificate for this Mac: a phone or machine paired now must connect again."
    static let recommended = "Recommended"
    static let setUpNow = "set up now"
    static let allUnpaired = "Every phone unpaired. Each must connect again."
    static func unpairSure(_ name: String) -> String { "Unpair \(name)?" }
    static func unpaired(_ name: String) -> String { "\(name) unpaired." }
    static func connected(_ name: String) -> String { "Connected: \(name)" }
    static func waiting(_ left: String) -> String { "Waiting for your phone · expires in \(left)" }
}

extension API {
    /// Settings → Phone: names and times, never a key or a code.
    struct Phones: Decodable, Equatable {
        let paired: [Phone]
    }

    struct Phone: Decodable, Equatable, Identifiable {
        let id: String
        let name: String
        let online: Bool?
        let last_seen: Double?
        let paired_at: Double?
        let legacy: Bool?
    }

    struct PhoneRoutes: Decodable, Equatable {
        let routes: [PhoneRoute]
        let advice: String?
    }

    struct PhoneRoute: Decodable, Equatable, Identifiable {
        let kind: String
        let host: String?
        let label: String
        let words: String?
        let usable: Bool
        let recommended: Bool?
        let current: Bool?
        let problem: String?
        let new_certificate: Bool?
        var id: String { "\(kind)|\(host ?? "")" }
    }

    struct PhoneInvite: Decodable, Equatable {
        let code: String
        let link: String
        let expires_in: Double
    }

    struct PhoneInviteState: Decodable, Equatable {
        struct Paired: Decodable, Equatable { let name: String }
        let expires_in: Double?
        let paired: Paired?
        let ended: String?
    }

    /// The daemon's refusal is plain text here ("no such route"), not JSON.
    private func phone<T: Decodable>(_ path: String, body: [String: Any]? = nil, query: [URLQueryItem] = []) async throws -> T {
        let (data, response) = try await send(request(path, method: body == nil ? "GET" : "POST", body: body, query: query))
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            let text = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            throw Failure.status(code, text.isEmpty || text.hasPrefix("{") ? PhoneCopy.noAnswer : text)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private struct Done: Decodable { let ok: Bool? }

    func phoneRoutes(host: String?) async throws -> PhoneRoutes {
        try await phone("voice/phone/routes", query: host.map { [URLQueryItem(name: "host", value: $0)] } ?? [])
    }

    func phoneInvite(_ route: PhoneRoute) async throws -> PhoneInvite {
        try await phone("voice/phone/invite", body: ["kind": route.kind, "host": route.host ?? ""])
    }

    func phoneInviteState() async throws -> PhoneInviteState { try await phone("voice/phone/invite") }

    func cancelPhoneInvite() async throws { let _: Done = try await phone("voice/phone/invite", body: ["cancel": true]) }

    func unpairPhone(_ id: String?) async throws {
        let _: Done = try await phone("voice/phone/unpair", body: id.map { ["id": $0] } ?? ["all": true])
    }
}

/// What the sheet asks of the daemon; a test or the demo gives its own.
struct PhoneActions {
    let routes: (String?) async throws -> API.PhoneRoutes
    let invite: (API.PhoneRoute) async throws -> API.PhoneInvite
    let state: () async throws -> API.PhoneInviteState
    let cancel: () async throws -> Void
    let unpair: (String?) async throws -> Void

    init(api: API) {
        routes = { try await api.phoneRoutes(host: $0) }
        invite = { try await api.phoneInvite($0) }
        state = { try await api.phoneInviteState() }
        cancel = { try await api.cancelPhoneInvite() }
        unpair = { try await api.unpairPhone($0) }
    }

    init(routes: @escaping (String?) async throws -> API.PhoneRoutes, invite: @escaping (API.PhoneRoute) async throws -> API.PhoneInvite,
         state: @escaping () async throws -> API.PhoneInviteState, cancel: @escaping () async throws -> Void,
         unpair: @escaping (String?) async throws -> Void) {
        self.routes = routes; self.invite = invite; self.state = state; self.cancel = cancel; self.unpair = unpair
    }
}

/// The sheet's steps, apart from how they are drawn: the list, choosing a route, the code and its countdown.
struct PhonePairing: Equatable {
    enum Step: Equatable { case list, routes, code }
    var step = Step.list
    var routes: API.PhoneRoutes?
    var pick: API.PhoneRoute?
    var invite: API.PhoneInvite?
    var until = Date.distantPast
    var done: String?
    var problem: String?
    /// Which Unpair was clicked once ("all" for every phone), and until when the second click counts.
    var sure: String?
    var sureUntil = Date.distantPast

    /// The routes arrived (after a typed name, or at the start): the typed one when it works, else what was picked while
    /// it still works, else the recommended one.
    mutating func found(_ fresh: API.PhoneRoutes, typed: String?) {
        routes = fresh
        let name = typed?.trimmingCharacters(in: .whitespaces).lowercased() ?? ""
        if let want = fresh.routes.first(where: { $0.kind == "host" && $0.host == name && $0.usable }), !name.isEmpty { pick = want }
        else if pick == nil || !fresh.routes.contains(where: { $0.id == pick?.id && $0.usable }) { pick = fresh.routes.first { $0.recommended == true } }
    }

    mutating func made(_ invite: API.PhoneInvite, now: Date) {
        self.invite = invite
        until = now.addingTimeInterval(invite.expires_in)
        step = .code
        done = nil
        problem = nil
    }

    /// The daemon's word on the code, once a second. True when the code is over (paired, ended or expired).
    mutating func follow(_ state: API.PhoneInviteState?, now: Date) -> Bool {
        guard step == .code else { return true }
        if let name = state?.paired?.name { finish(done: PhoneCopy.connected(name)); return true }
        if let ended = state?.ended, !ended.isEmpty { finish(problem: ended); return true }
        if now >= until || (state != nil && (state?.expires_in ?? 0) <= 0) { finish(problem: PhoneCopy.expired); return true }
        return false
    }

    mutating func finish(done: String? = nil, problem: String? = nil) {
        invite = nil
        step = .list
        self.done = done
        self.problem = problem
    }

    /// Two clicks, no dialog. True on the second, within three seconds of the first.
    mutating func confirmUnpair(_ id: String, now: Date) -> Bool {
        if sure == id, now < sureUntil { sure = nil; return true }
        sure = id
        sureUntil = now.addingTimeInterval(3)
        return false
    }

    func left(now: Date) -> String {
        let s = max(0, Int(until.timeIntervalSince(now).rounded()))
        return "\(s / 60):\(String(format: "%02d", s % 60))"
    }
}

struct PhoneSheet: View {
    let phones: [API.Phone]
    let act: PhoneActions
    @State private var pairing = PhonePairing()
    @State private var host = ""
    @State private var busy = false
    @State private var copied = false
    @State private var now = Date()
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    if phones.isEmpty { Text(PhoneCopy.none).foregroundStyle(Brand.muted) }
                    ForEach(phones) { phone in
                        LabeledContent {
                            Button(pairing.sure == phone.id && now < pairing.sureUntil ? PhoneCopy.unpairSure(phone.name) : PhoneCopy.unpair) {
                                unpair(phone.id, name: phone.legacy == true || phone.name.isEmpty ? "Phone" : phone.name)
                            }
                            .buttonStyle(.brandQuiet).controlSize(.small)
                            .accessibilityIdentifier("phoneUnpair.\(phone.name)")
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(phone.name)
                                Text(Self.seen(phone, now: now)).font(.brand(.caption)).foregroundStyle(Brand.muted)
                            }
                        }
                    }
                } footer: {
                    if !phones.isEmpty { Text(PhoneCopy.rule) }
                }
                switch pairing.step {
                case .list:
                    Section {
                        HStack {
                            Button(phones.isEmpty ? PhoneCopy.connect : PhoneCopy.connectAnother) { Task { await look(nil) } }
                                .buttonStyle(.brandPrimary).controlSize(.small).accessibilityIdentifier("phoneConnect")
                            if phones.count > 1 {
                                Button(pairing.sure == "all" && now < pairing.sureUntil ? PhoneCopy.unpairAllSure : PhoneCopy.unpairAll) { unpair(nil, name: "") }
                                    .buttonStyle(.brandQuiet).controlSize(.small)
                            }
                            if busy { ProgressView().controlSize(.small) }
                        }
                    }
                case .routes: routes
                case .code: code
                }
                if let done = pairing.done { Section { Text(done).foregroundStyle(Brand.successText).accessibilityIdentifier("phoneDone") } }
                if let problem = pairing.problem {
                    Section { Label(problem, systemImage: "exclamationmark.triangle.fill").foregroundStyle(Brand.accent).accessibilityIdentifier("phoneProblem") }
                }
            }
            .sheetTitle(PhoneCopy.title)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .task(id: pairing.step) {  // once a second while the code shows: the countdown, and the phone pairing
            while !Task.isCancelled, pairing.step == .code {
                try? await Task.sleep(for: .seconds(1))
                now = Date()
                let state = try? await act.state()
                if pairing.follow(state, now: now) { break }
            }
        }
        .onDisappear { if pairing.step == .code { Task { try? await act.cancel() } } }  // a code is never left showing behind a closed sheet
    }

    @ViewBuilder private var routes: some View {
        Section {
            if let found = pairing.routes {
                ForEach(found.routes) { route in
                    Button { pairing.pick = route } label: {
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: pairing.pick?.id == route.id ? "largecircle.fill.circle" : "circle")
                                .foregroundStyle(pairing.pick?.id == route.id ? Brand.accent : Brand.dim)
                            VStack(alignment: .leading, spacing: 2) {
                                HStack(spacing: 6) {
                                    Text(route.label).foregroundStyle(Brand.text)
                                    if route.recommended == true { Text(PhoneCopy.recommended).font(.brand(.caption2, .semibold)).foregroundStyle(Brand.successText) }
                                    if route.current == true { Text(PhoneCopy.setUpNow).font(.brand(.caption2)).foregroundStyle(Brand.muted) }
                                }
                                if let words = route.words, !words.isEmpty { Text(words).font(.brand(.caption)).foregroundStyle(Brand.muted) }
                                if let problem = route.problem, !problem.isEmpty { Text(problem).font(.brand(.caption)).foregroundStyle(Brand.accent) }
                            }
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(!route.usable)
                    .opacity(route.usable ? 1 : 0.5)
                    .accessibilityIdentifier("phoneRoute.\(route.kind)")
                }
            } else {
                Text(PhoneCopy.looking).foregroundStyle(Brand.muted)
            }
            HStack {
                TextField(PhoneCopy.hostHint, text: $host).textFieldStyle(.roundedBorder).plainEntry().onSubmit { Task { await look(host) } }
                Button(PhoneCopy.check) { Task { await look(host) } }.buttonStyle(.brandQuiet).controlSize(.small).disabled(busy)
            }
        } header: {
            Text(PhoneCopy.how)
        } footer: {
            VStack(alignment: .leading, spacing: 4) {
                if let advice = pairing.routes?.advice, !advice.isEmpty { Text(advice) }
                if pairing.pick?.new_certificate == true { Text(PhoneCopy.newCertificate) }
            }
        }
        Section {
            HStack {
                Button(PhoneCopy.show) { Task { await show() } }.buttonStyle(.brandPrimary).controlSize(.small)
                    .disabled(pairing.pick == nil || busy).accessibilityIdentifier("phoneShowCode")
                Button(PhoneCopy.cancel) { pairing.step = .list }.buttonStyle(.brandQuiet).controlSize(.small)
            }
        }
    }

    @ViewBuilder private var code: some View {
        Section {
            VStack(spacing: 12) {
                Text(PhoneCopy.scan).font(.brand(.callout)).foregroundStyle(Brand.muted)
                if let link = pairing.invite?.link, let image = Self.qr(link) {
                    Image(nsImage: image).interpolation(.none).resizable().frame(width: 220, height: 220)
                        .padding(12).background(Color.white, in: RoundedRectangle(cornerRadius: 12))  // a code is read on white, in either theme
                        .accessibilityLabel("Pairing code").accessibilityIdentifier("phoneCode")
                }
                Text(PhoneCopy.waiting(pairing.left(now: now))).font(.brand(.footnote)).monospacedDigit().foregroundStyle(Brand.muted)
                    .accessibilityIdentifier("phoneCountdown")
                HStack {
                    Button(copied ? PhoneCopy.copied : PhoneCopy.copyLink) {  // the link stays off the screen; the clipboard carries it
                        if let link = pairing.invite?.link { Clipboard.copy(link) }
                        copied = true
                        Task { try? await Task.sleep(for: .seconds(1.5)); copied = false }
                    }
                    .buttonStyle(.brandQuiet).controlSize(.small)
                    Button(PhoneCopy.cancel) { Task { try? await act.cancel(); pairing.finish() } }.buttonStyle(.brandQuiet).controlSize(.small)
                }
            }
            .frame(maxWidth: .infinity)
        }
    }

    private func look(_ typed: String?) async {
        pairing.done = nil; pairing.problem = nil
        if pairing.step != .routes { pairing.step = .routes; pairing.routes = nil; pairing.pick = nil }
        busy = true
        defer { busy = false }
        do { pairing.found(try await act.routes(typed.flatMap { $0.trimmingCharacters(in: .whitespaces).isEmpty ? nil : $0 }), typed: typed) }
        catch { pairing.problem = Self.reason(error) }
    }

    private func show() async {
        guard let pick = pairing.pick else { return }
        busy = true
        defer { busy = false }
        do { now = Date(); pairing.made(try await act.invite(pick), now: now) } catch { pairing.problem = Self.reason(error) }
    }

    private func unpair(_ id: String?, name: String) {
        now = Date()
        guard pairing.confirmUnpair(id ?? "all", now: now) else {
            Task { try? await Task.sleep(for: .seconds(3.1)); now = Date() }  // the button goes back to "Unpair"
            return
        }
        Task {
            do {
                try await act.unpair(id)
                pairing.done = id == nil ? PhoneCopy.allUnpaired : PhoneCopy.unpaired(name)
                pairing.problem = nil
            } catch { pairing.problem = Self.reason(error) }
        }
    }

    static func reason(_ error: Error) -> String {
        if case API.Failure.status(_, let detail) = error { return detail }
        return PhoneCopy.noAnswer
    }

    /// "online now · paired 3 days ago", as the page's row.
    static func seen(_ phone: API.Phone, now: Date) -> String {
        let seen = phone.online == true ? "online now" : phone.last_seen.map { "last seen \(since($0, now: now))" } ?? "not seen yet"
        let when = phone.legacy == true ? "paired before this Mac gave each phone its own key" : "paired \(since(phone.paired_at ?? 0, now: now))"
        return "\(seen) · \(when)"
    }

    static func since(_ epoch: Double, now: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .full
        return formatter.localizedString(for: Date(timeIntervalSince1970: epoch), relativeTo: now)
    }

    /// Drawn on this Mac: no image service sees the code.
    static func qr(_ text: String) -> NSImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: 8, y: 8)) else { return nil }
        let rep = NSCIImageRep(ciImage: output)
        let image = NSImage(size: rep.size)
        image.addRepresentation(rep)
        return image
    }
}
#endif
