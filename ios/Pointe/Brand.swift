import SwiftUI
import UIKit

/// Ballerine Brand Guidelines V6 as the app uses it (docs/design/brand-v6.md). The colours, the theme choices, the font
/// files and the harness marks are assets/theme.json, the same values the page (ui.html) carries: tests/test_theme.py
/// reads this file and fails when either side drifts, so keep each token on one line in the form below.
enum Brand {
    // theme tokens: name = Color(light:, dark:)
    static let bg = Color(light: 0xFFFFFF, dark: 0x0A0400)
    static let surface = Color(light: 0xFCFAFA, dark: 0x0C0906)
    static let card = Color(light: 0xFFFFFF, dark: 0x0F0B08)
    static let raised = Color(light: 0xF5F1EF, dark: 0x1A1410)
    static let raised2 = Color(light: 0xE9E2DE, dark: 0x26201B)
    static let group = Color(light: 0xF5F1EF, dark: 0x0C0906)
    static let cell = Color(light: 0xFFFFFF, dark: 0x1A1410)
    static let text = Color(light: 0x0A0400, dark: 0xF7F2F0)
    static let muted = Color(light: 0x5C5450, dark: 0xB5ADA8)
    static let dim = Color(light: 0x6E6762, dark: 0x958D88)
    static let line = Color(light: 0x0A0500, 0.10, dark: 0xFFFFFF, 0.08)
    static let lineStrong = Color(light: 0x0A0500, 0.18, dark: 0xFFFFFF, 0.16)
    static let orange = Color(light: 0xFF5A01, dark: 0xFF5A01)
    static let onOrange = Color(light: 0x0A0400, dark: 0x0A0400)
    static let accent = Color(light: 0xC24F0D, dark: 0xFF8C4A)
    static let tint = Color(light: 0xFFF1E9, dark: 0xFF5A01, 0.14)
    static let orangeLine = Color(light: 0xFF5A01, 0.45, dark: 0xFF5A01, 0.45)
    static let success = Color(light: 0x138A4B, dark: 0x138A4B)
    static let successText = Color(light: 0x0E7A41, dark: 0x3DBE7B)
    static let danger = Color(light: 0xC83A37, dark: 0xC83A37)
    static let dangerText = Color(light: 0xC83A37, dark: 0xF0706B)
    static let primary = Color(light: 0x0A0400, dark: 0xF7F2F0)
    static let onPrimary = Color(light: 0xFCFAFA, dark: 0x0A0400)
    static let glow = Color(light: 0xFF5A01, 0, dark: 0xFF5A01, 0.16)
    static let scrim = Color(light: 0x0A0400, 0.35, dark: 0x000000, 0.60)
    // end of theme tokens

    /// The page's name for the screen behind everything.
    static let background = bg

    /// The two families, bundled (Info.plist UIAppFonts; SIL OFL 1.1, ios/Pointe/Fonts/OFL-*.txt). They carry Latin only:
    /// iOS falls back to the system font for Hebrew and every other script, glyph by glyph.
    static let displayLight = "BricolageGrotesque-Light"
    static let displayRegular = "BricolageGrotesque-Regular"
    static func textFace(_ weight: Font.Weight) -> String {
        switch weight {
        case .medium: "InstrumentSans-Medium"
        case .semibold, .bold, .heavy, .black: "InstrumentSans-SemiBold"  // the brand has no weight above 600
        default: "InstrumentSans-Regular"
        }
    }

    /// Apple's sizes for each text style at the default Dynamic Type size; `relativeTo:` scales them from there.
    static func size(_ style: Font.TextStyle) -> CGFloat {
        switch style {
        case .largeTitle: 34
        case .title: 28
        case .title2: 22
        case .title3: 20
        case .headline, .body: 17
        case .callout: 16
        case .subheadline: 15
        case .footnote: 13
        case .caption: 12
        case .caption2: 11
        @unknown default: 17
        }
    }

