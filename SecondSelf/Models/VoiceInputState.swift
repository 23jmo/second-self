import Foundation

// MARK: - Voice Input State

/// Single state machine for voice input lifecycle.
/// Prevents race conditions from loose booleans.
enum VoiceInputState: Equatable {
    case hidden            // No API key — mic button not shown
    case idle              // Ready, mic button visible
    case permissionNeeded  // First use — need to request mic permission
    case recording         // AVAudioRecorder active
    case transcribing      // Audio uploaded, waiting for ElevenLabs response
    case error(String)     // Brief error, auto-clears after 2s

    static func == (lhs: VoiceInputState, rhs: VoiceInputState) -> Bool {
        switch (lhs, rhs) {
        case (.hidden, .hidden),
             (.idle, .idle),
             (.permissionNeeded, .permissionNeeded),
             (.recording, .recording),
             (.transcribing, .transcribing):
            return true
        case (.error(let a), .error(let b)):
            return a == b
        default:
            return false
        }
    }
}
