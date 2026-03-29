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

    var body: some View {
        VStack(spacing: 0) {
            // Recording overlay (shown above input bar when recording)
            if voiceState == .recording {
                recordingOverlay
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
            }

            // Main input bar
            HStack(spacing: 8) {
                TextField("Message your Twin...", text: $text)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13))
                    .foregroundColor(Color.ssTextPrimary)
                    .focused($isFocused)
                    .onSubmit { sendIfValid() }
                    .disabled(!isEnabled)
                    .opacity(voiceState == .recording ? 0.3 : 1.0)

                // Mic button: independent of isEnabled, RIGHT of text field
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
                    .fill(Color.ssInputBg)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 15)
                    .stroke(isFocused ? Color.ssTwinGreen.opacity(0.4) : Color.clear, lineWidth: 1)
            )
            .animation(.ssMicro, value: isFocused)
        }
        .animation(.ssContentReveal, value: voiceState == .recording)
        .onAppear {
            // Delay focus request so the panel animation settles
            // and the view is fully in the responder chain
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                isFocused = true
            }
        }
    }

    // MARK: - Recording Overlay

    private var recordingOverlay: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(Color.ssRecordingRed)
                .frame(width: 8, height: 8)

            Text("Recording...")
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(Color.ssTextPrimary)

            Text(formattedDuration)
                .font(.system(size: 12, weight: .medium).monospacedDigit())
                .foregroundColor(Color.ssTextSecondary)

            Spacer()

            Button(action: onVoiceCancel) {
                Image(systemName: "xmark.circle.fill")
                    .font(.system(size: 16))
                    .foregroundColor(Color.ssTextSecondary)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.ssRecordingRed.opacity(0.15))
        )
        .padding(.bottom, 6)
    }

    private var formattedDuration: String {
        let minutes = Int(recordingDuration) / 60
        let seconds = Int(recordingDuration) % 60
        return String(format: "%d:%02d", minutes, seconds)
    }

    // MARK: - Send Logic

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
