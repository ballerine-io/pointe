import PointeKit
import SwiftUI

/// Quick settings (pointe/quick.py, docs/features/quick-settings.md): reply length, speaking speed, clean up my words
/// and whisper, one tap away. The iPhone opens them from a sliders button in the header as a half-height sheet; the Mac
/// shows them as chips in the window's title strip, with the microphone, and repeats them in the Voice menu. The daemon
/// keeps every value; the speed is this device's own entry ("mac" or "iphone"), as the page keeps "page".

/// The page's words (ui_quick.html QUICK_COPY) and the daemon's (quick.COPY), word for word (tests/test_quick_page.py).
enum QuickCopy {
    static let title = "Quick settings"
    static let length = "Reply length"
    static let speed = "Speaking speed"
    static let polish = "Clean up my words"
    static let polishChip = "Clean words"
    static let polishHint = "Under each thing you say, a clean version of what the voice understood"
    static let whisper = "Whisper"
    static let microphone = "Microphone"
    static let brief = "Brief"
    static let concise = "Concise"
    static let detailed = "Detailed"
    static let thorough = "Thorough"
    static let briefHint = "One sentence: the answer only."
    static let conciseHint = "One or two short sentences."
    static let detailedHint = "The answer, then why, and the caveat that matters."
    static let thoroughHint = "Explains: what, why, how, and what to watch."
    static let slowest = "Slowest"
    static let slower = "Slower"
    static let normal = "Normal"
    static let faster = "Faster"
    static let fastest = "Fastest"
    static let slowestHint = "0.8× normal speed."
    static let slowerHint = "0.9× normal speed."
    static let normalHint = "Normal speed."
    static let fasterHint = "1.1× normal speed."
    static let fastestHint = "1.2×, the voice's top speed."
    static let lengthSay = "Or say it: “be more concise”, “more detail from now on”. “Tell me more” still makes one answer longer."
    static let speedSay = "Or say it: “speak faster”, “slow down”. The next sentence takes the new speed."
    static let sheetSay = "Or say it: “be more concise”, “speak faster”, “clean up my words”, “whisper mode”."
    static let allSettings = "All settings"
}

extension API {
    /// The row's values (daemon `_quick_status`). Nil from a Mac before quick settings: the row shows only its toggles.
    struct QuickStatus: Decodable, Equatable {
        var length: String?
        var speeds: [String: Double]?
        var speed_shown: Bool?  // false on a voice with no speed number (Gemini) or a realtime front: no speed control
        var by_voice: ByVoice?

        struct ByVoice: Decodable, Equatable {
            let key: String
            let at: Double
        }

        static let demo = QuickStatus(length: QuickRule.defaultLevel, speeds: [:], speed_shown: true, by_voice: nil)
    }
}

/// The rules of the row, without a view: what it shows and what a voice change does to it.
enum QuickRule {
    struct Level: Equatable {
        let value: String
        let name: String
        let hint: String
    }

    struct Speed: Equatable {
        let value: Double
        let name: String
        let hint: String
    }

    static let defaultLevel = "concise"
    static let levels = [Level(value: "brief", name: QuickCopy.brief, hint: QuickCopy.briefHint),
                         Level(value: "concise", name: QuickCopy.concise, hint: QuickCopy.conciseHint),
                         Level(value: "detailed", name: QuickCopy.detailed, hint: QuickCopy.detailedHint),
                         Level(value: "thorough", name: QuickCopy.thorough, hint: QuickCopy.thoroughHint)]
    static let speeds = [Speed(value: 0.8, name: QuickCopy.slowest, hint: QuickCopy.slowestHint),
                         Speed(value: 0.9, name: QuickCopy.slower, hint: QuickCopy.slowerHint),
                         Speed(value: 1.0, name: QuickCopy.normal, hint: QuickCopy.normalHint),
                         Speed(value: 1.1, name: QuickCopy.faster, hint: QuickCopy.fasterHint),
                         Speed(value: 1.2, name: QuickCopy.fastest, hint: QuickCopy.fastestHint)]

    /// This device's entry in "voice.speed".
    #if os(macOS)
    static let surface = "mac"
    #else
    static let surface = "iphone"
    #endif

