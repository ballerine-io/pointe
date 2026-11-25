import PointeKit
import SwiftUI

/// Connect: the one control that starts the call. Its words are the page's (`CONNECT_COPY` in ui.html); the parity
/// tests on both sides hold them to the same text.
enum ConnectCopy {
    static let connect = "Connect"
    static let tryAgain = "Try again"
    static let hangUp = "Hang up"
    static let cancel = "Cancel"
    static let connectFirst = "Connect first"
    static let notConnected = "Not connected"
    static let notPairedTitle = "Not paired"
    static let unreachableTitle = "Mac not reachable"
    static let elsewhere = "On a call elsewhere"
    /// A refused key: the page's CONNECT_COPY.cannotHear and cannotAnswer, and the action under them.
    static let cannotHear = "Cannot hear you"
    static let cannotAnswer = "Cannot answer you"
    static let fixKey = "Fix the key"
    static let does = "Starts the call on this iPhone's microphone"
    static let tapConnect = "Tap Connect to start talking"
    static let redialling = "The connection dropped. The call picks up where it was when it is back; Cancel ends it."
    static let elsewhereWhy = "The call is on the Mac's page or another phone. Hang up there to talk here."
    static let busy = "A call is already up on another page or phone. Hang up there first."
    static let notPaired = "This phone is no longer paired. Pair again from the page: Settings → Phone → Connect your phone."
    static let idleHangup = "The Mac hung up after 30 minutes of quiet. Tap Connect to talk again."
    static let micDenied = "Pointe needs the microphone: allow it in Settings, then tap Try again."
    /// Under Connect: the type bar opens from the keyboard button, and typing needs the call (the page's typeLaterTap).
    static let typeLaterTap = "Once connected, tap the keyboard to type"
    static func connecting(_ place: String) -> String { "Connecting to \(place)…" }
    static func micFailed(_ why: String) -> String { "The microphone could not start: \(why)" }
    static func failed(_ why: String) -> String { "The call did not connect\(why.isEmpty ? "" : ": " + why)." }
    /// From the phone, a Mac that does not answer and a Mac whose phone listener is off look the same: say both.
    static func unreachable(_ host: String) -> String {
        "Can't reach your Mac at \(host). Is Twingate or Tailscale on? Is the Mac awake?"
            + " If so, its phone listener may be off: on the Mac, Settings → Phone → Connect your phone."
    }

    static func offTitle(reach: Reach, macOnACall: Bool) -> String {
        switch reach {
        case .rejected: return Surface.isMac ? MacCopy.notConnected : notPairedTitle
        case .unreachable: return Surface.isMac ? MacCopy.notAnswering : unreachableTitle
        case .ok: return macOnACall ? elsewhere : notConnected
        }
    }
}

/// The lines above as each app says them. The Mac app is on the Mac: its words are the page's own (`MacCopy`, held to
/// ui.html by tests/test_macos_parity.py), "press" where a phone says "tap", this Mac's microphone, and Pointe on this
/// Mac where the phone speaks of the Mac it paired with.
extension ConnectCopy {
    static var doesHere: String { Surface.isMac ? MacCopy.does : does }
    static var tapConnectHere: String { Surface.isMac ? MacCopy.pressConnect : tapConnect }
    static var notPairedHere: String { Surface.isMac ? MacCopy.keyRefused : notPaired }
    static var idleHangupHere: String { Surface.isMac ? MacCopy.idleHangup : idleHangup }
    static var micDeniedHere: String { Surface.isMac ? MacCopy.micDenied : micDenied }
    static var elsewhereWhyHere: String { Surface.isMac ? MacCopy.elsewhereWhy : elsewhereWhy }
    static var typeLaterHere: String { Surface.isMac ? MacCopy.typeLater : typeLaterTap }
    static func unreachableHere(_ host: String) -> String { Surface.isMac ? MacCopy.daemonDown : unreachable(host) }
}

/// Whether /voice/status answers: the Mac away, or the Mac refusing this phone's key, are two different problems.
enum Reach: Equatable { case ok, unreachable, rejected }

/// What the Connect control shows, from what the screen knows. Pure, so the parity tests can read every state.
struct ConnectFace: Equatable {
    let why: String
    let bad: Bool          // the why line is a problem, not a description
    let button: String     // the empty stage's button
    let pill: String       // the header pill
    let dialling: Bool
    /// The microphone was refused: the panel offers the system's own switch for it.
    var opensSettings = false
    /// The phone could not get through, and why: the stage shows it with its fix and actions (ProblemCard) until the
    /// Mac answers or the person acts.
    var trouble: ConnectionProblem? = nil

