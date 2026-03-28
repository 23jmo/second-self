import SwiftUI

struct VNCPlaceholder: View {
    @State private var isPulsing = false

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(white: 0.08))
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .strokeBorder(Theme.pillBorder, lineWidth: 1)
                )

            VStack(spacing: 12) {
                Image(systemName: "display")
                    .font(.system(size: 32))
                    .foregroundStyle(Theme.secondaryText)
                    .opacity(isPulsing ? 0.4 : 0.8)
                    .animation(
                        .easeInOut(duration: 1.5).repeatForever(autoreverses: true),
                        value: isPulsing
                    )

                Text("VNC Stream")
                    .font(Theme.captionFont)
                    .foregroundStyle(Theme.secondaryText)

                Text("Connecting...")
                    .font(.system(size: 10))
                    .foregroundStyle(Theme.secondaryText.opacity(0.5))
            }
        }
        .onAppear { isPulsing = true }
    }
}