    static func level(_ value: String) -> Level { levels.first { $0.value == value } ?? levels[1] }
    static func speed(_ value: Double) -> Speed { speeds.min { abs($0.value - value) < abs($1.value - value) } ?? speeds[2] }

    /// "1×", "1.1×": the speed chip's value.
    static func speedLabel(_ value: Double) -> String {
        let tenths = Int((value * 10).rounded())
        return tenths % 10 == 0 ? "\(tenths / 10)×" : "\(tenths / 10).\(tenths % 10)×"
    }

    /// The iPhone's Quick button carries a dot while any quick setting is off its default.
    static func offDefault(_ model: QuickModel) -> Bool {
        model.length != defaultLevel || abs(model.speed - 1) > 0.01 || model.polish || model.whisper == true
    }

    /// The chip that glows after a change by voice: one the status has not shown before, and fresh. The first status a
    /// screen sees is not a change.
    static func glow(seen: API.QuickStatus.ByVoice?, now fresh: API.QuickStatus.ByVoice?, at time: Date = Date()) -> String? {
        guard let fresh, fresh != seen, time.timeIntervalSince1970 - fresh.at < 6 else { return nil }
        return fresh.key
    }

    static let glowSecs = 1.6
}

/// What the row shows: values only, compared as a whole, so a poll that changes none of them leaves it alone.
struct QuickModel: Equatable {
    var available = false  // the Mac has quick settings: length and speed show
    var length = QuickRule.defaultLevel
    var speed = 1.0
    var speedShown = false
    var polish = false
    var whisper: Bool?  // nil: this Mac has no whisper mode
    var microphone = "always"
    var byVoice: API.QuickStatus.ByVoice?

    init() {}

    init(status: API.Status?, microphone: String) {
        let quick = status?.quick
        available = quick != nil
        length = quick?.length.map { QuickRule.level($0).value } ?? QuickRule.defaultLevel
        speed = quick?.speeds?[QuickRule.surface] ?? 1
        speedShown = quick?.speed_shown == true
        polish = status?.polish ?? false
        whisper = status?.whisper.map(\.on) ?? (quick != nil ? false : nil)
        self.microphone = microphone
        byVoice = quick?.by_voice
    }
}

/// One change from the row, the sheet or the Voice menu.
public enum QuickChange: Equatable, Sendable {
    case length(String), speed(Double), polish(Bool), whisper(Bool), microphone(String)

    /// The daemon's settings for it (POST /voice/prefs). The microphone goes through the call (Call.setMicrophone).
    var prefs: [String: any Sendable] {
        switch self {
        case .length(let level): ["replies.length": level]
        case .speed(let speed): ["voice.speed": [QuickRule.surface: speed]]
        case .polish(let on): ["polish": on]
        case .whisper(let on): ["whisper": on]
        case .microphone(let mode): ["microphone": mode]
        }
    }

    /// The status as it will be once the daemon has it: the row moves at the tap.
    func apply(to status: inout API.Status?) {
        guard status != nil else { return }
        switch self {
        case .length(let level): status?.quick?.length = level
        case .speed(let speed):
            let speeds = (status?.quick?.speeds ?? [:]).merging([QuickRule.surface: speed]) { $1 }
            status?.quick?.speeds = speeds
        case .polish(let on): status?.polish = on
        case .whisper(let on):
            let w = status?.whisper
            status?.whisper = API.WhisperStatus(on: on, held: w?.held, output_gain: on ? 0.5 : 1, max_words: on ? 20 : nil,
                                                suggest_ptt: w?.suggest_ptt, lock_note: w?.lock_note)
        case .microphone: break
        }
    }
}

/// What the Mac's Voice menu lists, in the row's words.
public enum QuickMenu {
    public static let length = QuickCopy.length
    public static let speed = QuickCopy.speed
    public static let polish = QuickCopy.polish
    public static let whisper = QuickCopy.whisper
    public static let levels = QuickRule.levels.map { (value: $0.value, name: $0.name) }
    public static let speeds = QuickRule.speeds.map { (value: $0.value, name: "\($0.name) (\(QuickRule.speedLabel($0.value)))") }
}

