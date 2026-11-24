import SwiftUI

/// What was said, oldest first, and what you are saying now as the last bubble. Your turns can be tapped to fix a word.
struct ConversationView: View {
    let turns: [API.Turn]
    let polish: Bool
    let hearing: String
    var draft: String? = nil  // push to talk: the hearing is a press's words, not sent yet (TalkDraft)
    var large = false  // whisper mode: the words heard so far, big enough to check before they are acted on
    var placeholder = true  // false while the Connect stage stands where the words will be (no call up yet)
    var reading = false  // reading mode: Pointe's lines say Unread or Read, and a tap on one reads it and those before it
    var markRead: (API.Turn) -> Void = { _ in }
    var outgoing: [Outbox.Line] = []  // typed lines on their way: shown at once, under the conversation
    var retry: (String) -> Void = { _ in }
    let edit: (API.Turn) -> Void
    @Namespace private var speech

    var body: some View {
        if turns.isEmpty && hearing.isEmpty && outgoing.isEmpty {
            if placeholder {
                EmptyNote(title: "Nothing said yet", symbol: "waveform",
                          text: Surface.isMac ? "Talk, or press Type to type. Click anything you said to fix it."
                                              : "Talk, or tap the keyboard to type. Tap anything you said to fix it.")
                    .padding(.top, 40)
            }
        } else {
            LazyVStack(spacing: 0) {
                ForEach(Array(turns.enumerated()), id: \.element.id) { index, turn in
                    let next = index + 1 < turns.count ? turns[index + 1] : nil
                    let groupEnd = next?.who != turn.who
                    let newestMine = turn.mine && turn.id == turns.last?.id && hearing.isEmpty
                    Bubble(turn: turn, polish: polish, pending: polish && turn.id == turns.last(where: \.mine)?.id,
                           tail: groupEnd, readMark: reading && !turn.mine ? turn.unread == true : nil)
                        // the live bubble becomes this one: same place, same shape, so it flows instead of jumping
                        .matchedGeometryEffect(id: newestMine ? "speech" : "turn-\(turn.id)", in: speech)
                        .onTapGesture { if turn.mine { edit(turn) } else if reading { markRead(turn) } }
                        .padding(.bottom, groupEnd ? 14 : 4)
                        .transition(.opacity)
                }
                ForEach(outgoing) { line in
                    OutgoingBubble(line: line) { retry(line.id) }
                        .transition(.opacity)
                }
                if !hearing.isEmpty {
                    LiveBubble(text: hearing, large: large, draft: draft)
                        .matchedGeometryEffect(id: "speech", in: speech)
                        .padding(.bottom, 14)
                        .transition(.opacity)
                }
            }
            .animation(.smooth(duration: 0.35), value: turns.last?.id)
            .animation(.smooth(duration: 0.2), value: outgoing)
            .animation(.smooth(duration: 0.35), value: hearing.isEmpty)
        }
    }
}

struct Bubble: View {
    let turn: API.Turn
    let polish: Bool
    var pending = false
    var tail = true
    var readMark: Bool? = nil  // reading mode, one of Pointe's lines: true unread, false read; nil shows nothing
    @Environment(\.layoutDirection) private var direction

    var body: some View {
        HStack(alignment: .bottom, spacing: 0) {
            if turn.mine { Spacer(minLength: 56) }
            VStack(alignment: turn.mine ? Bubble.textStart(turn.text, in: direction) : .leading, spacing: 4) {
                if turn.mine, polish, let understood = turn.understood, understood != turn.text {
                    Text(turn.text).readingDirection(of: turn.text).font(.brand(.footnote)).foregroundStyle(Brand.muted)
                    Text(understood).readingDirection(of: understood)
                } else {
                    Text(turn.text).readingDirection(of: turn.text)
                }
                if turn.mine && (turn.typed == true || turn.corrected == true || (pending && turn.understood == nil)) {
                    badges
                }
                if let readMark { ReadMark(unread: readMark) }
            }
            .font(.brand(.body))
            .lineSpacing(2)
            .multilineTextAlignment(.leading)  // your bubble sits at the right; its lines start where the text reads from
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(turn.mine ? Brand.raised : Brand.card, in: shape)
            .overlay(shape.stroke(Brand.line))
            .frame(maxWidth: 520, alignment: turn.mine ? .trailing : .leading)
            if !turn.mine { Spacer(minLength: 56) }
        }
        .contentShape(Rectangle())
        .netProbe(turn.text)
        .accessibilityElement(children: .combine)
        .accessibilityLabel((turn.mine ? "You: " : "Pointe: ") + (turn.understood ?? turn.text))
        .accessibilityHint(turn.mine ? "Double-tap to fix what was heard" : readMark == true ? "Double-tap to mark it read" : "")
    }

