import Foundation

/// IMA ADPCM as phone.py sends it (protocol 5), bit for bit Python's audioop: 4 bits a sample, a quarter of 16-bit PCM.
/// Each message decodes on its own: a 4-byte header (the predictor, int16 little-endian, the step index, then 0) holds
/// the coder's state before it, then two samples a byte, the first in the high nibble.
public struct ADPCM: Equatable, Sendable {
    public var predictor: Int32 = 0
    public var index: Int32 = 0

    public init() {}

    static let steps: [Int32] = [
        7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107,
        118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
        1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894,
        6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794,
        32767,
    ]
    static let moves: [Int32] = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]

    /// One message from 16-bit samples, carrying the state on to the next. An odd last sample is dropped, as audioop does.
    public mutating func encode(_ samples: [Int16]) -> Data {
        var out = Data(capacity: 4 + samples.count / 2)
        var p = Int16(clamping: predictor).littleEndian
        withUnsafeBytes(of: &p) { out.append(contentsOf: $0) }
        out.append(UInt8(index))
        out.append(0)
        var high: UInt8 = 0
        for (i, sample) in samples.prefix(samples.count & ~1).enumerated() {
            let code = step(Int32(sample))
            if i % 2 == 0 { high = code << 4 } else { out.append(high | code) }
        }
        return out
    }

    private mutating func step(_ value: Int32) -> UInt8 {
        var step = ADPCM.steps[Int(index)]
        var diff = value - predictor
        var code: Int32 = 0
        if diff < 0 { code = 8; diff = -diff }
        var vpdiff = step >> 3
        if diff >= step { code |= 4; diff -= step; vpdiff += step }
        step >>= 1
        if diff >= step { code |= 2; diff -= step; vpdiff += step }
        step >>= 1
        if diff >= step { code |= 1; vpdiff += step }
        predictor = max(-32768, min(32767, code & 8 != 0 ? predictor - vpdiff : predictor + vpdiff))
        index = max(0, min(88, index + ADPCM.moves[Int(code)]))
        return UInt8(code)
    }

    /// The samples of one message, or nil for one that is not ADPCM (too short, a step index out of range).
    public static func decode(_ message: Data) -> [Int16]? {
        guard message.count >= 5 else { return nil }
        let bytes = [UInt8](message)
        var predictor = Int32(Int16(littleEndian: Int16(bitPattern: UInt16(bytes[0]) | UInt16(bytes[1]) << 8)))
        var index = Int32(bytes[2])
        guard index <= 88 else { return nil }
        var out = [Int16]()
        out.reserveCapacity((bytes.count - 4) * 2)
        for byte in bytes[4...] {
            for code in [Int32(byte >> 4), Int32(byte & 0x0f)] {
                let step = steps[Int(index)]
                index = max(0, min(88, index + moves[Int(code)]))
                var vpdiff = step >> 3
                if code & 4 != 0 { vpdiff += step }
                if code & 2 != 0 { vpdiff += step >> 1 }
                if code & 1 != 0 { vpdiff += step >> 2 }
                predictor = max(-32768, min(32767, code & 8 != 0 ? predictor - vpdiff : predictor + vpdiff))
                out.append(Int16(predictor))
            }
        }
        return out
    }
}

extension Wire {
    /// Floats to one ADPCM message, carrying `coder` on.
    public static func adpcm(_ samples: [Float], _ coder: inout ADPCM) -> Data {
        coder.encode(samples.map { Int16(max(-1, min(1, $0)) * 32767) })
    }

    /// One ADPCM message to floats; empty for one that is not.
    public static func floats(adpcm message: Data) -> [Float] {
        (ADPCM.decode(message) ?? []).map { Float($0) / 32768 }
    }
}