// MARK: the iPhone: a Quick button in the header and the sheet it opens

#if os(iOS)
/// The sliders button beside Sessions and •••; its dot says a quick setting is off its default.
struct QuickButton: View {
    let offDefault: Bool
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            Image(systemName: "slider.horizontal.3").font(.brand(.subheadline, .semibold))
                .frame(width: 36, height: 36).background(Brand.raised, in: Circle())
                .overlay(alignment: .topTrailing) {
                    if offDefault {
                        Circle().fill(Brand.orange).frame(width: 9, height: 9).offset(x: 1, y: -1)
                            .accessibilityHidden(true)
                    }
                }
                .touchTarget(width: 36, height: 36)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(QuickCopy.title)
        .accessibilityValue(offDefault ? "Changed" : "")
        .accessibilityIdentifier("quickButton")
    }
}

/// Reply length and speed as segmented controls with a line on what the level does, the two switches, and the phrases.
struct QuickSheet: View {
    let model: QuickModel
    let set: (QuickChange) -> Void
    let allSettings: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var lengthWanted: String?  // moves at the tap; the Mac's word replaces it on the next status
    @State private var speedWanted: Double?
    @State private var polishWanted: Bool?
    @State private var whisperWanted: Bool?

    var body: some View {
        let length = lengthWanted ?? model.length, speed = speedWanted ?? model.speed
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if model.available {
                        section(QuickCopy.length, "text.alignleft") {
                            Picker(QuickCopy.length, selection: Binding(get: { length }, set: { lengthWanted = $0; set(.length($0)) })) {
                                ForEach(QuickRule.levels, id: \.value) { Text($0.name).tag($0.value) }
                            }
                            .pickerStyle(.segmented)
                            .accessibilityIdentifier("quickLength")
                            hint(QuickRule.level(length).hint, "quickLengthHint")
                        }
                        if model.speedShown {
                            section(QuickCopy.speed, "gauge.with.dots.needle.33percent") {
                                Picker(QuickCopy.speed, selection: Binding(get: { QuickRule.speed(speed).value },
                                                                           set: { speedWanted = $0; set(.speed($0)) })) {
                                    ForEach(QuickRule.speeds, id: \.value) { Text($0.name).tag($0.value) }
                                }
                                .pickerStyle(.segmented)
                                .accessibilityIdentifier("quickSpeed")
                                hint(QuickRule.speed(speed).hint, "quickSpeedHint")
                            }
                        }
                    }
                    VStack(spacing: 0) {
                        Toggle(isOn: Binding(get: { polishWanted ?? model.polish }, set: { polishWanted = $0; set(.polish($0)) })) {
                            Label(QuickCopy.polish, systemImage: "wand.and.sparkles")
                        }
                        .padding(.horizontal, 16).padding(.vertical, 12)
                        .accessibilityIdentifier("quickPolish")
                        if let whisper = model.whisper {
                            Divider().overlay(Brand.line).padding(.leading, 16)
                            Toggle(isOn: Binding(get: { whisperWanted ?? whisper }, set: { whisperWanted = $0; set(.whisper($0)) })) {
                                Label(QuickCopy.whisper, systemImage: "waveform.badge.minus")
                            }
                            .padding(.horizontal, 16).padding(.vertical, 12)
                            .accessibilityIdentifier("quickWhisper")
                        }
                    }
                    .toggleStyle(SwitchToggleStyle(tint: Brand.orange))
                    .background(Brand.cell, in: RoundedRectangle(cornerRadius: 14))
                    .overlay(RoundedRectangle(cornerRadius: 14).stroke(Brand.line))
                    Text(QuickCopy.sheetSay).font(.brand(.footnote)).foregroundStyle(Brand.muted)
                        .accessibilityIdentifier("quickSay")
                    Button { dismiss(); allSettings() } label: {
                        Label(QuickCopy.allSettings, systemImage: "chevron.right").labelStyle(TrailingIcon())
                            .font(.brand(.footnote, .semibold)).foregroundStyle(Brand.accent)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("quickAllSettings")
                }
                .padding(.horizontal, 18).padding(.top, 6).padding(.bottom, 24)
            }
            .background(Brand.group)
            .sheetTitle(QuickCopy.title)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .presentationDetents([.medium, .large])
        .onChange(of: model.length) { lengthWanted = nil }
        .onChange(of: model.speed) { speedWanted = nil }
        .onChange(of: model.polish) { polishWanted = nil }
        .onChange(of: model.whisper) { whisperWanted = nil }
    }

    private func section<Content: View>(_ title: String, _ symbol: String, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: symbol).brandKicker()
            content()
        }
    }

    private func hint(_ text: String, _ id: String) -> some View {
        Text(text).font(.brand(.footnote)).foregroundStyle(Brand.muted).accessibilityIdentifier(id)
    }
}

