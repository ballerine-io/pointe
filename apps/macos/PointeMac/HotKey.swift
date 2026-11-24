import Carbon.HIToolbox
import OSLog
import PointeMacKit

/// One system-wide hot key, with its press and its release: what hold-to-talk needs. Carbon's `RegisterEventHotKey`
/// tells only this app, and only about this combination, so it needs neither Accessibility nor Input Monitoring
/// (docs/design/macos-app.md, "The shortcut"). The app has two, talk and skip: each has its own `id`, and hears only
/// its own presses (Carbon hands every hot key of the app to every handler).
@MainActor
final class HotKey {
    var onDown: (() -> Void)?
    var onUp: (() -> Void)?
    private(set) var registered: Shortcut?
    private let id: UInt32

    init(id: UInt32 = 1) { self.id = id }

    private var hotKey: EventHotKeyRef?
    private var handler: EventHandlerRef?
    private var down = false
    private var watcher: Task<Void, Never>?
    private let log = Logger(subsystem: Log.subsystem, category: "hotkey")
    private static let signature: OSType = 0x504E_5445  // 'PNTE'

    /// Registers `shortcut`, replacing any other; nil removes it. Returns false when the system refused it.
    @discardableResult
    func register(_ shortcut: Shortcut?) -> Bool {
        unregister()
        guard let shortcut else { return true }
        if handler == nil {
            var kinds = [EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
                         EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased))]
            let me = Unmanaged.passUnretained(self).toOpaque()
            InstallEventHandler(GetEventDispatcherTarget(), { _, event, context in
                guard let event, let context else { return noErr }
                var which = EventHotKeyID()
                GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                                  MemoryLayout<EventHotKeyID>.size, nil, &which)
                let pressed = GetEventKind(event) == UInt32(kEventHotKeyPressed)
                // Carbon delivers hot keys on the main thread, from the app's event loop.
                let mine = MainActor.assumeIsolated { Unmanaged<HotKey>.fromOpaque(context).takeUnretainedValue().fired(which.id, pressed: pressed) }
                return mine ? noErr : OSStatus(eventNotHandledErr)  // another of the app's keys: its own handler takes it
            }, 2, &kinds, me, &handler)
        }
        let name = EventHotKeyID(signature: Self.signature, id: id)
        let status = RegisterEventHotKey(shortcut.keyCode, shortcut.modifiers, name, GetEventDispatcherTarget(), 0, &hotKey)
        guard status == noErr else {
            log.error("hot key refused: \(status, privacy: .public)")
            return false
        }
        registered = shortcut
        return true
    }

    func unregister() {
        if let hotKey { UnregisterEventHotKey(hotKey) }
        hotKey = nil
        registered = nil
        release()
    }

    /// Key repeat sends no second press, but a release without a press (registered while the key was down) is dropped.
    /// False for another hot key's event.
    func fired(_ which: UInt32, pressed: Bool) -> Bool {
        guard Self.hears(which, as: id) else { return false }
        log.debug("hot key \(self.id, privacy: .public) \(pressed ? "down" : "up", privacy: .public)")
        if pressed {
            guard !down else { return true }
            down = true
            onDown?()
            watch()
        } else if down {
            release()
        }
        return true
    }

    /// A hot key hears the event that carries its own id, and no other: the talk key must not skip, nor the skip key talk.
    nonisolated static func hears(_ event: UInt32, as id: UInt32) -> Bool { event == id }

    private func release() {
        watcher?.cancel()
        watcher = nil
        guard down else { return }
        down = false
        onUp?()
    }

    /// The release event is the rule. This is the net under it: if the key reads as up for a while and no release
    /// came, the press ends anyway (`ReleaseWatch`). Reading one key's state needs no permission and sees no typing.
    private func watch() {
        guard let key = registered?.keyCode else { return }
        watcher?.cancel()
        watcher = Task { [weak self] in
            var watch = ReleaseWatch()
            while !Task.isCancelled {
                try? await Task.sleep(for: ReleaseWatch.every)
                guard let self, self.down, !Task.isCancelled else { return }
                if watch.sample(down: CGEventSource.keyState(.combinedSessionState, key: CGKeyCode(key))) {
                    self.log.info("hot key: no release event, and the key is up: released")
                    self.release()
                    return
                }
            }
        }
    }
}
