import CryptoKit
import Foundation
import Security

/// What `pointe pair` puts in its QR code: where the Mac listens, the certificate to trust, and the phone's key.
struct Pairing: Codable, Hashable {
    let host: String
    let port: Int
    let fingerprint: String  // SHA-256 of the listener's certificate, lowercase hex
    let key: String
    /// The machine's own lasting id, from its pairing answer; nil from a line with a lasting key, or an older machine.
    var id: String? = nil
    /// The machine's name, as it calls itself.
    var name: String? = nil
    /// How this phone reaches it: `tailscale`, `wifi` or `host` (a name the user routes, such as Twingate's).
    var via: String? = nil

    static let supportedVersion = 1

    /// `pointe://pair?v=1&host=...&port=7443&fp=...&key=...`; nil for anything else.
    init?(link: String) {
        guard let (q, host, port, fp) = Pairing.place(link, version: Pairing.supportedVersion),
              let key = q["key"], key.count >= 32 else { return nil }
        self.init(host: host, port: port, fingerprint: fp, key: key, via: Pairing.route(q["via"]))
    }

    /// A route kind a line may name; anything else is not shown.
    static func route(_ raw: String?) -> String? { raw.flatMap { ["tailscale", "wifi", "host"].contains($0) ? $0 : nil } }

    /// Where this machine is kept among several (docs/design/multi-machine-clients.md, 1.1): its own id, else its
    /// certificate. The same machine paired again lands on the same entry.
    var storeKey: String { id.map { "id:\($0)" } ?? "fp:\(fingerprint)" }

    /// What the list calls it until its status names it.
    var label: String { name ?? host }

    /// What a call is made with. Learning the machine's id or name changes the pairing, never the call.
    var connection: String { "\(host):\(port)|\(fingerprint)|\(key)" }

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

    init(host: String, port: Int, fingerprint: String, key: String, id: String? = nil, name: String? = nil, via: String? = nil) {
        self.host = host; self.port = port; self.fingerprint = fingerprint; self.key = key
        self.id = id; self.name = name; self.via = via
    }

    private enum CodingKeys: String, CodingKey { case host, port, fingerprint, key, id, name, via }

    /// From the Keychain: a pairing an older version saved with a host that makes no URL is not used. One saved before
    /// several machines has no id, name or route.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let host = try c.decode(String.self, forKey: .host)
        guard Pairing.isHost(host) else { throw DecodingError.dataCorruptedError(forKey: .host, in: c, debugDescription: "not a host") }
        self.init(host: host, port: try c.decode(Int.self, forKey: .port), fingerprint: try c.decode(String.self, forKey: .fingerprint),
                  key: try c.decode(String.self, forKey: .key), id: try c.decodeIfPresent(String.self, forKey: .id),
                  name: try c.decodeIfPresent(String.self, forKey: .name), via: try c.decodeIfPresent(String.self, forKey: .via))
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
    var via: String? = nil

    static let version = 2

    /// `pointe://pair?v=2&host=...&port=7443&fp=...&code=ABCD-EFGH`; nil for anything else.
    init?(link: String) {
        guard let (q, host, port, fp) = Pairing.place(link, version: PairingInvite.version),
              let code = q["code"], code.range(of: "^[0-9A-Za-z]{4}-?[0-9A-Za-z]{4}$", options: .regularExpression) != nil
        else { return nil }
        self.init(host: host, port: port, fingerprint: fp, code: code, via: Pairing.route(q["via"]))
    }

    init(host: String, port: Int, fingerprint: String, code: String, via: String? = nil) {
        self.host = host; self.port = port; self.fingerprint = fingerprint; self.code = code; self.via = via
    }

