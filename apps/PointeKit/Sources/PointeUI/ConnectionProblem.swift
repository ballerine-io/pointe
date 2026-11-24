import Foundation
import PointeKit
#if canImport(Darwin)
import Darwin
#endif

/// How the phone reaches its Mac, read from the paired address the way `pointe pair` writes it (phone_check.py
/// `route_kind`): an IPv4 address is the Mac's on its Wi-Fi, unless it is in Tailscale's 100.64.0.0/10; a `.ts.net` name
/// is Tailscale's; any other name is one the owner routes (Twingate, a VPN, a tunnel).
enum PhoneRoute: String, Equatable, Sendable {
    case wifi, tailscale, name

    init(host: String) {
        let h = host.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: ". "))
        if let ip = IPv4(h) { self = IPv4.tailscale.contains(ip) ? .tailscale : .wifi }
        else { self = h.hasSuffix(".ts.net") ? .tailscale : .name }
    }

    var label: String {
        switch self {
        case .wifi: RouteCopy.wifiLabel
        case .tailscale: RouteCopy.tailscaleLabel
        case .name: RouteCopy.nameLabel
        }
    }

    var hint: String {
        switch self {
        case .wifi: RouteCopy.wifiHint
        case .tailscale: RouteCopy.tailscaleHint
        case .name: RouteCopy.nameHint
        }
    }

    var help: URL {
        let link: String = switch self {
        case .wifi: RouteCopy.wifiHelp
        case .tailscale: RouteCopy.tailscaleHelp
        case .name: RouteCopy.nameHelp
        }
        return URL(string: link)!
    }
}

/// The words for each route, the Mac's own (phone_check.py LABELS, HINTS and HELP): tests/test_phone_check.py holds the
/// two to the same text, so the page, the Mac app, `pointe doctor` and the phone say one thing.
enum RouteCopy {
    static let wifiLabel = "Wi-Fi"
    static let tailscaleLabel = "Tailscale"
    static let nameLabel = "a name you route yourself (Twingate, a VPN or a tunnel)"
    static let nameHint = "Is your VPN app on, on both devices? Is the connector on the Mac running? With Docker or Colima it stops after a restart: run `colima start`."
    static let tailscaleHint = "Is Tailscale connected on both?"
    static let wifiHint = "Both must be on the same network; it stops working when either one moves."
    static let wifiHelp = "https://github.com/ballerine-io/pointe/blob/main/docs/phone/wifi.md#when-it-stops-working"
    static let tailscaleHelp = "https://github.com/ballerine-io/pointe/blob/main/docs/phone/tailscale.md#when-it-stops-working"
    static let nameHelp = "https://github.com/ballerine-io/pointe/blob/main/docs/phone/twingate.md#when-it-stops-working"
}

/// Why the phone did not get through, from what it can see: the system's error, the HTTP answer, the certificate the
/// pinned connection was offered, and whether this phone is on the Mac's Wi-Fi.
enum ConnectionCause: Equatable, Sendable {
    case nameNotFound, timedOut, refused, offline, wrongNetwork
    case certificateChanged, notPaired
    case macTooOld, appTooOld
    case codeSpent, tooManyTries
    case other(String)

    /// A request that got no HTTP answer. `pinRefused`: the pinned delegate was offered a certificate other than the
    /// paired one. `onMacNetwork`: whether a Wi-Fi route's address is on one of this phone's networks (nil: not known).
    static func of(_ error: Error, pinRefused: Bool = false, route: PhoneRoute, onMacNetwork: Bool? = nil) -> ConnectionCause {
        if pinRefused { return .certificateChanged }
        let ns = error as NSError
        let code = (error as? URLError)?.code ?? (ns.domain == NSURLErrorDomain ? URLError.Code(rawValue: ns.code) : nil)
        switch code {
        case .serverCertificateUntrusted?, .serverCertificateHasBadDate?, .serverCertificateHasUnknownRoot?,
             .serverCertificateNotYetValid?, .secureConnectionFailed?:
            return .certificateChanged
        case .notConnectedToInternet?, .dataNotAllowed?, .internationalRoamingOff?:
            return .offline
        default: break
        }
        // Off the Mac's Wi-Fi, a timeout or a refusal says nothing about the Mac: the phone is looking on another network.
        if route == .wifi, onMacNetwork == false { return .wrongNetwork }
        switch code {
        case .cannotFindHost?, .dnsLookupFailed?: return .nameNotFound
        case .timedOut?, .networkConnectionLost?: return .timedOut
        case .cannotConnectToHost?: return .refused
        default: return .other(ns.localizedDescription)
        }
    }

