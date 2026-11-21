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
              let host = q["host"], !host.isEmpty, host.range(of: #"^[A-Za-z0-9.\-:]+$"#, options: .regularExpression) != nil,
              let port = q["port"].flatMap(Int.init), (1...65535).contains(port),
              let fp = q["fp"]?.lowercased(), fp.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil
        else { return nil }
        return (q, host, port, fp)
    }

    init(host: String, port: Int, fingerprint: String, key: String) {
        self.host = host; self.port = port; self.fingerprint = fingerprint; self.key = key
    }

    var base: URL { URL(string: "https://\(host):\(port)")! }
    var callURL: URL { URL(string: "wss://\(host):\(port)/voice/phone")! }
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

    var pairURL: URL { URL(string: "https://\(host):\(port)/voice/phone/pair")! }

    func request(device: String, id: String) -> URLRequest {
        var r = URLRequest(url: pairURL)
        r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try? JSONSerialization.data(withJSONObject: ["code": code, "device": device, "id": id])
        r.timeoutInterval = 15
        return r
    }

    enum Failure: Error { case said(String) }

    static func problem(status: Int, text: String) -> String {
        status == 429 ? "Too many tries. Wait a minute, then scan the code again."
            : "This code has expired or was already used. On your Mac, open Pointe's Settings, then Phone, and press Connect your phone again."
    }

    static func unreachable(host: String) -> String {
        "Can't reach your Mac at \(host). Check that this phone is on the network you chose on the Mac (Tailscale, Twingate or the same Wi-Fi), then scan again."
    }

    /// The pairing, and the Mac's name. Throws `Failure.said` with words for the user.
    func redeem(device: String, id: String) async throws -> (Pairing, String) {
        let session = URLSession(configuration: .ephemeral, delegate: PinnedDelegate(fingerprint: fingerprint), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let data: Data, response: URLResponse
        do { (data, response) = try await session.data(for: request(device: device, id: id)) }
        catch { throw Failure.said(PairingInvite.unreachable(host: host)) }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200, let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let key = body["key"] as? String, key.count >= 32 else {
            throw Failure.said(PairingInvite.problem(status: status, text: String(data: data, encoding: .utf8) ?? ""))
        }
        return (Pairing(host: host, port: port, fingerprint: fingerprint, key: key), (body["mac"] as? String) ?? "your Mac")
    }
}

/// A scanned or opened `pointe://pair` link: a pairing ready to use (`pointe pair` in a terminal), or a code to trade.
enum PairingLink {
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

    static func save(_ pairing: Pairing) {
        let data = try! JSONEncoder().encode(pairing)
        forget()
        let item: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                   kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                                   kSecValueData as String: data]
        SecItemAdd(item as CFDictionary, nil)
    }

    static func forget() {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service] as CFDictionary)
    }
}

/// Trusts exactly the certificate the QR code named, and nothing else: no CA is installed or consulted.
final class PinnedDelegate: NSObject, URLSessionWebSocketDelegate, @unchecked Sendable {
    let fingerprint: String
    var onOpen: (@Sendable () -> Void)?
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
