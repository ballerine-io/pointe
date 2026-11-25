import LocalAuthentication
import SwiftUI
#if canImport(UIKit)
import UIKit
import UniformTypeIdentifiers
#else
import AppKit
#endif

// The few places where the iPhone and the Mac need a different call for the same thing. A screen is written once
// (docs/design/parity.md): what differs between the platforms is here, or behind `#if os(...)` where a whole control
// belongs to one of them.

/// Which surface this build draws, for a word or a size that differs.
enum Surface {
    #if os(macOS)
    static let isMac = true
    #else
    static let isMac = false
    #endif

    /// "this phone" on the iPhone, "this Mac" on the Mac, for a line both show.
    static let thisDevice = isMac ? "this Mac" : "this phone"
    /// What a finger does on the phone a pointer does on the Mac.
    static let tap = isMac ? "click" : "tap"
    static let Tap = isMac ? "Click" : "Tap"
    /// The symbol on Approve: what the device asks with (Face ID; Touch ID or the password on the Mac).
    static let ownerSymbol = isMac ? "touchid" : "faceid"

    /// A line the Mac (the daemon) wrote for every device, as this one shows it: its read-back ends "Say yes or tap.",
    /// which on the Mac is a click.
    static func shown(_ line: String) -> String {
        isMac ? line.replacingOccurrences(of: "Say yes or tap.", with: "Say yes or click.") : line
    }

    /// A line written for the phone (the page's words, or the Mac's own read-backs: "Say yes or tap."), as the Mac says
    /// it: a pointer clicks.
    static func pointer(_ line: String) -> String {
        guard isMac else { return line }
        return line.replacing(/\btap\b/, with: "click").replacing(/\bTap\b/, with: "Click")
    }
}

/// What Approve says when the owner check did not let it through: before, it did nothing at all.
enum OwnerCopy {
    static let notChecked = "Not approved: Pointe could not check that it is you. Try again."
    static let noPasscode = Surface.isMac ? "Not approved: this Mac has no password to check that it is you."
                                          : "Not approved: this phone has no passcode, so Pointe cannot check that it is you. Set one in Settings."
    static let noMatch = "Not approved: that did not match. Try again."

    /// Nil when the person cancelled: they know why nothing happened.
    static func refusal(_ code: LAError.Code?) -> String? {
        switch code {
        case .userCancel, .appCancel, .systemCancel, .userFallback: nil
        case .passcodeNotSet: noPasscode
        case .authenticationFailed: noMatch
        default: notChecked
        }
    }
}

enum Clipboard {
    /// A line of the conversation: an ordinary copy, kept until the person copies something else.
    @MainActor static func copy(_ text: String) {
        #if os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #else
        UIPasteboard.general.string = text
        #endif
    }

    #if os(macOS)
    /// nspasteboard.org's marker: clipboard managers and history tools do not keep or show what carries it.
    static let concealed = NSPasteboard.PasteboardType("org.nspasteboard.ConcealedType")

    /// A pairing code or an invite line: marked concealed, and cleared when the code ends unless something else was
    /// copied since.
    @MainActor static func copy(_ text: String, until: Date, on board: NSPasteboard = .general) {
        board.clearContents()
        board.setString(text, forType: .string)
        board.setData(Data(), forType: concealed)
        let mine = board.changeCount
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(max(0, until.timeIntervalSinceNow)))
            if board.changeCount == mine { board.clearContents() }
        }
    }
    #else
    /// A pairing code or an invite line: this iPhone only (not Universal Clipboard to the person's other devices), and
    /// gone when the code ends.
    @MainActor static func copy(_ text: String, until: Date) {
        UIPasteboard.general.setItems([[UTType.utf8PlainText.identifier: text]],
                                      options: [.localOnly: true, .expirationDate: until])
    }
    #endif
}

/// The system's own switch for the microphone: iOS opens Pointe's page in Settings, macOS its Privacy pane.
public enum SystemSettings {
    @MainActor public static func openMicrophone() {
        #if os(macOS)
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") { NSWorkspace.shared.open(url) }
        #else
        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
        #endif
    }
}

