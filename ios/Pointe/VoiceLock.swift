import AVFoundation
import SwiftUI

/// The owner-voice lock's levels, lowest first: each one takes more away from voices that are not the owner's.
enum VoiceLockLevel: String, CaseIterable, Identifiable {
    case off, approvals, commands, everything
    var id: String { rawValue }

    var label: String {
        switch self {
        case .off: "Off"
        case .approvals: "Approvals"
        case .commands: "Commands"
        case .everything: "Everything"
        }
    }

    var help: String {
        switch self {
        case .off: "Any voice works, as before."
        case .approvals: "A spoken yes counts only in your voice. A no counts from anyone."
        case .commands: "Only your voice reaches Pointe. Other voices are listed as ignored, with their words."
        case .everything: "Only your voice reaches Pointe. Other voices are dropped unseen."
        }
    }

    private var rank: Int { Self.allCases.firstIndex(of: self)! }

    /// A lowering (Off included) needs Face ID or the passcode: a stolen phone key must not be enough to loosen the lock.
    static func isLowering(from: VoiceLockLevel, to: VoiceLockLevel) -> Bool { to.rank < from.rank }
}

/// Word for word the page's copy (ui.html): the two must not drift.
enum VoiceLockCopy {
    static let title = "Voice lock"
    static let intro = "Pointe can learn your voice so other voices in the room can't approve or command. Your voiceprint stays on your Mac."
    static let enrol = "Enrol my voice"
    static let connectFirst = "Connect a call first: enrolment listens on the call."
    static let readAloud = "Read this line aloud"
    static let downloading = "Downloading the voice model (40 MB, once)…"
    static let pushToTalk = "Push to talk is on: hold talk while you read each line."
    static let cancel = "Cancel"
    static let addDevice = "Add this device"
    static let deleteAll = "Delete my voiceprint"
    static let deleteAllConfirm = "Delete your voiceprint from this Mac? The lock turns off."
    static let unsure = "Tap to approve, or re-enrol."
    static let ignoredTitle = "Ignored"

    static func enrolledOn(_ device: String) -> String { "Enrolled on: \(device)" }
    static func didntCount(_ reason: String) -> String { "Didn't count: \(reason)" }
    static func percent(_ progress: Double) -> String { "\(Int((max(0, min(1, progress)) * 100).rounded()))%" }
    static func problem(_ problem: String) -> String { "Voice lock can't check voices: \(problem). Until it can, only a tap approves." }
    static func ignored(_ count: Int) -> String { "\(count) ignored (not your voice)" }
    static func seconds(_ secs: Double) -> String { String(format: "%.1f s", secs) }

    /// The label a voiceprint is filed under on the Mac: one per microphone, since each one changes the voice.
    static func deviceLabel(builtIn: Bool, route: String?) -> String {
        guard !builtIn, let route = route?.trimmingCharacters(in: .whitespaces), !route.isEmpty else { return "iPhone" }
        return "iPhone · \(route)"
    }

    static var thisDevice: String {
        let input = AVAudioSession.sharedInstance().currentRoute.inputs.first
        return deviceLabel(builtIn: input == nil || input?.portType == .builtInMic, route: input?.portName)
    }
}

struct VoiceLockSheet: View {
    let lock: API.VoiceLock
    let callUp: Bool
    var pushToTalk = false
    /// The Mac's reason when it refused, nil when it took the change.
    let send: ([String: any Sendable]) async -> String?
    /// Face ID or the passcode; false when it failed or was cancelled, and then nothing changes.
    let ownerCheck: (String) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var busy = false
    @State private var refused: String?
    @State private var confirmDeleteAll = false

