// swift-tools-version: 6.0
import PackageDescription

// What the iPhone app and the Mac app share: the daemon's models, the wire format, the rules that are pure, and the
// words. Apple frameworks only: no package dependency (docs/security/supply-chain.md).
let package = Package(
    name: "PointeKit",
    platforms: [.iOS(.v18), .macOS(.v14)],
    products: [
        .library(name: "PointeKit", targets: ["PointeKit"]),
        .library(name: "PointeMacKit", targets: ["PointeMacKit"]),
    ],
    targets: [
        .target(name: "PointeKit"),
        .target(name: "PointeMacKit", dependencies: ["PointeKit"]),
        .testTarget(name: "PointeKitTests", dependencies: ["PointeKit"], resources: [.copy("Fixtures")]),
        .testTarget(name: "PointeMacKitTests", dependencies: ["PointeMacKit"]),
    ],
    swiftLanguageModes: [.v6]
)
