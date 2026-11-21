// swift-tools-version: 6.0
import PackageDescription

// What the iPhone app and the Mac app share. PointeUI is the app itself: the daemon's models, the call, the rules, the
// words and every screen, drawn once for both platforms (docs/design/parity.md). PointeKit is the wire format and the
// loopback client under it; PointeMacKit is what only a Mac does (find and start the daemon, the shortcut).
// Apple frameworks only: no package dependency (docs/security/supply-chain.md).
let package = Package(
    name: "PointeKit",
    platforms: [.iOS(.v18), .macOS(.v15)],
    products: [
        .library(name: "PointeKit", targets: ["PointeKit"]),
        .library(name: "PointeUI", targets: ["PointeUI"]),
        .library(name: "PointeMacKit", targets: ["PointeMacKit"]),
    ],
    targets: [
        .target(name: "PointeKit"),
        .target(name: "PointeUI", dependencies: ["PointeKit"], resources: [.process("Resources")]),
        .target(name: "PointeMacKit", dependencies: ["PointeKit"]),
        .testTarget(name: "PointeKitTests", dependencies: ["PointeKit"], resources: [.copy("Fixtures")]),
        .testTarget(name: "PointeUIUnitTests", dependencies: ["PointeUI"]),
        .testTarget(name: "PointeMacKitTests", dependencies: ["PointeMacKit"]),
    ],
    swiftLanguageModes: [.v6]
)