    var body: some View {
        NavigationStack {
            Form {
                if let problem = lock.problem, lock.lockLevel != .off {
                    Label(VoiceLockCopy.problem(problem), systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(Brand.orange)
                        .accessibilityIdentifier("voiceLockProblem")
                }
                Section { voiceprint }
                Section { levels } footer: {
                    Text(lock.lockLevel.help).accessibilityIdentifier("voiceLockHelp")
                }
                if let refused {
                    Label(refused, systemImage: "exclamationmark.triangle.fill").foregroundStyle(Brand.orange)
                }
            }
            .scrollContentBackground(.hidden)
            .disabled(busy)
            .navigationTitle(VoiceLockCopy.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .confirmationDialog(VoiceLockCopy.deleteAllConfirm, isPresented: $confirmDeleteAll, titleVisibility: .visible) {
                Button("Delete", role: .destructive) { Task { await delete(nil) } }
            }
        }
    }

    @ViewBuilder private var voiceprint: some View {
        if let e = lock.enrolling {
            VStack(alignment: .leading, spacing: 10) {
                Text(VoiceLockCopy.readAloud).font(.subheadline).foregroundStyle(.secondary)
                Text(e.text ?? "").font(.title2.weight(.semibold)).accessibilityIdentifier("enrolLine")
                HStack {
                    ProgressView(value: max(0, min(1, e.progress ?? 0))).tint(Brand.orange)
                    Text(VoiceLockCopy.percent(e.progress ?? 0)).font(.footnote.monospacedDigit())
                }
                if let reason = e.last_reason, !reason.isEmpty {
                    Text(VoiceLockCopy.didntCount(reason)).font(.footnote).foregroundStyle(Brand.orange)
                }
                if lock.model == "missing" || lock.model == "downloading" {
                    Text(VoiceLockCopy.downloading).font(.footnote).foregroundStyle(.secondary)
                } else if pushToTalk, lock.model == "ready" {
                    Text(VoiceLockCopy.pushToTalk).font(.footnote).foregroundStyle(.secondary)
                }
            }
            .padding(.vertical, 4)
            Button(VoiceLockCopy.cancel) { Task { await run(["action": "cancel"]) } }
        } else if !lock.isEnrolled {
            Text(VoiceLockCopy.intro)
            enrolButton(VoiceLockCopy.enrol)
        } else {
            ForEach(lock.devices ?? []) { d in
                HStack {
                    Text(VoiceLockCopy.enrolledOn(d.device))
                    Spacer()
                    Button("Delete", role: .destructive) { Task { await delete(d.device) } }
                        .buttonStyle(.borderless)
                        .accessibilityIdentifier("deleteVoiceprint-\(d.device)")
                }
            }
            enrolButton(VoiceLockCopy.addDevice)
            Button(VoiceLockCopy.deleteAll, role: .destructive) { confirmDeleteAll = true }
        }
    }

    @ViewBuilder private func enrolButton(_ title: String) -> some View {
        Button(title) { Task { await run(["action": "enrol", "device": VoiceLockCopy.thisDevice]) } }
            .disabled(!callUp)
        if !callUp {
            Text(VoiceLockCopy.connectFirst).font(.footnote).foregroundStyle(.secondary)
        }
    }

    /// A segmented row of buttons rather than a Picker: a level above Off is disabled until a voiceprint exists.
    private var levels: some View {
        HStack(spacing: 4) {
            ForEach(VoiceLockLevel.allCases) { level in
                let on = level == lock.lockLevel
                Button { Task { await setLevel(level) } } label: {
                    Text(level.label).font(.subheadline.weight(on ? .semibold : .regular))
                        .lineLimit(1).minimumScaleFactor(0.7)
                        .frame(maxWidth: .infinity).padding(.vertical, 7)
                        .background(on ? Brand.orange.opacity(0.85) : .clear, in: RoundedRectangle(cornerRadius: 8))
                }
                .buttonStyle(.plain)
                .disabled(level != .off && !lock.isEnrolled)
                .accessibilityIdentifier("voiceLevel-\(level.rawValue)")
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(3)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
    }

    private func setLevel(_ level: VoiceLockLevel) async {
        let current = lock.lockLevel
        guard level != current else { return }
        if VoiceLockLevel.isLowering(from: current, to: level), !(await ownerCheck("Lower the voice lock to \(level.label)")) { return }
        await run(["action": "level", "level": level.rawValue])
    }

    /// One device's voiceprint, or every one (nil). Always behind Face ID.
    private func delete(_ device: String?) async {
        guard await ownerCheck(device.map { "Delete the voiceprint for \($0)" } ?? "Delete your voiceprint") else { return }
        var body: [String: any Sendable] = ["action": "delete"]
        if let device { body["device"] = device }
        await run(body)
    }

    private func run(_ body: [String: any Sendable]) async {
        busy = true
        refused = await send(body)
        busy = false
    }
}

/// Speech the lock kept from Pointe, newest first. The words only at the Commands level.
struct IgnoredSheet: View {
    let ignored: API.Ignored
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                ForEach((ignored.recent ?? []).reversed(), id: \.self) { item in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(Date(timeIntervalSince1970: item.at).formatted(date: .omitted, time: .shortened)
                             + " · " + VoiceLockCopy.seconds(item.secs ?? 0))
                            .font(.subheadline.monospacedDigit())
                        if let text = item.text, !text.isEmpty {
                            Text(text).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .scrollContentBackground(.hidden)
            .navigationTitle(VoiceLockCopy.ignoredTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
