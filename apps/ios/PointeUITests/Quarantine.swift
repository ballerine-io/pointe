import XCTest

/// A step that fails in CI every run for a cause not found yet: there it is an expected failure, listed in the results
/// with its reason, and a run where it passes says nothing. Anywhere else it is an ordinary step. Each use is named in
/// CONTRIBUTING.md (UI tests in CI) and goes when its cause is fixed.
@MainActor func quarantinedInCI(_ reason: String, _ step: () -> Void) {
    guard ProcessInfo.processInfo.environment["CI"] == "true" else { return step() }
    let options = XCTExpectedFailure.Options()
    options.isStrict = false
    XCTExpectFailure(reason, options: options, failingBlock: step)
}
