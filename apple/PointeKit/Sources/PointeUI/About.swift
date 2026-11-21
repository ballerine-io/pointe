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
                    Link(AboutCopy.repo, destination: URL(string: AboutCopy.repoURL)!).accessibilityIdentifier("aboutRepo")
                    Link(AboutCopy.maker, destination: URL(string: AboutCopy.makerURL)!).accessibilityIdentifier("aboutMaker")
                    LabeledContent(AboutCopy.version, value: AppVersion.line(app: AppVersion.app, mac: mac))
                        .accessibilityIdentifier("aboutVersion")
                }
            }
            .navigationTitle(AboutCopy.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
