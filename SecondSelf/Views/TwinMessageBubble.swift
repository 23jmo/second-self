import SwiftUI

// MARK: - Twin Message Bubble

/// Chat bubble for messages from the Twin.
/// Dark background, 0.5px border, italic text (Twin's voice), left-aligned.
struct TwinMessageBubble: View {
    let text: String
    let timestamp: Date

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(text)
                    .font(.system(size: 13))
                    .italic() // Twin has its own "voice"
                    .foregroundColor(Color(hex: 0xF5F5F7))
                    .textSelection(.enabled)

                Text(formattedTime)
                    .font(.system(size: 10))
                    .foregroundColor(Color(hex: 0x8E8E93))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color(hex: 0x1C1C1E))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(Color(hex: 0x333333), lineWidth: 0.5)
                    )
            )

            Spacer(minLength: 60)
        }
    }

    private var formattedTime: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "h:mm a"
        return formatter.string(from: timestamp)
    }
}
