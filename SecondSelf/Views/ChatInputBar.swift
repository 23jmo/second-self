import SwiftUI

// MARK: - Chat Input Bar

/// Matches Figma node 90:129 (idle) and 136:1120 (recording).
/// Idle: [TextField "Message your Twin..."] [Mic]
/// Has text: [TextField] [Mic] [Send]
/// Recording: [Waveform visualization] [Mic] with cream glow
struct ChatInputBar: View {
    @Binding var text: String
    let isEnabled: Bool
    let voiceState: VoiceInputState
    let audioLevel: Float
    let onSend: (String) -> Void
    let onTapToRecord: () -> Void
    let onTapToStop: () -> Void
    let onVoiceCancel: () -> Void
    let onPermissionTap: () -> Void

    @FocusState private var isFocused: Bool
    @State private var textFieldID = UUID()

    var body: some View {
        VStack(spacing: 6) {
            // Error toast (above bar)
            if case .error(let message) = voiceState {
                errorToast(message)
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .bottom)),
                        removal: .opacity
                    ))
            }

            // Transcribing indicator (above bar)
            if voiceState == .transcribing {
                transcribingIndicator
                    .transition(.opacity)
            }

            // Main input bar
            mainInputBar
        }
        .animation(.ssContentReveal, value: voiceState)
        .onAppear {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                isFocused = true
            }
        }
    }

    // MARK: - Main Input Bar

    private var mainInputBar: some View {
        HStack(spacing: 8) {
            // Content area: text field OR waveform
            if voiceState == .recording {
                AudioWaveformView(audioLevel: audioLevel)
                    .frame(maxWidth: .infinity)
                    .frame(height: 28)
                    .transition(.opacity)
            } else {
                TextField("Message your Twin...", text: $text)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13))
                    .foregroundColor(Color.ssTextPrimary)
                    .focused($isFocused)
                    .id(textFieldID)
                    .onSubmit { sendIfValid() }
                    .disabled(!isEnabled)
                    .transition(.opacity)
            }

            // Mic button (always visible, independent of isEnabled)
            VoiceInputButton(
                voiceState: voiceState,
                onTapToRecord: onTapToRecord,
                onTapToStop: onTapToStop,
                onCancel: onVoiceCancel,
                onPermissionTap: onPermissionTap
            )

            // Send button: only when there's text to send
            if canSend {
                Button(action: sendIfValid) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 24))
                        .foregroundColor(Color.ssUserOlive)
                }
                .buttonStyle(.plain)
                .transition(.scale.combined(with: .opacity))
            }
        }
        .padding(.leading, 16)
        .padding(.trailing, 6)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 15)
                .fill(Color(hex: 0x262629))
        )
        .shadow(
            color: voiceState == .recording ? Color.ssCream.opacity(0.6) : Color.clear,
            radius: voiceState == .recording ? 18 : 0,
            x: 0, y: 0
        )
        .animation(.ssMicro, value: voiceState == .recording)
        .animation(.ssMicro, value: canSend)
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

    private var canSend: Bool {
        isEnabled && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func sendIfValid() {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty && isEnabled else { return }
        text = ""
        textFieldID = UUID()  // Force TextField recreation to bypass field editor cache
        onSend(trimmed)
        DispatchQueue.main.async {
            isFocused = true
        }
    }
}

// MARK: - Audio Waveform Visualization

/// Reactive waveform that responds to real microphone audio levels.
/// Matches the Figma waveform pattern at node 136:1117.
struct AudioWaveformView: View {
    let audioLevel: Float // 0.0 to 1.0

    private static let barWidth: CGFloat = 2
    private static let barSpacing: CGFloat = 2

    @State private var levelHistory: [Float] = []
    @State private var barCount: Int = 80

    var body: some View {
        GeometryReader { geo in
            let count = max(1, Int(geo.size.width / (Self.barWidth + Self.barSpacing)))
            HStack(spacing: Self.barSpacing) {
                ForEach(0..<count, id: \.self) { index in
                    RoundedRectangle(cornerRadius: 1)
                        .fill(Color.ssUserOlive.opacity(0.8))
                        .frame(width: Self.barWidth, height: barHeight(for: index))
                }
            }
            .frame(width: geo.size.width, height: geo.size.height, alignment: .center)
            .onAppear {
                barCount = count
                levelHistory = Array(repeating: 0, count: count)
            }
        }
        .onChange(of: audioLevel) { newLevel in
            guard !levelHistory.isEmpty else { return }
            levelHistory.removeFirst()
            let jitter = Float.random(in: -0.1...0.1)
            levelHistory.append(max(0, min(1, newLevel + jitter)))
        }
        .animation(.linear(duration: 0.05), value: audioLevel)
    }

    private func barHeight(for index: Int) -> CGFloat {
        guard index < levelHistory.count else { return 3 }
        let level = CGFloat(levelHistory[index])
        let minHeight: CGFloat = 3
        let maxHeight: CGFloat = 24
        return minHeight + level * (maxHeight - minHeight)
    }
}
