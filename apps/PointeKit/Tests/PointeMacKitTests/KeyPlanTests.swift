#if os(macOS)
import Testing
@testable import PointeMacKit

@Suite struct KeyPlanTests {
    @Test(arguments: [Set<Vendor>([.gemini]), [.openai], [.soniox, .anthropic]])
    func eachStartSetFillsEveryRole(_ keys: Set<Vendor>) {
        let plan = KeyPlan(present: keys)
        #expect(plan.ready && plan.fix == nil)
        #expect(Vendor.allCases.filter { !keys.contains($0) }.allSatisfy { plan.state($0) == .optional })
        #expect(plan.line == "\(KeyCopy.noSetupHead)\(KeyCopy.allFilled) \(KeyCopy.othersOptional)")
    }

    @Test func noKeyAsksForGemini() {
        let plan = KeyPlan(present: [])
        #expect(plan.fix == .gemini && !plan.ready && plan.state(.gemini) == .needed && plan.state(.anthropic) == .optional)
        #expect(plan.line.hasPrefix(KeyCopy.noKey) && plan.line.contains(KeyCopy.whatYouNeed))
    }

    @Test func anthropicAloneNeedsOneVoiceKey() {
        let plan = KeyPlan(present: [.anthropic])
        #expect(plan.empty == ["ears", "mouth"] && plan.fix == .soniox)
        #expect(plan.state(.anthropic) == .inUse && plan.state(.soniox) == .needed && plan.state(.elevenlabs) == .optional)
        #expect(plan.line == "Pointe cannot hear you or speak yet: add a Soniox key.")
    }

    @Test func sonioxAloneNeedsAnthropic() {
        let plan = KeyPlan(present: [.soniox])
        #expect(plan.fix == .anthropic)
        #expect(plan.line == "Pointe cannot think, read your sessions or check each send yet: add an Anthropic key.")
    }

    @Test func aKeyThatNoRoleReachesIsSavedNotUsed() {
        let plan = KeyPlan(present: [.anthropic, .soniox, .elevenlabs, .gemini, .openai])
        #expect(plan.state(.openai) == .notUsed && plan.state(.gemini) == .inUse)
        #expect(plan.line == KeyCopy.noSetupHead + KeyCopy.allFilled)
    }

    /// The setup guide drew a green "Every role is filled." over "Setup: None chosen": with no setup chosen the line
    /// says so, and whose keys fill the roles.
    @Test func noSetupChosenIsSaidBeforeEveryRoleIsFilled() {
        let plan = KeyPlan(present: [.gemini])
        #expect(plan.setup == nil && plan.ready)
        #expect(plan.line.hasPrefix("Setup: \(KeyCopy.noSetup), so Pointe uses the keys you have. "))
    }

    @Test func aChosenSetupNeedsItsOwnKeysAndNoOthers() {
        let two = SetupChoice.named("two")
        let plan = KeyPlan(present: [.anthropic, .gemini], setup: two)
        #expect(plan.needed == [.soniox] && !plan.ready)
        #expect(plan.state(.gemini) == .notUsed && plan.state(.anthropic) == .inUse && plan.state(.elevenlabs) == .optional)
        #expect(plan.line == "Setup: Two keys. It needs a Soniox key: pointe key soniox.")
    }

    @Test func aChosenSetupWithItsKeysIsReadyAndIgnoresTheRest() {
        let plan = KeyPlan(present: [.gemini, .openai], setup: SetupChoice.named("free"))
        #expect(plan.ready && plan.state(.openai) == .notUsed && plan.state(.soniox) == .optional)
        #expect(plan.line == "Setup: Free start. \(KeyCopy.allFilled) \(KeyCopy.othersOptional)")
    }

    @Test func theLocalSetupsFillTheirRolesOnTheMac() {
        #expect(KeyPlan(present: [], setup: SetupChoice.named("local")).ready)
        #expect(KeyPlan(present: [.anthropic], setup: SetupChoice.named("voice-local")).ready)
        #expect(KeyPlan(present: [], setup: SetupChoice.named("voice-local")).needed == [.anthropic])
    }
}
#endif
