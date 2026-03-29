import SwiftUI

// MARK: - Voice Input Button

/// Hold-to-talk microphone button for voice input.
/// Uses DragGesture(minimumDistance: 0) for immediate press/release detection.
/// States are driven by ChatViewModel.voiceState.
struct VoiceInputButton: View {
    let voiceState: VoiceInputState
    let onHoldStart: () -> Void
    let onHoldEnd: () -> Void
    let onCancel: () -> Void
    let onPermissionTap: () -> Void

    @State private var isPressing = false
    @State private var pressStartTime: Date?
    @State private var shakeOffset: CGFloat = 0

    // Debounce: don't start recording until 0.1s of hold
    private static let holdDebounce: TimeInterval = 0.1
    // Drag-off threshold: cancel if pointer moves >50pt from center
    private static let dragCancelDistance: CGFloat = 50

    var body: some View {
        Group {
            switch voiceState {
            case .hidden:
                EmptyView()

            case .permissionNeeded:
                permissionButton

            case .idle:
                idleButton

            case .recording:
                recordingButton

            case .transcribing:
                transcribingButton

            case .error:
                errorButton
            }
        }
    }

    // MARK: - State Views

    private var permissionButton: some View {
        Button(action: onPermissionTap) {
            Image(systemName: "mic.slash")
                .font(.system(size: 18))
                .foregroundColor(Color.ssTextSecondary)
        }
        .buttonStyle(.plain)
        .frame(width: 28, height: 28)
        .help("Tap to enable microphone")
    }

    private var idleButton: some View {
        Image(systemName: "mic.fill")
            .font(.system(size: 18))
            .foregroundColor(Color.ssUserOlive)
            .frame(width: 28, height: 28)
            .contentShape(Rectangle())
            .gesture(holdGesture)
    }

    private var recordingButton: some View {
        Image(systemName: "mic.fill")
            .font(.system(size: 18))
            .foregroundColor(Color.ssRecordingRed)
            .scaleEffect(isPressing ? 1.15 : 1.0)
            .opacity(isPressing ? 0.7 : 1.0)
            .animation(.ssRecordingPulse, value: isPressing)
            .frame(width: 28, height: 28)
            .contentShape(Rectangle())
            .gesture(holdGesture)
    }

    private var transcribingButton: some View {
        ProgressView()
            .controlSize(.small)
            .frame(width: 28, height: 28)
    }

    private var errorButton: some View {
        Image(systemName: "exclamationmark.circle")
            .font(.system(size: 18))
            .foregroundColor(Color.ssError)
            .offset(x: shakeOffset)
            .frame(width: 28, height: 28)
            .onAppear {
                shakeAnimation()
            }
    }

    // MARK: - Hold-to-Talk Gesture

    private var holdGesture: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                if !isPressing {
                    // Press started
                    isPressing = true
                    pressStartTime = Date()

                    // Debounce: start recording after 0.1s
                    DispatchQueue.main.asyncAfter(deadline: .now() + Self.holdDebounce) {
                        guard isPressing else { return }
                        onHoldStart()
                    }
                }

                // Drag-off cancellation: if pointer moves too far from start
                let distance = sqrt(
                    pow(value.translation.width, 2) + pow(value.translation.height, 2)
                )
                if distance > Self.dragCancelDistance && voiceState == .recording {
                    isPressing = false
                    pressStartTime = nil
                    onCancel()
                }
            }
            .onEnded { _ in
                let wasRecording = voiceState == .recording
                isPressing = false

                guard let start = pressStartTime else { return }
                pressStartTime = nil

                let holdDuration = Date().timeIntervalSince(start)

                if holdDuration < 0.5 && !wasRecording {
                    // Too short, recording never started (debounce caught it)
                    return
                }

                if wasRecording {
                    onHoldEnd()
                }
            }
    }

    // MARK: - Shake Animation

    private func shakeAnimation() {
        let duration = 0.08
        withAnimation(.linear(duration: duration)) { shakeOffset = 4 }
        DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
            withAnimation(.linear(duration: duration)) { shakeOffset = -4 }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + duration * 2) {
            withAnimation(.linear(duration: duration)) { shakeOffset = 4 }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + duration * 3) {
            withAnimation(.linear(duration: duration)) { shakeOffset = -4 }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + duration * 4) {
            withAnimation(.linear(duration: duration)) { shakeOffset = 0 }
        }
    }
}