private struct TrailingIcon: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 4) { configuration.title; configuration.icon.imageScale(.small) }
    }
}
#endif

// MARK: the Mac: chips in the title strip

#if os(macOS)
/// The row in the window's title strip: the microphone, reply length, speed, clean words and whisper. Each chip shows
/// its value; a menu chip opens the levels, a toggle chip flips on a click and shows a small switch, so its state is
/// never colour alone. The window picks the widest `Fit` that fits (Panels.swift): in a narrow window the toggles keep
/// their icon and switch, and at the narrowest the microphone keeps its icon (its mode is its value for VoiceOver).
public struct QuickRow: View {
    public enum Fit: Sendable { case full, compact, tight }

    let session: MacSession
    let micLabel: String
    let micGlyph: String
    let fit: Fit
    @State private var glowing: String?

    public init(session: MacSession, micLabel: String, micGlyph: String, fit: Fit = .full) {
        self.session = session
        self.micLabel = micLabel
        self.micGlyph = micGlyph
        self.fit = fit
    }

    public var body: some View {
        let model = session.quick
        chips(model, compact: fit != .full)
            .onChange(of: model.byVoice) { old, new in
                guard let key = QuickRule.glow(seen: old, now: new) else { return }
                glowing = key
                Task { try? await Task.sleep(for: .seconds(QuickRule.glowSecs)); if glowing == key { glowing = nil } }
            }
    }

    private func chips(_ model: QuickModel, compact: Bool) -> some View {
        HStack(spacing: 6) {
            Menu {
                Picker(QuickCopy.microphone, selection: Binding(get: { model.microphone }, set: { session.setQuick(.microphone($0)) })) {
                    Text("Always on").tag("always")
                    Text(AddressedCopy.setting).tag(AddressedCopy.mode)
                    Text("Push to talk").tag("ptt")
                }
                .pickerStyle(.inline)
            } label: {
                QuickChipLabel(symbol: micGlyph, text: fit == .tight ? nil : micLabel, menu: true)
            }
            .menuStyle(.button).buttonStyle(QuickChipStyle(glow: false)).menuIndicator(.hidden).fixedSize()
            .help(QuickCopy.microphone)
            .accessibilityLabel(QuickCopy.microphone)
            .accessibilityValue(micLabel)
            .accessibilityIdentifier("talkMode")
            if model.available {
                Menu {
                    Section(QuickCopy.length) {
                        ForEach(QuickRule.levels, id: \.value) { level in
                            Toggle(isOn: Binding(get: { model.length == level.value }, set: { if $0 { session.setQuick(.length(level.value)) } })) {
                                Text(level.name)
                                Text(level.hint)
                            }
                        }
                    }
                    Section { Text(QuickCopy.lengthSay) }
                } label: {
                    QuickChipLabel(symbol: "text.alignleft", text: QuickRule.level(model.length).name, menu: true)
                }
                .menuStyle(.button).buttonStyle(QuickChipStyle(glow: glowing == "replies.length")).menuIndicator(.hidden).fixedSize()
                .help(QuickCopy.length)
                .accessibilityLabel(QuickCopy.length)
                .accessibilityValue(QuickRule.level(model.length).name)
                .accessibilityIdentifier("quickLength")
                if model.speedShown {
                    Menu {
                        Section(QuickCopy.speed) {
                            ForEach(QuickRule.speeds, id: \.value) { speed in
                                Toggle(isOn: Binding(get: { abs(model.speed - speed.value) < 0.01 },
                                                     set: { if $0 { session.setQuick(.speed(speed.value)) } })) {
                                    Text(speed.name)
                                    Text(speed.hint)
                                }
                            }
                        }
                        Section { Text(QuickCopy.speedSay) }
                    } label: {
                        QuickChipLabel(symbol: "gauge.with.dots.needle.33percent", text: QuickRule.speedLabel(model.speed), menu: true)
                    }
                    .menuStyle(.button).buttonStyle(QuickChipStyle(glow: glowing == "voice.speed")).menuIndicator(.hidden).fixedSize()
                    .help(QuickCopy.speed)
                    .accessibilityLabel(QuickCopy.speed)
                    .accessibilityValue(QuickRule.speedLabel(model.speed))
                    .accessibilityIdentifier("quickSpeed")
                }
            }
            toggle(QuickCopy.polishChip, label: QuickCopy.polish, symbol: "wand.and.sparkles", on: model.polish, glow: glowing == "polish",
                   help: QuickCopy.polishHint, id: "quickPolish", compact: compact) { session.setQuick(.polish(!model.polish)) }
            if let whisper = model.whisper {
                toggle(QuickCopy.whisper, label: QuickCopy.whisper, symbol: "waveform.badge.minus", on: whisper, glow: false,
                       help: "Short, quiet replies for an open office", id: "quickWhisper", compact: compact) { session.setQuick(.whisper(!whisper)) }
            }
        }
    }

