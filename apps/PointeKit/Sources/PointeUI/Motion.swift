import SwiftUI

/// Reduce Motion (docs/features/accessibility.md): with the system setting on, nothing on a Pointe screen moves by
/// itself and no change is animated. The state is always in words or a shape as well, so nothing is lost. Every
/// animation in the apps goes through this file: `withAnimation` below, `.motion(_:value:)` where SwiftUI has
/// `.animation(_:value:)`, and the symbol effects at the end. tests/test_accessibility.py fails for one that does not.
public enum Motion {
    /// `-pointe.reduceMotion YES` at launch stands in for the system setting, which a UI test cannot switch.
    public static let forced = UserDefaults.standard.bool(forKey: "pointe.reduceMotion")

    /// `system`: the view's `\.accessibilityReduceMotion`.
    public static func reduced(_ system: Bool) -> Bool { system || forced }

    /// The one endless animation: the state dot's (Thinking.swift), which is not started with Reduce Motion.
    static func breathing(_ seconds: Double) -> Animation { .easeInOut(duration: seconds).repeatForever(autoreverses: true) }

    /// Where there is no view to ask (a `withAnimation` in a model or a callback).
    @MainActor
    public static var reducedNow: Bool {
        #if os(iOS)
        forced || UIAccessibility.isReduceMotionEnabled
        #else
        forced || NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        #endif
    }
}

/// Takes the place of SwiftUI's in this module: the same call, and with Reduce Motion the change is made at once.
@MainActor
func withAnimation<Result>(_ animation: Animation? = .default, _ body: () throws -> Result) rethrows -> Result {
    try SwiftUI.withAnimation(Motion.reducedNow ? nil : animation, body)
}

private struct MotionModifier<V: Equatable>: ViewModifier {
    let animation: Animation?
    let value: V
    @Environment(\.accessibilityReduceMotion) private var system

    func body(content: Content) -> some View {
        content.animation(Motion.reduced(system) ? nil : animation, value: value)
    }
}

private struct SymbolMotion: ViewModifier {
    enum Kind { case pulse, wave, swap }
    let kind: Kind
    var on = true
    @Environment(\.accessibilityReduceMotion) private var system

    @ViewBuilder
    func body(content: Content) -> some View {
        let moving = on && !Motion.reduced(system)
        switch kind {
        case .pulse: content.symbolEffect(.pulse, options: .repeating, isActive: moving)
        case .wave: content.symbolEffect(.variableColor.iterative, options: .repeating, isActive: moving)
        case .swap: content.contentTransition(moving ? .symbolEffect(.replace) : .identity)
        }
    }
}

public extension View {
    /// `.animation(_:value:)`, off with Reduce Motion.
    func motion<V: Equatable>(_ animation: Animation?, value: V) -> some View { modifier(MotionModifier(animation: animation, value: value)) }
    /// A symbol that pulses while `on`: still with Reduce Motion.
    func pulsing(_ on: Bool = true) -> some View { modifier(SymbolMotion(kind: .pulse, on: on)) }
    /// The wave beside words being heard: still with Reduce Motion.
    func listeningWave() -> some View { modifier(SymbolMotion(kind: .wave)) }
    /// One symbol drawn into the next: swapped at once with Reduce Motion.
    func symbolSwap() -> some View { modifier(SymbolMotion(kind: .swap)) }
}
