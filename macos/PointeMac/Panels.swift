import AppKit
import AVFoundation
import PointeKit
import PointeMacKit
import PointeUI
import SwiftUI

/// The window: the call screen once Pointe runs on this Mac (or a demo is on), the setup guide until then.
struct MainWindow: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            if model.ready {
                PointeMacRoot(session: model.session) { MacSettingsSections().environment(model) }
            } else {
                SetupPanel()
            }
        }
        .safeAreaInset(edge: .top, spacing: 0) {
            if model.ready, let note = model.versionNote {
                Label("\(note.line) \(note.fix)", systemImage: "arrow.triangle.2.circlepath")
                    .font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.accent)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 18).padding(.vertical, 6)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("versionNote")
            }
        }
        .background(PointeLook.bg)
        .animation(.smooth(duration: 0.25), value: model.ready)
    }
}

// MARK: setup

/// Pointe on this Mac is not ready: each step with its state, and the one thing to do about it.
struct SetupPanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Set up Pointe").font(PointeLook.display(28)).foregroundStyle(PointeLook.text).accessibilityAddTraits(.isHeader)
                step(done: model.plugin != nil, title: "The Pointe plugin",
                     detail: model.plugin.map { "Found version \($0.version)." } ?? "Install it in a terminal, then come back:") {
                    if model.plugin == nil {
                        HStack {
                            Text(MacCopy.installCommand).font(.system(.caption, design: .monospaced)).textSelection(.enabled).lineLimit(2)
                            Button("Copy") {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(MacCopy.installCommand, forType: .string)
                            }
                        }
                    }
                }
                step(done: model.keyPlan?.ready == true, title: "A setup and its keys",
                     detail: model.keyPlan?.ready == true ? "\(model.keyPlan?.line ?? KeyCopy.allFilled) The app never reads a key; Pointe on this Mac does."
                        : "\(model.keyPlan.map { $0.present.isEmpty && $0.setup == nil ? KeyCopy.noKey : $0.line } ?? KeyCopy.noKey) \(KeyCopy.whatYouNeedTitle) \(KeyCopy.whatYouNeed) Choose a setup, then add the keys it marks Needed in Settings, Model keys.\n\n\(KeyCopy.whyKeys)") {
                    SetupPicker()
                }
                step(done: model.daemon == .running, title: "Pointe on this Mac", detail: model.daemonLine) {
                    switch model.daemon {
                    case .stopped, .failed:
                        Button("Start Pointe") { Task { await model.startDaemon() } }.buttonStyle(.borderedProminent).tint(PointeLook.primary)
                            .accessibilityIdentifier("startDaemon")
                    case .starting, .checking: ProgressView().controlSize(.small)
                    default: EmptyView()
                    }
                }
                step(done: AVCaptureDevice.authorizationStatus(for: .audio) == .authorized, title: "The microphone",
                     detail: AVCaptureDevice.authorizationStatus(for: .audio) == .denied ? MacCopy.micDenied : "macOS asks the first time you press Connect.") {
                    if AVCaptureDevice.authorizationStatus(for: .audio) == .denied {
                        Button("Open Microphone settings…") { model.openMicrophoneSettings() }
                    }
                }
                step(done: model.session.sessionCount > 0, title: "A session", detail: MacCopy.noSessionsHow) { EmptyView() }
                Divider()
                HStack(spacing: 10) {
                    Button("Try a demo") { model.session.tryDemo() }.accessibilityIdentifier("tryDemo")
                    Text("Invented sessions, to look around: nothing is sent anywhere.").font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.muted)
                }
            }
            .padding(32)
            .frame(maxWidth: 560, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .onAppear { model.refreshKeys() }
        .accessibilityIdentifier("setup")
    }

    private func step<Action: View>(done: Bool, title: String, detail: String, @ViewBuilder action: () -> Action) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: done ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(done ? PointeLook.successText : PointeLook.dim)
                .accessibilityLabel(done ? "Done" : "To do")
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(PointeLook.font(.headline)).foregroundStyle(PointeLook.text)
                Text(detail).font(PointeLook.font(.callout)).foregroundStyle(PointeLook.muted).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                action()
            }
        }
        .accessibilityElement(children: .contain)
    }
}

// MARK: the call bubble

/// The call in a corner of the screen: the state, what is being heard, a talk button and who waits. It floats over
/// other apps and never takes the keyboard from them.
struct BubbleView: View {
    @Environment(AppModel.self) private var model
    @State private var pressed = false

    var body: some View {
        let session = model.session
        let live = session.live, ptt = session.pushToTalk, open = session.talking
        HStack(spacing: 10) {
            Image(systemName: !live ? "phone.fill" : ptt ? (open ? "mic.fill" : "mic") : (session.muted ? "mic.slash.fill" : "mic.fill"))
                .font(.system(size: 15, weight: .semibold))
                .frame(width: 36, height: 36)
                .foregroundStyle(open ? PointeLook.onOrange : PointeLook.text)
                .background(open ? PointeLook.orange : PointeLook.raised, in: Circle())
                .contentShape(Circle())
                .gesture(DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        guard !pressed else { return }
                        pressed = true
                        if !live { Task { await model.toggleCall() } } else { session.talkDown() }
                    }
                    .onEnded { _ in
                        pressed = false
                        session.talkUp()
                    })
                .accessibilityElement()
                .accessibilityAddTraits(.isButton)
                .accessibilityLabel(!live ? MacCopy.connect : ptt ? (open ? "Talking" : session.talkLabel) : (session.muted ? "Unmute" : "Mute"))
                .accessibilityAction {
                    if !live { Task { await model.toggleCall() } } else { session.talkDown(); if session.holdToTalk { session.talkUp() } }
                }
                .accessibilityIdentifier("bubble.talk")
            VStack(alignment: .leading, spacing: 1) {
                Text(session.stateTitle).font(PointeLook.font(.callout, .medium)).foregroundStyle(PointeLook.text).lineLimit(1)
                    .accessibilityIdentifier("bubble.state")
                Text(session.hearing.isEmpty ? (session.activeSession ?? MacCopy.appName) : session.hearing)
                    .font(PointeLook.font(.caption)).foregroundStyle(PointeLook.muted).lineLimit(1).truncationMode(.head)
            }
            Spacer(minLength: 0)
            if session.needCount > 0 {
                Button { model.windows.showMain() } label: {
                    Text("\(session.needCount)").font(PointeLook.font(.caption, .semibold)).monospacedDigit()
                        .frame(minWidth: 20, minHeight: 20).foregroundStyle(PointeLook.onOrange).background(PointeLook.orange, in: Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(MacCopy.needYou(session.needCount))
                .help(MacCopy.needYou(session.needCount))
            }
        }
        .padding(.horizontal, 12)
        .frame(width: 260, height: 60)
        .background(PointeLook.card, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(PointeLook.lineStrong))
        .padding(2)
        .contextMenu {
            Button("Open Pointe") { model.windows.showMain() }
            Button("Hide the bubble") { model.bubbleOn = false }
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Pointe call bubble")
    }
}
