import Carbon.HIToolbox
import OSLog
import PointeMacKit

/// One system-wide hot key, with its press and its release: what hold-to-talk needs. Carbon's `RegisterEventHotKey`
/// tells only this app, and only about this combination, so it needs neither Accessibility nor Input Monitoring
/// (docs/design/macos-app.md, "The shortcut").
@MainActor
final class HotKey {
    var onDown: (() -> Void)?
    var onUp: (() -> Void)?
    private(set) var registered: Shortcut?

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
                let pressed = GetEventKind(event) == UInt32(kEventHotKeyPressed)
                // Carbon delivers hot keys on the main thread, from the app's event loop.
                MainActor.assumeIsolated { Unmanaged<HotKey>.fromOpaque(context).takeUnretainedValue().fired(pressed: pressed) }
                return noErr
            }, 2, &kinds, me, &handler)
        }
        let id = EventHotKeyID(signature: Self.signature, id: 1)
        let status = RegisterEventHotKey(shortcut.keyCode, shortcut.modifiers, id, GetEventDispatcherTarget(), 0, &hotKey)
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
    private func fired(pressed: Bool) {
        log.debug("hot key \(pressed ? "down" : "up", privacy: .public)")
        if pressed {
            guard !down else { return }
            down = true
            onDown?()
            watch()
        } else if down {
            release()
        }
    }

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
