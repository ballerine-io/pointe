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

    /// How the engine is wired, best first. macOS's voice-processing unit refuses to initialise (-10875) when the mixer
    /// feeds it the output device's own stereo format: it takes one channel at the device's rate. Found on a MacBook
    /// Pro's built-in devices (macOS 27); the others are kept so a device that differs still gets a call.
    private enum Wiring: CaseIterable {
        /// Echo cancellation on, the mixer feeding the output one channel.
        case voiceMono
        /// Echo cancellation on, the engine's own connection to the output.
        case voiceDefault
        /// No voice processing: the call works, and the bot can hear itself through loudspeakers.
        case plain
    }

    /// False when no voice-processing wiring would start: the call is up without echo cancellation.
    private(set) var cancelsEcho = true

    private func run() throws {
        var last: Error = CallAudioError.failed("no audio wiring started")
        for wiring in Wiring.allCases {
            do {
                try run(wiring)
                cancelsEcho = wiring != .plain
                if wiring != .voiceMono { log.notice("audio up with \(String(describing: wiring), privacy: .public)") }
                return
            } catch let error as CallAudioError {
                throw error
            } catch {
                last = error
                log.error("audio wiring \(String(describing: wiring), privacy: .public) did not start: \(error.localizedDescription, privacy: .public)")
                engine.inputNode.removeTap(onBus: 0)
                engine.stop()
                engine.reset()
            }
        }
        throw last
    }

    private func run(_ wiring: Wiring) throws {
        guard let playFormat else { throw CallAudioError.failed("no playback format") }
        let input = engine.inputNode
        try input.setVoiceProcessingEnabled(wiring != .plain)
        if wiring != .plain {
            // Other apps' audio is ducked as little as the system allows while the call is up.
            input.voiceProcessingOtherAudioDuckingConfiguration = .init(enableAdvancedDucking: false, duckingLevel: .min)
        }
        // The output's format is read before the mixer exists: asking for the mixer connects it to the output in stereo.
        let out = engine.outputNode.inputFormat(forBus: 0)
        if !attached {
            engine.attach(player)
            attached = true
        }
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        let mono = wiring == .voiceMono ? AVAudioFormat(standardFormatWithSampleRate: out.sampleRate, channels: 1) : nil
        engine.connect(engine.mainMixerNode, to: engine.outputNode, format: mono)
        log.info("audio wiring \(String(describing: wiring), privacy: .public): out \(out.sampleRate, privacy: .public) Hz \(out.channelCount, privacy: .public) ch")
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
