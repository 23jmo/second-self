import AVFoundation
import AppKit
import os

// MARK: - Audio Recorder

/// Wraps AVAudioRecorder for voice input capture.
/// Records to a temp WAV file (16kHz mono PCM — optimal for STT).
/// Always called from ChatViewModel on the main thread.
final class AudioRecorder: ObservableObject {
    enum PermissionState {
        case notDetermined
        case authorized
        case denied
    }

    @Published private(set) var isRecording = false
    @Published private(set) var permissionState: PermissionState = .notDetermined
    @Published private(set) var recordingDuration: TimeInterval = 0
    @Published private(set) var audioLevel: Float = 0  // 0.0 to 1.0, normalized mic level

    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private var durationTimer: Timer?
    private let logger = Logger(subsystem: "com.secondself.app", category: "AudioRecorder")

    init() {
        // Clean up any orphaned temp files on launch
        cleanOrphanedTempFiles()

        // Clean up on app termination
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.cancelRecording()
        }
    }

    deinit {
        // Synchronous cleanup: deinit can't call @MainActor methods,
        // so we inline the cleanup directly
        recorder?.stop()
        if let url = recordingURL {
            try? FileManager.default.removeItem(at: url)
        }
    }

    // MARK: - Permission

    /// Check current mic permission without triggering the system dialog.
    /// Call this on view appear to pre-flight the permission state.
    func checkPermission() {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            permissionState = .authorized
        case .denied, .restricted:
            permissionState = .denied
        case .notDetermined:
            permissionState = .notDetermined
        @unknown default:
            permissionState = .notDetermined
        }
    }

    /// Request mic permission. Call this from a tap gesture (NOT during hold-to-talk).
    /// The system dialog steals focus and would kill a hold gesture + collapse the notch.
    func requestPermission(completion: @escaping (Bool) -> Void) {
        AVCaptureDevice.requestAccess(for: .audio) { [weak self] granted in
            DispatchQueue.main.async {
                self?.permissionState = granted ? .authorized : .denied
                if !granted {
                    self?.logger.warning("Microphone permission denied")
                }
                completion(granted)
            }
        }
    }

    // MARK: - Recording

    func startRecording() {
        guard permissionState == .authorized else {
            logger.error("Cannot record: mic permission not authorized")
            return
        }
        guard !isRecording else { return }

        let tempDir = NSTemporaryDirectory()
        let fileName = "secondself-voice-\(UUID().uuidString).wav"
        let url = URL(fileURLWithPath: tempDir).appendingPathComponent(fileName)
        recordingURL = url

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: 16000.0,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false
        ]

        do {
            recorder = try AVAudioRecorder(url: url, settings: settings)
            recorder?.isMeteringEnabled = true
            recorder?.record()
            isRecording = true
            recordingDuration = 0
            audioLevel = 0
            startDurationTimer()
            logger.info("Recording started: \(fileName)")
        } catch {
            logger.error("Failed to start recording: \(error.localizedDescription)")
            cleanUpTempFile()
        }
    }

    /// Stop recording and return the audio file URL, or nil if recording was too short.
    func stopRecording() -> URL? {
        guard isRecording, let recorder = recorder else { return nil }

        recorder.stop()
        stopDurationTimer()
        isRecording = false

        let duration = recordingDuration
        logger.info("Recording stopped: \(String(format: "%.1f", duration))s")

        // Too short — discard
        if duration < 0.5 {
            logger.info("Recording too short (<0.5s), discarding")
            cleanUpTempFile()
            return nil
        }

        let url = recordingURL
        // Don't clean up — caller will use the file and clean up after transcription
        recordingURL = nil
        self.recorder = nil
        return url
    }

    /// Cancel an active recording and clean up the temp file.
    func cancelRecording() {
        guard isRecording else { return }

        recorder?.stop()
        stopDurationTimer()
        isRecording = false
        recordingDuration = 0
        cleanUpTempFile()
        logger.info("Recording cancelled")
    }

    /// Delete a temp audio file after it's been uploaded or is no longer needed.
    func cleanUpFile(at url: URL) {
        try? FileManager.default.removeItem(at: url)
    }

    // MARK: - Private

    private func cleanUpTempFile() {
        if let url = recordingURL {
            try? FileManager.default.removeItem(at: url)
            recordingURL = nil
        }
        recorder = nil
    }

    private func startDurationTimer() {
        durationTimer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            guard let self, self.isRecording else { return }
            self.recordingDuration += 0.05

            // Sample audio level from AVAudioRecorder metering
            if let recorder = self.recorder {
                recorder.updateMeters()
                let dB = recorder.averagePower(forChannel: 0) // -160 to 0
                // Normalize: -50dB (silence) to 0dB (loud) → 0.0 to 1.0
                let normalized = max(0, min(1, (dB + 50) / 50))
                self.audioLevel = normalized
            }

            // Auto-stop at 120 seconds
            if self.recordingDuration >= 120 {
                _ = self.stopRecording()
            }
        }
    }

    private func stopDurationTimer() {
        durationTimer?.invalidate()
        durationTimer = nil
    }

    private func cleanOrphanedTempFiles() {
        let tempDir = NSTemporaryDirectory()
        let fm = FileManager.default
        guard let files = try? fm.contentsOfDirectory(atPath: tempDir) else { return }
        for file in files where file.hasPrefix("secondself-voice-") && file.hasSuffix(".wav") {
            let path = (tempDir as NSString).appendingPathComponent(file)
            try? fm.removeItem(atPath: path)
        }
    }
}
