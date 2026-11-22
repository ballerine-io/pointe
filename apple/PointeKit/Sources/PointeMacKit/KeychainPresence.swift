#if os(macOS)
import Foundation
import Security

/// Whether a vendor's key is in the Keychain: asked by attributes only, so no secret is loaded, shown or logged, and
/// macOS raises no prompt. The daemon is the only reader of the key itself.
public enum KeychainPresence {
    public static func has(_ vendor: Vendor) -> Bool {
        [vendor.service, vendor.legacyService].contains { service in
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecMatchLimit as String: kSecMatchLimitOne,
                kSecReturnAttributes as String: true,
                kSecReturnData as String: false,
            ]
            return SecItemCopyMatching(query as CFDictionary, nil) == errSecSuccess
        }
    }
}
#endif