    static func make(phase: Call.State, reach: Reach, host: String, problem: String?, macOnACall: Bool,
                     trouble: ConnectionProblem? = nil) -> ConnectFace {
        let issue: String? = trouble?.detail ?? (reach == .rejected ? ConnectCopy.notPairedHere : reach == .unreachable ? ConnectCopy.unreachableHere(host)
            : (problem?.isEmpty == false ? problem : nil))
        let dialling = phase == .connecting || phase == .reconnecting
        let why = issue ?? (phase == .reconnecting ? ConnectCopy.redialling
                            : phase == .off && macOnACall ? ConnectCopy.elsewhereWhyHere : ConnectCopy.doesHere)
        let button = dialling ? ConnectCopy.cancel : issue != nil ? ConnectCopy.tryAgain : ConnectCopy.connect
        return ConnectFace(why: why, bad: issue != nil, button: button, pill: phase == .live ? ConnectCopy.hangUp : button, dialling: dialling,
                           opensSettings: issue == ConnectCopy.micDeniedHere, trouble: trouble)
    }
}

/// The empty stage: nothing said yet, no call up. One primary button, the title the status line shows, and the reason
/// in plain words when the last attempt failed.
struct ConnectPanel: View {
    let title: String
    let face: ConnectFace
    let tap: () -> Void
    /// A connection problem's buttons (ProblemCard); none where there is nothing to pair again.
    var act: ((ConnectionProblem.Action) -> Void)? = nil

    var body: some View {
        VStack(spacing: 14) {
            ZStack {
                Circle().fill(Brand.raised).frame(width: 72, height: 72)
                    .overlay(Circle().stroke(Brand.line))
                Image(systemName: "phone.fill").font(.system(size: 26, weight: .semibold)).foregroundStyle(Brand.muted)
            }
            if let trouble = face.trouble, !face.dialling, let act {
                ProblemCard(problem: trouble) { act($0) }
            } else {
                stage
            }
            Text(ConnectCopy.typeLaterHere).font(.brand(.caption)).foregroundStyle(Brand.dim)
                .accessibilityIdentifier("connectHint")
        }
        .padding(.horizontal, 28)
        .frame(maxWidth: 360)
        .motion(.easeInOut(duration: 0.2), value: face)
    }

    /// Title, reason and the one button: when nothing failed, or while a Try again dials.
    @ViewBuilder private var stage: some View {
        Text(title).font(.brand(.title2)).multilineTextAlignment(.center)
            .accessibilityIdentifier("connectTitle")
        Text(face.why).font(.brand(.subheadline)).foregroundStyle(face.bad ? Brand.accent : Brand.muted)
            .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier("connectWhy")
        Button(action: tap) {
            HStack(spacing: 8) {
                if face.dialling { ProgressView().tint(Brand.muted) } else { Image(systemName: "phone.fill") }
                Text(face.button).font(.brand(.headline))
            }
            .foregroundStyle(face.dialling ? Brand.text : Brand.onOrange)
            .padding(.horizontal, 24).frame(height: 48)
            .background(face.dialling ? Brand.raised : Brand.orange, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(face.dialling ? Brand.lineStrong : Color.clear))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("connectButton")
        .padding(.top, 4)
        if face.opensSettings {
            Button(Surface.isMac ? "Open Microphone settings…" : "Open Settings") { SystemSettings.openMicrophone() }
                .font(.brand(.subheadline, .semibold)).tint(Brand.accent)
                .accessibilityIdentifier("connectOpenSettings")
        }
    }
}

/// The small Connect in the header: the way back once the conversation covers the stage, and Hang up while live.
struct ConnectPill: View {
    let phase: Call.State
    let face: ConnectFace
    let tap: () -> Void

    private var live: Bool { phase == .live }

    var body: some View {
        Button(action: tap) {
            HStack(spacing: 6) {
                if face.dialling { ProgressView().controlSize(.mini) } else { Image(systemName: live ? "phone.down.fill" : "phone.fill") }
                Text(face.pill)
            }
            .font(.brand(.subheadline, .semibold))
            .foregroundStyle(live ? Brand.dangerText : face.dialling ? Brand.muted : Brand.text)
            .padding(.horizontal, 12).frame(height: 36)
            .background(face.dialling ? Brand.raised : Color.clear, in: Capsule())
            .overlay(Capsule().stroke(live ? Brand.danger.opacity(0.5) : Brand.lineStrong))
            .touchTarget(height: 36)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("topConnect")
    }
}
