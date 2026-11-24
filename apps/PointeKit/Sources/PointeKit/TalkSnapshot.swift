import Foundation
#if os(iOS)
import ActivityKit
#endif

/// What the Home Screen widget shows, written by the app each time it hears from the Mac (a status poll, a background
/// refresh) into the app group the widget reads. The widget holds no key and reaches no Mac: it shows the app's last
/// look, with its time. Only a count of what needs you, never a session's name or a request's text.
public struct TalkSnapshot: Codable, Equatable, Sendable {
    public enum Reach: String, Codable, Sendable { case ok, unreachable, rejected }

    public var outside: Bool
    public var paired: Bool
    public var reach: Reach
    public var mac: String
    public var needs: Int
    public var call: TalkLaunch.Phase
    public var at: Date

    public init(outside: Bool, paired: Bool, reach: Reach, mac: String, needs: Int, call: TalkLaunch.Phase, at: Date) {
        self.outside = outside
        self.paired = paired
        self.reach = reach
        self.mac = mac
        self.needs = needs
        self.call = call
        self.at = at
    }

    /// The same on screen: only the time differs. The widget is reloaded when this is false, or the last look is old.
    public func shows(like other: TalkSnapshot?) -> Bool {
        guard var other else { return false }
        other.at = at
        return other == self
    }

    /// A look older than this is written again even when nothing changed, so the widget's "as of" stays near.
    public static let refreshAfter: TimeInterval = 5 * 60
}

/// The widget extension's kinds, which the app reloads by name.
public enum TalkWidgetKind {
    public static let home = "io.ballerine.pointe.talk.widget"
    public static let control = "io.ballerine.pointe.talk.control"
    public static let activity = "io.ballerine.pointe.talk.activity"
}

/// The app group both the app and its widget extension belong to. Its name is in each one's Info.plist (`PointeAppGroup`,
/// `group.` plus the app's bundle ID, set by the build): a team that builds Pointe under its own bundle ID gets its own
/// group. Nil when the build is not signed into the group (POINTE_SHARE_GROUP=NO, the project's default, which a free
/// Personal Team needs: its profiles carry no App Groups): the setting then lives in the app's own defaults, the widget
/// shows no Mac status, and everything else of Talk to Pointe works, since it runs in the app.
public struct TalkStore: @unchecked Sendable {  // UserDefaults is thread-safe
    public static let infoKey = "PointeAppGroup"
    static let snapshotKey = "talk.snapshot"
    static let outsideKey = "talk.outside"

    let defaults: UserDefaults

    public init?(bundle: Bundle = .main) {
        guard let group = bundle.object(forInfoDictionaryKey: Self.infoKey) as? String, group.hasPrefix("group."),
              FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: group) != nil,
              let defaults = UserDefaults(suiteName: group) else { return nil }
        self.defaults = defaults
    }

    /// This app's own defaults, when there is no group: the setting still holds, and no widget reads the rest.
    public init(defaults: UserDefaults) { self.defaults = defaults }

    /// Settings → "Talk from outside the app". On unless turned off.
    public var outside: Bool {
        get { defaults.object(forKey: Self.outsideKey) as? Bool ?? true }
        nonmutating set { defaults.set(newValue, forKey: Self.outsideKey) }
    }

    public var snapshot: TalkSnapshot? {
        get { defaults.data(forKey: Self.snapshotKey).flatMap { try? JSONDecoder().decode(TalkSnapshot.self, from: $0) } }
        nonmutating set { defaults.set(newValue.flatMap { try? JSONEncoder().encode($0) }, forKey: Self.snapshotKey) }
    }

    /// Writes `fresh` when it shows something new, or the last look is older than `refreshAfter`. True when written:
    /// the caller then reloads the widget.
    @discardableResult
    public func publish(_ fresh: TalkSnapshot) -> Bool {
        if let last = snapshot, fresh.shows(like: last), fresh.at.timeIntervalSince(last.at) < TalkSnapshot.refreshAfter { return false }
        snapshot = fresh
        return true
    }
}

#if os(iOS)
/// The Live Activity of a call a press from outside the app started or pressed: the call on the Lock Screen and in the
/// Dynamic Island once you leave the app. One type for the app, which starts and updates it, and the widget extension,
/// which draws it.
public struct TalkActivityAttributes: ActivityAttributes {
    public typealias ContentState = TalkActivityState
    public let started: Date

    public init(started: Date) { self.started = started }
}
#endif
