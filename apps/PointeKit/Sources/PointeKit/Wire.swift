import Foundation

/// The wire format of phone.py: 16-bit little-endian mono PCM, 16 kHz up and 24 kHz down; or, once the Mac's `call`
/// message says so (protocol 5), IMA ADPCM at the same rates (ADPCM.swift).
public enum Wire {
    public static let upRate = 16000.0
    public static let downRate = 24000.0
    public static let chunk = 320  // 20 ms up
    public static let protocolVersion = 5

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

    /// What this client can do: push to talk (3), coming back to a call on a new link and ADPCM audio (5), and lowering
    /// its own playback while the Mac judges a voice over it ("duck").
    public static let capabilities = ["ptt", "resume", "adpcm", "duck"]

    /// The client's hello: who it is and what it can do, and the call it is coming back to, if any (protocol 5).
    /// `machines`: the machines a client that holds several can be moved to by "call kite" (ids and names only).
    public static func hello(device: String, capabilities: [String] = capabilities, resume: String? = nil,
                             machines: [[String: String]] = []) -> String {
        var body: [String: Any] = ["type": "hello", "protocol": protocolVersion, "device": device, "capabilities": capabilities]
        if let resume { body["resume"] = resume }
        if !machines.isEmpty { body["machines"] = machines }
        return json(body)
    }

    /// The answer to a ping, with the bot audio this client holds and has not played (protocol 5).
    public static func pong(_ id: Int, aheadMs: Int? = nil) -> String {
        json(["type": "pong", "id": id].merging(aheadMs.map { ["ahead_ms": $0] } ?? [:]) { a, _ in a })
    }

    /// The client is here, sent every 2 s whatever arrives (protocol 4). The daemon's pings come in order behind its
    /// audio, so on a path slower than the bot's voice they wait behind seconds of it; this goes the other way. Shaped
    /// as a pong for the newest ping already answered (0 before the first), so an older daemon counts it as one.
    public static func alive(answered id: Int, aheadMs: Int? = nil) -> String {
        json(["type": "pong", "id": id, "alive": true].merging(aheadMs.map { ["ahead_ms": $0] } ?? [:]) { a, _ in a })
    }

    /// This client's audio is ADPCM from the next message on (protocol 5).
    public static let adpcmUp = json(["type": "codec", "up": "adpcm"])

    static func json(_ body: [String: Any]) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])) ?? Data()
        return String(data: data, encoding: .utf8) ?? ""
    }

    /// Text from the daemon on the call's socket. Unknown text is ignored, so an older client keeps working.
    public enum Control: Equatable, Sendable {
        case interrupt
        case ptt(open: Bool)
        /// `heardMs`: this socket's audio the Mac had taken when it sent the ping (protocol 5).
        case ping(id: Int, rttMs: Int?, heardMs: Int? = nil)
        /// The Mac's answer to the hello (protocol 5): the token that brings this call back on a new link, whether this
        /// link resumed a call, the codec of the audio from here on, and how long the Mac holds the call for a resume.
        case call(resume: String, resumed: Bool, adpcm: Bool, grace: Double)
        /// The voice's playback level, 0 to 1: lowered the moment a voice comes over it, back to 1 once its words are
        /// judged not to be a turn (or after a cut).
        case duck(gain: Double)

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
                self = .ping(id: id, rttMs: message["rtt_ms"] as? Int, heardMs: message["heard_ms"] as? Int)
            case "call":
                guard let token = message["resume"] as? String else { return nil }
                self = .call(resume: token, resumed: message["resumed"] as? Bool ?? false,
                             adpcm: message["codec"] as? String == "adpcm", grace: message["grace"] as? Double ?? 0)
            case "duck":
                guard let gain = (message["gain"] as? NSNumber)?.doubleValue else { return nil }
                self = .duck(gain: min(1, max(0, gain)))
            default: return nil
            }
        }
    }
}