    /// Navigation titles and segmented controls are UIKit's: they take the families here, once, at launch.
    static func install() {
        let title = UIFont(name: displayRegular, size: 17) ?? .systemFont(ofSize: 17)
        let large = UIFont(name: displayLight, size: 34) ?? .systemFont(ofSize: 34, weight: .light)
        UINavigationBar.appearance().titleTextAttributes = [.font: title]
        UINavigationBar.appearance().largeTitleTextAttributes = [.font: large]
        let segment = UIFont(name: textFace(.medium), size: 13) ?? .systemFont(ofSize: 13, weight: .medium)
        UISegmentedControl.appearance().setTitleTextAttributes([.font: segment, .foregroundColor: UIColor(text)], for: .normal)
        UISegmentedControl.appearance().backgroundColor = UIColor(raised)
        UISegmentedControl.appearance().selectedSegmentTintColor = UIColor(card)
    }
}

extension Color {
    /// A colour that follows the appearance: 0xRRGGBB for each, with an optional opacity after it.
    init(light: UInt32, _ lightAlpha: Double = 1, dark: UInt32, _ darkAlpha: Double = 1) {
        func ui(_ hex: UInt32, _ alpha: Double) -> UIColor {
            UIColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
        }
        self.init(uiColor: UIColor { $0.userInterfaceStyle == .dark ? ui(dark, darkAlpha) : ui(light, lightAlpha) })
    }
}

extension Font {
    /// Instrument Sans at a text style's size, scaling with Dynamic Type; the title styles are Bricolage Grotesque, which
    /// the brand sets at 300 or 400 and never bolder.
    static func brand(_ style: Font.TextStyle = .body, _ weight: Font.Weight = .regular) -> Font {
        switch style {
        case .largeTitle, .title, .title2, .title3:
            .custom(weight == .light ? Brand.displayLight : Brand.displayRegular, size: Brand.size(style), relativeTo: style)
        case .headline:
            .custom(Brand.textFace(weight == .regular ? .semibold : weight), size: Brand.size(style), relativeTo: style)
        default:
            .custom(Brand.textFace(weight), size: Brand.size(style), relativeTo: style)
        }
    }

    /// The display family at a fixed size, for the few big lines (the drive line, a pairing code's title).
    static func display(_ size: CGFloat, light: Bool = false) -> Font {
        .custom(light ? Brand.displayLight : Brand.displayRegular, size: size, relativeTo: .title)
    }
}

/// Appearance: System, Light or Dark, kept on this phone, as the page keeps it in its browser. System is the default.
enum Theme: String, CaseIterable, Identifiable {
    case system, light, dark

    static let key = "pointe.theme"
    static let fallback = Theme.system
    static let setting = "Appearance"

    var id: String { rawValue }
    var label: String {
        switch self {
        case .system: "System"
        case .light: "Light"
        case .dark: "Dark"
        }
    }
    /// nil follows the phone.
    var scheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }
    static func stored(_ raw: String?) -> Theme { raw.flatMap(Theme.init(rawValue:)) ?? fallback }
}

/// Which coding agent runs a session. The vendors' own logos are not used: their terms do not let a third party show
/// them recoloured without permission (docs/design/brand-v6.md), so the mark is a neutral letter tile with the agent's
/// name as its label, and as text beside it once the voice mixes agents. The table is assets/theme.json's.
enum Harness {
    static let marks: [String: (name: String, glyph: String)] = [
        "claude-code": (name: "Claude", glyph: "C"),
        "codex": (name: "Codex", glyph: "X"),
        "opencode": (name: "OpenCode", glyph: "O"),
        "pi": (name: "Pi", glyph: "P"),
    ]

    static func mark(_ harness: String?) -> (name: String, glyph: String) {
        let id = (harness ?? "").isEmpty ? "claude-code" : harness!
        return marks[id] ?? (name: id, glyph: String(id.prefix(1)).uppercased())
    }
}

struct HarnessMark: View {
    let harness: String?
    var named = false

    var body: some View {
        let mark = Harness.mark(harness)
        HStack(spacing: 4) {
            Text(mark.glyph).font(.brand(size: 9.5, .semibold))
                .frame(width: 15, height: 15)
                .overlay(RoundedRectangle(cornerRadius: 3).stroke(Brand.lineStrong))
            if named { Text(mark.name).font(.brand(.caption2, .semibold)) }
        }
        .foregroundStyle(Brand.muted)
        .environment(\.layoutDirection, .leftToRight)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("runs on \(mark.name)")
        .accessibilityIdentifier("harnessMark.\((harness ?? "").isEmpty ? "claude-code" : harness!)")
    }
}

extension Font {
    /// Instrument Sans at a fixed size (a glyph in a tile, a number in a ring).
    static func brand(size: CGFloat, _ weight: Font.Weight = .regular) -> Font { .custom(Brand.textFace(weight), fixedSize: size) }
}

