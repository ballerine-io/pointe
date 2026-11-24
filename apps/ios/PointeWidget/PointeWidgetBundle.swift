import SwiftUI
import WidgetKit

/// Pointe's widget extension: the Talk to Pointe Control, the Home Screen tile, and the call's Live Activity. What they
/// do runs in the app (apps/ios/PointeShared/TalkIntents.swift); this draws them.
@main
struct PointeWidgetBundle: WidgetBundle {
    var body: some Widget {
        TalkControl()
        TalkWidget()
        TalkLiveActivity()
    }
}
