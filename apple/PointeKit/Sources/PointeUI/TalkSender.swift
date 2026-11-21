import Foundation

/// What of the microphone goes to the Mac, in the wire's chunks. Times are seconds on the monotonic clock
/// (`ProcessInfo.systemUptime`, the same as audio host time).
///
/// Push to talk closed: nothing is sent, and only the last `keep` seconds are held, in memory. A press sends at once the
/// audio from its touch-down on (`margin` earlier, for the audio clock's slack), then the live audio: the words begun with
/// the touch are not lost to the time the touch took to reach the gate, nor to the wait for the microphone's next buffer.
/// The Mac's gate opens on the press message, which goes first on the same socket, so these chunks pass it.
struct TalkSender {
    /// The longest a press can reach back to its touch-down: a touch handled later than this loses its first words.
    static let keep: TimeInterval = 1.5  // memory only: nothing from before the touch (less the margin) is ever sent
    /// Taken before the touch-down: a buffer's capture time is known only to within about this.
    static let margin: TimeInterval = 0.1

    private var pending: [Float] = []  // sending: less than a chunk, waiting for the rest
    private var held: [Float] = []     // closed: the last `keep` seconds
    private var heldEnd: TimeInterval = 0  // when the last held sample was captured

    /// New microphone samples, captured up to `end`. The chunks to send now: none while closed.
    mutating func capture(_ samples: [Float], end: TimeInterval, sending: Bool) -> [[Float]] {
        guard sending else {
            pending.removeAll()
            held += samples
            if held.count > Self.capacity { held.removeFirst(held.count - Self.capacity) }
            heldEnd = end
            return []
        }
        held.removeAll()
        pending += samples
        return chunks()
    }

    /// A press opened the gate. The held audio from `touched` (less the margin) on, as chunks to send right after the
    /// press message; what is left of a chunk goes out with the next live samples. `from`: when the first of it was
    /// captured, nil when nothing was held.
    mutating func opened(touched: TimeInterval) -> (chunks: [[Float]], from: TimeInterval?) {
        let back = min(held.count, max(0, Int(((heldEnd - touched + Self.margin) * Wire.upRate).rounded(.up))))
        let from = back > 0 ? heldEnd - Double(back) / Wire.upRate : nil
        pending = Array(held.suffix(back)) + pending
        held.removeAll()
        return (chunks(), from)
    }

    /// A call ended or a link dropped: nothing carries over.
    mutating func reset() {
        pending.removeAll()
        held.removeAll()
        heldEnd = 0
    }

    private static let capacity = Int(keep * Wire.upRate)

    private mutating func chunks() -> [[Float]] {
        var out: [[Float]] = []
        while pending.count >= Wire.chunk {
            out.append(Array(pending.prefix(Wire.chunk)))
            pending.removeFirst(Wire.chunk)
        }
        return out
    }
}
