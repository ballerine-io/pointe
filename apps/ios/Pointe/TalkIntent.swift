import AppIntents

// The intents themselves are apps/ios/PointeShared/TalkIntents.swift, compiled into the widget extension too. What only the
// app declares is here: the phrases Siri and Shortcuts offer.

struct PointeShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: TalkIntent(), phrases: ["\(.applicationName): Talk", "Talk to \(.applicationName)"],
                    shortTitle: "Talk", systemImageName: "mic.fill")
    }
}
