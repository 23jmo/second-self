import SwiftUI

// MARK: - User Message Bubble

/// Chat bubble for messages from the user.
/// Dark gray background, no border, regular text, right-aligned.
struct UserMessageBubble: View {
    let text: String
    let timestamp: Date

    var body: some View {
        HStack {
            Spacer(minLength: 60)

            VStack(alignment: .trailing, spacing: 4) {
                Text(text)
                    .font(.system(size: 13))
                    .foregroundColor(Color.ssTextPrimary)
                    .textSelection(.enabled)

                Text(formattedTime)
                    .font(.system(size: 10))
                    .foregroundColor(Color.ssTextSecondary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.ssUserBubble)
            )
        }
    }

    private var formattedTime: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "h:mm a"
        return formatter.string(from: timestamp)
    }
}
