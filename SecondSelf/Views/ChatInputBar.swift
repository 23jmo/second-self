import SwiftUI

// MARK: - Chat Input Bar

/// Rounded input bar with olive send button. Matches Figma node 90:129.
struct ChatInputBar: View {
    @Binding var text: String
    let isEnabled: Bool
    let onSend: (String) -> Void

    @FocusState private var isFocused: Bool

    var body: some View {
        HStack(spacing: 8) {
            TextField("Message your Twin...", text: $text)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundColor(Color.ssTextPrimary)
                .focused($isFocused)
                .onSubmit { sendIfValid() }
                .disabled(!isEnabled)

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
        .onAppear {
            // Delay focus request so the panel animation settles
            // and the view is fully in the responder chain
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                isFocused = true
            }
        }
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
