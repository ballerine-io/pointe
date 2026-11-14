import SwiftUI

/// What was said, oldest first, and what you are saying now as the last bubble. Your turns can be tapped to fix a word.
struct ConversationView: View {
    let turns: [API.Turn]
    let polish: Bool
    let hearing: String
    var large = false  // whisper mode: the words heard so far, big enough to check before they are acted on
    var placeholder = true  // false while the Connect stage stands where the words will be (no call up yet)
    let edit: (API.Turn) -> Void
    @Namespace private var speech

    var body: some View {
        if turns.isEmpty && hearing.isEmpty {
            if placeholder {
                ContentUnavailableView {
                    Label("Nothing said yet", systemImage: "waveform")
                } description: {
                    Text("Talk, or tap the keyboard to type. Tap anything you said to fix it.")
                }
                .padding(.top, 40)
            }
        } else {
            LazyVStack(spacing: 0) {
                ForEach(Array(turns.enumerated()), id: \.element.id) { index, turn in
                    let next = index + 1 < turns.count ? turns[index + 1] : nil
                    let groupEnd = next?.who != turn.who
                    let newestMine = turn.mine && turn.id == turns.last?.id && hearing.isEmpty
                    Bubble(turn: turn, polish: polish, pending: polish && turn.id == turns.last(where: \.mine)?.id,
                           tail: groupEnd)
                        // the live bubble becomes this one: same place, same shape, so it flows instead of jumping
                        .matchedGeometryEffect(id: newestMine ? "speech" : "turn-\(turn.id)", in: speech)
                        .onTapGesture { if turn.mine { edit(turn) } }
                        .padding(.bottom, groupEnd ? 14 : 4)
                        .transition(.opacity)
                }
                if !hearing.isEmpty {
                    LiveBubble(text: hearing, large: large)
                        .matchedGeometryEffect(id: "speech", in: speech)
                        .padding(.bottom, 14)
                        .transition(.opacity)
                }
            }
            .animation(.smooth(duration: 0.35), value: turns.last?.id)
            .animation(.smooth(duration: 0.35), value: hearing.isEmpty)
        }
    }
}

struct Bubble: View {
    let turn: API.Turn
    let polish: Bool
    var pending = false
    var tail = true

    var body: some View {
        HStack(alignment: .bottom, spacing: 0) {
            if turn.mine { Spacer(minLength: 56) }
            VStack(alignment: turn.mine ? .trailing : .leading, spacing: 4) {
                if turn.mine, polish, let understood = turn.understood, understood != turn.text {
                    Text(turn.text).readingDirection(of: turn.text).font(.footnote).foregroundStyle(.white.opacity(0.5))
                    Text(understood).readingDirection(of: understood)
                } else {
                    Text(turn.text).readingDirection(of: turn.text)
                }
                if turn.mine && (turn.typed == true || turn.corrected == true || (pending && turn.understood == nil)) {
                    badges
                }
            }
            .font(.body)
            .lineSpacing(2)
            .multilineTextAlignment(turn.mine ? .trailing : .leading)
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(turn.mine ? AnyShapeStyle(Brand.orange.opacity(0.18)) : AnyShapeStyle(Brand.card), in: shape)
            .frame(maxWidth: 520, alignment: turn.mine ? .trailing : .leading)
            if !turn.mine { Spacer(minLength: 56) }
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel((turn.mine ? "You: " : "Pointe: ") + (turn.understood ?? turn.text))
        .accessibilityHint(turn.mine ? "Double-tap to fix what was heard" : "")
    }

    private var shape: UnevenRoundedRectangle {
        let small: CGFloat = tail ? 6 : 18
        return UnevenRoundedRectangle(topLeadingRadius: 18, bottomLeadingRadius: turn.mine ? 18 : small,
                                      bottomTrailingRadius: turn.mine ? small : 18, topTrailingRadius: 18)
    }

    private var badges: some View {
        HStack(spacing: 6) {
            if turn.typed == true { Label("typed", systemImage: "keyboard") }
            if turn.corrected == true { Label("edited", systemImage: "pencil") }
            if pending && turn.understood == nil && turn.corrected != true { Label("cleaning up", systemImage: "wand.and.sparkles") }
        }
        .labelStyle(.titleAndIcon)
        .font(.caption2)
        .foregroundStyle(.white.opacity(0.55))
    }
}

/// What you are saying right now: the last bubble in the conversation, live, until the sentence is done.
struct LiveBubble: View {
    let text: String
    var large = false

    var body: some View {
        HStack(alignment: .bottom, spacing: 0) {
            Spacer(minLength: 56)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: "waveform").font(.callout).foregroundStyle(Brand.orange)
                    .symbolEffect(.variableColor.iterative, options: .repeating)
                Text(text)
                    .readingDirection(of: text)
                    .font(large ? .title2.weight(.semibold) : .body.weight(.medium))
                    .multilineTextAlignment(.trailing)
                    .contentTransition(.interpolate)
                    .animation(.easeOut(duration: 0.12), value: text)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(Brand.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(Brand.orange.opacity(0.45), style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
            .frame(maxWidth: 520, alignment: .trailing)
        }
        .accessibilityLabel("Hearing: \(text)")
    }
}

/// Fix what the voice heard. It is told what it heard and what you meant, and fixes anything it did on the wrong words.
struct EditTurnSheet: View {
    let turn: API.Turn
    let send: (String) async -> Bool
    @Environment(\.dismiss) private var dismiss
    @State private var text: String
    @State private var sending = false
    @State private var sent = 0
    @FocusState private var focused: Bool

    init(turn: API.Turn, send: @escaping (String) async -> Bool) {
        self.turn = turn
        self.send = send
        _text = State(initialValue: turn.text)
    }

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 14) {
                Text("Heard").font(.caption.bold()).foregroundStyle(.secondary)
                Text(turn.text).readingDirection(of: turn.text).font(.callout).foregroundStyle(.secondary)
                Text("You meant").font(.caption.bold()).foregroundStyle(.secondary)
                TextField("What you said", text: $text, axis: .vertical)
                    .lineLimit(2...6)
                    .accessibilityIdentifier("fixField")
                    .padding(12)
                    .background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
                    .focused($focused)
                Text("If it already acted on the misheard words, it says what it did and fixes it.")
                    .font(.footnote).foregroundStyle(.secondary)
                Spacer()
            }
            .padding(20)
            .navigationTitle("Fix it")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Send") {
                        sending = true
                        Task {
                            if await send(text.trimmingCharacters(in: .whitespacesAndNewlines)) { sent += 1; dismiss() }
                            sending = false
                        }
                    }
                    .bold()
                    .disabled(sending || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || text == turn.text)
                }
            }
            .onAppear { focused = true }
            .sensoryFeedback(.success, trigger: sent)
        }
    }
}
