import Foundation

/// The mute button's requests to the Mac (both apps: the status line's button and the Mac's play/pause key), one at a
/// time in the order of the taps, as the page sends them (ui_mute.html). Sent at once, a mute and a quick unmute could
/// reach the Mac in either order and leave the call muted after the person unmuted it.
@MainActor
final class MuteRequests {
    private var last: Task<Void, Never>?

    func send(_ on: Bool, with api: API) async throws {
        let previous = last
        let request = Task { await previous?.value; try await api.reading(on) }
        last = Task { _ = try? await request.value }  // the next tap waits for this one, answered or failed
        try await request.value
    }
}
