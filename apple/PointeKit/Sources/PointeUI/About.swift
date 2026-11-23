import SwiftUI

/// Settings → About: the same words as the page's ABOUT_COPY (tests/test_copy_parity.py).
enum AboutCopy {
    static let title = "About"
    static let body = "Pointe is open source (MIT). Built and open-sourced by Ballerine Engineering."
    static let repo = "Source code on GitHub"
    static let repoURL = "https://github.com/ballerine-io/pointe"
    static let maker = "ballerine.com"
    static let makerURL = "https://ballerine.com"
    static let version = "Version"
}

struct AboutSheet: View {
    var mac: String? = nil
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            BrandForm {
                Section {
                    Text(AboutCopy.body).accessibilityIdentifier("aboutBody")
                    // In the accent with the arrow that says it leaves the app: in the form's ink they read as two more lines of text.
                    link(AboutCopy.repo, AboutCopy.repoURL).accessibilityIdentifier("aboutRepo")
                    link(AboutCopy.maker, AboutCopy.makerURL).accessibilityIdentifier("aboutMaker")
                    LabeledContent(AboutCopy.version, value: AppVersion.line(app: AppVersion.app, mac: mac))
                        .accessibilityIdentifier("aboutVersion")
                }
            }
            .sheetTitle(AboutCopy.title)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
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