    /// Where a text's lines start inside a bubble, on a screen laid out in `direction`: English on the left, Hebrew on the
    /// right, whichever side the bubble is on.
    static func textStart(_ text: String, in direction: LayoutDirection) -> HorizontalAlignment {
        TextDirection.of(text) == direction ? .leading : .trailing
    }

    private var shape: UnevenRoundedRectangle {
        let small: CGFloat = tail ? 3 : 16  // the brand's radius scale: 16 for a bubble, 3 where it points at its speaker
        return UnevenRoundedRectangle(topLeadingRadius: 16, bottomLeadingRadius: turn.mine ? 16 : small,
                                      bottomTrailingRadius: turn.mine ? small : 16, topTrailingRadius: 16)
    }

    private var badges: some View {
        HStack(spacing: 6) {
            if turn.typed == true { Label("typed", systemImage: "keyboard") }
            if turn.corrected == true { Label("edited", systemImage: "pencil") }
            if pending && turn.understood == nil && turn.corrected != true { Label("cleaning up", systemImage: "wand.and.sparkles") }
        }
        .labelStyle(.titleAndIcon)
        .font(.brand(.caption2))
        .foregroundStyle(Brand.muted)
    }
}

/// What you are saying right now: the last bubble in the conversation, live, until the sentence is done.
struct LiveBubble: View {
    let text: String
    var large = false
    var draft: String? = nil
    @Environment(\.layoutDirection) private var direction

    var body: some View {
        HStack(alignment: .bottom, spacing: 0) {
            Spacer(minLength: 56)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: "waveform").font(.brand(.callout)).foregroundStyle(Brand.accent)
                    .symbolEffect(.variableColor.iterative, options: .repeating)
                VStack(alignment: Bubble.textStart(text, in: direction), spacing: 2) {
                    if let draft {
                        Text(draft).font(.brand(.caption, .semibold)).foregroundStyle(Brand.accent)
                            .accessibilityIdentifier("talkDraft")
                    }
                    Text(text)
                        .readingDirection(of: text)
                        .font(large ? .brand(.title2) : .brand(.body, .medium))  // the brand has no italic: a draft is muted
                        .foregroundStyle(draft != nil ? AnyShapeStyle(Brand.muted) : AnyShapeStyle(.primary))
                        .multilineTextAlignment(.leading)
                        .contentTransition(.interpolate)
                        .animation(.easeOut(duration: 0.12), value: text)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(Brand.tint, in: RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
            .frame(maxWidth: 520, alignment: .trailing)
        }
        .accessibilityLabel(draft.map { "\($0): \(text)" } ?? "Hearing: \(text)")
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
            ScrollView {  // at large text every word of what was heard shows: it is what the person is here to check
            VStack(alignment: .leading, spacing: 8) {  // a label sits on what it names; the two groups stand apart
                Text("Heard").brandKicker()
                Text(turn.text).readingDirection(of: turn.text).font(.brand(.callout)).foregroundStyle(Brand.muted)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("fixHeard")
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.bottom, 12)
                Text("You meant").brandKicker()
                TextField("What you said", text: $text, axis: .vertical)
                    .lineLimit(2...6)
                    .accessibilityIdentifier("fixField")
                    .padding(12)
                    .background(Brand.card, in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(Brand.line))
                    .focused($focused)
                Text("If it already acted on the misheard words, it says what it did and fixes it.")
                    .font(.brand(.footnote)).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
            }
            .padding(20)
            }
            .scrollBounceBehavior(.basedOnSize)
            .sheetTitle("Fix it")
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