/// The brand's buttons, 12-point corners. Primary: warm black on light, bone on dark (orange is kept for the live mic
/// and Connect, so an ordinary "do it" button is ink). Quiet: a hairline, ink text, no fill.
struct BrandButtonStyle: ButtonStyle {
    let prominent: Bool
    @Environment(\.controlSize) private var size
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        let shape = RoundedRectangle(cornerRadius: 12)
        configuration.label
            .font(.brand(size == .small ? .footnote : .subheadline, .semibold))
            .padding(.horizontal, size == .large ? 20 : size == .small ? 12 : 16)
            .frame(minHeight: size == .large ? 50 : size == .small ? 32 : 40)
            .foregroundStyle(prominent ? Brand.onPrimary : Brand.text)
            .background(prominent ? Brand.primary : configuration.isPressed ? Brand.raised : Color.clear, in: shape)
            .overlay(shape.stroke(prominent ? Color.clear : Brand.lineStrong))
            .opacity(!enabled ? 0.4 : configuration.isPressed && prominent ? 0.8 : 1)
            .contentShape(shape)
    }
}

extension ButtonStyle where Self == BrandButtonStyle {
    static var brandPrimary: BrandButtonStyle { BrandButtonStyle(prominent: true) }
    static var brandQuiet: BrandButtonStyle { BrandButtonStyle(prominent: false) }
}

/// An empty screen: a quiet symbol, a display line and one muted sentence. The system's version takes the app's body font
/// and ink for its description, which reads louder than the conversation it stands in for.
struct EmptyNote: View {
    let title: String
    let symbol: String
    let text: String

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: symbol).font(.system(size: 30, weight: .regular)).foregroundStyle(Brand.dim).padding(.bottom, 6)
                .accessibilityHidden(true)
            Text(title).font(.brand(.title3))
            Text(text).font(.brand(.subheadline)).foregroundStyle(Brand.muted)
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: 300)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}

/// A plain button in a settings row: the accent, or red when it deletes. The app's ink foreground would otherwise make
/// "Enrol my voice" and "Delete my voiceprint" look like two more lines of text. Set on the section that needs it, not on
/// the whole list: a swipe action is a button too, and takes the style around it.
struct BrandRowButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(!enabled ? Brand.dim : configuration.role == .destructive ? Brand.dangerText : Brand.accent)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle().scale(x: 1, y: 2))
            .opacity(configuration.isPressed ? 0.5 : 1)
    }
}

/// What a card holds when it may be long (a command, the cards over the bar): its own height up to a limit, and past that
/// it scrolls in place, so what is under it (Approve, the mic) stays on screen.
struct FitScroll<Content: View>: View {
    let limit: CGFloat
    @ViewBuilder var content: Content
    @State private var height: CGFloat = 0

    var body: some View {
        ScrollView {
            content.onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height = $0 }
        }
        .scrollBounceBehavior(.basedOnSize)
        .frame(height: min(height, max(0, limit)))
    }
}

/// A section under a kicker.
struct KickerSection<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View { Section { content } header: { Text(title).brandKicker() } }
}

/// A Form on the brand's surfaces: warm cells on a warm ground with hairline separators, in place of the system greys.
struct BrandForm<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        Form { Group { content }.listRowBackground(Brand.cell).listRowSeparatorTint(Brand.line) }
            .toggleStyle(SwitchToggleStyle(tint: Brand.orange))  // a switch that is on is the brand's orange, in every sheet
            .contentMargins(.top, 12, for: .scrollContent)       // under an inline title the system's 35 points read as a hole
            .scrollContentBackground(.hidden)
            .background(Brand.group)
    }
}

/// The same for a List.
struct BrandList<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        List { Group { content }.listRowBackground(Brand.cell).listRowSeparatorTint(Brand.line) }
            .toggleStyle(SwitchToggleStyle(tint: Brand.orange))  // a switch that is on is the brand's orange, in every sheet
            .contentMargins(.top, 12, for: .scrollContent)       // under an inline title the system's 35 points read as a hole
            .scrollContentBackground(.hidden)
            .background(Brand.group)
    }
}

