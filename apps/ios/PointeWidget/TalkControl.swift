import PointeKit
import SwiftUI
import WidgetKit

/// "Talk to Pointe" as a Control: Control Center, the Lock Screen, and the Action button (Settings, Action Button,
/// Controls). One press starts a call to the orchestrator and talks; the next press sends
/// (developer.apple.com/documentation/widgetkit/creating-controls-to-perform-actions-across-the-system).
struct TalkControl: ControlWidget {
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: TalkWidgetKind.control) {
            ControlWidgetButton(action: TalkIntent()) {
                Label(TalkLaunchCopy.name, systemImage: "waveform")
            }
        }
        .displayName(LocalizedStringResource(stringLiteral: TalkLaunchCopy.name))
        .description(LocalizedStringResource(stringLiteral: TalkLaunchCopy.controlAbout))
    }
}
