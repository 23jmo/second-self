import SwiftUI

// MARK: - Chat Input Bar

/// Rounded pill-shaped text input with olive-green send button.
/// Sends on Enter key or click of the send button.
struct ChatInputBar: View {
    @Binding var text: String
    let isEnabled: Bool
    let onSend: (String) -> Void

    @FocusState private var isFocused: Bool

    var body: some View {
        HStack(spacing: 8) {
            // Text field
            TextField("Message your Twin...", text: $text)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundColor(Color.ssTextPrimary)
                .focused($isFocused)
                .onSubmit {
                    sendIfValid()
                }
                .disabled(!isEnabled)

            // Send button
            Button(action: sendIfValid) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 24))
                    .foregroundColor(canSend ? twinGreen : twinGreen.opacity(0.3))
            }
            .buttonStyle(.plain)
            .disabled(!canSend)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(
            Capsule()
                .fill(Color.ssUserBubble)
        )
    }

    private var twinGreen: Color {
        Color.ssTwinGreen
    }

    private var canSend: Bool {
        isEnabled && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func sendIfValid() {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty && isEnabled else { return }
        onSend(trimmed)
        text = ""
    }
}
