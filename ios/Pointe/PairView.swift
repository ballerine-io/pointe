import AVFoundation
import SwiftUI

struct PairView: View {
    let submit: (String) -> Void  // a pointe://pair link; PointeApp pairs with it and says how it went
    @State private var link = ""
    @State private var problem: String?
    @State private var scanning = true

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            BrandHeader()
            Text("On your Mac, open Pointe's page: Settings, then Phone, then Connect your phone. Scan the code it shows here, or with the Camera app.")
                .foregroundStyle(.secondary)
            if scanning {
                Scanner { code in
                    if PairingLink(code) != nil { submit(code) } else { problem = "That code is not a Pointe pairing code." }
                }
                .frame(maxWidth: .infinity, minHeight: 280)
                .clipShape(RoundedRectangle(cornerRadius: 16))
            }
            TextField("or paste the pointe:// link", text: $link)
                .textFieldStyle(.roundedBorder).autocorrectionDisabled().textInputAutocapitalization(.never)
                .onSubmit(use)
            Button("Pair", action: use).buttonStyle(.borderedProminent).tint(Brand.orange).disabled(link.isEmpty)
            if let problem { Text(problem).foregroundStyle(Brand.orange) }
            Spacer()
            Text("The code holds a secret that opens a call into your coding sessions. Scan only your own.")
                .font(.footnote).foregroundStyle(.secondary)
        }
        .padding(24)
        .background(Brand.background)
    }

    private func use() {
        if PairingLink(link) != nil { submit(link) } else { problem = "That link is not a Pointe pairing link." }
    }
}

/// The camera, reading QR codes only.
struct Scanner: UIViewRepresentable {
    let found: (String) -> Void

    final class Preview: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    }

    /// Owns the capture session; AVFoundation calls it on the main queue, and starts the session off it.
    final class Reader: NSObject, AVCaptureMetadataOutputObjectsDelegate, @unchecked Sendable {
        let session = AVCaptureSession()
        var found: ((String) -> Void)?

        func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
            guard let code = (objects.first as? AVMetadataMachineReadableCodeObject)?.stringValue else { return }
            session.stopRunning()
            found?(code)
        }
    }

    func makeCoordinator() -> Reader { Reader() }

    func makeUIView(context: Context) -> Preview {
        let view = Preview(), reader = context.coordinator
        reader.found = found
        let layer = view.layer as! AVCaptureVideoPreviewLayer
        layer.session = reader.session
        layer.videoGravity = .resizeAspectFill
        if let camera = AVCaptureDevice.default(for: .video), let input = try? AVCaptureDeviceInput(device: camera),
           reader.session.canAddInput(input) {
            reader.session.addInput(input)
            let output = AVCaptureMetadataOutput()
            if reader.session.canAddOutput(output) {
                reader.session.addOutput(output)
                output.setMetadataObjectsDelegate(reader, queue: .main)
                output.metadataObjectTypes = [.qr]
            }
            DispatchQueue.global(qos: .userInitiated).async { reader.session.startRunning() }
        }
        return view
    }

    func updateUIView(_ uiView: Preview, context: Context) {}
}
