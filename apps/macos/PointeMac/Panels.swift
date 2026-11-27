import AppKit
import AVFoundation
import PointeKit
import PointeMacKit
import PointeUI
import SwiftUI

/// The window: the call screen once Pointe runs on this Mac (or a demo is on), the setup guide until then.
struct MainWindow: View {
    /// The smallest window that keeps every primary button in it: Deny and Approve, Start shift, Connect, I've stopped.
    /// Below 560 high the cards over the bar had no room left for their buttons.
    static let minSize = NSSize(width: 420, height: 560)

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
                HStack(spacing: 10) {
                    if model.canUpdate {  // the standalone install, older than this app: the app brings it up itself
                        Label(model.installRun?.line ?? model.installProblem ?? note.line, systemImage: "arrow.triangle.2.circlepath")
                        if let run = model.installRun {
                            ProgressView(value: run.fraction).frame(width: 120)
                        } else {
                            Button("Update Pointe to \(model.appVersion)") { Task { await model.installPointe() } }
                                .help("Installs Pointe \(model.appVersion), checked, beside the old one, restarts Pointe on it (a call in progress ends), then removes the old one.")
                                .accessibilityIdentifier("updatePointe")
                        }
                    } else {
                        Label("\(note.line) \(note.fix)", systemImage: "arrow.triangle.2.circlepath").textSelection(.enabled)
                    }
                }
                .font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.accent)
                .padding(.vertical, 6)
                .accessibilityIdentifier("versionNote")
                .frame(maxWidth: .infinity, alignment: .trailing)
                .padding(.horizontal, 18)
            }
        }
        .overlay(alignment: .topTrailing) {  // in the title bar's row, beside nothing: a row of its own floated over the header
            if model.ready {
                // The widest that fits beside the window buttons (QuickRow.Fit): a narrow window drops words, never a chip.
                ViewThatFits(in: .horizontal) {
                    strip(.full)
                    strip(.compact)
                    strip(.tight)
                }
                .font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.muted)
                .frame(height: 28)
                .padding(.leading, 84)  // the close, minimise and zoom buttons
                .padding(.trailing, 14)
                .ignoresSafeArea(edges: .top)
            }
        }
        .background(PointeLook.bg)
        .motion(.smooth(duration: 0.25), value: model.ready)
    }
}

extension MainWindow {
    /// The title strip: what an AirPods press does, the skip shortcut, then the quick settings row (QuickSettings.swift).
    @ViewBuilder func strip(_ fit: QuickRow.Fit) -> some View {
        HStack(spacing: fit == .tight ? 8 : 14) {
            if let airPods = model.session.airPodsHint {  // during a call: what a stem press does now
                Label(airPods, systemImage: AirPodsPress.glyph)
                    .labelStyle(StripLabelStyle(iconOnly: fit != .full))
                    .help("During a call an AirPods press turns the mic off and on, with the system's chime; in push to talk it talks. Play/pause from other headsets and the keyboard does what Settings, This Mac, says.")
                    .accessibilityLabel(airPods)
                    .accessibilityIdentifier("airPodsHint")
            }
            if let skip = model.skipHint {  // beside the microphone chip, said the same way
                Label(skip, systemImage: BubbleRule.skipGlyph)
                    .labelStyle(StripLabelStyle(iconOnly: fit == .tight))
                    .help("The skip shortcut skips what Pointe is saying, from any app. Set it in Settings, This Mac.")
                    .accessibilityLabel(skip)
                    .accessibilityIdentifier("skipShortcut")
            }
            // The microphone first, where the talk mode was said, then reply length, speed, clean words and whisper.
            // The switch above the mic is gone on the Mac.
            QuickRow(session: model.session, micLabel: model.talkMode,
                     micGlyph: BubbleRule.talkModeGlyph(pushToTalk: model.session.pushToTalk), fit: fit)
        }
    }
}

/// A title-strip label with its words, or its icon alone in a narrow window (its words stay its accessibility label).
private struct StripLabelStyle: LabelStyle {
    let iconOnly: Bool

    func makeBody(configuration: Configuration) -> some View {
        if iconOnly { configuration.icon } else { HStack(spacing: 4) { configuration.icon; configuration.title } }
    }
}

// MARK: setup
// MARK: setup