    /// The pairing from the machine's answer: its key, and its id and name when it sends them.
    func pairing(from body: [String: Any]) -> Pairing? {
        guard let key = body["key"] as? String, key.count >= 32 else { return nil }
        let id = (body["id"] as? String).flatMap { $0.range(of: "^[\\w-]{1,64}$", options: .regularExpression) != nil ? $0 : nil }
        let name = (body["name"] as? String ?? body["mac"] as? String).map { String($0.prefix(60)) }
        return Pairing(host: host, port: port, fingerprint: fingerprint, key: key, id: id, name: name, via: via)
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
              let pairing = pairing(from: body) else {
            throw ConnectionProblem(cause: ConnectionCause.of(status: status, pairing: true) ?? .other("HTTP \(status)"), host: host, port: port)
        }
        return (pairing, (body["mac"] as? String) ?? "your Mac")
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

/// The pairings live in the Keychain, this device only: each opens a microphone into somebody's sessions. One item per
/// machine, its account the machine's `storeKey` (PairedMachines.swift); the item a version before several machines
/// saved has no account, and is replaced the first time its machine is saved again.
enum PairingStore {
    static let service = "io.ballerine.pointe.pairing"

    /// The current machine: the one a call goes to.
    static func load() -> Pairing? { KeychainPairing().load() }
    /// This machine, in place of every other: what pairing did before a phone held several.
    static func save(_ pairing: Pairing) { KeychainPairing().save(pairing) }
    /// Every pairing.
    static func forget() { KeychainPairing().forget() }
    /// Every machine, in the list's order.
    static func all() -> [Pairing] { KeychainPairing().all() }
}

/// The Keychain under `PairedMachines`: generic passwords of one service, found again by their persistent reference.
struct KeychainVault: PairingVault {
    /// Each item by its attributes and persistent reference, then its data one by one: the Keychain refuses data for
    /// several items in one query (errSecParam), which read as no pairing at all. If listing fails, the one item an
    /// older version kept is read the old way, so a phone never loses its pairing to this.
    func rows() -> [VaultRow] {
        var out: AnyObject?
        let all: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: PairingStore.service,
                                  kSecMatchLimit as String: kSecMatchLimitAll, kSecReturnAttributes as String: true,
                                  kSecReturnPersistentRef as String: true]
        if SecItemCopyMatching(all as CFDictionary, &out) == errSecSuccess, let found = out as? [[String: Any]] {
            let rows = found.compactMap { row -> VaultRow? in
                guard let ref = row[kSecValuePersistentRef as String] as? Data, let p = Self.pairing(ref: ref) else { return nil }
                return VaultRow(account: row[kSecAttrAccount as String] as? String ?? "", pairing: p, ref: ref)
            }
            if !rows.isEmpty { return rows }
        }
        var one: AnyObject?
        let first: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: PairingStore.service,
                                    kSecReturnAttributes as String: true, kSecReturnData as String: true,
                                    kSecReturnPersistentRef as String: true]
        guard SecItemCopyMatching(first as CFDictionary, &one) == errSecSuccess, let row = one as? [String: Any],
              let data = row[kSecValueData as String] as? Data, let p = try? JSONDecoder().decode(Pairing.self, from: data) else { return [] }
        return [VaultRow(account: row[kSecAttrAccount as String] as? String ?? "", pairing: p, ref: row[kSecValuePersistentRef as String] as? Data)]
    }

    private static func pairing(ref: Data) -> Pairing? {
        var out: AnyObject?
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecValuePersistentRef as String: ref,
                                    kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return try? JSONDecoder().decode(Pairing.self, from: data)
    }

    /// Written over the item of that account, never deleted first: a write that fails leaves the old pairing in place.
    func put(_ pairing: Pairing, account: String) -> Bool {
        guard let data = try? JSONEncoder().encode(pairing) else { return false }
        let item: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: PairingStore.service,
                                   kSecAttrAccount as String: account]
        let value: [String: Any] = [kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
                                    kSecValueData as String: data]
        var status = SecItemUpdate(item as CFDictionary, value as CFDictionary)
        if status == errSecItemNotFound { status = SecItemAdd(item.merging(value) { $1 } as CFDictionary, nil) }
        return status == errSecSuccess
    }

    func delete(_ row: VaultRow) {
        if let ref = row.ref {
            SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecValuePersistentRef as String: ref] as CFDictionary)
        } else {
            SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: PairingStore.service,
                           kSecAttrAccount as String: row.account] as CFDictionary)
        }
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
