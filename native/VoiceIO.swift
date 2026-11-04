// Full-duplex microphone + Jarvis playback through one echo-cancelling engine.
// Local JSON-lines IPC only; no network, persisted recordings, or app controls.
import AVFoundation
import Foundation

let outputQueue = DispatchQueue(label: "jarvis.voice.output")
func emit(_ item: [String: Any]) {
    outputQueue.async {
        guard let data = try? JSONSerialization.data(withJSONObject: item) else { return }
        do {
            try FileHandle.standardOutput.write(contentsOf: data + Data([10]))
        } catch { exit(0) }
    }
}

final class VoiceIO {
    let engine = AVAudioEngine()
    let player = AVAudioPlayerNode()
    let tapSlots = DispatchSemaphore(value: 4)
    let captureQueue = DispatchQueue(label: "jarvis.voice.capture")
    var playingID: String?

    func start() throws {
        let input = engine.inputNode
        try input.setVoiceProcessingEnabled(true)
        input.isVoiceProcessingAGCEnabled = true
        engine.attach(player)
        let playback = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1)!
        engine.connect(player, to: engine.mainMixerNode, format: playback)
        let source = input.outputFormat(forBus: 0)
        let destination = AVAudioFormat(standardFormatWithSampleRate: 16000, channels: 1)!
        guard source.sampleRate > 0,
              let converter = AVAudioConverter(from: source, to: destination) else {
            throw NSError(domain: "JarvisVoice", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "No usable microphone format"])
        }
        input.installTap(onBus: 0, bufferSize: 1024, format: source) { [weak self] buffer, _ in
            guard let self = self else { return }
            // The converter consumes the tap buffer synchronously. Never block
            // CoreAudio on Python's reader, and bound outstanding captured data.
            if self.tapSlots.wait(timeout: .now()) != .success { return }
            let capacity = AVAudioFrameCount(ceil(Double(buffer.frameLength) *
                destination.sampleRate / source.sampleRate)) + 32
            guard let converted = AVAudioPCMBuffer(pcmFormat: destination,
                                                  frameCapacity: capacity) else {
                self.tapSlots.signal(); return
            }
            var supplied = false
            var error: NSError?
            let status = converter.convert(to: converted, error: &error) { _, inputStatus in
                if supplied { inputStatus.pointee = .noDataNow; return nil }
                supplied = true; inputStatus.pointee = .haveData; return buffer
            }
            guard error == nil, status != .error,
                  let channel = converted.floatChannelData?[0] else {
                self.tapSlots.signal(); return
            }
            let samples = (0..<Int(converted.frameLength)).map {
                Int16(max(-32767, min(32767, channel[$0] * 32767)))
            }
            let data = samples.withUnsafeBufferPointer { Data(buffer: $0) }
            self.captureQueue.async {
                emit(["event": "audio", "pcm": data.base64EncodedString()])
                self.tapSlots.signal()
            }
        }
        engine.prepare()
        try engine.start()
        guard engine.isRunning, input.isVoiceProcessingEnabled else {
            throw NSError(domain: "JarvisVoice", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Voice processing did not start"])
        }
        emit(["event": "ready", "echo_cancellation": true])
    }

    func stopPlayback() {
        player.stop()
        if let id = playingID {
            playingID = nil
            emit(["event": "played", "id": id])
        }
    }

    func command(_ item: [String: Any]) {
        switch item["command"] as? String {
        case "play":
            guard let path = item["path"] as? String, let id = item["id"] as? String else { return }
            do {
                let file = try AVAudioFile(forReading: URL(fileURLWithPath: path))
                guard file.processingFormat.sampleRate == 24000,
                      file.processingFormat.channelCount == 1 else {
                    throw NSError(domain: "JarvisVoice", code: 3,
                                  userInfo: [NSLocalizedDescriptionKey: "Expected 24 kHz mono speech"])
                }
                stopPlayback()
                playingID = id
                player.scheduleFile(file, at: nil, completionCallbackType: .dataPlayedBack) {
                    [weak self] _ in
                    DispatchQueue.main.async {
                        if self?.playingID == id {
                            self?.playingID = nil
                            emit(["event": "played", "id": id])
                        }
                    }
                }
                player.play()
            } catch {
                emit(["event": "play_error", "id": id, "error": error.localizedDescription])
            }
        case "stop": stopPlayback()
        case "quit":
            stopPlayback(); engine.inputNode.removeTap(onBus: 0); engine.stop(); exit(0)
        default: break
        }
    }
}

if CommandLine.arguments.contains("--version") {
    print("Jarvis VoiceIO 1 — AVAudioEngine Voice Processing")
    exit(0)
}
let voice = VoiceIO()
do { try voice.start() }
catch {
    emit(["event": "error", "error": error.localizedDescription])
    outputQueue.sync {}; exit(1)
}
DispatchQueue.global().async {
    while let line = readLine() {
        guard line.utf8.count < 16384, let data = line.data(using: .utf8),
              let item = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            continue
        }
        DispatchQueue.main.async { voice.command(item) }
    }
    DispatchQueue.main.async { voice.command(["command": "quit"]) }
}
RunLoop.main.run()
