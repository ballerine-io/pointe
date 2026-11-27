// One signing identity from the login keychain as a .p12, base64 on stdout, for tools/release_secrets.sh to pipe into
// `gh secret set`. `security export -t identities` exports every identity in the keychain, other people's and other
// teams' included; this exports only the one named. Its intermediate (Apple's WWDR G3 or Developer ID G2) is not a
// keychain item and cannot go in the .p12; the hosted macOS runners carry both.
//
//   POINTE_P12_PASSPHRASE=… swift tools/export_identity.swift "Developer ID Application: Name (TEAMID)"
//
// The passphrase comes from the environment, never argv. Nothing is written to disk. macOS may ask the owner, in a
// dialog, to allow the export of the private key: that click is the owner's.
import Foundation
import Security

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("export_identity: \(message)\n".utf8))
    exit(1)
}

guard CommandLine.arguments.count == 2 else { fail("usage: export_identity.swift \"<the certificate's common name>\"") }
let wanted = CommandLine.arguments[1]
guard let passphrase = ProcessInfo.processInfo.environment["POINTE_P12_PASSPHRASE"], passphrase.count >= 16 else {
    fail("POINTE_P12_PASSPHRASE must hold a passphrase of 16 characters or more")
}
let passphraseRef = passphrase as CFString  // held for the export: the parameters keep only an unretained pointer

var found: CFTypeRef?
let query: [String: Any] = [kSecClass as String: kSecClassIdentity, kSecMatchLimit as String: kSecMatchLimitAll,
                            kSecReturnRef as String: true]
guard SecItemCopyMatching(query as CFDictionary, &found) == errSecSuccess, let identities = found as? [SecIdentity] else {
    fail("no identities in the keychain")
}
let matches = identities.filter { identity in
    var cert: SecCertificate?
    SecIdentityCopyCertificate(identity, &cert)
    return cert.flatMap { SecCertificateCopySubjectSummary($0) as String? } == wanted
}
guard matches.count == 1, let identity = matches.first else { fail("\(matches.count) identities named \(wanted), not one") }

var parameters = SecItemImportExportKeyParameters()
parameters.version = UInt32(SEC_KEY_IMPORT_EXPORT_PARAMS_VERSION)
parameters.passphrase = Unmanaged.passUnretained(passphraseRef as AnyObject)
var exported: CFData?
let status = SecItemExport(identity, .formatPKCS12, [], &parameters, &exported)
guard status == errSecSuccess, let p12 = exported as Data? else {
    fail("the export was refused (OSStatus \(status)\(status == errSecUserCanceled ? ": the dialog was cancelled" : ""))")
}
FileHandle.standardOutput.write(Data(p12.base64EncodedString().utf8))
