import XCTest
@testable import PointeUI

/// Mute, then unmute before the first request is answered: the last tap wins on the Mac, as on the page
/// (tests/test_mute_page.py). Sent at once, the two requests could reach the Mac in either order and leave the call muted.
@MainActor
final class MuteRequestsTests: XCTestCase {
    func testAMuteAndAQuickUnmuteReachTheMacInTheOrderOfTheTaps() async throws {
        let api = SlowFirstMute.api()
        let requests = MuteRequests()
        async let mute: Void = requests.send(true, with: api)
        try await Task.sleep(nanoseconds: 50_000_000)  // the unmute is tapped while the mute is still on its way
        async let unmute: Void = requests.send(false, with: api)
        _ = try await (mute, unmute)
        XCTAssertEqual(SlowFirstMute.heard, [true, false], "the Mac hears the taps in order: the call ends unmuted")
    }

    func testBothAppsSendTheMuteThroughIt() throws {
        for name in ["MacShell.swift", "CallView.swift"] {
            let source = try Repo.source(name)
            XCTAssertFalse(source.contains("api.reading("), "\(name) sends a mute around MuteRequests")
            XCTAssertTrue(source.contains("muteRequests.send("), name)
        }
    }
}

/// A Mac that takes 0.3 s to receive the first mute request: what it hears, in the order it hears it.
final class SlowFirstMute: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var heard: [Bool] = []
    nonisolated(unsafe) static var started = 0

    static func api() -> API {
        heard = []; started = 0
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [SlowFirstMute.self]
        return API(pairing: Demo.pairing, session: URLSession(configuration: config))
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
        }
        let on = ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any])?["on"] as? Bool ?? false
        Self.started += 1
        let delay: TimeInterval = Self.started == 1 ? 0.3 : 0
        DispatchQueue.global().asyncAfter(deadline: .now() + delay) {
            Self.heard.append(on)
            let response = HTTPURLResponse(url: self.request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: Data(#"{"reading": {"on": false}, "applied": true}"#.utf8))
            self.client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {}
}
