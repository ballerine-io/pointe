import CryptoKit
import Foundation
import Security

/// What `pointe pair` puts in its QR code: where the Mac listens, the certificate to trust, and the phone's key.
struct Pairing: Codable, Hashable {
    let host: String
    let port: Int
    let fingerprint: String  // SHA-256 of the listener's certificate, lowercase hex
    let key: String

    static let supportedVersion = 1

    /// `pointe://pair?v=1&host=...&port=7443&fp=...&key=...`; nil for anything else.
    init?(link: String) {
        guard let (q, host, port, fp) = Pairing.place(link, version: Pairing.supportedVersion),
              let key = q["key"], key.count >= 32 else { return nil }
        self.init(host: host, port: port, fingerprint: fp, key: key)
    }

    /// A `pointe://pair` link of this version: its fields, and the Mac's host, port and certificate fingerprint.
    static func place(_ link: String, version: Int) -> ([String: String], String, Int, String)? {
        guard let url = URLComponents(string: link.trimmingCharacters(in: .whitespacesAndNewlines)),
              url.scheme == "pointe", url.host == "pair" else { return nil }
        var q: [String: String] = [:]
        for item in url.queryItems ?? [] { q[item.name] = item.value }
        guard q["v"].flatMap(Int.init) == version,
              let host = q["host"], Pairing.isHost(host),
              let port = q["port"].flatMap(Int.init), (1...65535).contains(port),
              let fp = q["fp"]?.lowercased(), fp.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil
        else { return nil }
        return (q, host, port, fp)
    }

    /// A name or an IPv4 address, nothing else: a colon makes no URL, and a pairing that makes none would crash the app
    /// at every launch from the Keychain, which outlives a reinstall.
    static func isHost(_ host: String) -> Bool {
        host.range(of: #"^[A-Za-z0-9.\-]{1,253}$"#, options: .regularExpression) != nil
            && URL(string: "https://\(host):1") != nil
    }

    init(host: String, port: Int, fingerprint: String, key: String) {
        self.host = host; self.port = port; self.fingerprint = fingerprint; self.key = key
    }

    private enum CodingKeys: String, CodingKey { case host, port, fingerprint, key }

    /// From the Keychain: a pairing an older version saved with a host that makes no URL is not used.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let host = try c.decode(String.self, forKey: .host)
        guard Pairing.isHost(host) else { throw DecodingError.dataCorruptedError(forKey: .host, in: c, debugDescription: "not a host") }
        self.init(host: host, port: try c.decode(Int.self, forKey: .port), fingerprint: try c.decode(String.self, forKey: .fingerprint),
                  key: try c.decode(String.self, forKey: .key))
    }

    // Never forced: a URL that cannot be made goes nowhere instead of crashing the app.
    var base: URL { URL(string: "https://\(host):\(port)") ?? URL(fileURLWithPath: "/") }
    var callURL: URL { URL(string: "wss://\(host):\(port)/voice/phone") ?? URL(fileURLWithPath: "/") }
}

/// What the page's QR holds (Settings → Phone): where the Mac listens, its certificate, and a one-time code. No lasting
/// secret: `redeem` trades the code for the phone key over a connection pinned to that certificate.
struct PairingInvite: Hashable {
    let host: String
    let port: Int
    let fingerprint: String
    let code: String

    static let version = 2

    /// `pointe://pair?v=2&host=...&port=7443&fp=...&code=ABCD-EFGH`; nil for anything else.
    init?(link: String) {
        guard let (q, host, port, fp) = Pairing.place(link, version: PairingInvite.version),
              let code = q["code"], code.range(of: "^[0-9A-Za-z]{4}-?[0-9A-Za-z]{4}$", options: .regularExpression) != nil
        else { return nil }
        self.init(host: host, port: port, fingerprint: fp, code: code)
    }

    init(host: String, port: Int, fingerprint: String, code: String) {
        self.host = host; self.port = port; self.fingerprint = fingerprint; self.code = code
    }

    var pairURL: URL { URL(string: "https://\(host):\(port)/voice/phone/pair") ?? URL(fileURLWithPath: "/") }

