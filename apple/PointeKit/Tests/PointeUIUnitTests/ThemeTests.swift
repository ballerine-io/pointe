import CoreText
import SwiftUI
import XCTest
#if canImport(UIKit)
import UIKit
#else
import AppKit
#endif
@testable import PointeUI

/// Brand Guidelines V6 in the app (docs/design/brand-v6.md). The colour values are compared with the page's by
/// tests/test_theme.py, which reads Brand.swift; these hold what only the app can check.
final class ThemeTests: XCTestCase {
    func testTheChoicesAreThePagesAndSystemIsTheDefault() {
        XCTAssertEqual(Theme.allCases.map(\.rawValue), ["system", "light", "dark"])
        XCTAssertEqual(Theme.allCases.map(\.label), ["System", "Light", "Dark"])
        XCTAssertEqual(Theme.fallback, .system)
        XCTAssertEqual(Theme.key, "pointe.theme")
        XCTAssertNil(Theme.system.scheme, "System follows the phone")
        XCTAssertEqual(Theme.light.scheme, .light)
        XCTAssertEqual(Theme.dark.scheme, .dark)
    }

    func testAStoredValueThatIsNotAChoiceFallsBackToSystem() {
        XCTAssertEqual(Theme.stored("dark"), .dark)
        XCTAssertEqual(Theme.stored("sepia"), .system)
        XCTAssertEqual(Theme.stored(nil), .system)
    }

    func testTheBundledFontsLoadByTheNamesTheAppAsksFor() {
        Brand.registerFonts()  // what PointeBoot.start does in an app
        for face in [Brand.displayLight, Brand.displayRegular, Brand.textFace(.regular), Brand.textFace(.medium), Brand.textFace(.semibold)] {
            let font = CTFontCreateWithName(face as CFString, 17, nil)
            XCTAssertEqual(CTFontCopyPostScriptName(font) as String, face, "\(face) is not registered (Brand.registerFonts)")
        }
        XCTAssertEqual(Brand.textFace(.bold), "InstrumentSans-SemiBold", "the brand has no weight above 600")
        XCTAssertEqual(Brand.textFace(.heavy), "InstrumentSans-SemiBold")
    }

    func testAColourFollowsTheAppearance() {
        func hex(_ color: Color, _ style: ColorScheme) -> String {
            var environment = EnvironmentValues()
            environment.colorScheme = style
            let c = color.resolve(in: environment)
            func part(_ linear: Float) -> Int {  // Color.Resolved is linear sRGB
                let v = Double(linear)
                return Int(((v <= 0.0031308 ? v * 12.92 : 1.055 * pow(v, 1 / 2.4) - 0.055) * 255).rounded())
            }
            return String(format: "#%02X%02X%02X", part(c.linearRed), part(c.linearGreen), part(c.linearBlue))
        }
        XCTAssertEqual(hex(Brand.bg, .light), "#FFFFFF")
        XCTAssertEqual(hex(Brand.bg, .dark), "#0A0400")  // warm black, never #000
        XCTAssertEqual(hex(Brand.text, .dark), "#F7F2F0")  // bone, never white
        XCTAssertEqual(hex(Brand.orange, .light), hex(Brand.orange, .dark))
        XCTAssertEqual(hex(Brand.accent, .light), "#C24F0D")
        XCTAssertEqual(hex(Brand.accent, .dark), "#FF8C4A")
    }
}

