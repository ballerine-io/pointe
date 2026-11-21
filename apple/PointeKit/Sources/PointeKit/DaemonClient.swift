import Foundation

/// A JSON value a request body may carry. `[String: Any]` is not `Sendable`; this is.
public enum JSONValue: Sendable, Equatable, ExpressibleByStringLiteral, ExpressibleByBooleanLiteral, ExpressibleByIntegerLiteral {
    case string(String), bool(Bool), int(Int), double(Double), strings([String]), null

    public init(stringLiteral value: String) { self = .string(value) }
    public init(booleanLiteral value: Bool) { self = .bool(value) }
    public init(integerLiteral value: Int) { self = .int(value) }

    var any: Any {
        switch self {
        case .string(let v): v
        case .bool(let v): v
        case .int(let v): v
        case .double(let v): v
        case .strings(let v): v
        case .null: NSNull()
        }
    }
}

/// How a request proves who it is on the loopback listener (guards.LocalAuth).
public enum Credential: Sendable, Equatable {
    /// The page's key, as the cookie the page itself holds.
    case pageKey(String)
    /// The per-daemon token scripts use.
    case token(String)

    public static let cookieName = "pointe_local"

    public func apply(to request: inout URLRequest) {
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
