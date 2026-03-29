import SwiftUI

// MARK: - Twin Message Bubble

/// Chat bubble for Twin messages. Dark olive background, left-aligned, white text.
/// Matches Figma node 90:112.
struct TwinMessageBubble: View {
    let text: String
    let timestamp: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .bottom, spacing: 0) {
                // Tail on the left
                BubbleTail(isUser: false)
                    .fill(Color.ssTwinOlive)
                    .frame(width: 15, height: 20)
                    .offset(x: 4, y: -1)

                Text(text)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(.white)
                    .textSelection(.enabled)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(
                        RoundedRectangle(cornerRadius: 15)
                            .fill(
                                LinearGradient(
                                    colors: [
                                        Color.ssTwinOlive.opacity(0.85),
                                        Color.ssTwinOlive
                                    ],
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                    )

                Spacer(minLength: 60)
            }

            Text(formattedTime)
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(Color.ssCream.opacity(0.6))
        }
    }

    private static let timeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "h:mm a"
        return f
    }()

    private var formattedTime: String {
        Self.timeFormatter.string(from: timestamp)
    }
}
