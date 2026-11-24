import AppIntents
import PointeKit

// "Talk to Pointe" from outside the app (docs/features/push-to-talk.md). Compiled into the app and into the widget
// extension: the Control, the widget and the Live Activity's buttons name these types, and the app performs them
// (developer.apple.com/documentation/widgetkit/adding-interactivity-to-widgets-and-live-activities). The rules and the
// work are the app's (PointeKit's TalkLaunch, PointeUI's PhoneTalk); these only hand the press over.

/// The press: the Action button, the Control (Control Center, the Lock Screen), the Home Screen widget, the Live
/// Activity's Talk, Back Tap and Siri. It opens Pointe talking to the orchestrator, calling the Mac first if no call is
/// up; the next press sends. Opening the app is the point: the microphone starts at once in front, the mic under your
/// thumb sends, and a locked iPhone asks to unlock before anything listens (TalkLaunch says why not in the background).
struct TalkIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "Talk to Pointe"
    static let description = IntentDescription("Open Pointe talking to the orchestrator; press again to send.")
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let launcher = TalkLaunchers.current else { return .result(dialog: "\(TalkLaunchCopy.setUp).") }
        return .result(dialog: IntentDialog(stringLiteral: await launcher.press().said))
    }
}

/// The Live Activity's Send: closes the open press, and the Mac sends it as one turn.
struct SendTalkIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "Send to Pointe"
    static let description = IntentDescription("Send what you said since you pressed Talk.")
    static let isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        _ = await TalkLaunchers.current?.send()
        return .result()
    }
}

/// The Live Activity's Cancel and Hang up: the call ends, and a press still open is never sent.
struct CancelTalkIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "Hang up Pointe"
    static let description = IntentDescription("End the call. Nothing you said since the last send is sent.")
    static let isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        _ = await TalkLaunchers.current?.cancel()
        return .result()
    }
}
