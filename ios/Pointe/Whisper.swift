import SwiftUI

/// Whisper mode (docs/plans/next-features.md, "9. Whisper mode"): the Mac answers briefly and plays the voice at half
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

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label(WhisperCopy.title, systemImage: "waveform.badge.minus").font(.subheadline.weight(.semibold))
            Text(WhisperCopy.limit).font(.footnote).foregroundStyle(.secondary)
            if let note = status.lock_note {
                Text(note).font(.footnote).foregroundStyle(.secondary).accessibilityIdentifier("whisperLockNote")
            }
            if suggestPushToTalk {
                Text(WhisperCopy.suggest).font(.footnote).foregroundStyle(.secondary)
            }
            HStack(spacing: 8) {
                if suggestPushToTalk {
                    Button(WhisperCopy.notNow, action: notNow).buttonStyle(.bordered).accessibilityIdentifier("whisperNotNow")
                    Button(WhisperCopy.turnOn, action: pushToTalk).buttonStyle(.borderedProminent).tint(Brand.orange)
                        .accessibilityIdentifier("whisperPushToTalk")
                }
                Button(WhisperCopy.back, action: back).buttonStyle(.bordered).accessibilityIdentifier("whisperOff")
            }
            .font(.subheadline)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(Brand.orange.opacity(0.45)))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("whisperCard")
    }
}
