import SwiftUI

/// The call's controls, at your thumb: the mic in the middle, brainstorm and the keyboard either side, hang up last.
struct BottomBar: View {
    let phase: Call.State
    let muted: Bool
    let monologue: Bool
    let typing: Bool
    let mic: () -> Void
    let listen: () -> Void
    let type: () -> Void
    let sessions: () -> Void
    let hangUp: () -> Void

    private var live: Bool { phase == .live || phase == .reconnecting }

    var body: some View {
        HStack(spacing: 0) {
            side(monologue ? "Back" : "Brainstorm", monologue ? "bubble.left.and.bubble.right.fill" : "brain.head.profile",
                 on: monologue, action: listen)
                .disabled(!live)
            Spacer()
            side("Type", typing ? "keyboard.chevron.compact.down" : "keyboard", on: typing, action: type)
            Spacer()
            micButton
            Spacer()
            side("Sessions", "rectangle.stack", action: sessions)
            Spacer()
            if live {
                side("Hang up", "phone.down.fill", tint: .red, action: hangUp)
            } else {
                side("Hang up", "phone.down.fill", action: {}).hidden().accessibilityHidden(true)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 30))
        .sensoryFeedback(.impact(weight: .medium), trigger: muted)
        .sensoryFeedback(.impact(weight: .light), trigger: monologue)
    }

    private var micButton: some View {
        Button(action: mic) {
            ZStack {
                Circle().fill(phase == .live && !muted ? AnyShapeStyle(Brand.orange.gradient) : AnyShapeStyle(Brand.card))
                Image(systemName: phase == .live && !muted ? "mic.fill" : phase == .off ? "mic" : "mic.slash.fill")
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundStyle(.white)
                    .contentTransition(.symbolEffect(.replace))
                if phase == .connecting || phase == .reconnecting { ProgressView().tint(.white).offset(y: 30) }
            }
            .frame(width: 70, height: 70)
            .shadow(color: phase == .live && !muted ? Brand.orange.opacity(0.5) : .clear, radius: 12)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(phase == .live ? (muted ? "Unmute" : "Mute") : phase == .off ? "Connect" : "Connecting")
    }

    private func side(_ label: String, _ symbol: String, on: Bool = false, tint: Color = .primary,
                      action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: symbol).font(.system(size: 19, weight: .medium))
                    .frame(width: 46, height: 46)
                    .background(on ? AnyShapeStyle(Brand.orange.opacity(0.25)) : AnyShapeStyle(.thinMaterial), in: Circle())
                    .contentTransition(.symbolEffect(.replace))
                Text(label).font(.caption2).lineLimit(1).fixedSize()
            }
            .foregroundStyle(tint)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// Typed instead of spoken: for a noisy room or a quiet one.
struct TypeBar: View {
    var prompt = "Type to Pointe"
    let send: (String) async -> Bool
    let close: () -> Void
    @State private var text = ""
    @State private var sending = false
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 10) {
            TextField(prompt, text: $text, axis: .vertical)
                .lineLimit(1...4)
                .focused($focused)
                .accessibilityIdentifier("typeField")
                .submitLabel(.send)
                .onSubmit(submit)
                .onChange(of: text) {  // a multi-line field takes Return as a new line: Return sends, as the key says
                    if text.hasSuffix("\n") { text.removeLast(); submit() }
                }
                .padding(.horizontal, 14).padding(.vertical, 10)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 20))
            Button(action: submit) {
                Image(systemName: "arrow.up").font(.body.bold()).foregroundStyle(.white)
                    .frame(width: 38, height: 38)
                    .background(empty ? AnyShapeStyle(Color.gray.opacity(0.4)) : AnyShapeStyle(Brand.orange.gradient), in: Circle())
            }
            .disabled(empty || sending)
            .accessibilityLabel("Send")
        }
        .onAppear { focused = true }
    }

    private var empty: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    private func submit() {
        guard !empty else { return }
        let words = text.trimmingCharacters(in: .whitespacesAndNewlines)
        sending = true
        Task {
            if await send(words) { text = "" }
            sending = false
        }
    }
}
