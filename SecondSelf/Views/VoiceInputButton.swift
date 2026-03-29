import SwiftUI

// MARK: - Voice Input Button

/// Olive mic button matching Figma node 90:185 / 136:1014.
/// Tap to start recording, tap again to stop. Simple toggle.
struct VoiceInputButton: View {
    let voiceState: VoiceInputState
    let onTapToRecord: () -> Void
    let onTapToStop: () -> Void
    let onCancel: () -> Void
    let onPermissionTap: () -> Void

    @State private var shakeOffset: CGFloat = 0

    var body: some View {
        Group {
            switch voiceState {
            case .hidden:
                EmptyView()
            case .permissionNeeded:
                micButton(icon: "mic.slash", bg: Color.ssTextSecondary.opacity(0.3))
                    .onTapGesture { onPermissionTap() }
                    .help("Tap to enable microphone")
            case .idle:
                micButton(icon: "mic.fill", bg: Color.ssUserOlive)
                    .onTapGesture { onTapToRecord() }
            case .recording:
                micButton(icon: "stop.fill", bg: Color.ssRecordingRed)
                    .onTapGesture { onTapToStop() }
            case .transcribing:
                ZStack {
                    RoundedRectangle(cornerRadius: 14)
                        .fill(Color.ssUserOlive)
                        .frame(width: 28, height: 28)
                    ProgressView()
                        .controlSize(.small)
                        .tint(.white)
                }
                .frame(width: 36, height: 36)
            case .error:
                micButton(icon: "exclamationmark.circle.fill", bg: Color.ssError)
                    .offset(x: shakeOffset)
                    .onAppear { runShake() }
            }
        }
        .animation(.ssMicro, value: voiceState)
    }

    // MARK: - Mic Button (matches Figma 90:185)

    private func micButton(icon: String, bg: Color) -> some View {
        ZStack {
            RoundedRectangle(cornerRadius: 14)
                .fill(bg)
                .frame(width: 28, height: 28)

            Image(systemName: icon)
                .font(.system(size: 14, weight: .medium))
                .foregroundColor(.white)
        }
        .frame(width: 36, height: 36)
        .contentShape(Rectangle())
    }

    // MARK: - Shake Animation

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
            withAnimation(.spring(response: 0.15, dampingFraction: 0.5)) { shakeOffset = 0 }
        }
    }
}
