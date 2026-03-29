import SwiftUI

// MARK: - Expanded Notch Content

/// Switches between status mini view (stage 1) and full chat (stage 2).
/// DynamicNotchKit sees this as one "expanded" view, but we swap content internally.
struct ExpandedNotchContent: View {
    @ObservedObject var chatViewModel: ChatViewModel
    @ObservedObject var authManager: GoogleAuthManager

    var body: some View {
        VStack(spacing: 0) {
            if !authManager.isAuthenticated {
                // Not signed in — show sign-in view
                if chatViewModel.expansionStage >= 2 {
                    signInExpandedContent
                        .transition(.asymmetric(
                            insertion: .opacity.combined(with: .move(edge: .bottom)),
                            removal: .opacity
                        ))
                } else {
                    signInMiniContent
                        .transition(.asymmetric(
                            insertion: .opacity,
                            removal: .opacity.combined(with: .move(edge: .bottom))
                        ))
                }
            } else if chatViewModel.expansionStage >= 2 {
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
        .animation(.ssPanelSpring, value: authManager.isAuthenticated)
        .environment(\.colorScheme, .dark)
    }

    // MARK: - Sign In: Mini (stage 1)

    private var signInMiniContent: some View {
        HStack(spacing: 10) {
            Image(systemName: "person.crop.circle")
                .font(.system(size: 16))
                .foregroundColor(Color.ssTwinGreen)

            Text("Sign in to get started")
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(Color.ssTextSecondary)

            Spacer()
        }
        .padding(.horizontal, 14)
        .frame(width: 300, height: 36)
        .contentShape(Rectangle())
        .onTapGesture { chatViewModel.onNotchTap?() }
    }

    // MARK: - Sign In: Expanded (stage 2)

    private var signInExpandedContent: some View {
        VStack(spacing: 20) {
            Spacer()

            VStack(spacing: 6) {
                Text("Second Self")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundColor(Color.ssTextPrimary)

                Text("Sign in to activate your digital twin")
                    .font(.system(size: 12))
                    .foregroundColor(Color.ssTextSecondary)
            }

            Button(action: { authManager.signIn() }) {
                HStack(spacing: 8) {
                    Image(systemName: "person.crop.circle.fill")
                        .font(.system(size: 16))
                    Text("Sign in with Google")
                        .font(.system(size: 13, weight: .semibold))
                }
                .foregroundColor(.white)
                .padding(.horizontal, 20)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.ssTwinGreen)
                )
            }
            .buttonStyle(.plain)
            .disabled(authManager.isAuthenticating)

            if authManager.isAuthenticating {
                HStack(spacing: 6) {
                    ProgressView()
                        .progressViewStyle(.circular)
                        .scaleEffect(0.7)
                    Text("Waiting for sign-in...")
                        .font(.system(size: 11))
                        .foregroundColor(Color.ssTextSecondary)
                }
            }

            if let error = authManager.errorMessage {
                Text(error)
                    .font(.system(size: 10))
                    .foregroundColor(Color.ssError)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 20)
            }

            Spacer()
        }
        .frame(width: 420, height: 300)
        .background(Color.ssNotchBlack)
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

    // MARK: - Stage 2: Full Chat (matches Figma 136:996)

    private var fullChatContent: some View {
        VStack(spacing: 0) {
            // Chat messages (no header, chat starts immediately)
            ChatView(viewModel: chatViewModel)

            // VNC PiP: shows on computer-use tool calls, fills remaining space
            if chatViewModel.showVNCFeed {
                ZStack {
                    VNCPipView(twinState: chatViewModel.twinState)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)

                    // Dismiss button — top right
                    VStack {
                        HStack {
                            Spacer()
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
                        Spacer()
                    }

                    // Twin character — bottom right
                    VStack {
                        Spacer()
                        HStack {
                            Spacer()
                            TwinCharacterView(twinState: chatViewModel.twinState)
                                .frame(width: 72, height: 99)
                                .offset(x: 4, y: 10)
                        }
                    }
                }
                .padding(.horizontal, 12)
                .padding(.bottom, 4)
                .transition(.opacity.combined(with: .move(edge: .bottom)))
            }

            // Input bar
            ChatInputBar(
                text: $chatViewModel.inputText,
                isEnabled: chatViewModel.twinState != .thinking && chatViewModel.twinState != .working,
                onSend: { text in chatViewModel.sendMessage(text: text) }
            )
            .padding(.horizontal, 12)
            .padding(.bottom, 12)
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
    @ObservedObject var authManager: GoogleAuthManager
    @State private var pulsePhase: Bool = false

    var body: some View {
        if authManager.isAuthenticated {
            TwinCharacterView(twinState: chatViewModel.twinState, compact: true)
                .frame(width: 24, height: 24)
                .contentShape(Rectangle())
                .onTapGesture { chatViewModel.onNotchTap?() }
        } else {
            HStack(spacing: 6) {
                Image(systemName: "person.crop.circle")
                    .font(.system(size: 12))
                    .foregroundColor(Color.ssTwinGreen)
                Text("Sign in")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundColor(Color.ssTwinGreen)
            }
            .opacity(pulsePhase ? 1.0 : 0.5)
            .animation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true), value: pulsePhase)
            .onAppear { pulsePhase = true }
            .contentShape(Rectangle())
            .onTapGesture { chatViewModel.onNotchTap?() }
        }
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