    /// An HTTP answer that is a refusal: nil for one that is not about the connection. `pairing`: the answer to the
    /// one-time code (POST /voice/phone/pair), where 403 is a spent code and 404 a Mac whose Pointe has no such route.
    static func of(status: Int, pairing: Bool) -> ConnectionCause? {
        switch status {
        case 401, 403: pairing ? .codeSpent : .notPaired
        case 404: pairing ? .macTooOld : nil
        case 429: .tooManyTries
        default: nil
        }
    }

    /// The Mac's status names the call protocol it speaks and the oldest app it still serves (daemon.py `phone`):
    /// either side can be too old for the other. A Mac that names neither is from before this check: no verdict.
    static func of(macProtocol: Int?, oldestApp: Int?) -> ConnectionCause? {
        if let oldestApp, oldestApp > PhoneProtocol.app { return .appTooOld }
        if let macProtocol, macProtocol < PhoneProtocol.oldestMac { return .macTooOld }
        return nil
    }
}

/// The call protocol this app speaks (its hello), and the oldest Mac protocol it still works with.
enum PhoneProtocol {
    static let app = Wire.protocolVersion
    static let oldestMac = 4
}

/// What the phone says when it can't reach its Mac: a plain cause, where it looked and over what, the fix for that
/// route, and the way forward. It stays on screen until the person acts on it (PairingFlow, CallView).
struct ConnectionProblem: Equatable, Sendable, Error {
    enum Action: Equatable, Sendable { case tryAgain, pairAgain, howToFix }

    let cause: ConnectionCause
    let host: String
    let port: Int
    var route: PhoneRoute { PhoneRoute(host: host) }

    var title: String {
        switch cause {
        case .nameNotFound: ProblemCopy.nameNotFoundTitle
        case .timedOut: ProblemCopy.timedOutTitle
        case .refused: ProblemCopy.refusedTitle
        case .offline: ProblemCopy.offlineTitle
        case .wrongNetwork: ProblemCopy.wrongNetworkTitle
        case .certificateChanged: ProblemCopy.certificateTitle
        case .notPaired: ProblemCopy.notPairedTitle
        case .macTooOld: ProblemCopy.macTooOldTitle
        case .appTooOld: ProblemCopy.appTooOldTitle
        case .codeSpent: ProblemCopy.codeSpentTitle
        case .tooManyTries: ProblemCopy.tooManyTriesTitle
        case .other: ProblemCopy.otherTitle
        }
    }

    /// The cause in one sentence, naming the address.
    var detail: String {
        switch cause {
        case .nameNotFound: ProblemCopy.nameNotFound(host)
        case .timedOut: ProblemCopy.timedOut(place)
        case .refused: ProblemCopy.refused(host, port)
        case .offline: ProblemCopy.offline
        case .wrongNetwork: ProblemCopy.wrongNetwork(host)
        case .certificateChanged: ProblemCopy.certificate(host)
        case .notPaired: ProblemCopy.notPaired
        case .macTooOld: ProblemCopy.macTooOld
        case .appTooOld: ProblemCopy.appTooOld
        case .codeSpent: ProblemCopy.codeSpent
        case .tooManyTries: ProblemCopy.tooManyTries
        case .other(let why): ProblemCopy.other(place, why)
        }
    }

    /// What to do: the route's own hint for a road that did not get through, the one fix for the rest.
    var fix: String {
        switch cause {
        case .nameNotFound, .timedOut, .wrongNetwork, .other: route.hint
        case .refused: ProblemCopy.startPointe
        case .offline: ProblemCopy.goOnline
        case .certificateChanged, .notPaired, .codeSpent: ProblemCopy.pairAgainHow
        case .macTooOld: ProblemCopy.updatePlugin
        case .appTooOld: ProblemCopy.updateApp
        case .tooManyTries: ProblemCopy.waitAMinute
        }
    }

    var place: String { "\(host):\(port)" }

    /// "Tried pointe.example.internal:7443 · a name you route yourself (…)".
    var tried: String { ProblemCopy.tried(place, route.label) }

    /// The first is the one to press. A Mac that refuses this phone, or a certificate that changed, needs a new
    /// pairing: trying again cannot help.
    var actions: [Action] {
        switch cause {
        case .certificateChanged, .notPaired, .codeSpent: [.pairAgain, .howToFix]
        default: [.tryAgain, .pairAgain, .howToFix]
        }
    }
}

