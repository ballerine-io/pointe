import SwiftUI

/// Settings → About: the same words as the page's ABOUT_COPY (tests/test_copy_parity.py).
enum AboutCopy {
    static let title = "About"
    static let body = "Pointe is open source (MIT). Built and open-sourced by Ballerine Engineering."
    static let repo = "Source code on GitHub"
    static let repoURL = "https://github.com/ballerine-io/pointe"
    static let maker = "ballerine.com"
    static let makerURL = "https://ballerine.com"
    static let privacy = "Privacy policy"
    static let privacyURL = "https://github.com/ballerine-io/pointe/blob/main/PRIVACY.md"
    static let version = "Version"
}

/// About's rows, for the sheet here and for the Mac's setup guide, which has no call screen to open the sheet from.
public struct PointeAboutRows: View {
    public static let title = AboutCopy.title
    var mac: String?

    public init(mac: String? = nil) { self.mac = mac }

    public var body: some View {
        Section {
            HStack(spacing: 12) {
                Image("ChorusMark", bundle: .module).resizable().frame(width: 40, height: 40).accessibilityHidden(true)
                Text("Pointe").font(.brand(.title2))
            }
            Text(AboutCopy.body).accessibilityIdentifier("aboutBody")
            // In the accent with the arrow that says it leaves the app: in the form's ink they read as two more lines of text.
            link(AboutCopy.repo, AboutCopy.repoURL).accessibilityIdentifier("aboutRepo")
            link(AboutCopy.maker, AboutCopy.makerURL).accessibilityIdentifier("aboutMaker")
            link(AboutCopy.privacy, AboutCopy.privacyURL).accessibilityIdentifier("aboutPrivacy")
            LabeledContent(AboutCopy.version, value: AppVersion.line(app: AppVersion.app, mac: mac))
                .accessibilityIdentifier("aboutVersion")
        }
    }

    private func link(_ title: String, _ url: String) -> some View {
        Link(destination: URL(string: url)!) {
            HStack {
                Text(title)
                Spacer(minLength: 8)
                Image(systemName: "arrow.up.right").font(.brand(.footnote, .semibold))
            }
            .foregroundStyle(Brand.accent)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
    }
}

struct AboutSheet: View {
    var mac: String? = nil
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            BrandForm {
                PointeAboutRows(mac: mac)
            }
            .sheetTitle(AboutCopy.title)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