extension View {
    /// A sheet's title: in the bar on the iPhone, over the content on the Mac.
    @ViewBuilder func sheetTitle(_ title: String) -> some View {
        #if os(macOS)
        // Over the content, in line with the section headings: in the sheet's bar macOS keeps an empty slot for window
        // buttons a sheet does not have, and the title sat about 48 points in from everything under it.
        navigationTitle(title)
            .toolbar(removing: .title)
            .safeAreaInset(edge: .top, spacing: 0) {
                Text(title).font(.brand(.headline, .semibold))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 28).padding(.top, 16).padding(.bottom, 4)
                    .background(Brand.group)
                    .accessibilityAddTraits(.isHeader)
            }
        #else
        navigationTitle(title).navigationBarTitleDisplayMode(.inline)
        #endif
    }

    /// What a sheet stands on: the brand's grouped ground. On the Mac a sheet takes its size from its content, and a
    /// form's own ideal size is a few rows: the sheet is given the size of a panel instead.
    @ViewBuilder func sheetSurface() -> some View {
        #if os(macOS)
        frame(minWidth: 480, idealWidth: 520, maxWidth: 560, minHeight: 380, idealHeight: 560, maxHeight: 640)
            .background(Brand.group)
            .presentationBackground(Brand.group)
            .tint(Brand.primary)  // a sheet's Done is the brand's primary button, never orange
            .modifier(EscCloses())
        #else
        presentationBackground(Brand.group)
        #endif
    }

    /// A menu whose label draws itself as a field (brain dump's To:): macOS otherwise lays its own pop-up bezel and a
    /// second arrow under the label, two controls drawn over each other.
    @ViewBuilder func fieldMenu() -> some View {
        #if os(macOS)
        menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden)
        #else
        self
        #endif
    }

    /// A field for a name, a path or a term: nothing is capitalised for the person. The Mac never does.
    @ViewBuilder func plainEntry() -> some View {
        #if os(macOS)
        autocorrectionDisabled()
        #else
        textInputAutocapitalization(.never).autocorrectionDisabled()
        #endif
    }

    /// Chrome that stops growing with Dynamic Type shows its label large on a long press (iOS's Large Content Viewer).
    @ViewBuilder func largeContent<Shown: View>(@ViewBuilder _ shown: () -> Shown) -> some View {
        #if os(macOS)
        self
        #else
        accessibilityShowsLargeContentViewer(shown)
        #endif
    }
}

/// A choice of two or three, side by side. The phone's is the system's segmented control, in the brand's colours
/// (`Brand.install`). The Mac's own would fill the chosen segment with the accent colour, and the brand never marks a
/// choice with orange: there it is drawn here, a card on the raised track, as the page draws it.
struct Segments<Value: Hashable, Native: View>: View {
    @Binding var selection: Value
    let options: [(value: Value, label: String)]
    @ViewBuilder var native: Native

    var body: some View {
        #if os(macOS)
        HStack(spacing: 2) {
            ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                let on = option.value == selection
                Button { selection = option.value } label: {
                    Text(option.label).font(.brand(.footnote, .medium)).lineLimit(1).fixedSize()
                        .foregroundStyle(on ? Brand.text : Brand.muted)
                        .padding(.horizontal, 10).padding(.vertical, 6)
                        .frame(maxWidth: .infinity)
                        .background(on ? AnyShapeStyle(Brand.card) : AnyShapeStyle(Color.clear), in: RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(on ? Brand.lineStrong : Color.clear))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(on ? [.isSelected] : [])
            }
        }
        .padding(2)
        .background(Brand.raised, in: RoundedRectangle(cornerRadius: 10))
        .motion(.snappy(duration: 0.18), value: selection)
        .accessibilityElement(children: .contain)
        #else
        native
        #endif
    }
}

/// Esc closes a Mac sheet, as it closes any panel. (A sheet's Done is its default button: Return.)
struct EscCloses: ViewModifier {
    @Environment(\.dismiss) private var dismiss

    func body(content: Content) -> some View {
        #if os(macOS)
        content.onExitCommand { dismiss() }
        #else
        content
        #endif
    }
}

/// A control under the pointer answers it, as the page's do on `:hover`: a step lighter on dark, darker on light.
/// A finger has no hover: on the phone this is nothing.
struct HoverLift: ViewModifier {
    @State private var over = false
    @Environment(\.colorScheme) private var scheme
    @Environment(\.isEnabled) private var enabled

    func body(content: Content) -> some View {
        #if os(macOS)
        content.brightness(over && enabled ? (scheme == .dark ? 0.07 : -0.04) : 0)
            .onHover { over = $0 }
            .motion(.easeOut(duration: 0.12), value: over)
        #else
        content
        #endif
    }
}

extension View {
    func hoverLift() -> some View { modifier(HoverLift()) }
}

extension ToolbarItemPlacement {
    /// The leading edge of a sheet's bar. On the Mac a sheet's buttons sit at the bottom, and its leading side is the
    /// destructive one's place: the cancel side would make the button the sheet's Esc (Esc on Sessions opened New session).
    static var sheetLeading: ToolbarItemPlacement {
        #if os(macOS)
        .destructiveAction
        #else
        .topBarLeading
        #endif
    }

    /// Done on a sheet whose only way out it is: on the Mac the cancel side, so Esc closes the sheet.
    static var sheetDone: ToolbarItemPlacement {
        #if os(macOS)
        .cancellationAction
        #else
        .confirmationAction
        #endif
    }
}
