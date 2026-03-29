import SwiftUI

// MARK: - Chat View

/// Message list only. Input bar and VNC are handled by NotchViews.
struct ChatView: View {
    @ObservedObject var viewModel: ChatViewModel

    var body: some View {
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                // Suggestion banner (slides in from top)
                if let suggestion = viewModel.currentSuggestion {
                    SuggestionBanner(
                        suggestion: suggestion,
                        onAccept: { viewModel.acceptSuggestion() },
                        onDismiss: { viewModel.dismissSuggestion() },
                        onTellMeMore: { viewModel.tellMeMore() }
                    )
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .padding(.top, 28)
                    .padding(.horizontal, 19)
                    .zIndex(1)
                }

                ScrollViewReader { scrollProxy in
                    ScrollView {
                        LazyVStack(spacing: 8) {
                            ForEach(viewModel.messages) { message in
                                messageView(for: message)
                                    .id(message.id)
                                    .transition(transitionForMessage(message))
                            }

                            if viewModel.twinState == .thinking || viewModel.twinState == .working {
                                TwinWorkingIndicator()
                                    .id("working-indicator")
                                    .transition(.ssTwinMessage)
                            }
                        }
                    }
                    .padding(.horizontal, 19)
                    .padding(.top, 26)
                    .padding(.bottom, 12)
                    .animation(.ssMessageEntrance, value: viewModel.messages.count)
                    .onAppear {
                        if let lastMessage = viewModel.messages.last {
                            scrollProxy.scrollTo(lastMessage.id, anchor: .bottom)
                        }
                    }
                    .onChange(of: viewModel.messages.count) { _ in
                        withAnimation(.ssScrollSpring) {
                            if let lastMessage = viewModel.messages.last {
                                scrollProxy.scrollTo(lastMessage.id, anchor: .bottom)
                            }
                        }
                    }
                }
            }

            // Solid black + fade covering the notch area so content can't peek through
            VStack(spacing: 0) {
                Color.black
                    .frame(height: 16)

                LinearGradient(
                    colors: [.black, .black.opacity(0)],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .frame(height: 8)
            }
            .allowsHitTesting(false)
        }
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
        case .toolCall(let tool, let args, let result, let progress):
            ToolCallPill(tool: tool, args: args, result: result, progress: progress)
        case .component(let payload):
            A2UIRenderer(payload: payload, isStreaming: false, onAction: { actionId, context in
                viewModel.sendComponentAction(actionId: actionId, context: context)
            })
        }
    }

    private func transitionForMessage(_ message: ChatMessage) -> AnyTransition {
        switch message.content {
        case .text:
            return message.sender == .twin ? .ssTwinMessage : .ssUserMessage
        case .toolCall:
            return .ssToolPill
        case .component:
            return .ssToolPill
        }
    }
}

// MARK: - Twin Working Indicator

struct TwinWorkingIndicator: View {
    @State private var phase: Int = 0

    var body: some View {
        HStack {
            TimelineView(.periodic(from: .now, by: 0.4)) { context in
                HStack(spacing: 5) {
                    ForEach(0..<3, id: \.self) { index in
                        Circle()
                            .fill(Color.white.opacity(0.9))
                            .frame(width: 8, height: 8)
                            .scaleEffect(index == phase ? 1.15 : 1.0)
                            .opacity(index == phase ? 1.0 : 0.5)
                            .animation(.ssMicro, value: phase)
                    }
                }
                .onChange(of: context.date) { _ in
                    phase = (phase + 1) % 3
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                RoundedRectangle(cornerRadius: 15)
                    .fill(Color.ssTwinOlive)
            )

            Spacer()
        }
    }
}
