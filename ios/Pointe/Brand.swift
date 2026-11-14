import SwiftUI

/// Ballerine | Pointe, Command center: the same lockup as the page.
struct BrandHeader: View {
    var mac: String? = nil  // the Mac's version from /voice/status, when a call knows it

    var body: some View {
        HStack(spacing: 12) {
            Image("BallerineLogo").resizable().renderingMode(.template).scaledToFit()
                .frame(height: 22).foregroundStyle(.white).accessibilityLabel("Ballerine")
            Rectangle().fill(.white.opacity(0.25)).frame(width: 1, height: 28)
            VStack(alignment: .leading, spacing: 0) {
                Text("Pointe").font(.title3.bold())
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("Command center").font(.system(.footnote, design: .serif)).italic().foregroundStyle(.secondary)
                    Text(AppVersion.line(app: AppVersion.app, mac: mac)).font(.caption2.weight(.medium)).foregroundStyle(.tertiary)
                        .accessibilityIdentifier("versionLine")
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}

/// The version, always on screen but quiet: "1.2.0", or "1.2.0 · Mac 1.1.0" when the Mac runs another build, so an
/// update that landed on one side only is visible at a glance.
enum AppVersion {
    static var app: String {
        let short = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
        return build.map { "\(short) (\($0))" } ?? short
    }

    static func line(app: String, mac: String?) -> String {
        guard let mac, !mac.isEmpty, mac != app.split(separator: " ").first.map(String.init) else { return app }
        return "\(app) · Mac \(mac)"
    }
}
