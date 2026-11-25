import XCTest

/// The bundle's principal class (NSPrincipalClass in its Info.plist): XCTest makes one when it loads the bundle, before
/// any test starts the app. These tests put windows on a screen and take the keyboard, so on a Mac a person works at
/// they run only when that person said so: CI=true or POINTE_UI_LOCAL=1, the rule of tools/ui_guard.py, which
/// tests/test_ui_guard.py holds this file to. xcodebuild hands the runner the variables named TEST_RUNNER_*, without
/// the prefix: `TEST_RUNNER_POINTE_UI_LOCAL=1 xcodebuild test …`; in Xcode, the scheme's Test environment.
@objc(UIGuard) final class UIGuard: NSObject {
    override init() {
        super.init()
        let env = ProcessInfo.processInfo.environment
        if let folder = env["FAILURE_SHOTS"], !folder.isEmpty { XCTestObservationCenter.shared.addTestObserver(FailureShots(folder: folder)) }
        if env["CI"] == "true" || env["POINTE_UI_LOCAL"] == "1" { return }
        let line = "refused: these UI tests open windows and take the keyboard and pointer on this Mac. They run in CI: push, or `gh workflow run ui.yml`, and read its artifacts. To run them here anyway: TEST_RUNNER_POINTE_UI_LOCAL=1.\n"
        FileHandle.standardError.write(Data(line.utf8))
        exit(2)
    }
}

/// What CI saw when a test failed: the screen and the app's element tree, written to FAILURE_SHOTS (the ui workflow
/// uploads that folder) at a test's first issue. The tests attach no picture of their own when an assertion fails.
final class FailureShots: NSObject, XCTestObservation {
    private let folder: String
    private var taken = Set<String>()

    init(folder: String) { self.folder = folder }

    func testCase(_ testCase: XCTestCase, didRecord issue: XCTIssue) {
        let name = testCase.name.replacingOccurrences(of: "[^A-Za-z0-9]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        guard taken.insert(name).inserted else { return }  // the first issue is the one to see; and no loop if a picture fails
        let path = "\(folder)/\(name)", what = issue.compactDescription
        MainActor.assumeIsolated {
            try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: "\(path).png"))
            let app = XCUIApplication()
            guard app.state == .runningForeground else { return }  // asking a stopped app for its tree records one more issue
            try? "\(what)\n\n\(app.debugDescription)".write(toFile: "\(path).txt", atomically: true, encoding: .utf8)
        }
    }
}
