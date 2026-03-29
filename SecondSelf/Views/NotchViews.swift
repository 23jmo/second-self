import SwiftUI

// MARK: - Expanded Notch Content

/// Full content shown when the notch expands.
/// Contains the chat header, chat messages, input bar, and VNC PiP.
struct ExpandedNotchContent: View {
    @ObservedObject var chatViewModel: ChatViewModel

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                TwinCharacterView(twinState: chatViewModel.twinState, compact: true)
                    .frame(width: 28, height: 28)

                Text("Second Self")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(Color.ssTextPrimary)

                Spacer()

                Circle()
                    .fill(chatViewModel.isConnected ? Color.ssSuccess : Color.ssError)
                    .frame(width: 6, height: 6)

                Button(action: { chatViewModel.onNotchClose?() }) {
                    Image(systemName: "chevron.up")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(Color.ssTextSecondary)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)

            Divider()
                .background(Color.ssBorder)

            // Chat + VNC
            ZStack(alignment: .bottomTrailing) {
                ChatView(viewModel: chatViewModel)

                VNCPipView(twinState: chatViewModel.twinState)
                    .frame(width: 120, height: 75)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .padding(.trailing, 12)
                    .padding(.bottom, 68)
            }
        }
        .frame(width: 380, height: 480)
        .background(Color.ssSurface)
    }
}

// MARK: - Compact Leading Content

/// Shown to the left of the notch in compact mode.
/// Twin character head. Tap anywhere on the notch area to expand.
struct CompactLeadingContent: View {
    @ObservedObject var chatViewModel: ChatViewModel

    var body: some View {
        TwinCharacterView(twinState: chatViewModel.twinState, compact: true)
            .frame(width: 24, height: 24)
            .contentShape(Rectangle())
            .onTapGesture { chatViewModel.onNotchTap?() }
    }
}

// MARK: - Compact Trailing Content

/// Shown to the right of the notch in compact mode.
/// Connection status dot. Tap to expand.
struct CompactTrailingContent: View {
    @ObservedObject var chatViewModel: ChatViewModel

    var body: some View {
        Circle()
            .fill(chatViewModel.isConnected ? Color.ssSuccess : Color.ssError)
            .frame(width: 8, height: 8)
            .contentShape(Rectangle())
            .onTapGesture { chatViewModel.onNotchTap?() }
    }
}
