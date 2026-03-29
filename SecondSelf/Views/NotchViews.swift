import SwiftUI

// MARK: - Expanded Notch Content

/// Switches between status mini view (stage 1) and full chat (stage 2).
/// DynamicNotchKit sees this as one "expanded" view, but we swap content internally.
struct ExpandedNotchContent: View {
    @ObservedObject var chatViewModel: ChatViewModel

    var body: some View {
        VStack(spacing: 0) {
            if chatViewModel.expansionStage >= 2 {
                fullChatContent
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .bottom)),
                        removal: .opacity
                    ))
            } else {
                statusMiniContent
                    .transition(.asymmetric(
                        insertion: .opacity,
                        removal: .opacity.combined(with: .move(edge: .bottom))
                    ))
            }
        }
        .animation(.ssPanelSpring, value: chatViewModel.expansionStage)
        .environment(\.colorScheme, .dark)
    }

    // MARK: - Stage 1: Status Mini View

    private var statusMiniContent: some View {
        HStack(spacing: 10) {
            // Twin character
            TwinCharacterView(twinState: chatViewModel.twinState, compact: true)
                .frame(width: 28, height: 28)

            // Status chip
            HStack(spacing: 4) {
                Circle()
                    .fill(chatViewModel.isConnected ? Color.ssSuccess : Color.ssError)
                    .frame(width: 5, height: 5)
                Text(statusText)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(Color.ssTextSecondary)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(
                Capsule()
                    .fill(Color.ssUserBubble)
            )

            // Twin state chip (only when active)
            if chatViewModel.twinState == .working || chatViewModel.twinState == .thinking {
                HStack(spacing: 4) {
                    Circle()
                        .fill(Color.ssTwinGreen)
                        .frame(width: 5, height: 5)
                    Text(chatViewModel.twinState == .thinking ? "Thinking" : "Working")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(Color.ssTwinGreen)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(
                    Capsule()
                        .fill(Color.ssTwinGreen.opacity(0.15))
                )
                .transition(.scale.combined(with: .opacity))
            }

            Spacer()
        }
        .padding(.horizontal, 14)
        .frame(width: 300, height: 36)
        .contentShape(Rectangle())
        .onTapGesture { chatViewModel.onNotchTap?() }
        .animation(.ssContentReveal, value: chatViewModel.twinState)
    }

    // MARK: - Stage 2: Full Chat (matches Figma 90:102)

    private var fullChatContent: some View {
        VStack(spacing: 0) {
            // Chat messages (no header, chat starts immediately)
            ChatView(viewModel: chatViewModel)

            // VNC PiP: appears when agent starts working, stays until user dismisses
            if chatViewModel.showVNCFeed {
                ZStack(alignment: .topTrailing) {
                    VNCPipView(twinState: chatViewModel.twinState)
                        .frame(maxWidth: .infinity)
                        .frame(height: 220)

                    // Dismiss button overlaid on stream
                    Button(action: { chatViewModel.dismissVNCFeed() }) {
                        Image(systemName: "xmark")
                            .font(.system(size: 8, weight: .bold))
                            .foregroundColor(.white.opacity(0.7))
                            .padding(5)
                            .background(Circle().fill(Color.black.opacity(0.5)))
                    }
                    .buttonStyle(.plain)
                    .padding(6)
                }
                .clipShape(RoundedRectangle(cornerRadius: 5))
                .padding(.horizontal, 12)
                .padding(.bottom, 8)
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            }

            // Input bar
            ChatInputBar(
                text: $chatViewModel.inputText,
                isEnabled: chatViewModel.twinState != .thinking && chatViewModel.twinState != .working,
                voiceState: chatViewModel.voiceState,
                audioLevel: chatViewModel.audioLevel,
                onSend: { text in chatViewModel.sendMessage(text: text) },
                onTapToRecord: { chatViewModel.startRecording() },
                onTapToStop: { chatViewModel.stopRecording() },
                onVoiceCancel: { chatViewModel.cancelVoiceRecording() },
                onPermissionTap: { chatViewModel.requestMicPermission() }
            )
            .padding(.horizontal, 12)
            .padding(.bottom, 12)
            .onAppear { chatViewModel.checkMicPermission() }
        }
        .frame(width: 420, height: 560)
        .background(Color.ssNotchBlack)
    }

    private var statusText: String {
        if !chatViewModel.isConnected { return "Connecting..." }
        switch chatViewModel.twinState {
        case .idle:     return "Ready"
        case .thinking: return "Thinking..."
        case .working:  return "Working..."
        case .complete: return "Done"
        case .error:    return "Error"
        }
    }
}

// MARK: - Compact Leading Content

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

struct CompactTrailingContent: View {
    @ObservedObject var chatViewModel: ChatViewModel
    @State private var showCompletionBadge = false

    var body: some View {
        HStack(spacing: 4) {
            if showCompletionBadge {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 10))
                    .foregroundColor(Color.ssTwinGreen)
                    .transition(.scale.combined(with: .opacity))
            }

            Circle()
                .fill(chatViewModel.isConnected ? Color.ssSuccess : Color.ssError)
                .frame(width: 8, height: 8)
        }
        .contentShape(Rectangle())
        .onTapGesture { chatViewModel.onNotchTap?() }
        .onChange(of: chatViewModel.twinState) { newState in
            if newState == .complete {
                withAnimation(.ssMicro) { showCompletionBadge = true }
                Task {
                    try? await Task.sleep(for: .seconds(2))
                    withAnimation(.ssContentDismiss) { showCompletionBadge = false }
                }
            }
        }
    }
}
