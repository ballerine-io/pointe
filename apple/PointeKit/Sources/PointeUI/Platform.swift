import SwiftUI
#if canImport(UIKit)
import UIKit
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
}

enum Clipboard {
    @MainActor static func copy(_ text: String) {
        #if os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #else
        UIPasteboard.general.string = text
        #endif
    }
}

extension View {
    /// A sheet's title, in the bar's own line on both platforms.
    @ViewBuilder func sheetTitle(_ title: String) -> some View {
        #if os(macOS)
        navigationTitle(title)  // macOS draws it in the sheet's own bar
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
            .modifier(EscCloses())
        #else
        presentationBackground(Brand.group)
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
                    Text(option.label).font(.brand(.footnote, .medium)).lineLimit(1)
                        .foregroundStyle(on ? Brand.text : Brand.muted)
                        .padding(.horizontal, 14).padding(.vertical, 6)
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
        .animation(.snappy(duration: 0.18), value: selection)
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

extension ToolbarItemPlacement {
    /// The leading edge of a sheet's bar. On the Mac a sheet's buttons sit at the bottom: the cancel side.
    static var sheetLeading: ToolbarItemPlacement {
        #if os(macOS)
        .cancellationAction
        #else
        .topBarLeading
        #endif
    }
}
