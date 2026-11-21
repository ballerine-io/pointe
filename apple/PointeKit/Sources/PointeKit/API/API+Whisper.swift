import Foundation

// The daemon's status and replies, as the page and the apps read them. Every field a newer daemon added is optional:
// an older daemon sends none of them and the status must still decode.

extension API {
    public struct WhisperStatus: Decodable, Equatable, Sendable {
        public let on: Bool
        public var held: String? = nil  // "drive": drive mode holds it, and nothing of whisper mode applies until it ends
        public let output_gain: Double?
        public let max_words: Int?
        public let suggest_ptt: Bool?  // on, and the microphone is not push to talk
        public let lock_note: String?  // the voice lock is on: a whisper may not match the voiceprint

        public init(on: Bool, held: String? = nil, output_gain: Double? = nil, max_words: Int? = nil, suggest_ptt: Bool? = nil, lock_note: String? = nil) {
            self.on = on
            self.held = held
            self.output_gain = output_gain
            self.max_words = max_words
            self.suggest_ptt = suggest_ptt
            self.lock_note = lock_note
        }
    }
}
