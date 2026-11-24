import Foundation
import PointeKit

/// The daemon on this Mac, for the Mac app (docs/design/macos-app.md, "Authentication"): the endpoint the app verified
/// last, asked at each request so a key that changed on disk is read again. Nil while nothing is verified: the page
/// key is never sent to a port whose listener was not just checked.
public final class LocalDaemon: Hashable, @unchecked Sendable {
    let endpoint: @Sendable () -> DaemonEndpoint?
    /// Nothing answered: whoever listens next is checked before it gets the key.
    let lost: @Sendable () -> Void

    public init(endpoint: @escaping @Sendable () -> DaemonEndpoint?, lost: @escaping @Sendable () -> Void = {}) {
        self.endpoint = endpoint
        self.lost = lost
    }

    public static func == (a: LocalDaemon, b: LocalDaemon) -> Bool { a === b }
    public func hash(into hasher: inout Hasher) { hasher.combine(ObjectIdentifier(self)) }
}

/// Where Pointe is and how this device proves itself to it. The iPhone reaches a Mac it paired with, over that Mac's
/// pinned TLS listener with the phone's key; the Mac app reaches the daemon on its own Mac, on loopback, with the
/// page's key. The routes, the models and the call's wire format are the same on both (daemon.py serves one app).
struct DaemonLink: Hashable, Sendable {
    enum Kind: Hashable, Sendable {
        case phone(Pairing)
        case local(LocalDaemon)
    }

    let kind: Kind

    init(_ pairing: Pairing) { kind = .phone(pairing) }
    init(local: LocalDaemon) { kind = .local(local) }

    var pairing: Pairing? { if case .phone(let p) = kind { p } else { nil } }
    var isLocal: Bool { pairing == nil }

    /// The other end's name until its status says one: the paired address, or this Mac.
    var host: String { pairing?.host ?? "this Mac" }
    /// Where the call is dialled, for a reason that names it.
    var place: String { pairing.map { "\($0.host):\($0.port)" } ?? "this Mac" }
    /// What a call says it is in its hello.
    var device: String { isLocal ? "Mac" : "iPhone" }

    /// False only on the Mac, while no listener is verified: nothing is sent.
    var ready: Bool {
        switch kind {
        case .phone: true
        case .local(let daemon): daemon.endpoint() != nil
        }
    }

    private var base: URL? {
        switch kind {
        case .phone(let pairing): pairing.base
        case .local(let daemon): daemon.endpoint()?.base
        }
    }

    /// A request with this device's credential on it. With no verified listener the URL is a closed loopback port and
    /// carries no key; `ready` is checked before anything is sent.
    func request(_ path: String, method: String = "GET", body: [String: Any]? = nil, query: [URLQueryItem] = [],
                 timeout: TimeInterval = 10) -> URLRequest {
        var url = (base ?? URL(fileURLWithPath: "/")).appendingPathComponent(path)
        if !query.isEmpty, var parts = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            parts.queryItems = query
            url = parts.url ?? url
        }
        var r = URLRequest(url: url)
        r.httpMethod = method
        if let body {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        r.timeoutInterval = timeout
        authorize(&r)  // last: the Mac's proof covers the method, the address and the body
        return r
    }

    private func authorize(_ r: inout URLRequest) {
        switch kind {
        case .phone(let pairing):
            r.setValue("Bearer \(pairing.key)", forHTTPHeaderField: "Authorization")
            r.setValue(API.deviceHeader, forHTTPHeaderField: "X-Pointe-Device")  // names a phone paired before per-phone keys
        case .local(let daemon):
            guard let endpoint = daemon.endpoint() else { return }
            r.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
            r.httpShouldHandleCookies = false
            endpoint.credential.apply(to: &r)
        }
    }

    /// The call's socket: `/voice/phone` for a phone, `/voice/call` on the Mac. Nil with no verified listener.
    /// `reading`: this device's reading mode, said as it calls (`?reading=1`), so the greeting is already text.
    func callRequest(reading: Bool = false) -> URLRequest? {
        switch kind {
        case .phone(let pairing):
            var r = URLRequest(url: ReadingChoice.callURL(pairing.callURL, on: reading))
            r.setValue("Bearer \(pairing.key)", forHTTPHeaderField: "Authorization")
            return r
        case .local(let daemon):
            return daemon.endpoint()?.callRequest(reading: reading)
        }
    }

    /// One session for the call and its requests. The phone's trusts exactly the paired certificate; the Mac's keeps
    /// nothing (no cookie jar, no cache) and talks to loopback only.
    func session(onOpen: @escaping @Sendable () -> Void) -> URLSession {
        switch kind {
        case .phone(let pairing):
            let delegate = PinnedDelegate(fingerprint: pairing.fingerprint)
            delegate.onOpen = onOpen
            return URLSession(configuration: .ephemeral, delegate: delegate, delegateQueue: nil)
        case .local:
            return URLSession(configuration: DaemonEndpoint.session().configuration, delegate: OpenDelegate(onOpen: onOpen), delegateQueue: nil)
        }
    }

    /// Why the phone did not get through to its Mac, in the words its screen shows. Nil on the Mac: the Mac app looks
    /// at its own Mac and says so in its own words (MacCopy).
    func problem(_ error: Error, pinRefused: Bool) -> ConnectionProblem? {
        guard let p = pairing else { return nil }
        let route = PhoneRoute(host: p.host)
        let near = route == .wifi ? LocalNetwork.contains(p.host, in: LocalNetwork.current()) : nil
        return ConnectionProblem(cause: .of(error, pinRefused: pinRefused, route: route, onMacNetwork: near), host: p.host, port: p.port)
    }

    func problem(status: Int) -> ConnectionProblem? {
        guard let p = pairing, let cause = ConnectionCause.of(status: status, pairing: false) else { return nil }
        return ConnectionProblem(cause: cause, host: p.host, port: p.port)
    }

    /// A Mac that answers, and is too old or too new for this app.
    func problem(version status: API.Status) -> ConnectionProblem? {
        guard let p = pairing,
              let cause = ConnectionCause.of(macProtocol: status.phone_protocol, oldestApp: status.oldest_phone_protocol) else { return nil }
        return ConnectionProblem(cause: cause, host: p.host, port: p.port)
    }

    /// A request found nobody there (not a refusal: the daemon answered those).
    func unreachable() {
        if case .local(let daemon) = kind { daemon.lost() }
    }
}

/// Tells the call its socket opened. The Mac's link has no certificate to pin: it is loopback.
final class OpenDelegate: NSObject, URLSessionWebSocketDelegate, @unchecked Sendable {
    private let onOpen: @Sendable () -> Void
    init(onOpen: @escaping @Sendable () -> Void) { self.onOpen = onOpen }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
        onOpen()
    }
}
