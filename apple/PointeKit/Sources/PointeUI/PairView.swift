// The pairing screen is the iPhone's alone: the Mac app talks to the daemon on its own Mac and has nothing to pair.
#if os(iOS)
import AVFoundation
import SwiftUI

struct PairView: View {
    let flow: PairingFlow  // keeps a scanned or pasted code only after the owner confirms it (PairingFlow)
    var tryDemo: (() -> Void)?  // a sample call, no Mac needed; none when the scanner is over a call
    @State private var link = ""
    @State private var problem: String?
    @State private var scanning = true
    @State private var room: CGFloat = 0    // the screen's height for this view, less the keyboard
    @State private var whole: CGFloat = 0   // the form's height, camera included
    @State private var camera: CGFloat = 0  // the camera's height as drawn

    /// The camera takes what the rest leaves, from 200 to 480 points. Past that the form scrolls: at the largest type
    /// Pair and Try a demo were below the screen, out of reach.
    static func cameraHeight(room: CGFloat, rest: CGFloat) -> CGFloat {
        guard room > 0 else { return 240 }
        return min(480, max(200, room - rest))
    }

    var body: some View {
        ScrollView {
            form.frame(minHeight: room, alignment: .top)
        }
        .scrollBounceBehavior(.basedOnSize)
        .scrollDismissesKeyboard(.interactively)
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { room = $0 }
        .clipped()  // what scrolls up never draws under the clock
        .background(Brand.background)
        .alert(flow.offer?.title ?? "", isPresented: Binding(get: { flow.offer != nil }, set: { _ in }), presenting: flow.offer) { offer in
            Button(offer.action) { flow.confirmTapped() }.accessibilityIdentifier("confirmPairing")
            Button("Cancel", role: .cancel) { flow.cancel() }
        } message: { offer in
            Text(offer.message)
        }
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 16) {
            BrandHeader().dynamicTypeSize(...DynamicTypeSize.accessibility2)  // the call screen's header stops there too
            Text("On your Mac, open Pointe's page: Settings, then Phone, then Connect your phone. Scan the code it shows here.")
                .font(.brand(.callout)).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
            if scanning {
                ZStack {  // under the camera: what shows before it starts, without one, or when it was not allowed
                    VStack(spacing: 8) {
                        Image(systemName: "qrcode.viewfinder").font(.system(size: 36, weight: .light)).foregroundStyle(Brand.dim)
                        Text("Point the camera at the code").font(.brand(.footnote)).foregroundStyle(Brand.dim)
                    }
                    .accessibilityHidden(true)
                    Scanner { code in
                        if PairingLink(code) != nil { flow.scanned(code) } else { problem = "That code is not a Pointe pairing code." }
                    }
                    .id(flow.attempt)  // a code cancelled or refused: the camera reads again
                }
                .frame(maxWidth: .infinity)
                .frame(height: Self.cameraHeight(room: room, rest: whole - camera))
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { camera = $0 }
                .background(Brand.raised, in: RoundedRectangle(cornerRadius: 16))
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.line))
            }
            // Over the field, not under Pair: with the keyboard up, under Pair was behind the keyboard.
            if let problem {
                Text(problem).font(.brand(.footnote)).foregroundStyle(Brand.accent).fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("pairProblem")
            }
            TextField("or paste the pointe:// link", text: $link)
                .autocorrectionDisabled().textInputAutocapitalization(.never).keyboardType(.URL).submitLabel(.go)
                .padding(.horizontal, 14).frame(minHeight: 48)
                .background(Brand.raised, in: RoundedRectangle(cornerRadius: 12))
                .onSubmit(use)
            Button(action: use) { Text("Pair").frame(maxWidth: .infinity) }
                .buttonStyle(.brandPrimary).controlSize(.large).disabled(link.isEmpty)
            if !scanning { Spacer(minLength: 0) }
            if let tryDemo {
                Button(action: tryDemo) {
                    Label("No Mac yet? Try a demo", systemImage: "play.circle")
                        .font(.brand(.subheadline, .semibold)).foregroundStyle(Brand.muted)
                        .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, minHeight: 44).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("tryDemo")
            }
            Text("The code holds a secret that opens a call into your coding sessions. Scan only your own.")
                .font(.brand(.footnote)).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("pairSecurityNote")
        }
        .padding(.horizontal, 20).padding(.top, 12).padding(.bottom, 16)
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { whole = $0 }
    }

    private func use() {
        if PairingLink(link) != nil { problem = nil; flow.scanned(link) } else { problem = "That link is not a Pointe pairing link." }
    }
}

/// A `pointe://` link opened Pointe from outside: another app, a web page or the Camera. It pairs nothing, since any of
/// them can open one; the code is scanned inside the app.
struct ScanInsideSheet: View {
    let scan: () -> Void
    let close: () -> Void

    static let title = "Pair inside Pointe"
    static let text = "Pointe pairs only with a code you scan in this app, so a link from another app or a web page can't change which Mac it talks to. On your Mac, open Pointe's page: Settings, then Phone, then Connect your phone, and scan the code here."

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(Self.title).font(.brand(.title2, .semibold))
            Text(Self.text).font(.brand(.callout)).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("scanInside")
            Button(action: scan) { Text("Scan the code").frame(maxWidth: .infinity) }
                .buttonStyle(.brandPrimary).controlSize(.large)
                .accessibilityIdentifier("scanInsideScan")
            Button("Not now", action: close).frame(maxWidth: .infinity)
        }
        .padding(20)
        .presentationDetents([.medium])
        .background(Brand.background)
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
