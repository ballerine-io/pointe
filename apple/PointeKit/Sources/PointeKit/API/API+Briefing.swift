import Foundation

// The daemon's status and replies, as the page and the apps read them. Every field a newer daemon added is optional:
// an older daemon sends none of them and the status must still decode.

extension API {
    public struct BriefingStatus: Decodable, Equatable, Sendable {
        public var playing: Bool?
        public var paused: String?         // "", "question" (the user asked something), "press" (push to talk)
        public var part: Int?
        public var parts: Int?
        public let id: String?
        public var building: Bool?
        public let latest_id: String?
        public var ready: BriefingReady?   // a scheduled briefing not heard yet

        public var isPlaying: Bool { playing == true }
        public var isPaused: Bool { !(paused ?? "").isEmpty }
        public var isOn: Bool { isPlaying || isPaused }

        public init(playing: Bool? = nil, paused: String? = nil, part: Int? = nil, parts: Int? = nil, id: String? = nil, building: Bool? = nil, latest_id: String? = nil, ready: BriefingReady? = nil) {
            self.playing = playing
            self.paused = paused
            self.part = part
            self.parts = parts
            self.id = id
            self.building = building
            self.latest_id = latest_id
            self.ready = ready
        }
    }

    public struct BriefingReady: Decodable, Equatable, Sendable {
        public let id: String
        public let at: Double?
        public let slot: String?
        public let empty: Bool?

        public init(id: String, at: Double? = nil, slot: String? = nil, empty: Bool? = nil) {
            self.id = id
            self.at = at
            self.slot = slot
            self.empty = empty
        }
    }

    public struct BriefingSection: Decodable, Equatable, Hashable, Sendable {
        public let session: String
        public let status: String          // waiting, failed, done, quiet
        public let text: String

        public init(session: String, status: String, text: String) {
            self.session = session
            self.status = status
            self.text = text
        }
    }

    public struct Briefing: Decodable, Equatable, Identifiable, Sendable {
        public let id: String
        public let at: Double
        public let since_label: String?
        public let length: String?
        public let sections: [BriefingSection]?
        public let opener: String?
        public let scheduled: Bool?
        public let empty: Bool?

        public init(id: String, at: Double, since_label: String? = nil, length: String? = nil, sections: [BriefingSection]? = nil, opener: String? = nil, scheduled: Bool? = nil, empty: Bool? = nil) {
            self.id = id
            self.at = at
            self.since_label = since_label
            self.length = length
            self.sections = sections
            self.opener = opener
            self.scheduled = scheduled
            self.empty = empty
        }
    }

    public struct BriefingSchedule: Decodable, Equatable, Sendable {
        public var time: String
        public var days: [Int]
        public var length: String
        public var speak_on_connect: Bool
        public var skip_empty: Bool

        public init(time: String, days: [Int], length: String, speak_on_connect: Bool, skip_empty: Bool) {
            self.time = time
            self.days = days
            self.length = length
            self.speak_on_connect = speak_on_connect
            self.skip_empty = skip_empty
        }
    }

    public struct BriefingsPage: Decodable, Sendable {
        public let briefings: [Briefing]?
        public let schedule: BriefingSchedule?
        public let status: BriefingStatus?

        public init(briefings: [Briefing]? = nil, schedule: BriefingSchedule? = nil, status: BriefingStatus? = nil) {
            self.briefings = briefings
            self.schedule = schedule
            self.status = status
        }
    }
}