extension View {
    /// The screen behind a call: the page colour, and on dark the brand's one orange glow off the top right edge.
    func brandStage() -> some View {
        background {
            ZStack {
                Brand.bg
                RadialGradient(colors: [Brand.glow, Brand.glow.opacity(0)], center: .topTrailing, startRadius: 0, endRadius: 420)
            }
            .ignoresSafeArea()
        }
    }
}

extension View {
    /// The controls under a call. Opaque, with a short fade above: what scrolls behind (the conversation, the notes) goes
    /// away under it instead of showing through between a card, the bar and the keyboard.
    func brandDock() -> some View {
        background(alignment: .top) {
            VStack(spacing: 0) {
                LinearGradient(colors: [Brand.bg.opacity(0), Brand.bg], startPoint: .top, endPoint: .bottom).frame(height: 16)
                Brand.bg
            }
            .padding(.top, -16)
            .ignoresSafeArea(edges: .bottom)
            .allowsHitTesting(false)
        }
    }

    /// A control drawn smaller than 44 points still takes a 44-point touch (HIG): give what it draws, in points.
    /// The view is laid out at the touch's size and then reports what it draws, so its neighbours do not move.
    func touchTarget(width: CGFloat? = nil, height: CGFloat? = nil) -> some View {
        let dx = width.map { max(0, (44 - $0) / 2) } ?? 0, dy = height.map { max(0, (44 - $0) / 2) } ?? 0
        return padding(.horizontal, dx).padding(.vertical, dy).contentShape(Rectangle())
            .padding(.horizontal, -dx).padding(.vertical, -dy)
    }

    /// A list's section footer, or a sentence above a section. Headers and footers take the font around the list, and the
    /// app's is body: unstyled, a footnote is as loud as the rows it explains.
    func brandFootnote() -> some View { font(.brand(.footnote)).foregroundStyle(Brand.muted).textCase(nil) }

    /// A section label: 11 points, upper case, tracked, in the dim colour.
    func brandKicker() -> some View {
        font(.brand(.caption2, .medium)).kerning(1.3).textCase(.uppercase).foregroundStyle(Brand.dim)
    }

    /// The hairline that makes a card a card on a ground of nearly its own colour.
    func brandCard(_ radius: CGFloat = 16) -> some View {
        background(Brand.card, in: RoundedRectangle(cornerRadius: radius)).overlay(RoundedRectangle(cornerRadius: radius).stroke(Brand.line))
    }
}

/// Ballerine | Pointe, Command center: the same lockup as the page.
struct BrandHeader: View {
    var mac: String? = nil  // the Mac's version from /voice/status, when a call knows it

    var body: some View {
        HStack(spacing: 12) {
            Image("BallerineLogo").resizable().renderingMode(.template).scaledToFit()
                .frame(height: 24).foregroundStyle(Brand.text).accessibilityLabel("Ballerine")
            Rectangle().fill(Brand.lineStrong).frame(width: 1, height: 28)
            VStack(alignment: .leading, spacing: 1) {
                Text("Pointe").font(.brand(.title3)).lineLimit(1)
                // Never a cut word: with less room the build number goes first, then the tagline. The version stays.
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) { tagline; version(AppVersion.line(app: AppVersion.app, mac: mac)) }
                    HStack(alignment: .firstTextBaseline, spacing: 6) { tagline; version(AppVersion.line(app: AppVersion.short, mac: mac)) }
                    version(AppVersion.line(app: AppVersion.short, mac: mac))
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }

    private var tagline: some View {
        Text("Command center").font(.brand(.caption)).foregroundStyle(Brand.muted).lineLimit(1)
    }

    private func version(_ line: String) -> some View {
        Text(line).font(.brand(.caption2, .medium)).foregroundStyle(Brand.dim).lineLimit(1)
            .accessibilityIdentifier("versionLine")
    }
}

/// The version, always on screen but quiet: "1.2.0", or "1.2.0 · Mac 1.1.0" when the Mac runs another build, so an
/// update that landed on one side only is visible at a glance.
enum AppVersion {
    static var app: String {
        let short = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
        return build.map { "\(short) (\($0))" } ?? short
    }

    /// "1.2.0", without the build number, for a header with little room.
    static var short: String { app.split(separator: " ").first.map(String.init) ?? app }

    static func line(app: String, mac: String?) -> String {
        guard let mac, !mac.isEmpty, mac != app.split(separator: " ").first.map(String.init) else { return app }
        return "\(app) · Mac \(mac)"
    }
}
