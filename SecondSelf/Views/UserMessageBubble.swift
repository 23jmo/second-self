import SwiftUI

// MARK: - User Message Bubble

/// Chat bubble for user messages. Olive green background, right-aligned, white text.
/// Matches Figma node 90:103.
struct UserMessageBubble: View {
    let text: String
    let timestamp: Date

    var body: some View {
        VStack(alignment: .trailing, spacing: 5) {
            HStack(alignment: .bottom, spacing: 0) {
                Spacer(minLength: 60)

                Text(text)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(.white)
                    .textSelection(.enabled)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(
                        RoundedRectangle(cornerRadius: 15)
                            .fill(Color.ssUserOlive)
                    )

                // Tail on the right
                BubbleTail(isUser: true)
                    .fill(Color.ssUserOlive)
                    .frame(width: 15, height: 20)
                    .offset(x: -4, y: -1)
            }

            Text(formattedTime)
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(Color.ssCream.opacity(0.6))
        }
    }

    private var formattedTime: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "h:mm a"
        return formatter.string(from: timestamp)
    }
}
