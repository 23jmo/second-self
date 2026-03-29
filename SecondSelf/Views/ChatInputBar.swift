import SwiftUI

// MARK: - Chat Input Bar

/// Rounded input bar with voice mic button and olive send button.
/// Layout: [TextField] [Mic] [Send]
/// Mic button has independent enabled state (stays active during Twin thinking).
struct ChatInputBar: View {
    @Binding var text: String
    let isEnabled: Bool
    let voiceState: VoiceInputState
    let recordingDuration: TimeInterval
    let onSend: (String) -> Void
    let onHoldStart: () -> Void
    let onHoldEnd: () -> Void
    let onVoiceCancel: () -> Void
    let onPermissionTap: () -> Void

    @FocusState private var isFocused: Bool
    @State private var recordingPulseOpacity: Double = 0.0

    var body: some View {
        VStack(spacing: 6) {
            // Recording indicator (slides in above input bar)
            if voiceState == .recording {
                recordingIndicator
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .scale(scale: 0.95, anchor: .bottom)),
                        removal: .opacity
                    ))
            }

            // Error toast
            if case .error(let message) = voiceState {
                errorToast(message)
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .bottom)),
                        removal: .opacity
                    ))
            }

            // Transcribing indicator
            if voiceState == .transcribing {
                transcribingIndicator
                    .transition(.opacity)
            }

            // Main input bar
            mainInputBar
        }
        .animation(.ssContentReveal, value: voiceState)
        .onAppear {
            // Delay focus request so the panel animation settles
            // and the view is fully in the responder chain
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                isFocused = true
            }
        }
    }

    // MARK: - Main Input Bar

    private var mainInputBar: some View {
        HStack(spacing: 8) {
            TextField("Message your Twin...", text: $text)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundColor(Color.ssTextPrimary)
                .focused($isFocused)
                .onSubmit { sendIfValid() }
                .disabled(!isEnabled)

            // Mic button: independent of isEnabled
            VoiceInputButton(
                voiceState: voiceState,
                onHoldStart: onHoldStart,
                onHoldEnd: onHoldEnd,
                onCancel: onVoiceCancel,
                onPermissionTap: onPermissionTap
            )

            // Send button
            Button(action: sendIfValid) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 24))
                    .foregroundColor(canSend ? Color.ssUserOlive : Color.ssUserOlive.opacity(0.3))
                    .scaleEffect(canSend ? 1.0 : 0.95)
                    .animation(.ssMicro, value: canSend)
            }
            .buttonStyle(.plain)
            .disabled(!canSend)
        }
        .padding(.leading, 16)
        .padding(.trailing, 6)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 15)
                .fill(voiceState == .recording ? Color.ssRecordingRed.opacity(0.08) : Color.ssInputBg)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 15)
                .stroke(borderColor, lineWidth: 1)
        )
        .animation(.ssMicro, value: isFocused)
        .animation(.ssMicro, value: voiceState == .recording)
    }

    private var borderColor: Color {
        if voiceState == .recording {
            return Color.ssRecordingRed.opacity(0.4)
        }
        if isFocused {
            return Color.ssTwinGreen.opacity(0.4)
        }
        return Color.clear
    }

    // MARK: - Recording Indicator

    private var recordingIndicator: some View {
        HStack(spacing: 8) {
            // Pulsing red dot
            Circle()
                .fill(Color.ssRecordingRed)
                .frame(width: 7, height: 7)
                .opacity(recordingPulseOpacity)
                .onAppear {
                    withAnimation(.easeInOut(duration: 0.6).repeatForever(autoreverses: true)) {
                        recordingPulseOpacity = 1.0
                    }
                }
                .onDisappear { recordingPulseOpacity = 0.0 }

            Text("Listening")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(Color.ssRecordingRed)
                .tracking(0.3)

            Text(formattedDuration)
                .font(.system(size: 11, weight: .medium).monospacedDigit())
                .foregroundColor(Color.ssTextSecondary)

            Spacer()

            // Cancel button
            Button(action: onVoiceCancel) {
                HStack(spacing: 3) {
                    Image(systemName: "xmark")
                        .font(.system(size: 8, weight: .bold))
                    Text("Cancel")
                        .font(.system(size: 10, weight: .medium))
                }
                .foregroundColor(Color.ssTextSecondary)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(
                    Capsule().fill(Color.ssUserBubble)
                )
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 6)
    }

    // MARK: - Transcribing Indicator

    private var transcribingIndicator: some View {
        HStack(spacing: 8) {
            ProgressView()
                .controlSize(.mini)
                .tint(Color.ssUserOlive)

            Text("Transcribing...")
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(Color.ssTextSecondary)

            Spacer()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 4)
    }

    // MARK: - Error Toast

    private func errorToast(_ message: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: "exclamationmark.circle.fill")
                .font(.system(size: 11))
                .foregroundColor(Color.ssError)

            Text(message)
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(Color.ssError.opacity(0.9))
                .lineLimit(1)

            Spacer()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 5)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color.ssError.opacity(0.1))
        )
    }

    // MARK: - Helpers

    private var formattedDuration: String {
        let minutes = Int(recordingDuration) / 60
        let seconds = Int(recordingDuration) % 60
        return String(format: "%d:%02d", minutes, seconds)
    }

    private var canSend: Bool {
        isEnabled && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func sendIfValid() {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty && isEnabled else { return }
        isFocused = false
        text = ""
        onSend(trimmed)
    }
}
