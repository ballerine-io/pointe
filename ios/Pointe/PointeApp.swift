import SwiftUI

@main
struct PointeApp: App {
    @State private var pairing = PairingStore.load()

    var body: some Scene {
        WindowGroup {
            Group {
                if let demo = Demo.fromLaunch() {
                    CallView(pairing: Demo.pairing, unpair: {}, demo: demo)
                } else if let pairing {
                    CallView(pairing: pairing, unpair: { PairingStore.forget(); self.pairing = nil })
                        .id(pairing)  // a new pairing is a new call: the old one pins the old certificate
                } else {
                    PairView { PairingStore.save($0); self.pairing = $0 }
                }
            }
            .preferredColorScheme(.dark)
            .tint(Brand.orange)
            .onOpenURL { url in  // scanned with the Camera app: pointe://pair?...
                if let p = Pairing(link: url.absoluteString) { PairingStore.save(p); pairing = p }
            }
            .task {  // tests and the simulator: a link given at launch replaces any earlier pairing
                if let link = ProcessInfo.processInfo.environment["POINTE_PAIR"], let p = Pairing(link: link), p != pairing {
                    PairingStore.save(p); pairing = p
                }
            }
        }
    }
}

enum Brand {
    static let orange = Color(red: 1, green: 0.31, blue: 0.12)
    static let card = Color(red: 0.075, green: 0.11, blue: 0.165)
    static let background = Color(red: 0.043, green: 0.063, blue: 0.094)
}
