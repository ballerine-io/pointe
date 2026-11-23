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
            if model.ready {
                VStack(alignment: .leading, spacing: 0) {
                    if let note = model.versionNote {
                        Label("\(note.line) \(note.fix)", systemImage: "arrow.triangle.2.circlepath")
                            .font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.accent)
                            .padding(.vertical, 6)
                            .textSelection(.enabled)
                            .accessibilityIdentifier("versionNote")
                    }
                    Label(model.talkMode, systemImage: BubbleRule.talkModeGlyph(pushToTalk: model.session.pushToTalk))
                        .font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.muted)
                        .padding(.vertical, 4)
                        .help(model.session.pushToTalk ? "Push to talk: the shortcut talks from any app. Set it in Settings, This Mac." : "Always on: Pointe hears you while the call is up.")
                        .accessibilityIdentifier("talkMode")
                }
                .frame(maxWidth: .infinity, alignment: .trailing)
                .padding(.horizontal, 18)
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
        .sheet(item: Binding(get: { model.setupSheet }, set: { model.setupSheet = $0 })) { sheet in
            MacSetupSheetView(sheet: sheet, version: model.session.daemonVersion) { MacSettingsSections().environment(model) }
        }
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
