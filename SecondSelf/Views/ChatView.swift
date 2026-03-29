import SwiftUI

// MARK: - Chat View

/// Full chat interface with message list, VNC PiP, and input bar.
/// Shown in the .fullChat panel state.
struct ChatView: View {
    @ObservedObject var viewModel: ChatViewModel

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            VStack(spacing: 0) {
                // Message list
                ScrollViewReader { scrollProxy in
                    ScrollView {
                        LazyVStack(spacing: 8) {
                            ForEach(viewModel.messages) { message in
                                messageView(for: message)
                                    .id(message.id)
                            }

                            // "Twin is working..." indicator
                            if viewModel.twinState == .thinking || viewModel.twinState == .working {
                                TwinWorkingIndicator(state: viewModel.twinState)
                                    .id("working-indicator")
                            }
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                    }
                    .onChange(of: viewModel.messages.count) { _ in
                        withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
                            if let lastMessage = viewModel.messages.last {
                                scrollProxy.scrollTo(lastMessage.id, anchor: .bottom)
                            }
                        }
                    }
                }

                // Input bar
                ChatInputBar(
                    text: $viewModel.inputText,
                    isEnabled: viewModel.twinState != .thinking && viewModel.twinState != .working,
                    onSend: { text in
                        viewModel.sendMessage(text: text)
                    }
                )
                .padding(.horizontal, 12)
                .padding(.bottom, 12)
                .padding(.top, 6)
            }

            // VNC PiP thumbnail in bottom-right
            VNCPipView(twinState: viewModel.twinState)
                .padding(.trailing, 16)
                .padding(.bottom, 72) // Above the input bar
        }
        .background(Color(hex: 0x1C1C1E))
    }

    @ViewBuilder
    private func messageView(for message: ChatMessage) -> some View {
        switch message.content {
        case .text(let text):
            if message.sender == .twin {
                TwinMessageBubble(text: text, timestamp: message.timestamp)
            } else {
                UserMessageBubble(text: text, timestamp: message.timestamp)
            }
        case .toolCall(let tool, let args, let result):
            ToolCallPill(tool: tool, args: args, result: result)
        }
    }
}

// MARK: - Twin Working Indicator

struct TwinWorkingIndicator: View {
    let state: TwinState

    @State private var dotCount: Int = 1
    private let timer = Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack {
            HStack(spacing: 6) {
                // Animated dots
                ForEach(0..<3, id: \.self) { index in
                    Circle()
                        .fill(Color(hex: 0xB5B055))
                        .frame(width: 5, height: 5)
                        .opacity(index < dotCount ? 1.0 : 0.3)
                }

                Text(state == .thinking ? "Twin is thinking" : "Twin is working")
                    .font(.system(size: 11))
                    .italic()
                    .foregroundColor(Color(hex: 0x8E8E93))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(
                Capsule()
                    .fill(Color(hex: 0x1C1C1E))
                    .overlay(
                        Capsule()
                            .stroke(Color(hex: 0x333333), lineWidth: 0.5)
                    )
            )

            Spacer()
        }
        .onReceive(timer) { _ in
            dotCount = (dotCount % 3) + 1
        }
    }
}
