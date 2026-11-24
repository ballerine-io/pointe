import Testing
@testable import PointeKit

/// The Mac app's setup guide, step 4: starting Pointe downloads nothing. The packages were installed in step 1
/// (Installer.swift says "about 180 MB" there, where it is true).
@Suite struct MacCopyTests {
    @Test func startingPointeClaimsNoDownload() {
        #expect(MacCopy.starting == "Starting Pointe…")
    }
}
