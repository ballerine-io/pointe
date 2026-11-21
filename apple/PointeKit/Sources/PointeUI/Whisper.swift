import SwiftUI

/// Whisper mode (docs/features/whisper-mode.md): the Mac answers briefly and plays the voice at half
/// volume; the phone shows it, brings typing forward, and suggests push to talk. The Mac's pref "whisper" is the truth,
/// set here, on the page, or by saying "whisper mode" / "back to normal". The audio itself is changed on the Mac, so the
/// phone sends and plays as always.
extension API {
    struct WhisperStatus: Decodable, Equatable {
        let on: Bool
        var held: String? = nil  // "drive": drive mode holds it, and nothing of whisper mode applies until it ends
        let output_gain: Double?
        let max_words: Int?
        let suggest_ptt: Bool?  // on, and the microphone is not push to talk
        let lock_note: String?  // the voice lock is on: a whisper may not match the voiceprint
    }
}

/// The page's words (ui_whisper.html), word for word.
enum WhisperCopy {
    static let button = "Whisper"
    static let buttonOn = "Whispering"
    static let title = "Whisper mode: short, quiet replies."
    static let limit = "Whisper recognition is limited; type when it matters."
    static let suggest = "Whisper works best with Push to talk. Turn it on?"
    static let turnOn = "Turn on"
    static let notNow = "Not now"
    static let back = "Back to normal"
    static let failed = "Whisper mode did not change: the voice is not reachable."
    static let folded = "Whisper mode"  // the title of a folded card, which shares its one line with Show notes
    static let showNotes = "Show notes"
    static let hideNotes = "Hide notes"

    /// The card folds to its title when the dock leaves it less than its whole height (a small phone with the keyboard
    /// up), unless the notes were asked for. Nothing is measured yet (0): whole.
    static func folds(room: CGFloat, whole: CGFloat, asked: Bool) -> Bool { whole > 0 && room < whole && !asked }
}

/// Follows the Mac's setting. When whisper mode is on at the first look, or turns on (here, on the page or by voice),
/// typing comes forward once; "Not now" on the push-to-talk suggestion lasts until whisper mode ends.
struct WhisperFollow: Equatable {
    private(set) var on: Bool?
    private(set) var pttNotNow = false

    /// True when typing should open now.
    mutating func follow(_ status: API.WhisperStatus?) -> Bool {
        let now = status?.on == true && status?.held == nil
        let opened = now && on != true
        on = now
        if !now { pttNotNow = false }
        return opened
    }

    mutating func notNow() { pttNotNow = true }

    func suggestsPushToTalk(_ status: API.WhisperStatus?) -> Bool {
        status?.on == true && status?.held == nil && status?.suggest_ptt == true && !pttNotNow
    }
}

/// Above the controls while whisper mode is on, like the page's card.
struct WhisperCard: View {
    let status: API.WhisperStatus
    let suggestPushToTalk: Bool
    let pushToTalk: () -> Void
    let notNow: () -> Void
    let back: () -> Void
    @Environment(\.dockRoom) private var room
    @State private var whole: CGFloat = 0  // the unfolded card's height, measured while it shows whole
    @State private var asked = false       // Show notes was tapped while the room is short

    private var short: Bool { WhisperCopy.folds(room: room, whole: whole, asked: false) }
    private var folded: Bool { WhisperCopy.folds(room: room, whole: whole, asked: asked) }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if short {
                ViewThatFits(in: .horizontal) {  // the title and the toggle on one line: the short title if the long one will not fit
                    titleRow(WhisperCopy.title)
                    titleRow(WhisperCopy.folded)
                }
            } else {
                title(WhisperCopy.title)
            }
            if !folded {
                Group {  // read whole, never cut: with the keyboard up the card scrolls in the dock instead
                    Text(WhisperCopy.limit)
                    if let note = status.lock_note { Text(note).accessibilityIdentifier("whisperLockNote") }
                    if suggestPushToTalk { Text(WhisperCopy.suggest) }
                }
                .font(.brand(.footnote)).foregroundStyle(Brand.muted).fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 8) {
                    if suggestPushToTalk {
                        Button(WhisperCopy.notNow, action: notNow).buttonStyle(.brandQuiet).accessibilityIdentifier("whisperNotNow")
                        Button(WhisperCopy.turnOn, action: pushToTalk).buttonStyle(.brandPrimary)
                            .accessibilityIdentifier("whisperPushToTalk")
                    }
                    Button(WhisperCopy.back, action: back).buttonStyle(.brandQuiet).accessibilityIdentifier("whisperOff")
                }
                .font(.brand(.subheadline))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { if !folded { whole = $0 } }
        .onChange(of: short) { if !short { asked = false } }  // the room came back: the next squeeze folds it again
        .padding(.horizontal, 12).padding(.vertical, folded ? 4 : 12)  // folded, one line: an iPhone SE with the keyboard up has about 30 points
        .background(Brand.raised, in: RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Brand.orangeLine))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("whisperCard")
    }

    private func title(_ words: String) -> some View {
        Label(words, systemImage: "waveform.badge.minus").font(.brand(.subheadline, .semibold))
    }

    private func titleRow(_ words: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            title(words).lineLimit(1).fixedSize()
            Spacer(minLength: 0)
            Button(asked ? WhisperCopy.hideNotes : WhisperCopy.showNotes) { withAnimation(.snappy) { asked.toggle() } }
                .font(.brand(.footnote, .semibold)).foregroundStyle(Brand.accent)
                .lineLimit(1).fixedSize()
                .touchTarget(height: 20)
                .accessibilityIdentifier("whisperNotes")
        }
    }
}
