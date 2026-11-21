import AppIntents
import PointeUI

/// "Pointe: Talk" for the Action button, Back Tap and Siri: starts or stops talking on the call that is up, with the app
/// in the background too (the call holds the audio session). With no call up it opens the app and says so. The rule is
/// the shared module's (`TalkShortcut`); an intent has to be declared in the app itself for iOS to find it.
struct TalkIntent: AppIntent, ForegroundContinuableIntent {
    static let title: LocalizedStringResource = "Talk"
    static let description = IntentDescription("Start or stop talking to Pointe, when the microphone is set to push to talk.")
    static let openAppWhenRun = false

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let done = TalkShortcut.run()
        switch done.decision {
        case .noCall: throw needsToContinueInForegroundError("No call is up: tap Connect in Pointe first.")
        case .alwaysOn: return .result(dialog: "Microphone is Always on: set it to Push to talk in Pointe's settings.")
        case .toggle: return .result(dialog: done.talking ? "Talking." : "Stopped.")
        }
    }
}

struct PointeShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: TalkIntent(), phrases: ["\(.applicationName): Talk", "Talk to \(.applicationName)"],
                    shortTitle: "Talk", systemImageName: "mic.fill")
    }
}
