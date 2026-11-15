import SwiftUI
import UserNotifications

// Audio briefings (docs/features/briefings.md): what each session did, failed and waits on, most
// urgent first. The Mac builds and speaks it; the phone starts it, steers it, shows it written, and sets the schedule.

extension API {
    struct BriefingStatus: Decodable, Equatable {
        var playing: Bool?
        var paused: String?         // "", "question" (the user asked something), "press" (push to talk)
        var part: Int?
        var parts: Int?
        let id: String?
        var building: Bool?
        let latest_id: String?
        var ready: BriefingReady?   // a scheduled briefing not heard yet

        var isPlaying: Bool { playing == true }
        var isPaused: Bool { !(paused ?? "").isEmpty }
        var isOn: Bool { isPlaying || isPaused }
    }

    struct BriefingReady: Decodable, Equatable {
        let id: String
        let at: Double?
        let slot: String?
        let empty: Bool?
    }

    struct BriefingSection: Decodable, Equatable, Hashable {
        let session: String
        let status: String          // waiting, failed, done, quiet
        let text: String
    }

    struct Briefing: Decodable, Equatable, Identifiable {
        let id: String
        let at: Double
        let since_label: String?
        let length: String?
        let sections: [BriefingSection]?
        let opener: String?
        let scheduled: Bool?
        let empty: Bool?
    }

    struct BriefingSchedule: Decodable, Equatable {
        var time: String
        var days: [Int]
        var length: String
        var speak_on_connect: Bool
        var skip_empty: Bool
    }

    struct BriefingsPage: Decodable {
        let briefings: [Briefing]?
        let schedule: BriefingSchedule?
        let status: BriefingStatus?
    }
}

extension API.Status {
    /// "Your 08:30 briefing is ready.": the Mac's attention item for a scheduled briefing.
    var briefingAlert: API.Attention? { attention?.first { $0.kind == "briefing" } }
}

/// Word for word the page's copy (ui.html): the two must not drift.
enum BriefingCopy {
    static let title = "Briefing"
    static let lede = "What each session did, failed and waits on, most urgent first. It reads; it never sends or approves."
    static let start = "Brief me"
    static let history = "Last 7 briefings"
    static let settingsTitle = "Briefings"
    static let settingsItem = "Briefing settings"
    static let scheduled = "Scheduled briefing"
    static let note = "The briefing is read on your Mac at that time, with or without a call. Nothing is sent to your sessions."
    static let speakOnConnect = "Speak when I connect"
    static let skipEmpty = "Skip empty briefings"
    static let reminderBody = "Your briefing is ready"
    static let days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]  // Monday is 0, as on the Mac
    static let lengths = [("short", "Short"), ("normal", "Normal"), ("full", "Full")]
    static let sinceChoices: [(label: String, since: String)] = [("The night", "the night"), ("Today", "today"), ("Yesterday", "yesterday")]

    static func chip(_ status: String) -> String {
        switch status {
        case "waiting": "Needs you"
        case "failed": "Failed"
        case "quiet": "Quiet"
        default: "Done"
        }
    }

    static func progress(_ s: API.BriefingStatus) -> String? {
        if s.building == true { return "Reading your sessions…" }
        let n = max(s.part ?? 1, 1), m = s.parts ?? 0
        if s.isPaused { return "Paused: part \(n) of \(m)" }
        if s.isPlaying { return "Part \(n) of \(m)" }
        return nil
    }

    /// The page's checks before a schedule is sent: a scheduled briefing needs a time and at least one day.
    static func check(time: String, days: [Int]) -> String? {
        guard !time.isEmpty else { return nil }  // off: nothing to check
        return days.isEmpty ? "Pick at least one day for the briefing." : nil
    }

    /// The Mac's 400 says what was wrong with the schedule; without it, why it was not saved is unknown.
    static func notSaved(_ detail: String?) -> String {
        guard let d = detail?.trimmingCharacters(in: .whitespaces), !d.isEmpty, !d.hasPrefix("HTTP ") else {
            return "Not saved: the Mac did not answer."
        }
        let said = CallView.sentence(d)
        return "Not saved: \(said.prefix(1).lowercased())\(said.dropFirst())"
    }

    static func cannotStart(callUp: Bool, meetingOn: Bool) -> String? {
        if !callUp { return "Connect to hear it." }
        if meetingOn { return "Not during a meeting." }
        return nil
    }

    static func heading(at: Double, since: String, scheduled: Bool) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "EEE HH:mm"
        return "\(f.string(from: Date(timeIntervalSince1970: at))) · \(since)" + (scheduled ? " · scheduled" : "")
    }
}