    func request(device: String, id: String) -> URLRequest {
        var r = URLRequest(url: pairURL)
        r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try? JSONSerialization.data(withJSONObject: ["code": code, "device": device, "id": id])
        r.timeoutInterval = 15
        return r
    }

    /// The pairing, and the Mac's name. Throws a `ConnectionProblem`: why it failed, read from what the phone saw.
    func redeem(device: String, id: String) async throws -> (Pairing, String) {
        let pin = PinnedDelegate(fingerprint: fingerprint)
        let session = URLSession(configuration: .ephemeral, delegate: pin, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let data: Data, response: URLResponse
        do { (data, response) = try await session.data(for: request(device: device, id: id)) }
        catch {
            let route = PhoneRoute(host: host)
            let near = route == .wifi ? LocalNetwork.contains(host, in: LocalNetwork.current()) : nil
            throw ConnectionProblem(cause: .of(error, pinRefused: pin.refused, route: route, onMacNetwork: near), host: host, port: port)
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200, let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let key = body["key"] as? String, key.count >= 32 else {
            throw ConnectionProblem(cause: ConnectionCause.of(status: status, pairing: true) ?? .other("HTTP \(status)"), host: host, port: port)
        }
        return (Pairing(host: host, port: port, fingerprint: fingerprint, key: key), (body["mac"] as? String) ?? "your Mac")
    }
}

/// A scanned or pasted `pointe://pair` link: a pairing ready to use (`pointe pair` in a terminal), or a code to trade.
enum PairingLink: Equatable {
    case ready(Pairing)
    case invite(PairingInvite)

    init?(_ link: String) {
        if let p = Pairing(link: link) { self = .ready(p) }
        else if let i = PairingInvite(link: link) { self = .invite(i) }
        else { return nil }
    }
}

/// The pairing lives in the Keychain, this device only: it opens a microphone into the user's sessions.
enum PairingStore {
    private static let service = "io.ballerine.pointe.pairing"

    static func load() -> Pairing? {
        var out: AnyObject?
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                    kSecReturnData as String: true]
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return try? JSONDecoder().decode(Pairing.self, from: data)
    }

    /// Written over the old item, never deleted first: a write that fails leaves the old pairing in place.
    static func save(_ pairing: Pairing) {
        guard let data = try? JSONEncoder().encode(pairing) else { return }
        let item: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        let value: [String: Any] = [kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                                    kSecValueData as String: data]
        if SecItemUpdate(item as CFDictionary, value as CFDictionary) == errSecItemNotFound {
            SecItemAdd(item.merging(value) { $1 } as CFDictionary, nil)
        }
    }

    static func forget() {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service] as CFDictionary)
    }
}

/// Trusts exactly the certificate the QR code named, and nothing else: no CA is installed or consulted.
final class PinnedDelegate: NSObject, URLSessionWebSocketDelegate, @unchecked Sendable {
    let fingerprint: String
    var onOpen: (@Sendable () -> Void)?
    private let lock = NSLock()
    private var offeredOther = false
    /// A certificate other than the paired one was offered and refused: the system reports only "cancelled".
    var refused: Bool { lock.withLock { offeredOther } }
    init(fingerprint: String) { self.fingerprint = fingerprint }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
        onOpen?()
    }

    static func fingerprint(of certificate: SecCertificate) -> String {
        SHA256.hash(data: SecCertificateCopyData(certificate) as Data).map { String(format: "%02x", $0) }.joined()
    }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              let leaf = (SecTrustCopyCertificateChain(trust) as? [SecCertificate])?.first,
              PinnedDelegate.fingerprint(of: leaf) == fingerprint else {
            if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust { lock.withLock { offeredOther = true } }
            print("pointe: certificate does not match the pairing")
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        // App Transport Security still checks the chain for a real host name: anchor it to this one pinned certificate.
        SecTrustSetAnchorCertificates(trust, [leaf] as CFArray)
        SecTrustSetAnchorCertificatesOnly(trust, true)
        var error: CFError?
        guard SecTrustEvaluateWithError(trust, &error) else {
            print("pointe: pinned certificate still refused: \(String(describing: error))")
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        completionHandler(.useCredential, URLCredential(trust: trust))
    }
}
