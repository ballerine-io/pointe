import Foundation

/// The bundle's principal class (NSPrincipalClass in its Info.plist): XCTest makes one when it loads the bundle, before
/// any test starts the app. These tests put windows on a screen and take the keyboard, so on a Mac a person works at
/// they run only when that person said so: CI=true or POINTE_UI_LOCAL=1, the rule of tools/ui_guard.py, which
/// tests/test_ui_guard.py holds this file to. xcodebuild hands the runner the variables named TEST_RUNNER_*, without
/// the prefix: `TEST_RUNNER_POINTE_UI_LOCAL=1 xcodebuild test …`; in Xcode, the scheme's Test environment.
@objc(UIGuard) final class UIGuard: NSObject {
    override init() {
        super.init()
        let env = ProcessInfo.processInfo.environment
        if env["CI"] == "true" || env["POINTE_UI_LOCAL"] == "1" { return }
        let line = "refused: these UI tests open windows and take the keyboard and pointer on this Mac. They run in CI: push, or `gh workflow run ui.yml`, and read its artifacts. To run them here anyway: TEST_RUNNER_POINTE_UI_LOCAL=1.\n"
        FileHandle.standardError.write(Data(line.utf8))
        exit(2)
    }
}
