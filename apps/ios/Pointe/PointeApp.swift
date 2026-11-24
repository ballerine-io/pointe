import PointeUI
import SwiftUI

/// The iPhone app. Everything it shows and does is the shared module's (apps/PointeKit, PointeUI: docs/design/parity.md),
/// the same screens the Mac app draws; this target holds what iOS wants declared in the app itself: the entry point, the
/// background refresh, the Talk intent, the icon and the Info.plist.
@main
struct PointeApp: App {
    init() { PointeBoot.start() }

    var body: some Scene {
        WindowGroup { PointeRoot() }
            .backgroundTask(.appRefresh(PointeBoot.refreshTask)) { await PointeBoot.refresh() }
    }
}