/// Pointe on this Mac is not ready: each step with its state, and the one thing to do about it.
struct SetupPanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 12) {
                    PointeLook.mark(36)
                    Text("Set up Pointe").font(PointeLook.display(28)).foregroundStyle(PointeLook.text).accessibilityAddTraits(.isHeader)
                }
                VStack(alignment: .leading, spacing: 6) {
                    ProgressView(value: Double(stepsDone), total: 4).tint(PointeLook.primary)
                    Text(stepsDone == 4 ? "Ready: press Connect and say hello." : "Step \(stepsDone + 1) of 4. About five minutes, then your first call.")
                        .font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.muted)
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("setup.progress")
                installStep
                step(done: setupChosen, title: "Your setup", detail: setupChosen
                     ? (model.setupID == nil ? model.keyPlan?.line ?? KeyCopy.allFilled : "Pointe uses this setup's vendors. Settings, Model keys, changes it.")
                     : KeyCopy.freeStart) {
                    if !setupChosen {
                        Button("Start with Free start") { Task { await model.chooseSetup("free") } }
                            .buttonStyle(.borderedProminent).tint(PointeLook.primary)
                            .disabled(model.plugin == nil || model.setupBusy)
                            .accessibilityIdentifier("setup.free")
                    }
                    SetupPicker()
                }
                step(done: model.keyPlan?.ready == true, title: "Your key",
                     detail: model.keyPlan?.ready == true ? "\(model.keyPlan?.line ?? KeyCopy.allFilled) The app never reads a key; Pointe on this Mac does."
                        : "Add… opens the vendor's key page in your browser and a small Mac window. Make a key there, paste it in the window and press Save: it goes straight to your Keychain, never to a file or this app. Pointe tries it with one tiny call.") {
                    ForEach(neededKeys) { vendor in
                        Button("Add the \(vendor.label) key…") { Task { await model.addKey(vendor) } }
                            .buttonStyle(.borderedProminent).tint(PointeLook.primary)
                            .disabled(model.plugin == nil)
                            .accessibilityIdentifier("setup.key.\(vendor.rawValue)")
                    }
                    if let note = model.keyNote { Text(note).font(PointeLook.font(.footnote)).foregroundStyle(PointeLook.muted) }
                }
                step(done: model.daemon == .running, title: "Your first call", detail: [.stopped, .noPlugin].contains(model.daemon)
                     ? "Start Pointe, put on headphones, press Connect and say hello: Pointe answers that it hears you." : model.daemonLine) {
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

    private var setupChosen: Bool { model.setupID != nil || model.keyPlan?.ready == true }

    /// The keys the chosen setup still lacks (with none chosen, the one key that fills an empty role).
    private var neededKeys: [Vendor] { model.keyPlan.map { plan in Vendor.allCases.filter { plan.state($0) == .needed } } ?? [] }

    private var stepsDone: Int {
        [model.plugin != nil, setupChosen, model.keyPlan?.ready == true, model.daemon == .running].filter { $0 }.count
    }

    /// Pointe itself: found, being installed (install.sh, built into the app, with its own progress), or one button.
    @ViewBuilder private var installStep: some View {
        let version = model.appVersion
        if let plugin = model.plugin {
            step(done: true, title: "Pointe", detail: plugin.isStandalone ? "Pointe \(plugin.version) is installed in your home folder."
                 : "Pointe \(plugin.version) is installed: the Claude Code plugin.") { EmptyView() }
        } else if let run = model.installRun {
            step(done: false, title: "Installing Pointe \(version)", detail: run.line) {
                ProgressView(value: run.fraction).tint(PointeLook.primary).frame(maxWidth: 360).accessibilityIdentifier("install.progress")
            }
        } else if model.canInstall {
            step(done: false, title: "Pointe", detail: model.installProblem ?? "The app installs Pointe \(version) in your home folder: it downloads it from GitHub, checks it against the SHA-256 built into this app, and installs its Python (about 180 MB). No Terminal and no password. Pointe → Uninstall Pointe… removes it again.") {
                Button(model.installProblem == nil ? "Install Pointe" : "Try Again") { Task { await model.installPointe() } }
                    .buttonStyle(.borderedProminent).tint(PointeLook.primary).keyboardShortcut(.defaultAction)
                    .accessibilityIdentifier("install")
            }
        } else {
            step(done: false, title: "The Pointe plugin", detail: "\(MacCopy.noPlugin) Install it in a terminal, then come back:") {
                HStack {
                    Text(MacCopy.installCommand).font(.system(.caption, design: .monospaced)).textSelection(.enabled).lineLimit(2)
                    Button("Copy") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(MacCopy.installCommand, forType: .string)
                    }
                }
            }
        }
    }

    /// A slash command stays on one line: a word joiner after its slash, so "/pointe:voice" never wraps after the "/".
    static func unbroken(_ text: String) -> String {
        text.replacingOccurrences(of: #"(^|\s)/(?=\w)"#, with: "$1/\u{2060}", options: .regularExpression)
    }

    private func step<Action: View>(done: Bool, title: String, detail: String, @ViewBuilder action: () -> Action) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: done ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(done ? PointeLook.successText : PointeLook.dim)
                .accessibilityLabel(done ? "Done" : "To do")
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(PointeLook.font(.headline)).foregroundStyle(PointeLook.text)
                Text(Self.unbroken(detail)).font(PointeLook.font(.callout)).foregroundStyle(PointeLook.muted).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                action()
            }
        }
        .accessibilityElement(children: .contain)
    }
}

