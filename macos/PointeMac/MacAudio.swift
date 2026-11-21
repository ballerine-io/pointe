import AVFoundation
import OSLog
import PointeKit

/// The Mac's microphone and speaker for a call: one `AVAudioEngine` with voice processing on its input, so the bot's
/// voice, played through the same engine, is taken out of what the microphone hears (echo cancellation).
@MainActor
final class MacAudio: CallAudio {
    var onSpeaking: ((Bool) -> Void)?
    /// The engine could not be restarted after the audio devices changed: the reason, for the Connect panel.
    var onLost: ((String) -> Void)?

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let playFormat = AVAudioFormat(standardFormatWithSampleRate: Wire.downRate, channels: 1)
    private var deliver: (@Sendable ([Float]) -> Void)?
    private var queued = 0
    private var running = false
    private var attached = false
    private var changes: NSObjectProtocol?
    private let log = Logger(subsystem: Log.subsystem, category: "audio")

    /// Idempotent: a redial calls it again while the engine runs.
    func start(deliver: @escaping @Sendable ([Float]) -> Void) async throws {
        self.deliver = deliver
        guard !running else { return }
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: break
        case .notDetermined:
            guard await AVCaptureDevice.requestAccess(for: .audio) else { throw CallAudioError.denied }
        default: throw CallAudioError.denied
        }
        guard AVCaptureDevice.default(for: .audio) != nil else { throw CallAudioError.noMicrophone }
        do { try run() } catch let error as CallAudioError { throw error } catch { throw CallAudioError.failed(error.localizedDescription) }
        // AirPods joined or left, the default device or its sample rate changed: the engine stopped itself.
        changes = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.devicesChanged() }
        }
    }

    private func run() throws {
        guard let playFormat else { throw CallAudioError.failed("no playback format") }
        let input = engine.inputNode
        try input.setVoiceProcessingEnabled(true)
        // Other apps' audio is ducked as little as the system allows while the call is up.
        input.voiceProcessingOtherAudioDuckingConfiguration = .init(enableAdvancedDucking: false, duckingLevel: .min)
        if !attached {
            engine.attach(player)
            attached = true
        }
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        let format = input.outputFormat(forBus: 0)  // voice processing decides the rate and the channel count
        guard format.sampleRate > 0, format.channelCount > 0 else { throw CallAudioError.noMicrophone }
        if let deliver {
            input.installTap(onBus: 0, bufferSize: 1024, format: format, block: Self.tap(rate: format.sampleRate, deliver))
        }
        engine.prepare()
        try engine.start()
        player.play()
        running = true
        log.info("audio up: \(format.sampleRate, privacy: .public) Hz, \(format.channelCount, privacy: .public) ch in")
    }

    private func halt() {
        engine.inputNode.removeTap(onBus: 0)
        player.stop()
        engine.stop()
        running = false
        queued = 0
        onSpeaking?(false)
    }

    private func devicesChanged() {
        guard running else { return }
        log.info("audio devices changed: restarting the engine")
        halt()
        do { try run() } catch {
            let why = (error as? CallAudioError).map { "\($0)" } ?? error.localizedDescription
            log.error("audio restart failed: \(why, privacy: .public)")
            onLost?(why)
        }
    }

    func stop() {
        if let changes { NotificationCenter.default.removeObserver(changes) }
        changes = nil
        guard running else { return }
        halt()
        try? engine.inputNode.setVoiceProcessingEnabled(false)  // gives the microphone back: the orange dot goes out
    }

    func play(_ samples: [Float]) {
        guard running, !samples.isEmpty, let playFormat,
              let buffer = AVAudioPCMBuffer(pcmFormat: playFormat, frameCapacity: AVAudioFrameCount(samples.count)),
              let channel = buffer.floatChannelData?[0] else { return }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        samples.withUnsafeBufferPointer { source in
            if let base = source.baseAddress { channel.update(from: base, count: samples.count) }
        }
        queued += 1
        if queued == 1 { onSpeaking?(true) }
        player.scheduleBuffer(buffer, completionHandler: Self.whenPlayed(self))
    }

    func flush() {
        guard running else { return }
        player.stop()
        queued = 0
        onSpeaking?(false)
        player.play()
    }

    private func played() {
        queued = max(0, queued - 1)
        if queued == 0 { onSpeaking?(false) }
    }

    // Built outside the main actor: AVFoundation calls these on its audio thread, and a closure written inside a
    // @MainActor method would assert that it runs on the main thread.
    nonisolated private static func tap(rate: Double, _ deliver: @escaping @Sendable ([Float]) -> Void) -> AVAudioNodeTapBlock {
        { buffer, _ in
            guard let data = buffer.floatChannelData?[0] else { return }
            let samples = Array(UnsafeBufferPointer(start: data, count: Int(buffer.frameLength)))
            deliver(Wire.resample(samples, from: rate, to: Wire.upRate))
        }
    }

    nonisolated private static func whenPlayed(_ audio: MacAudio) -> @Sendable () -> Void {
        { [weak audio] in Task { @MainActor in audio?.played() } }
    }
}

enum Log {
    static let subsystem = "io.ballerine.pointe.mac"
}
