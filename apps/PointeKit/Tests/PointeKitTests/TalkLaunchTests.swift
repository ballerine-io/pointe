import Foundation
import Testing
@testable import PointeKit

/// "Talk to Pointe" from outside the app (docs/features/push-to-talk.md): what a press does, when a call may start,
/// what the Live Activity and the widget say.
@Suite struct TalkLaunchTests {
    typealias Now = TalkLaunch.Now

    @Test func aPressStartsACallThenOpensAndSendsPresses() {
        #expect(TalkLaunch.press(Now(call: .off)) == .start)
        #expect(TalkLaunch.press(Now(call: .live, ptt: true, pressOpen: false)) == .open)
        #expect(TalkLaunch.press(Now(call: .live, ptt: true, pressOpen: true)) == .send, "the second press sends")
    }

    @Test func aPressWhileTheCallIsDialledChangesNothing() {
        #expect(TalkLaunch.press(Now(call: .connecting)) == .wait)
        #expect(TalkLaunch.press(Now(call: .reconnecting)) == .wait)
    }

    @Test func alwaysOnIsNeverHungUpByAPress() {
        #expect(TalkLaunch.press(Now(call: .live, ptt: false)) == .refuse(.alwaysOn))
        #expect(TalkLaunch.press(Now(call: .live, ptt: false, pressOpen: true)) == .refuse(.alwaysOn))
    }

    @Test func unpairedOrSwitchedOffStartsNothing() {
        #expect(TalkLaunch.press(Now(paired: false, call: .off)) == .refuse(.notPaired))
        #expect(TalkLaunch.press(Now(outside: false, call: .off)) == .refuse(.noCall), "off: only a call already up")
        #expect(TalkLaunch.press(Now(outside: false, call: .live, pressOpen: false)) == .open, "off still talks on a call that is up")
        #expect(TalkLaunch.press(Now(outside: false, call: .live, pressOpen: true)) == .send)
    }

    @Test func sendOnlyClosesAnOpenPress() {
        #expect(TalkLaunch.send(Now(call: .live, ptt: true, pressOpen: true)) == .send)
        #expect(TalkLaunch.send(Now(call: .live, ptt: true, pressOpen: false)) == .wait, "a late Send does not open a press")
        #expect(TalkLaunch.send(Now(call: .off, pressOpen: true)) == .wait)
        #expect(TalkLaunch.send(Now(call: .live, ptt: false, pressOpen: true)) == .wait)
    }

    @Test func onlySessionModeIsSwitchedToTheOrchestrator() {
        #expect(TalkLaunch.orchestrates(mode: "session"))
        #expect(!TalkLaunch.orchestrates(mode: "orchestrator"))
        #expect(!TalkLaunch.orchestrates(mode: "challenge"), "a challenge on the Mac is left alone")
        #expect(!TalkLaunch.orchestrates(mode: nil))
    }

    @Test func theLiveActivityShowsTheCallsStateAndItsButtons() {
        func of(_ call: TalkLaunch.Phase, ptt: Bool = true, open: Bool = false, speaking: Bool = false, note: String? = nil) -> TalkActivityState {
            TalkActivityState.of(call: call, ptt: ptt, pressOpen: open, speaking: speaking, note: note, needs: 2, mac: "studio")
        }
        #expect(of(.connecting).kind == .connecting && of(.connecting).title == "Calling studio…")
        #expect(of(.reconnecting).kind == .connecting)
        #expect(of(.live, open: true) == TalkActivityState(kind: .talking, title: "Talking · tap to send",
                                                           detail: "Orchestrator", needs: 2, mac: "studio"))
        #expect(of(.live).kind == .ready && of(.live).title == "On a call")
        #expect(of(.live, note: "Sent").title == "Sent", "the call screen's line right after a send")
        #expect(of(.live, speaking: true, note: "Sent").title == "Speaking")
        #expect(of(.live, ptt: false).kind == .listening && of(.live, ptt: false).title == "Listening")
        #expect(of(.off).kind == .ended && of(.off).detail == "Nothing was sent")
        #expect(TalkActivityState.of(call: .off, ptt: true, pressOpen: false, speaking: false, note: nil, needs: 0, mac: "studio",
                                     problem: "studio did not answer.").detail == "studio did not answer.")
    }

    @Test func theWidgetSaysWhatTheAppLastSaw() {
        let at = Date(timeIntervalSince1970: 1_800_000_000)
        let base = TalkSnapshot(outside: true, paired: true, reach: .ok, mac: "studio", needs: 0, call: .off, at: at)
        #expect(TalkLaunchCopy.line(nil) == nil, "no look at the Mac (none yet, or no app group): the widget is only its button")
        #expect(TalkLaunchCopy.needs(nil) == nil)
        #expect(TalkLaunchCopy.line(base) == "studio is reachable" && TalkLaunchCopy.needs(base) == "Nothing needs you")
        var s = base
        s.needs = 1
        #expect(TalkLaunchCopy.needs(s) == "1 needs you")
        s.needs = 3
        #expect(TalkLaunchCopy.needs(s) == "3 need you", "the call screen's words: \"· 3 need you\"")
        s.call = .live
        #expect(TalkLaunchCopy.line(s) == "On a call with studio")
        s.reach = .unreachable
        #expect(TalkLaunchCopy.line(s) == "studio is not reachable" && TalkLaunchCopy.needs(s) == nil, "no count from a Mac that did not answer")
        s.reach = .rejected
        #expect(TalkLaunchCopy.line(s) == "Pair this phone again")
        s.paired = false
        #expect(TalkLaunchCopy.line(s) == "Pair with your Mac in Pointe")
        s.outside = false
        #expect(TalkLaunchCopy.line(s) == "Off in Pointe's settings")
    }

    @Test func theStorePublishesOnlyWhatIsNewOrOld() throws {
        let name = "TalkLaunchTests.store"
        let defaults = try #require(UserDefaults(suiteName: name))
        defaults.removePersistentDomain(forName: name)
        defer { defaults.removePersistentDomain(forName: name) }
        let store = TalkStore(defaults: defaults)
        #expect(store.outside, "on unless turned off")
        store.outside = false
        #expect(!store.outside)

        let at = Date(timeIntervalSince1970: 1_800_000_000)
        let first = TalkSnapshot(outside: true, paired: true, reach: .ok, mac: "studio", needs: 0, call: .off, at: at)
        #expect(store.publish(first))
        #expect(store.snapshot == first)
        var same = first
        same.at = at.addingTimeInterval(30)
        #expect(!store.publish(same), "nothing new: the widget is not reloaded on every poll")
        same.at = at.addingTimeInterval(TalkSnapshot.refreshAfter + 1)
        #expect(store.publish(same), "an old look is written again, so its time stays near")
        var changed = same
        changed.needs = 2
        changed.at = same.at.addingTimeInterval(1)
        #expect(store.publish(changed))
        #expect(store.snapshot?.needs == 2)
    }

    @Test func noAppGroupMeansNoStore() {
        #expect(TalkStore(bundle: Bundle(for: Marker.self)) == nil, "a bundle without PointeAppGroup")
    }
}

private final class Marker {}
