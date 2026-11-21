import Foundation

/// A JSON value a request body may carry. `[String: Any]` is not `Sendable`; this is.
public enum JSONValue: Sendable, Equatable, ExpressibleByStringLiteral, ExpressibleByBooleanLiteral, ExpressibleByIntegerLiteral {
    case string(String), bool(Bool), int(Int), double(Double), null

    public init(stringLiteral value: String) { self = .string(value) }
    public init(booleanLiteral value: Bool) { self = .bool(value) }
    public init(integerLiteral value: Int) { self = .int(value) }

    var any: Any {
        switch self {
        case .string(let v): v
        case .bool(let v): v
        case .int(let v): v
        case .double(let v): v
        case .null: NSNull()
        }
    }
}

/// What a screen can ask of the daemon. The Mac app talks to it on loopback (`DaemonClient`); tests and the demo use
/// `StubDaemon`. Every rule about what an answer may do is the daemon's: these only carry the click.
public protocol DaemonAPI: Sendable {
    func status() async throws -> API.Status
    func prefs() async throws -> API.Prefs
    func setPrefs(_ changes: [String: JSONValue]) async throws
    /// A click on the exact request (`viaNotification` false), or an action on a notification, which the daemon accepts
    /// for Approve only when it could read the request out and the setting is on. 409: no longer pending.
    func answer(session: String, requestId: String, allow: Bool, viaNotification: Bool) async throws
    func switchTo(_ name: String) async throws
    func disconnect(_ name: String) async throws
    /// Typed instead of spoken. It never answers a permission prompt.
    func say(_ text: String) async throws
    func correct(turn: Int, to text: String) async throws
    func hungUp() async throws
    /// start, done, more, edit (with text), discard, send (to a session, or to = "orchestrator"), read.
    func dump(_ action: String, text: String?, session: String?, to: String?) async throws
    /// The voice lock's level. Raising it needs a voiceprint (409 with the reason).
    func voiceLock(level: String) async throws
    /// on, off or toggle: the gate, pressed from outside the call's own socket.
    func talk(_ action: String) async throws
    func dismissAttention(_ id: String) async throws
}

/// How a request proves who it is on the loopback listener (guards.LocalAuth).
public enum Credential: Sendable, Equatable {
    /// The page's key, as the cookie the page itself holds.
    case pageKey(String)
    /// The per-daemon token scripts use.
    case token(String)

    public static let cookieName = "pointe_local"

    func apply(to request: inout URLRequest) {
        switch self {
        case .pageKey(let key): request.setValue("\(Self.cookieName)=\(key)", forHTTPHeaderField: "Cookie")
        case .token(let token): request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
    }
}

/// Where the daemon listens and how to reach it. Loopback only: `init` refuses any other host.
public struct DaemonEndpoint: Sendable, Equatable {
    public let port: Int
    public let credential: Credential

    public init(port: Int, credential: Credential) {
        self.port = port
        self.credential = credential
    }

    public static let host = "127.0.0.1"
    public var base: URL { URL(string: "http://\(Self.host):\(port)") ?? URL(fileURLWithPath: "/") }
    public var callURL: URL { URL(string: "ws://\(Self.host):\(port)/voice/call") ?? base }
    /// The page, for what the app leaves to it. No key in it: the browser holds its own cookie.
    public var pageURL: URL { base.appendingPathComponent("voice") }
    public var place: String { "\(Self.host):\(port)" }

    /// A request the daemon's loopback guard accepts: a local Host (URLSession sets it from the URL), no Origin, the
    /// credential, and no cookie jar or cache behind it.
    public func request(_ path: String, method: String = "GET", body: [String: JSONValue]? = nil,
                        query: [URLQueryItem] = [], timeout: TimeInterval = 10) -> URLRequest {
        var url = base.appendingPathComponent(path)
        if !query.isEmpty, var parts = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            parts.queryItems = query
            url = parts.url ?? url
        }
        var r = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData, timeoutInterval: timeout)
        r.httpMethod = method
        r.httpShouldHandleCookies = false
        credential.apply(to: &r)
        if let body {
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
            r.httpBody = try? JSONSerialization.data(withJSONObject: body.mapValues(\.any))
        }
        return r
    }

    public var callRequest: URLRequest {
        var r = URLRequest(url: callURL)
        r.httpShouldHandleCookies = false
        credential.apply(to: &r)
        return r
    }

    /// A session that keeps nothing: no cookies, no cache, no credential store.
    public static func session() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.urlCache = nil
        config.urlCredentialStorage = nil
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }
}

/// The daemon over loopback HTTP.
public struct DaemonClient: DaemonAPI {
    public let endpoint: DaemonEndpoint
    private let session: URLSession

    public init(endpoint: DaemonEndpoint, session: URLSession = DaemonEndpoint.session()) {
        self.endpoint = endpoint
        self.session = session
    }

    /// The reply's body, or `API.Failure.status` with the daemon's own reason: JSON `detail`, else its plain text.
    private func checked(_ r: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: r)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else { throw API.Failure.status(code, Self.reason(data, code: code)) }
        return data
    }

    static func reason(_ data: Data, code: Int) -> String {
        if let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String { return detail }
        let text = String(decoding: data.prefix(300), as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty || text.hasPrefix("{") || text.hasPrefix("<") ? "HTTP \(code)" : text
    }

    private func post(_ path: String, _ body: [String: JSONValue] = [:], timeout: TimeInterval = 10) async throws {
        _ = try await checked(endpoint.request(path, method: "POST", body: body, timeout: timeout))
    }

    public func status() async throws -> API.Status {
        try JSONDecoder().decode(API.Status.self, from: try await checked(endpoint.request("voice/status", timeout: 5)))
    }

    public func prefs() async throws -> API.Prefs {
        try JSONDecoder().decode(API.Prefs.self, from: try await checked(endpoint.request("voice/prefs")))
    }

    public func setPrefs(_ changes: [String: JSONValue]) async throws { try await post("voice/prefs", changes) }

    public func answer(session: String, requestId: String, allow: Bool, viaNotification: Bool) async throws {
        var body: [String: JSONValue] = ["session": .string(session), "request_id": .string(requestId),
                                         "decision": allow ? "allow" : "deny"]
        if viaNotification { body["via"] = "notification" }
        try await post("voice/approve", body)
    }

    public func switchTo(_ name: String) async throws { try await post("voice/switch", ["name": .string(name)]) }
    public func disconnect(_ name: String) async throws { try await post("voice/disconnect", ["name": .string(name)]) }
    public func say(_ text: String) async throws { try await post("voice/say", ["text": .string(text)]) }
    public func correct(turn: Int, to text: String) async throws { try await post("voice/correct", ["id": .int(turn), "text": .string(text)]) }
    public func hungUp() async throws { try await post("voice/hung-up") }

    public func dump(_ action: String, text: String?, session: String?, to: String?) async throws {
        var body: [String: JSONValue] = ["action": .string(action)]
        if let text { body["text"] = .string(text) }
        if let session { body["session"] = .string(session) }
        if let to { body["to"] = .string(to) }
        try await post("voice/dump", body, timeout: 30)  // done waits for the reading model
    }

    public func voiceLock(level: String) async throws { try await post("voice/voiceprint", ["action": "level", "level": .string(level)]) }
    public func talk(_ action: String) async throws { try await post("voice/talk", ["action": .string(action)]) }
    public func dismissAttention(_ id: String) async throws { try await post("voice/attention", ["id": .string(id)]) }
}
