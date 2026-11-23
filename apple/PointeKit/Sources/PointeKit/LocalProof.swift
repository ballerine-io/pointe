import CryptoKit
import Foundation

/// The Mac app's proof that it holds the page key, made for one request (`local_proof.py` on the daemon): the key itself
/// never leaves the app. An HMAC, keyed by the page key and the token of this daemon start, over the time, a fresh
/// nonce, the method, the path, the query and the body's SHA-256. A program that takes the port while the daemon is down
/// gets a proof that works once, for two minutes, for that request, on a daemon that is gone.
public enum LocalProof {
    public static let header = "X-Pointe-Proof"

    public static func value(pageKey: String, token: String, method: String, url: URL, body: Data?,
                             time: Date = Date(), nonce: String = LocalProof.nonce()) -> String {
        let parts = URLComponents(url: url, resolvingAgainstBaseURL: false)
        let ts = String(Int(time.timeIntervalSince1970))
        let bodyHash = hex(SHA256.hash(data: body ?? Data()))
        let key = SymmetricKey(data: HMAC<SHA256>.authenticationCode(for: Data("pointe-mac-proof|\(token)".utf8),
                                                                     using: SymmetricKey(data: Data(pageKey.utf8))))
        let text = ["v1", ts, nonce, method.uppercased(), parts?.path ?? url.path, parts?.percentEncodedQuery ?? "", bodyHash]
            .joined(separator: "\n")
        return "v1.\(ts).\(nonce).\(bodyHash).\(hex(HMAC<SHA256>.authenticationCode(for: Data(text.utf8), using: key)))"
    }

    /// 128 random bits, as 32 hex digits.
    public static func nonce() -> String {
        var generator = SystemRandomNumberGenerator()
        return (0..<16).map { _ in String(format: "%02x", UInt8.random(in: .min ... .max, using: &generator)) }.joined()
    }

    private static func hex<D: Sequence>(_ digest: D) -> String where D.Element == UInt8 {
        digest.map { String(format: "%02x", $0) }.joined()
    }
}
