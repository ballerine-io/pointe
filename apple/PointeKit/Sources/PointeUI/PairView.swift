// The pairing screen is the iPhone's alone: the Mac app talks to the daemon on its own Mac and has nothing to pair.
#if os(iOS)
import AVFoundation
import SwiftUI

struct PairView: View {
    let submit: (String) -> Void  // a pointe://pair link; PointeApp pairs with it and says how it went
    var tryDemo: () -> Void = {}  // a sample call, no Mac needed
    @State private var link = ""
    @State private var problem: String?
    @State private var scanning = true

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            BrandHeader()
            Text("On your Mac, open Pointe's page: Settings, then Phone, then Connect your phone. Scan the code it shows here, or with the Camera app.")
                .font(.brand(.callout)).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
            if scanning {
                ZStack {  // under the camera: what shows before it starts, without one, or when it was not allowed
                    VStack(spacing: 8) {
                        Image(systemName: "qrcode.viewfinder").font(.system(size: 36, weight: .light)).foregroundStyle(Brand.dim)
                        Text("Point the camera at the code").font(.brand(.footnote)).foregroundStyle(Brand.dim)
                    }
                    .accessibilityHidden(true)
                    Scanner { code in
                        if PairingLink(code) != nil { submit(code) } else { problem = "That code is not a Pointe pairing code." }
                    }
                }
                .frame(maxWidth: .infinity, minHeight: 240, maxHeight: .infinity)
                .background(Brand.raised, in: RoundedRectangle(cornerRadius: 16))
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.line))
            }
            TextField("or paste the pointe:// link", text: $link)
                .autocorrectionDisabled().textInputAutocapitalization(.never).keyboardType(.URL).submitLabel(.go)
                .padding(.horizontal, 14).frame(minHeight: 48)
                .background(Brand.raised, in: RoundedRectangle(cornerRadius: 12))
                .onSubmit(use)
            Button(action: use) { Text("Pair").frame(maxWidth: .infinity) }
                .buttonStyle(.brandPrimary).controlSize(.large).disabled(link.isEmpty)
            if let problem { Text(problem).font(.brand(.footnote)).foregroundStyle(Brand.accent) }
            if !scanning { Spacer() }
            Button(action: tryDemo) {
                Label("No Mac yet? Try a demo", systemImage: "play.circle")
                    .font(.brand(.subheadline, .semibold)).foregroundStyle(Brand.muted)
                    .frame(maxWidth: .infinity, minHeight: 44).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("tryDemo")
            Text("The code holds a secret that opens a call into your coding sessions. Scan only your own.")
                .font(.brand(.footnote)).foregroundStyle(Brand.muted)
        }
        .padding(.horizontal, 20).padding(.top, 12).padding(.bottom, 16)
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
#endif
