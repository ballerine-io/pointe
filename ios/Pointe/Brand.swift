import SwiftUI

/// Ballerine | Pointe, Command center: the same lockup as the page.
struct BrandHeader: View {
    var body: some View {
        HStack(spacing: 12) {
            Image("BallerineLogo").resizable().renderingMode(.template).scaledToFit()
                .frame(height: 22).foregroundStyle(.white).accessibilityLabel("Ballerine")
            Rectangle().fill(.white.opacity(0.25)).frame(width: 1, height: 28)
            VStack(alignment: .leading, spacing: 0) {
                Text("Pointe").font(.title3.bold())
                Text("Command center").font(.system(.footnote, design: .serif)).italic().foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}
