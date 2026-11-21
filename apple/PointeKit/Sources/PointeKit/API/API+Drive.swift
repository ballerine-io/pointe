import Foundation

// The daemon's status and replies, as the page and the apps read them. Every field a newer daemon added is optional:
// an older daemon sends none of them and the status must still decode.

extension API {
    public struct DriveStatus: Decodable, Equatable, Sendable {
        public var on: Bool
        public let since: Double?
        public let how: String?            // "voice" or "button"
        public var pending: [DrivePending]?

        public init(on: Bool, since: Double? = nil, how: String? = nil, pending: [DrivePending]? = nil) {
            self.on = on
            self.since = since
            self.how = how
            self.pending = pending
        }
    }

    /// A request waiting now, and whether a spoken yes may answer it while driving.
    public struct DrivePending: Decodable, Equatable, Sendable {
        public let session: String
        public let request_id: String?
        public let voice: Bool

        public init(session: String, request_id: String? = nil, voice: Bool) {
            self.session = session
            self.request_id = request_id
            self.voice = voice
        }
    }
}
