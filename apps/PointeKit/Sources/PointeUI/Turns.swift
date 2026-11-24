import Foundation

/// Turn taking (docs/design/turn-taking.md): how long a pause ends a sentence, and a hold ("don't interrupt me") that
/// keeps the Mac quiet until "go ahead" or 8 s of quiet. The Mac's pref "turns.patience" is the truth, set here or on
/// the page; the words are the page's, word for word (tests/test_turn_taking.py checks both).
enum TurnsCopy {
    static let setting = "Wait before answering"
    static let levels: [(value: String, label: String)] = [("quick", "Quick"), ("normal", "Normal"), ("patient", "Patient")]
    static let holding = "Holding"
    static let holdingHow = "Say “go ahead” when you're done"  // the line under the state
    static let failed = "The Mac did not take the setting. Is Pointe on the Mac up to date?"
    static let defaultLevel = "normal"
}