/// The phone's own nudge at the scheduled time: the Mac cannot push, so the phone keeps the clock too.
enum BriefingReminder {
    static let prefix = "pointe-briefing-"

    /// One weekly trigger per chosen day. Monday is 0 on the Mac; Apple counts Sunday as 1.
    static func triggers(time: String, days: [Int]) -> [DateComponents] {
        let parts = time.split(separator: ":").compactMap { Int($0) }
        guard time.count == 5, parts.count == 2, (0...23).contains(parts[0]), (0...59).contains(parts[1]) else { return [] }
        return days.filter { (0...6).contains($0) }.map { day in
            var c = DateComponents()
            c.weekday = (day + 1) % 7 + 1
            c.hour = parts[0]
            c.minute = parts[1]
            return c
        }
    }

    /// Replaces the reminders with the schedule's. Asks for permission only when a time is set.
    static func apply(_ schedule: API.BriefingSchedule) async {
        let center = UNUserNotificationCenter.current()
        let old = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix(prefix) }
        center.removePendingNotificationRequests(withIdentifiers: old)
        let wanted = triggers(time: schedule.time, days: schedule.days)
        guard !wanted.isEmpty, (try? await center.requestAuthorization(options: [.alert, .sound])) == true else { return }
        for c in wanted {
            let content = UNMutableNotificationContent()
            content.title = "Pointe"
            content.body = BriefingCopy.reminderBody
            let trigger = UNCalendarNotificationTrigger(dateMatching: c, repeats: true)
            try? await center.add(UNNotificationRequest(identifier: "\(prefix)\(c.weekday ?? 0)", content: content, trigger: trigger))
        }
    }
}

/// The ready banner: a scheduled briefing waits to be heard.
struct BriefingReadyCard: View {
    let alert: API.Attention
    let hear: () async -> Void
    let dismiss: () async -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(alert.text ?? "", systemImage: "sun.horizon.fill").font(.brand(.subheadline, .semibold))
            HStack(spacing: 10) {
                Button { Task { await dismiss() } } label: { Text("Dismiss").frame(maxWidth: .infinity) }
                    .buttonStyle(.brandQuiet)
                Button { Task { await hear() } } label: { Text("Hear it").frame(maxWidth: .infinity) }
                    .buttonStyle(.brandPrimary)
            }
        }
        .padding(14)
        .brandCard()
        .accessibilityIdentifier("briefingReady")
    }
}

struct BriefingSheet: View {
    let status: API.BriefingStatus?
    let callUp: Bool
    let meetingOn: Bool
    let load: () async -> API.BriefingsPage?
    /// start / skip / stop / continue: nil when the Mac took it, else its reason.
    let act: ([String: any Sendable]) async -> String?
    @Environment(\.dismiss) private var dismiss
    @State private var since = "the night"
    @State private var length: String?
    @State private var page: API.BriefingsPage?
    @State private var loaded = false
    @State private var refused: String?
    @State private var busy = false

