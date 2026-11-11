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
        guard let url = URLComponents(string: link.trimmingCharacters(in: .whitespacesAndNewlines)),
              url.scheme == "pointe", url.host == "pair" else { return nil }
        var q: [String: String] = [:]
        for item in url.queryItems ?? [] { q[item.name] = item.value }
        guard q["v"].flatMap(Int.init) == Pairing.supportedVersion,
              let host = q["host"], !host.isEmpty, host.range(of: #"^[A-Za-z0-9.\-:]+$"#, options: .regularExpression) != nil,
              let port = q["port"].flatMap(Int.init), (1...65535).contains(port),
              let fp = q["fp"]?.lowercased(), fp.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
              let key = q["key"], key.count >= 32 else { return nil }
        self.init(host: host, port: port, fingerprint: fp, key: key)
    }

    init(host: String, port: Int, fingerprint: String, key: String) {
        self.host = host; self.port = port; self.fingerprint = fingerprint; self.key = key
    }

    var base: URL { URL(string: "https://\(host):\(port)")! }
    var callURL: URL { URL(string: "wss://\(host):\(port)/voice/phone")! }
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
