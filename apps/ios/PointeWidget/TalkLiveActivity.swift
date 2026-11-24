import ActivityKit
import AppIntents
import PointeKit
import SwiftUI
import WidgetKit

/// The call on the Lock Screen and in the Dynamic Island once you leave the app with a press's call up (iOS shows it
/// only then): what it is doing, and its buttons (TalkActivityState.Kind). Send closes the press; Cancel and Hang up end the call, and an open press
/// is never sent. The buttons run in the app (they are Live Activity intents); none of them approves anything.
struct TalkLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: TalkActivityAttributes.self) { context in
            TalkActivityCard(state: context.state)
                .activityBackgroundTint(WidgetBrand.card)
                .activitySystemActionForegroundColor(WidgetBrand.text)
        } dynamicIsland: { context in
            let state = context.state
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) { TalkMark(state: state).padding(.leading, 4) }
                DynamicIslandExpandedRegion(.trailing) { NeedsBadge(needs: state.needs).padding(.trailing, 4) }
                DynamicIslandExpandedRegion(.center) {
                    VStack(spacing: 2) {
                        Text(state.title).font(.system(size: 15, weight: .semibold)).lineLimit(1)
                        Text(state.detail).font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(1)
                    }
                }
                DynamicIslandExpandedRegion(.bottom) { TalkButtons(kind: state.kind).padding(.top, 4) }
            } compactLeading: {
                TalkMark(state: state)
            } compactTrailing: {
                Text(state.needs > 0 ? "\(state.needs)" : "")  // the compact island opens the app on a tap: no Send here
                    .font(.system(size: 13, weight: .semibold)).foregroundStyle(WidgetBrand.orange)
            } minimal: {
                TalkMark(state: state)
            }
            .keylineTint(WidgetBrand.orange)
        }
    }
}

/// The Lock Screen's banner: the state line, Pointe's Mac, and the buttons.
struct TalkActivityCard: View {
    let state: TalkActivityState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                TalkMark(state: state)
                VStack(alignment: .leading, spacing: 1) {
                    Text(state.title).font(.system(size: 17, weight: .semibold)).foregroundStyle(WidgetBrand.text).lineLimit(1)
                    Text("\(state.mac) · \(state.detail)").font(.system(size: 13)).foregroundStyle(WidgetBrand.muted).lineLimit(1)
                }
                Spacer(minLength: 0)
                NeedsBadge(needs: state.needs)
            }
            TalkButtons(kind: state.kind)
        }
        .padding(14)
    }
}

/// Orange while a press is open, as the mic ring is.
struct TalkMark: View {
    let state: TalkActivityState

    var body: some View {
        Image(systemName: state.kind == .talking ? "waveform" : state.kind == .connecting ? "phone.arrow.up.right" : "mic.fill")
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(state.kind == .talking ? WidgetBrand.onOrange : WidgetBrand.orange)
            .frame(width: 28, height: 28)
            .background(state.kind == .talking ? WidgetBrand.orange : WidgetBrand.raised, in: Circle())
            .accessibilityHidden(true)
    }
}

struct NeedsBadge: View {
    let needs: Int

    var body: some View {
        if needs > 0 {
            Text(TalkLaunchCopy.needYou(needs))
                .font(.system(size: 12, weight: .semibold)).foregroundStyle(WidgetBrand.accent).lineLimit(1)
        }
    }
}

/// Talking: Send and Cancel. On a call with no press: Talk and Hang up. Always on: Hang up. Dialling: Cancel.
struct TalkButtons: View {
    let kind: TalkActivityState.Kind

    var body: some View {
        HStack(spacing: 8) {
            switch kind {
            case .talking:
                quiet(TalkLaunchCopy.cancel, "xmark")
                primary(TalkLaunchCopy.send, "arrow.up", SendTalkIntent())
            case .ready:
                quiet(TalkLaunchCopy.hangUp, "phone.down.fill")
                primary(TalkLaunchCopy.talk, "mic.fill", TalkIntent())
            case .listening:
                quiet(TalkLaunchCopy.hangUp, "phone.down.fill")
            case .connecting:
                quiet(TalkLaunchCopy.cancel, "xmark")
            case .ended:
                EmptyView()
            }
        }
    }

    private func quiet(_ title: String, _ symbol: String) -> some View {
        Button(intent: CancelTalkIntent()) {
            Label(title, systemImage: symbol).font(.system(size: 14, weight: .semibold)).frame(maxWidth: .infinity, minHeight: 36)
        }
        .buttonStyle(.plain)
        .foregroundStyle(WidgetBrand.text)
        .background(WidgetBrand.raised, in: RoundedRectangle(cornerRadius: 12))
    }

    private func primary(_ title: String, _ symbol: String, _ intent: some AppIntent) -> some View {
        Button(intent: intent) {
            Label(title, systemImage: symbol).font(.system(size: 14, weight: .semibold)).frame(maxWidth: .infinity, minHeight: 36)
        }
        .buttonStyle(.plain)
        .foregroundStyle(WidgetBrand.onOrange)
        .background(WidgetBrand.orange, in: RoundedRectangle(cornerRadius: 12))
    }
}

#Preview("Talking", as: .content, using: TalkActivityAttributes(started: .now)) {
    TalkLiveActivity()
} contentStates: {
    TalkActivityState.of(call: .live, ptt: true, pressOpen: true, speaking: false, note: nil, needs: 2, mac: "studio")
    TalkActivityState.of(call: .live, ptt: true, pressOpen: false, speaking: false, note: "Sent", needs: 0, mac: "studio")
    TalkActivityState.of(call: .live, ptt: false, pressOpen: false, speaking: false, note: nil, needs: 1, mac: "studio")
}
