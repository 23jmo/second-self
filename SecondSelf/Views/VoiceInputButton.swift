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
    @State private var pulseScale: CGFloat = 1.0
    @State private var shakeOffset: CGFloat = 0
    @State private var isHovering = false

    private static let holdDebounce: TimeInterval = 0.1
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
        .animation(.ssMicro, value: voiceState)
    }

    // MARK: - State Views

    private var permissionButton: some View {
        Button(action: onPermissionTap) {
            micIcon("mic.slash")
                .foregroundColor(Color.ssTextSecondary)
        }
        .buttonStyle(.plain)
        .help("Tap to enable microphone")
    }

    private var idleButton: some View {
        micIcon("mic.fill")
            .foregroundColor(isHovering ? Color.ssUserOlive : Color.ssUserOlive.opacity(0.7))
            .scaleEffect(isPressing ? 0.85 : 1.0)
            .contentShape(Circle())
            .onHover { isHovering = $0 }
            .gesture(holdGesture)
            .animation(.ssMicro, value: isPressing)
            .animation(.ssMicro, value: isHovering)
    }

    private var recordingButton: some View {
        ZStack {
            // Pulsing ring behind the mic
            Circle()
                .fill(Color.ssRecordingRed.opacity(0.2))
                .frame(width: 36, height: 36)
                .scaleEffect(pulseScale)

            micIcon("mic.fill")
                .foregroundColor(Color.ssRecordingRed)
                .scaleEffect(1.1)
        }
        .contentShape(Circle())
        .gesture(holdGesture)
        .onAppear { startPulse() }
        .onDisappear { pulseScale = 1.0 }
    }

    private var transcribingButton: some View {
        ZStack {
            Circle()
                .fill(Color.ssUserOlive.opacity(0.15))
                .frame(width: 28, height: 28)

            ProgressView()
                .controlSize(.small)
                .tint(Color.ssUserOlive)
        }
        .frame(width: 28, height: 28)
        .transition(.scale.combined(with: .opacity))
    }

    private var errorButton: some View {
        micIcon("exclamationmark.circle.fill")
            .foregroundColor(Color.ssError)
            .offset(x: shakeOffset)
            .onAppear { runShake() }
    }

    // MARK: - Shared Icon

    private func micIcon(_ systemName: String) -> some View {
        Image(systemName: systemName)
            .font(.system(size: 18, weight: .medium))
            .frame(width: 28, height: 28)
    }

    // MARK: - Animations

    private func startPulse() {
        pulseScale = 1.0
        withAnimation(.easeInOut(duration: 0.7).repeatForever(autoreverses: true)) {
            pulseScale = 1.4
        }
    }

    private func runShake() {
        shakeOffset = 0
        withAnimation(.linear(duration: 0.06)) { shakeOffset = 5 }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.06) {
            withAnimation(.linear(duration: 0.06)) { shakeOffset = -5 }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.12) {
            withAnimation(.linear(duration: 0.06)) { shakeOffset = 4 }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) {
            withAnimation(.linear(duration: 0.06)) { shakeOffset = -3 }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.24) {
            withAnimation(.spring(response: 0.15, dampingFraction: 0.5)) { shakeOffset = 0 }
        }
    }

    // MARK: - Hold-to-Talk Gesture

    private var holdGesture: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                if !isPressing {
                    isPressing = true
                    pressStartTime = Date()

                    DispatchQueue.main.asyncAfter(deadline: .now() + Self.holdDebounce) {
                        guard isPressing else { return }
                        onHoldStart()
                    }
                }

                // Drag-off cancellation
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
                    return
                }

                if wasRecording {
                    onHoldEnd()
                }
            }
    }
}
