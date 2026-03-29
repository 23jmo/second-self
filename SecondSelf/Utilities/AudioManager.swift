import AppKit
import AVFoundation

// MARK: - Audio Manager

/// Manages sound effects for the Second Self app.
/// Uses NSSound for system sounds as placeholders.
/// Will be replaced with custom bundled sounds later.
final class AudioManager {
    private var typingCounter: Int = 0

    /// Play a short ascending chime when a task starts.
    func playTaskStart() {
        // Placeholder: use system sound
        // Will be replaced with custom ascending chime
        playSystemSound("Tink")
    }

    /// Play a gentle ding when a task completes.
    func playCompletion() {
        // Placeholder: use system sound
        playSystemSound("Glass")
    }

    /// Play a subtle key click. Called every ~5th character for typing feel.
    func playTypingClick() {
        // Placeholder: very subtle system click
        playSystemSound("Pop")
    }

    /// Increment the typing counter and play a click every 5th character.
    func incrementTypingCounter() {
        typingCounter += 1
        if typingCounter % 5 == 0 {
            playTypingClick()
        }
    }

    /// Reset the typing counter (e.g., when a new message starts).
    func resetTypingCounter() {
        typingCounter = 0
    }

    // MARK: - Private

    private func playSystemSound(_ name: String) {
        // Respect system mute by using NSSound which honors volume settings
        if let sound = NSSound(named: NSSound.Name(name)) {
            sound.volume = 0.3 // Keep it subtle
            sound.play()
        } else {
            // Fallback to beep
            NSSound.beep()
        }
    }
}
