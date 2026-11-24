import SwiftUI

/// A connection that failed, drawn where it happened: the cause, where the phone looked and over what, the fix, and
/// the actions. It has no timer: it leaves only when the person acts (PairingFlow, CallView).
struct ProblemCard: View {
    let problem: ConnectionProblem
    /// Under the cause: "Still paired with studio.example.ts.net." when a replacement failed.
    var kept: String? = nil
    /// Over a call that still works: the person may keep the pairing they have and close this.
    var close: (() -> Void)? = nil
    let act: (ConnectionProblem.Action) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top) {
                Label(problem.title, systemImage: "exclamationmark.triangle.fill")
                    .font(.brand(.headline)).foregroundStyle(Brand.accent)
                    .accessibilityIdentifier("problemTitle")
                Spacer(minLength: 0)
                if let close {
                    Button(action: close) { Image(systemName: "xmark").font(.brand(.footnote, .semibold)).foregroundStyle(Brand.muted) }
                        .buttonStyle(.plain).touchTarget(height: 32)
                        .accessibilityLabel(ProblemCopy.close).accessibilityIdentifier("problemClose")
                }
            }
            Text(problem.detail).font(.brand(.callout)).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("problemDetail")
            Text(problem.tried).font(.brand(.footnote)).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("problemTried")
            Text(Self.rich(problem.fix)).font(.brand(.callout)).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("problemFix")
            if let kept { Text(kept).font(.brand(.footnote)).foregroundStyle(Brand.muted) }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) { buttons }
                VStack(alignment: .leading, spacing: 8) { buttons }
            }
            .padding(.top, 2)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Brand.card, in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Brand.orangeLine))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("connectionProblem")
    }

    @ViewBuilder private var buttons: some View {
        ForEach(Array(problem.actions.enumerated()), id: \.offset) { index, action in
            let label = Self.label(action)
            if index == 0 {
                Button(label) { act(action) }.buttonStyle(.brandPrimary).controlSize(.regular)
                    .accessibilityIdentifier(Self.id(action))
            } else {
                Button(label) { act(action) }.buttonStyle(.brandQuiet).controlSize(.regular)
                    .accessibilityIdentifier(Self.id(action))
            }
        }
    }

    /// A fix names a command in backticks (the Mac's words, phone_check.py): drawn as code, not as two marks.
    static func rich(_ line: String) -> AttributedString {
        (try? AttributedString(markdown: line, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(line)
    }

    static func label(_ action: ConnectionProblem.Action) -> String {
        switch action {
        case .tryAgain: ProblemCopy.tryAgain
        case .pairAgain: ProblemCopy.pairAgain
        case .howToFix: ProblemCopy.howToFix
        }
    }

    static func id(_ action: ConnectionProblem.Action) -> String {
        switch action {
        case .tryAgain: "problemTryAgain"
        case .pairAgain: "problemPairAgain"
        case .howToFix: "problemHowToFix"
        }
    }
}

/// "How to fix": the cause again, the address and route, the fix and the route's own checks, and its guide.
struct ConnectionHelpSheet: View {
    let problem: ConnectionProblem
    let close: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(problem.title).font(.brand(.title3, .semibold))
                    Text(problem.detail).font(.brand(.body)).fixedSize(horizontal: false, vertical: true)
                    Text(problem.tried).font(.brand(.footnote)).foregroundStyle(Brand.muted)
                    VStack(alignment: .leading, spacing: 8) {
                        Text(ProblemCard.rich(problem.fix)).fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("helpFix")
                        if problem.route.hint != problem.fix {
                            Text(ProblemCard.rich(problem.route.hint)).fixedSize(horizontal: false, vertical: true)
                                .accessibilityIdentifier("helpRouteHint")
                        }
                    }
                    .font(.brand(.callout))
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Brand.raised, in: RoundedRectangle(cornerRadius: 12))
                    Link(destination: problem.route.help) {
                        Label(ProblemCopy.readGuide, systemImage: "book")
                    }
                    .font(.brand(.callout, .semibold))
                    .accessibilityIdentifier("helpGuide")
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(Brand.background)
            .navigationTitle(ProblemCopy.howToFix)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button(ProblemCopy.close, action: close).accessibilityIdentifier("helpClose") } }
        }
    }
}
