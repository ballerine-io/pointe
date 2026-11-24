import Foundation

/// When to dial again after the call's link dropped: almost at once (a blip, a network switch), then backing off to
/// 8 s, each wait with jitter so a phone does not dial in step with its own failures. A call the Mac holds for its
/// grace (calllink.py, 30 s) is reached within it however the backoff stands. `random` is 0..<1.
public struct Redial: Equatable, Sendable {
    public static let first: TimeInterval = 0.25
    public static let cap: TimeInterval = 8

    public private(set) var attempt = 0

    public init() {}

    public mutating func next(random: Double) -> TimeInterval {
        attempt += 1
        let base = min(Redial.cap, Redial.first * pow(2, Double(attempt - 1)))
        return base / 2 + base / 2 * min(1, max(0, random))
    }

    /// The Mac answered on a link: the next drop starts from the first wait again.
    public mutating func reset() { attempt = 0 }
}

/// When the bot's voice plays. What arrives while the speaker is dry waits until `target` seconds are in hand (or it
/// has waited that long), then plays straight on: a path that delivers in bursts plays smoothly. A reply that runs dry
/// in its middle is an underrun, and the next starts with more in hand; a quiet spell brings the target back down.
/// Nothing is dropped here: the Mac sends a reply at twice its pace, so audio far ahead is the reply, not a backlog
/// (the Mac drops what would play late, phone.Heartbeat.lagging). Times are the caller's clock, in seconds.
public struct JitterBuffer: Equatable, Sendable {
    public static let minTarget: TimeInterval = 0.06
    public static let maxTarget: TimeInterval = 0.4
    public static let startTarget: TimeInterval = 0.1
    /// Dry for longer than this, the next audio is a new reply, not the same one late.
    public static let sameReply: TimeInterval = 1.0
    /// No underrun for this long: the target comes down a step.
    public static let calm: TimeInterval = 20

    public private(set) var target = JitterBuffer.startTarget
    public private(set) var underruns = 0
    public private(set) var gapSecs: TimeInterval = 0
    /// Arrived and held back while the speaker is dry.
    public private(set) var held: TimeInterval = 0
    private var heldSince: TimeInterval?
    /// When what the speaker has been given will have played; 0 while dry.
    private var until: TimeInterval = 0
    private var lastUnderrun: TimeInterval = 0
    private var dryAt: TimeInterval?

    public init() {}

    /// `secs` of audio arrived at `now`: true when everything held goes to the speaker now (it then plays at once).
    public mutating func arrived(_ secs: TimeInterval, at now: TimeInterval) -> Bool {
        if until > now {
            until += secs
            return true
        }
        if until > 0 { dryAt = until }
        until = 0
        if let dry = dryAt, heldSince == nil {
            if now - dry < JitterBuffer.sameReply {
                underruns += 1
                gapSecs += now - dry
                target = min(JitterBuffer.maxTarget, target * 1.5 + 0.02)
                lastUnderrun = now
            } else if now - lastUnderrun > JitterBuffer.calm {
                target = max(JitterBuffer.minTarget, target - 0.02)
            }
            dryAt = nil
        }
        held += secs
        heldSince = heldSince ?? now
        return release(at: now)
    }

    /// While something is held: true once it has waited `target`, and it goes to the speaker.
    public mutating func tick(at now: TimeInterval) -> Bool { release(at: now) }

    /// When to tick next while something is held; nil when nothing is.
    public func due() -> TimeInterval? { heldSince.map { $0 + target } }

    private mutating func release(at now: TimeInterval) -> Bool {
        guard let since = heldSince, held >= target || now - since >= target - 1e-6 else { return false }
        until = now + held
        held = 0
        heldSince = nil
        return true
    }

    /// The bot was cut off: nothing held, nothing playing, and the silence after it is no underrun.
    public mutating func flush() {
        held = 0
        heldSince = nil
        until = 0
        dryAt = nil
    }

    /// Audio in hand that has not played yet: what the phone tells the Mac in its pongs (ahead_ms).
    public func ahead(at now: TimeInterval) -> TimeInterval { max(0, until - now) + held }
}

/// What the phone's microphone may send. The Mac's pings say how much of this socket's audio it took (heard_ms); what
/// was sent beyond that is still on the way. More than FULL seconds on the way, over the round trip, and newer chunks
/// are dropped until it is below CLEAR: a path slower than the voice never puts the user's words seconds behind them.
/// The kernel's buffers on both ends hold many seconds before a send ever waits, so the send's own completion cannot
/// tell this. A Mac before protocol 5 says nothing, and nothing is dropped.
public struct Uplink: Equatable, Sendable {
    public static let full: TimeInterval = 1.5
    public static let clear: TimeInterval = 0.5

    public private(set) var sent: TimeInterval = 0
    public private(set) var onTheWay: TimeInterval = 0
    public private(set) var dropping = false
    public private(set) var dropped: TimeInterval = 0

    public init() {}

    /// The Mac's ping: it had taken `heard` seconds of this socket's audio when it sent it.
    public mutating func heard(_ heard: TimeInterval) { onTheWay = max(0, sent - heard) }

    /// A chunk of `secs` is ready: true to send it, false to drop it. `rtt` is the link's last round trip.
    public mutating func admit(_ secs: TimeInterval, rtt: TimeInterval) -> Bool {
        dropping = onTheWay > (dropping ? Uplink.clear : Uplink.full) + rtt
        if dropping {
            dropped += secs
            return false
        }
        sent += secs
        return true
    }
}
