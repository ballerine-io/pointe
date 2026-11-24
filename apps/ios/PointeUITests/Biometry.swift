import XCTest

/// The simulator's Face ID, driven from a UI test: Features → Face ID → Enrolled, and a matching or other face.
enum Biometry {
    private static func symbol<T>(_ name: String, _: T.Type) -> T { unsafeBitCast(dlsym(dlopen(nil, RTLD_NOW), name), to: T.self) }
    private static let post = symbol("notify_post", (@convention(c) (UnsafePointer<CChar>) -> UInt32).self)
    private static let register = symbol("notify_register_check",
                                         (@convention(c) (UnsafePointer<CChar>, UnsafeMutablePointer<Int32>) -> UInt32).self)
    private static let setState = symbol("notify_set_state", (@convention(c) (Int32, UInt64) -> UInt32).self)

    static func enrol() {
        var token: Int32 = 0
        _ = register("com.apple.BiometricKit.enrollmentChanged", &token)
        _ = setState(token, 1)
        _ = post("com.apple.BiometricKit.enrollmentChanged")
    }

    static func match(_ yes: Bool) {
        _ = post(yes ? "com.apple.BiometricKit_Sim.pearl.match" : "com.apple.BiometricKit_Sim.pearl.nomatch")
        _ = post(yes ? "com.apple.BiometricKit_Sim.fingerTouch.match" : "com.apple.BiometricKit_Sim.fingerTouch.nomatch")
    }

    /// The first Face ID use asks the system's permission once.
    @MainActor static func allowFaceID() {
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        for name in ["OK", "Allow"] where springboard.buttons[name].waitForExistence(timeout: 2) { springboard.buttons[name].tap() }
    }
}
