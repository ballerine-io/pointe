import SwiftUI
import UIKit

/// The few brand tokens the widget extension draws with. The extension does not link the app's screens (PointeUI, with
/// its fonts), so it carries these; tests/test_widget.py holds each one to the token of the same name in
/// apps/PointeKit/Sources/PointeUI/Brand.swift. Keep each on one line in the same form.
enum WidgetBrand {
    static let orange = Color(light: 0xFF5A01, dark: 0xFF5A01)
    static let onOrange = Color(light: 0x0A0400, dark: 0x0A0400)
    static let card = Color(light: 0xFFFFFF, dark: 0x0F0B08)
    static let raised = Color(light: 0xF5F1EF, dark: 0x1A1410)
    static let text = Color(light: 0x0A0400, dark: 0xF7F2F0)
    static let muted = Color(light: 0x5C5450, dark: 0xB5ADA8)
    static let accent = Color(light: 0xC24F0D, dark: 0xFF8C4A)
    static let successText = Color(light: 0x0E7A41, dark: 0x3DBE7B)
    static let dangerText = Color(light: 0xC83A37, dark: 0xF0706B)
}

extension Color {
    init(light: UInt32, _ lightAlpha: Double = 1, dark: UInt32, _ darkAlpha: Double = 1) {
        func ui(_ hex: UInt32, _ alpha: Double) -> UIColor {
            UIColor(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
        }
        self.init(uiColor: UIColor { $0.userInterfaceStyle == .dark ? ui(dark, darkAlpha) : ui(light, lightAlpha) })
    }
}