    var body: some View {
        NavigationStack {
            BrandForm {
                Section { controls } header: { Group { Text(BriefingCopy.lede).textCase(nil) }.brandFootnote() }
                if let refused {
                    Label(refused, systemImage: "exclamationmark.triangle.fill").foregroundStyle(Brand.accent)
                }
                KickerSection(BriefingCopy.history) { history }
            }
            .scrollContentBackground(.hidden)
            .navigationTitle(BriefingCopy.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task { await reload() }
            .onChange(of: status?.latest_id) { Task { await reload() } }
        }
    }

    @ViewBuilder private var controls: some View {
        if let line = status.flatMap(BriefingCopy.progress) {
            Text(line).font(.brand(.headline)).accessibilityIdentifier("briefingProgress")
        }
        if let s = status, s.isOn {
            HStack(spacing: 10) {
                if s.isPaused {
                    button("Go on", "continue", prominent: true)
                } else {
                    button("Skip", "skip", prominent: true)
                }
                button("Stop", "stop", prominent: false)
            }
        } else {
            Picker("Since", selection: $since) {
                ForEach(BriefingCopy.sinceChoices, id: \.since) { Text($0.label).tag($0.since) }
            }
            .pickerStyle(.segmented)
            Picker("Length", selection: Binding(get: { length ?? page?.schedule?.length ?? "normal" }, set: { length = $0 })) {
                ForEach(BriefingCopy.lengths, id: \.0) { Text($0.1).tag($0.0) }
            }
            let why = BriefingCopy.cannotStart(callUp: callUp, meetingOn: meetingOn)
            Button {
                Task { await run(["action": "start", "since": since, "length": length ?? page?.schedule?.length ?? "normal"]) }
            } label: { Text(BriefingCopy.start).frame(maxWidth: .infinity) }
                .buttonStyle(.brandPrimary)
                .disabled(why != nil || busy || status?.building == true)
            if let why { Text(why).font(.brand(.footnote)).foregroundStyle(Brand.muted) }
        }
    }

    private func button(_ title: String, _ action: String, prominent: Bool) -> some View {
        Button { Task { await run(["action": action]) } } label: { Text(title).frame(maxWidth: .infinity) }
            .buttonStyle(BrandButtonStyle(prominent: prominent))
            .disabled(busy)
    }

    @ViewBuilder private var history: some View {
        let items = page?.briefings ?? []
        if items.isEmpty {
            Text(loaded ? "No briefing yet." : "Loading…").foregroundStyle(Brand.muted)
        }
        ForEach(items) { b in
            VStack(alignment: .leading, spacing: 8) {
                Text(BriefingCopy.heading(at: b.at, since: b.since_label ?? "", scheduled: b.scheduled == true))
                    .font(.brand(.caption)).foregroundStyle(Brand.muted)
                if let opener = b.opener { Text(opener).font(.brand(.subheadline, .semibold)) }
                if b.empty != true {
                    ForEach(b.sections ?? [], id: \.self) { s in
                        VStack(alignment: .leading, spacing: 3) {
                            HStack(spacing: 6) {
                                Text(s.session).font(.brand(.footnote, .semibold))
                                Text(BriefingCopy.chip(s.status)).font(.brand(.caption2, .semibold))
                                    .padding(.horizontal, 7).padding(.vertical, 2)
                                    .background(s.status == "waiting" || s.status == "failed" ? Brand.tint : Brand.raised,
                                                in: Capsule())
                            }
                            Text(s.text).readingDirection(of: s.text).font(.brand(.footnote)).foregroundStyle(Brand.muted)
                        }
                    }
                }
            }
            .padding(.vertical, 4)
        }
    }

    private func reload() async {
        if let fresh = await load() { page = fresh }
        loaded = true
    }

    private func run(_ body: [String: any Sendable]) async {
        busy = true
        refused = await act(body)
        busy = false
    }
}

/// Lets one button pick bordered or prominent without two copies of its label.
struct AnyPrimitiveButtonStyle: PrimitiveButtonStyle {
    private let make: (Configuration) -> AnyView
    init<S: PrimitiveButtonStyle>(_ style: S) { make = { AnyView(style.makeBody(configuration: $0)) } }
    func makeBody(configuration: Configuration) -> some View { make(configuration) }
}

struct BriefingNotSaved: Error { let message: String }

/// Settings → Briefings: the schedule, kept on the Mac. The phone also sets its own reminder at that time.
struct BriefingSettingsSheet: View {
    let load: () async -> API.BriefingSchedule?
    /// The changed fields; the Mac's schedule back, or why it was not saved.
    let save: ([String: any Sendable]) async -> Result<API.BriefingSchedule, BriefingNotSaved>
    @Environment(\.dismiss) private var dismiss
    @State private var schedule: API.BriefingSchedule?
    @State private var loaded = false
    @State private var saved: String?