/// The session list: a harness mark on every session, grouped by machine (docs/design/brand-v6.md, section 9).
final class HarnessMarkTests: XCTestCase {
    private func status(_ json: String) -> API.Status {
        try! JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testEachKnownAgentHasItsNameAndLetterAndAnUnknownOneFallsBackToItsOwn() {
        XCTAssertEqual(Harness.mark("claude-code").name, "Claude"); XCTAssertEqual(Harness.mark("claude-code").glyph, "C")
        XCTAssertEqual(Harness.mark("codex").name, "Codex"); XCTAssertEqual(Harness.mark("codex").glyph, "X")
        XCTAssertEqual(Harness.mark("opencode").name, "OpenCode"); XCTAssertEqual(Harness.mark("opencode").glyph, "O")
        XCTAssertEqual(Harness.mark("pi").name, "Pi"); XCTAssertEqual(Harness.mark("pi").glyph, "P")
        XCTAssertEqual(Harness.mark(nil).name, "Claude", "an older Mac sends no harness: Claude Code")
        XCTAssertEqual(Harness.mark("").name, "Claude")
        XCTAssertEqual(Harness.mark("aider").name, "aider"); XCTAssertEqual(Harness.mark("aider").glyph, "A")
    }

    func testASessionNamesItsAgentFromTheSameTable() {
        let s = status(#"{"connected": true, "sessions": [{"name": "a", "working": false, "waiting": false, "harness": "codex"}, {"name": "b", "working": false, "waiting": false}]}"#)
        XCTAssertEqual(s.sessions.map(\.agent), ["Codex", "Claude"])
        XCTAssertTrue(s.sessions.mixesAgents)
    }

    func testSessionsGroupByNamedMachineWithMixedAgentsAndAnOfflineNode() {
        let s = status("""
        {"connected": true, "mode": "orchestrator",
         "sessions": [{"name": "billing", "working": true, "waiting": false, "harness": "claude-code"},
                      {"name": "shop", "working": false, "waiting": true, "request_id": "r1", "machine": "devbox", "online": true, "harness": "codex"},
                      {"name": "api", "working": true, "waiting": false, "machine": "devbox", "online": true, "harness": "opencode"},
                      {"name": "notes", "working": false, "waiting": false, "machine": "laptop", "online": false, "harness": "pi"}],
         "machines": [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true},
                      {"id": "n1", "name": "devbox", "here": false, "os": "linux", "online": true, "rtt_ms": 23},
                      {"id": "n2", "name": "laptop", "here": false, "os": "macos", "online": false, "since": 1794400000}]}
        """)
        let view = MachineView(s)
        XCTAssertTrue(view.multi)
        XCTAssertEqual(view.names, ["studio", "devbox", "laptop"], "this Mac first, each machine by its own name")
        XCTAssertEqual(view.onMachine("studio").map(\.name), ["billing"])
        XCTAssertEqual(byAttention(view.onMachine("devbox")).map(\.name), ["shop", "api"], "inside a machine: what needs you first")
        XCTAssertEqual(view.onMachine("devbox").map { Harness.mark($0.harness).glyph }, ["X", "O"])
        XCTAssertTrue(view.isOffline("laptop")); XCTAssertFalse(view.isOffline("devbox"))
        XCTAssertEqual(view.header("studio"), "studio · this Mac")
        XCTAssertEqual(view.header("devbox"), "devbox · Linux · 23 ms")
        XCTAssertTrue(view.header("laptop").hasPrefix("laptop · macOS · offline since "))
    }

    func testOneMachineHasNoGroups() {
        let s = status(#"{"connected": true, "sessions": [{"name": "a", "working": false, "waiting": false}], "machines": [{"id": "hub", "name": "studio", "here": true, "os": "macos", "online": true}]}"#)
        XCTAssertFalse(MachineView(s).multi)
        XCTAssertFalse(MachineView(status(#"{"connected": true, "sessions": []}"#)).multi, "a Mac without machines: as before")
    }
}

/// "Keeping your Mac awake": one quiet line on a live call while the Mac says so (mac.py KeepAwake, /voice/status).
final class KeepAwakeTests: XCTestCase {
    private func status(_ json: String) -> API.Status {
        try! JSONDecoder().decode(API.Status.self, from: Data(json.utf8))
    }

    func testTheLineShowsOnlyOnALiveCallWhileTheMacKeepsItselfAwake() {
        let on = status(#"{"connected": true, "sessions": [], "keep_awake": {"on": true, "why": "a call from the phone, on AC power"}}"#)
        XCTAssertEqual(on.keep_awake?.why, "a call from the phone, on AC power")
        XCTAssertEqual(API.KeepAwake.shown(on, live: true), "Keeping your Mac awake")
        XCTAssertNil(API.KeepAwake.shown(on, live: false), "no call here: nothing to say")
        let off = status(#"{"connected": true, "sessions": [], "keep_awake": {"on": false, "why": null}}"#)
        XCTAssertNil(API.KeepAwake.shown(off, live: true))
        let older = status(#"{"connected": true, "sessions": []}"#)
        XCTAssertNil(older.keep_awake, "an older Mac sends no such field")
        XCTAssertNil(API.KeepAwake.shown(older, live: true))
        XCTAssertNil(API.KeepAwake.shown(nil, live: true))
    }
}