/// The words of `ConnectionProblem`, one place for the iPhone and the Mac app.
enum ProblemCopy {
    static let tryAgain = "Try again"
    static let pairAgain = "Pair again"
    static let howToFix = "How to fix"
    static let readGuide = "Read the guide"
    static let close = "Close"
    static let nameNotFoundTitle = "Can't find your Mac"
    static let timedOutTitle = "Your Mac did not answer"
    static let refusedTitle = "Pointe is not answering"
    static let offlineTitle = "This phone is offline"
    static let wrongNetworkTitle = "Not on your Mac's Wi-Fi"
    static let certificateTitle = "Your Mac's certificate changed"
    static let notPairedTitle = "Not paired"
    static let macTooOldTitle = "Pointe on your Mac is too old"
    static let appTooOldTitle = "This app is too old"
    static let codeSpentTitle = "The code was used"
    static let tooManyTriesTitle = "Too many tries"
    static let otherTitle = "Can't reach your Mac"
    static let offline = "This phone has no network connection."
    static let notPaired = "This phone is no longer paired with your Mac."
    static let macTooOld = "The Pointe plugin on your Mac is older than this app."
    static let appTooOld = "This app is older than the Pointe plugin on your Mac."
    static let codeSpent = "This code has expired or was already used."
    static let tooManyTries = "Your Mac refused this phone after too many wrong codes."
    static let startPointe = "On the Mac, start Pointe: /pointe:voice in a Claude Code session. Then try again."
    static let goOnline = "Turn off Airplane Mode or join a network, then try again."
    static let pairAgainHow = "Pair again: on the Mac, Settings → Phone → Connect your phone, then scan the new code."
    static let updatePlugin = "Update the plugin on the Mac: claude plugin update pointe@pointe, then /pointe:stop and /pointe:voice."
    static let updateApp = "Update the app: on the Mac, run pointe apps ios."
    static let waitAMinute = "Wait a minute, then scan the code again."
    static func nameNotFound(_ host: String) -> String { "This phone can't look up \(host)." }
    static func timedOut(_ place: String) -> String { "Nothing answered at \(place)." }
    static func refused(_ host: String, _ port: Int) -> String { "\(host) answered, but nothing listens on port \(port)." }
    static func wrongNetwork(_ host: String) -> String { "Your Mac is at \(host) on its Wi-Fi, and this phone is not on that network." }
    static func certificate(_ host: String) -> String { "\(host) answered with a certificate this phone was not paired with." }
    static func other(_ place: String, _ why: String) -> String { "Nothing got through to \(place): \(why)" }
    static func tried(_ place: String, _ route: String) -> String { "Tried \(place) · \(route)" }
    static func stillPaired(_ host: String) -> String { "Still paired with \(host)." }
}

/// The phone's own IPv4 networks, for a Wi-Fi route: is the Mac's address on one of them?
enum LocalNetwork {
    struct Interface: Equatable { let address: IPv4; let netmask: IPv4 }

    /// Nil when `host` is not an IPv4 address. A loopback address is this device: on its network.
    static func contains(_ host: String, in interfaces: [Interface]) -> Bool? {
        guard let ip = IPv4(host) else { return nil }
        if ip.value >> 24 == 127 { return true }
        return interfaces.contains { ($0.address.value & $0.netmask.value) == (ip.value & $0.netmask.value) && $0.netmask.value != 0 }
    }

    /// The interfaces that are up, loopback and Tailscale's own excepted.
    static func current() -> [Interface] {
        var out: [Interface] = []
        var first: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&first) == 0 else { return out }
        defer { freeifaddrs(first) }
        var each = first
        while let i = each?.pointee {
            defer { each = i.ifa_next }
            guard let addr = i.ifa_addr, addr.pointee.sa_family == UInt8(AF_INET), let mask = i.ifa_netmask,
                  (Int32(i.ifa_flags) & IFF_UP) != 0, (Int32(i.ifa_flags) & IFF_LOOPBACK) == 0 else { continue }
            let a = addr.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { UInt32(bigEndian: $0.pointee.sin_addr.s_addr) }
            let m = mask.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { UInt32(bigEndian: $0.pointee.sin_addr.s_addr) }
            let ip = IPv4(value: a)
            if IPv4.tailscale.contains(ip) { continue }
            out.append(Interface(address: ip, netmask: IPv4(value: m)))
        }
        return out
    }
}

struct IPv4: Equatable, Sendable {
    let value: UInt32

    init(value: UInt32) { self.value = value }

    init?(_ text: String) {
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 4 else { return nil }
        var v: UInt32 = 0
        for p in parts {
            guard !p.isEmpty, p.count <= 3, p.allSatisfy(\.isASCII), let n = UInt8(p) else { return nil }
            v = v << 8 | UInt32(n)
        }
        value = v
    }

    struct Block { let base: UInt32; let bits: UInt32
        func contains(_ ip: IPv4) -> Bool { bits == 0 || ip.value >> (32 - bits) == base >> (32 - bits) }
    }
    /// Tailscale's addresses (CGNAT, 100.64.0.0/10).
    static let tailscale = Block(base: 0x6440_0000, bits: 10)
}