    var body: some View {
        NavigationStack {
            BrandForm {
                if let s = schedule {
                    Section {
                        Toggle(BriefingCopy.scheduled, isOn: Binding(get: { !s.time.isEmpty },
                                                                    set: { update(["time": $0 ? "08:30" : ""]) }))
                            .tint(Brand.orange)
                        if !s.time.isEmpty {
                            DatePicker("Time", selection: Binding(get: { Self.date(s.time) }, set: { update(["time": Self.clock($0)]) }),
                                       displayedComponents: .hourAndMinute)
                            HStack(spacing: 4) {
                                ForEach(Array(BriefingCopy.days.enumerated()), id: \.offset) { i, day in
                                    let on = s.days.contains(i)
                                    Button { update(["days": on ? s.days.filter { $0 != i } : (s.days + [i]).sorted()]) } label: {
                                        Text(day).font(.brand(.caption, on ? .semibold : .regular)).lineLimit(1).minimumScaleFactor(0.7)
                                            .dynamicTypeSize(...DynamicTypeSize.xxLarge)  // seven in a row
                                            .frame(maxWidth: .infinity).padding(.vertical, 7)
                                            .foregroundStyle(on ? Brand.text : Brand.muted)  // chosen like every other chip: the tint, not a block of ink
                                            .background(on ? Brand.tint : .clear, in: RoundedRectangle(cornerRadius: 8))
                                            .overlay(RoundedRectangle(cornerRadius: 8).stroke(on ? Brand.orangeLine : Brand.line))
                                            .touchTarget(height: 30)
                                    }
                                    .buttonStyle(.plain)
                                    .accessibilityIdentifier("day-\(day)")
                                    .accessibilityAddTraits(on ? .isSelected : [])
                                }
                            }
                        }
                        Picker("Length", selection: Binding(get: { s.length }, set: { update(["length": $0]) })) {
                            ForEach(BriefingCopy.lengths, id: \.0) { Text($0.1).tag($0.0) }
                        }
                        Toggle(BriefingCopy.speakOnConnect, isOn: Binding(get: { s.speak_on_connect }, set: { update(["speak_on_connect": $0]) }))
                            .tint(Brand.orange)
                        Toggle(BriefingCopy.skipEmpty, isOn: Binding(get: { s.skip_empty }, set: { update(["skip_empty": $0]) }))
                            .tint(Brand.orange)
                    } footer: {
                        Group {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(BriefingCopy.note)
                                if let saved { Text(saved).foregroundStyle(Brand.accent) }
                            }
                        }.brandFootnote()
                    }
                } else if loaded {
                    Label("The Mac did not send its briefing schedule. Is Pointe on the Mac up to date and reachable?",
                          systemImage: "exclamationmark.triangle.fill").foregroundStyle(Brand.accent)
                } else {
                    ProgressView()
                }
            }
            .scrollContentBackground(.hidden)
            .navigationTitle(BriefingCopy.settingsTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .task { schedule = await load(); loaded = true }
        }
    }

    private func update(_ change: [String: any Sendable]) {
        saved = nil
        guard let s = schedule else { return }
        if let why = BriefingCopy.check(time: change["time"] as? String ?? s.time, days: change["days"] as? [Int] ?? s.days) {
            saved = why
            return
        }
        Task {
            switch await save(change) {
            case .success(let fresh):
                schedule = fresh
                saved = "Saved."
            case .failure(let why):
                schedule = await load()
                saved = why.message
            }
        }
    }

    static func date(_ time: String) -> Date {
        let p = time.split(separator: ":").compactMap { Int($0) }
        return Calendar.current.date(bySettingHour: p.first ?? 8, minute: p.count > 1 ? p[1] : 30, second: 0, of: Date()) ?? Date()
    }

    static func clock(_ date: Date) -> String {
        let c = Calendar.current.dateComponents([.hour, .minute], from: date)
        return String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
    }
}

/// On the call screen while a briefing plays or waits: how far it is, and the same controls as the sheet.
struct BriefingNowBar: View {
    let status: API.BriefingStatus
    let act: ([String: any Sendable]) async -> String?

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "sun.horizon.fill").foregroundStyle(Brand.accent)
            Text(BriefingCopy.progress(status) ?? "").font(.brand(.subheadline, .semibold))
            Spacer(minLength: 4)
            if status.isOn {
                Button(status.isPaused ? "Go on" : "Skip") { Task { _ = await act(["action": status.isPaused ? "continue" : "skip"]) } }
                    .buttonStyle(.brandQuiet)
                Button("Stop") { Task { _ = await act(["action": "stop"]) } }.buttonStyle(.brandQuiet)
            }
        }
        .controlSize(.small)
        .padding(.horizontal, 14).padding(.vertical, 10)
        .brandCard()
        .accessibilityIdentifier("briefingNow")
    }
}
