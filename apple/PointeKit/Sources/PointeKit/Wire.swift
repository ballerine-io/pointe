import Foundation

/// The wire format of phone.py: 16-bit little-endian mono PCM, 16 kHz up and 24 kHz down.
public enum Wire {
    public static let upRate = 16000.0
    public static let downRate = 24000.0
    public static let chunk = 320  // 20 ms up
    public static let protocolVersion = 3

    public static func pcm16(_ samples: [Float]) -> Data {
        var out = Data(capacity: samples.count * 2)
        for s in samples {
            var v = Int16(max(-1, min(1, s)) * 32767).littleEndian
            withUnsafeBytes(of: &v) { out.append(contentsOf: $0) }
        }
        return out
    }

    public static func floats(_ data: Data) -> [Float] {
        let n = data.count / 2
        return data.withUnsafeBytes { raw in
            (0..<n).map { Float(Int16(littleEndian: raw.loadUnaligned(fromByteOffset: $0 * 2, as: Int16.self))) / 32768 }
        }
    }

    /// Linear resampling: speech only, so it needs no more than this.
    public static func resample(_ x: [Float], from: Double, to: Double) -> [Float] {
        guard !x.isEmpty, from != to, from > 0, to > 0 else { return x }
        let n = Int(Double(x.count) * to / from)
        return (0..<n).map { i in
            let p = Double(i) * from / to, j = Int(p), f = Float(p - Double(j))
            let a = x[min(j, x.count - 1)], b = x[min(j + 1, x.count - 1)]
            return a + (b - a) * f
        }
    }

    /// The client's hello (protocol 3): who it is and what it can do.
    public static func hello(device: String, capabilities: [String] = ["ptt"]) -> String {
        json(["type": "hello", "protocol": protocolVersion, "device": device, "capabilities": capabilities])
    }

    public static func pong(_ id: Int) -> String { json(["type": "pong", "id": id]) }

    static func json(_ body: [String: Any]) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])) ?? Data()
        return String(data: data, encoding: .utf8) ?? ""
    }

    /// Text from the daemon on the call's socket. Unknown text is ignored, so an older client keeps working.
    public enum Control: Equatable, Sendable {
        case interrupt
        case ptt(open: Bool)
        case ping(id: Int, rttMs: Int?)

        public init?(_ text: String) {
            guard let data = text.data(using: .utf8),
                  let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
            switch message["type"] as? String {
            case "interrupt": self = .interrupt
            case "ptt":
                guard let open = message["open"] as? Bool else { return nil }
                self = .ptt(open: open)
            case "ping":
                guard let id = message["id"] as? Int else { return nil }
                self = .ping(id: id, rttMs: message["rtt_ms"] as? Int)
            default: return nil
            }
        }
    }
}
