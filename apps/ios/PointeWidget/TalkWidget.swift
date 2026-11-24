import PointeKit
import SwiftUI
import WidgetKit

/// The Home Screen tile: one "Talk to Pointe" button, the same press as the Control's. With the app group (not on a free
/// Personal Team) it also shows whether the Mac is reachable and how many sessions need you, as the app last saw them
/// (TalkSnapshot), with the time; with nothing seen it shows no status at all. It reaches no Mac and holds no key.
struct TalkWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: TalkWidgetKind.home, provider: TalkTimeline()) { entry in
            TalkTile(snapshot: entry.snapshot)
                .containerBackground(WidgetBrand.card, for: .widget)
        }
        .configurationDisplayName(TalkLaunchCopy.name)
        .description(TalkLaunchCopy.widgetAbout)
        .supportedFamilies([.systemSmall])
    }
}

struct TalkEntry: TimelineEntry {
    let date: Date
    let snapshot: TalkSnapshot?
}

struct TalkTimeline: TimelineProvider {
    static let sample = TalkSnapshot(outside: true, paired: true, reach: .ok, mac: "studio", needs: 2, call: .off, at: Date())

    func placeholder(in context: Context) -> TalkEntry { TalkEntry(date: Date(), snapshot: Self.sample) }

    func getSnapshot(in context: Context, completion: @escaping (TalkEntry) -> Void) {
        completion(TalkEntry(date: Date(), snapshot: context.isPreview ? Self.sample : TalkStore()?.snapshot))
    }

    /// One entry, until the app writes a new look and reloads: the widget has nothing of its own to ask.
    func getTimeline(in context: Context, completion: @escaping (Timeline<TalkEntry>) -> Void) {
        completion(Timeline(entries: [TalkEntry(date: Date(), snapshot: TalkStore()?.snapshot)], policy: .never))
    }
}

struct TalkTile: View {
    let snapshot: TalkSnapshot?

    var body: some View {
        Button(intent: TalkIntent()) {
            if let line = TalkLaunchCopy.line(snapshot) { status(line) } else { plain }
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel([TalkLaunchCopy.name, TalkLaunchCopy.line(snapshot), TalkLaunchCopy.needs(snapshot)]
            .compactMap { $0 }.joined(separator: ", "))
    }

    /// Nothing seen of the Mac (none yet, or no app group, as on a free Personal Team): only the button, no status.
    private var plain: some View {
        VStack(spacing: 10) {
            mark(size: 64, symbol: 28)
            Text(TalkLaunchCopy.name)
                .font(.system(size: 15, weight: .semibold)).foregroundStyle(WidgetBrand.text)
                .lineLimit(1).minimumScaleFactor(0.8)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func status(_ line: String) -> some View {
        let ready = snapshot.map { $0.outside && $0.paired && $0.reach == .ok } ?? false
        let needs = ready ? snapshot?.needs ?? 0 : 0
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                mark(size: 36, symbol: 17)
                Spacer(minLength: 0)
                if needs > 0 {
                    Text("\(needs)")
                        .font(.system(size: 13, weight: .semibold)).monospacedDigit()
                        .foregroundStyle(WidgetBrand.onOrange)
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .background(WidgetBrand.orange, in: Capsule())
                }
            }
            Spacer(minLength: 0)
            Text(TalkLaunchCopy.name)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(WidgetBrand.text)
                .lineLimit(1).minimumScaleFactor(0.8)
            HStack(spacing: 5) {
                Circle().fill(ready ? WidgetBrand.successText : WidgetBrand.muted).frame(width: 6, height: 6)
                Text(line).lineLimit(2)
            }
            .font(.system(size: 12)).foregroundStyle(WidgetBrand.muted)
            if let line = TalkLaunchCopy.needs(snapshot) {
                Text(line).font(.system(size: 12, weight: .medium))
                    .foregroundStyle(needs > 0 ? WidgetBrand.accent : WidgetBrand.muted).lineLimit(1)
            }
            if let at = snapshot?.at {
                Text("As of \(at, style: .time)").font(.system(size: 11)).foregroundStyle(WidgetBrand.muted).lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    private func mark(size: CGFloat, symbol: CGFloat) -> some View {
        Image(systemName: "waveform")
            .font(.system(size: symbol, weight: .semibold))
            .foregroundStyle(WidgetBrand.onOrange)
            .frame(width: size, height: size)
            .background(WidgetBrand.orange, in: Circle())
    }
}

#Preview("Reachable, two need you", as: .systemSmall) {
    TalkWidget()
} timeline: {
    TalkEntry(date: .now, snapshot: TalkTimeline.sample)
    TalkEntry(date: .now, snapshot: TalkSnapshot(outside: true, paired: true, reach: .unreachable, mac: "studio", needs: 0, call: .off, at: .now))
    TalkEntry(date: .now, snapshot: nil)
}
