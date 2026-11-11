import Foundation

/// The wire format of phone.py, version 1: 16-bit little-endian mono PCM, 16 kHz up and 24 kHz down.
enum Wire {
    static let upRate = 16000.0
    static let downRate = 24000.0
    static let chunk = 320  // 20 ms up

    static func pcm16(_ samples: [Float]) -> Data {
        var out = Data(capacity: samples.count * 2)
        for s in samples {
            var v = Int16(max(-1, min(1, s)) * 32767).littleEndian
            withUnsafeBytes(of: &v) { out.append(contentsOf: $0) }
        }
        return out
    }

    static func floats(_ data: Data) -> [Float] {
        let n = data.count / 2
        return data.withUnsafeBytes { raw in
            (0..<n).map { Float(Int16(littleEndian: raw.loadUnaligned(fromByteOffset: $0 * 2, as: Int16.self))) / 32768 }
        }
    }

    /// Linear resampling: speech only, so it needs no more than this.
    static func resample(_ x: [Float], from: Double, to: Double) -> [Float] {
        guard !x.isEmpty, from != to else { return x }
        let n = Int(Double(x.count) * to / from)
        return (0..<n).map { i in
            let p = Double(i) * from / to, j = Int(p), f = Float(p - Double(j))
            let a = x[min(j, x.count - 1)], b = x[min(j + 1, x.count - 1)]
            return a + (b - a) * f
        }
    }
}