    private func toggle(_ text: String, label: String, symbol: String, on: Bool, glow: Bool, help: String, id: String, compact: Bool,
                        flip: @escaping () -> Void) -> some View {
        Button(action: flip) {
            HStack(spacing: 5) {
                Image(systemName: symbol).imageScale(.small)
                if !compact { Text(text).lineLimit(1) }
                MiniSwitch(on: on)
            }
        }
        .buttonStyle(QuickChipStyle(glow: glow, on: on))
        .fixedSize()
        .help(help)
        .accessibilityLabel(label)
        .accessibilityValue(on ? "On" : "Off")
        .accessibilityIdentifier(id)
    }
}

/// A menu chip's face: the icon, the value and the up-down chevrons.
private struct QuickChipLabel: View {
    let symbol: String
    let text: String?
    let menu: Bool

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: symbol).imageScale(.small).foregroundStyle(Brand.muted)
            if let text { Text(text).lineLimit(1) }
            if menu { Image(systemName: "chevron.up.chevron.down").font(.system(size: 8, weight: .semibold)).foregroundStyle(Brand.dim) }
        }
    }
}

/// The chip: a small capsule on the raised colour; orange-tinted while a toggle is on; a glow for a moment after a
/// change by voice.
struct QuickChipStyle: ButtonStyle {
    var glow: Bool
    var on = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.brand(.caption, .medium))
            .foregroundStyle(on ? Brand.accent : Brand.text)
            .padding(.leading, 8).padding(.trailing, 9)
            .frame(height: 22)
            .background(on ? AnyShapeStyle(Brand.tint) : AnyShapeStyle(configuration.isPressed ? Brand.lineStrong : Brand.raised), in: Capsule())
            .overlay(Capsule().stroke(on ? Brand.orangeLine : Brand.line))
            .shadow(color: glow ? Brand.orange.opacity(0.45) : .clear, radius: glow ? 5 : 0)
            .contentShape(Capsule())
            .motion(.easeOut(duration: 0.3), value: glow)
    }
}

extension Brand {
    static let knob = Color(light: 0xFFFFFF, dark: 0xF7F2F0)  // a chip's switch, off
}

/// A switch small enough for a chip; the shortcuts are the Voice menu's (PointeMacApp.swift), not repeated here.
private struct MiniSwitch: View {
    let on: Bool

    var body: some View {
        Capsule().fill(on ? Brand.orange : Brand.lineStrong).frame(width: 20, height: 12)
            .overlay(alignment: on ? .trailing : .leading) {
                Circle().fill(on ? Color.white : Brand.knob).frame(width: 8, height: 8).padding(2)
            }
            .accessibilityHidden(true)
    }
}
#endif
