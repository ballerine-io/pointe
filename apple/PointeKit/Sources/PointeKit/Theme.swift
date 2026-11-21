import Foundation
#if canImport(SwiftUI)
import SwiftUI
#endif
#if canImport(AppKit)
import AppKit
#elseif canImport(UIKit)
import UIKit
#endif

/// Ballerine Brand Guidelines V6 as the apps use it (docs/design/brand-v6.md). The values are assets/theme.json's, the
/// same the page carries: tests/test_macos_parity.py reads this file and fails when it drifts, so keep each token on one
/// line in the form below.
public enum BrandToken {
    /// One colour for light and one for dark: 0xRRGGBB with an opacity.
    public struct Token: Equatable, Sendable {
        public let light: UInt32, lightAlpha: Double, dark: UInt32, darkAlpha: Double
        public init(light: UInt32, _ lightAlpha: Double = 1, dark: UInt32, _ darkAlpha: Double = 1) {
            self.light = light; self.lightAlpha = lightAlpha; self.dark = dark; self.darkAlpha = darkAlpha
        }
    }

    // theme tokens: name = Token(light:, dark:)
    public static let bg = Token(light: 0xFFFFFF, dark: 0x0A0400)
    public static let surface = Token(light: 0xFCFAFA, dark: 0x0C0906)
    public static let card = Token(light: 0xFFFFFF, dark: 0x0F0B08)
    public static let raised = Token(light: 0xF5F1EF, dark: 0x1A1410)
    public static let raised2 = Token(light: 0xE9E2DE, dark: 0x26201B)
    public static let group = Token(light: 0xF5F1EF, dark: 0x0C0906)
    public static let cell = Token(light: 0xFFFFFF, dark: 0x1A1410)
    public static let text = Token(light: 0x0A0400, dark: 0xF7F2F0)
    public static let muted = Token(light: 0x5C5450, dark: 0xB5ADA8)
    public static let dim = Token(light: 0x6E6762, dark: 0x958D88)
    public static let line = Token(light: 0x0A0500, 0.10, dark: 0xFFFFFF, 0.08)
    public static let lineStrong = Token(light: 0x0A0500, 0.18, dark: 0xFFFFFF, 0.16)
    public static let orange = Token(light: 0xFF5A01, dark: 0xFF5A01)
    public static let onOrange = Token(light: 0x0A0400, dark: 0x0A0400)
    public static let accent = Token(light: 0xC24F0D, dark: 0xFF8C4A)
    public static let tint = Token(light: 0xFFF1E9, dark: 0xFF5A01, 0.14)
    public static let orangeLine = Token(light: 0xFF5A01, 0.45, dark: 0xFF5A01, 0.45)
    public static let success = Token(light: 0x138A4B, dark: 0x138A4B)
    public static let successText = Token(light: 0x0E7A41, dark: 0x3DBE7B)
    public static let danger = Token(light: 0xC83A37, dark: 0xC83A37)
    public static let dangerText = Token(light: 0xC83A37, dark: 0xF0706B)
    public static let primary = Token(light: 0x0A0400, dark: 0xF7F2F0)
    public static let onPrimary = Token(light: 0xFCFAFA, dark: 0x0A0400)
    public static let glow = Token(light: 0xFF5A01, 0, dark: 0xFF5A01, 0.16)
    public static let scrim = Token(light: 0x0A0400, 0.35, dark: 0x000000, 0.60)
    // end of theme tokens
}

/// Appearance: System, Light or Dark, kept on the device, as the page keeps it in its browser. System is the default.
public enum Theme: String, CaseIterable, Identifiable, Sendable {
    case system, light, dark

    public static let key = "pointe.theme"
    public static let fallback = Theme.system
    public static let setting = "Appearance"

    public var id: String { rawValue }
    public var label: String {
        switch self {
        case .system: "System"
        case .light: "Light"
        case .dark: "Dark"
        }
    }
    public static func stored(_ raw: String?) -> Theme { raw.flatMap(Theme.init(rawValue:)) ?? fallback }
}

#if canImport(SwiftUI)
extension Theme {
    /// nil follows the system.
    public var scheme: ColorScheme? {
        switch self {
        case .system: nil
        case .light: .light
        case .dark: .dark
        }
    }
}

extension Color {
    /// A colour that follows the appearance.
    public init(_ token: BrandToken.Token) {
        #if canImport(AppKit)
        func ns(_ hex: UInt32, _ alpha: Double) -> NSColor {
            NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
        }
        self.init(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? ns(token.dark, token.darkAlpha) : ns(token.light, token.lightAlpha)
        })
        #else
        func ui(_ hex: UInt32, _ alpha: Double) -> UIColor {
            UIColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
        }
        self.init(uiColor: UIColor { $0.userInterfaceStyle == .dark ? ui(token.dark, token.darkAlpha) : ui(token.light, token.lightAlpha) })
        #endif
    }
}
#endif
