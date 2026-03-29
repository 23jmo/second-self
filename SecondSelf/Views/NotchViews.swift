import SwiftUI

// MARK: - Expanded Notch Content

/// Switches between status mini view (stage 1) and full chat (stage 2).
/// DynamicNotchKit sees this as one "expanded" view, but we swap content internally.
struct ExpandedNotchContent: View {
    @ObservedObject var chatViewModel: ChatViewModel
    @ObservedObject var authManager: GoogleAuthManager

    // Medium expansion: cycling status text
    @State private var currentWordIndex = 0
    @State private var dotPulsePhase = false
    @State private var showSignOutConfirm = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 0) {
            if chatViewModel.needsSetup && chatViewModel.expansionStage >= 2 {
                // First-run setup wizard
                SetupWizardView(authManager: authManager) {
                    chatViewModel.needsSetup = false
                }
                    .transition(.asymmetric(
                        insertion: .opacity.combined(with: .move(edge: .bottom)),
                        removal: .opacity
                    ))
            } else if !authManager.isAuthenticated {
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
        .animation(.ssPanelSpring, value: chatViewModel.needsSetup)
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

    // MARK: - Stage 1: Medium Expansion Bar (personality bar)

    private var isActiveState: Bool {
        chatViewModel.twinState == .thinking || chatViewModel.twinState == .working
    }

    private var statusMiniContent: some View {
        HStack(spacing: 12) {
            // Status text with crossfade
            ZStack {
                Text(displayText)
                    .font(.system(size: 18, weight: .medium))
                    .foregroundColor(Color.ssTextPrimary)
                    .id(displayText)
                    .transition(.opacity)
            }
            .animation(.ssContentReveal, value: displayText)

            Spacer()

            // Status indicator
            statusIndicator
        }
        .padding(.leading, 14)
        .padding(.trailing, 14)
        .frame(width: 360, height: 56)
        .contentShape(Rectangle())
        .onTapGesture { chatViewModel.onNotchTap?() }
        .task(id: isActiveState) {
            guard isActiveState else {
                withAnimation(.ssMicro) { dotPulsePhase = false }
                return
            }
            // Randomize starting word each time twin becomes active
            currentWordIndex = Int.random(in: 0..<ThinkingWords.all.count)
            withAnimation(.easeInOut(duration: 1.0).repeatForever(autoreverses: true)) {
                dotPulsePhase = true
            }
            // Cycle words every 2.5s while active
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(2.5))
                guard !Task.isCancelled else { break }
                currentWordIndex = (currentWordIndex + 1) % ThinkingWords.all.count
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Twin status: \(accessibilityStatusText)")
    }

    // MARK: - Stage 2: Full Chat (matches Figma 136:996)

    private var fullChatContent: some View {
        ZStack(alignment: .topTrailing) {
        VStack(spacing: 0) {
            // Chat messages (no header, chat starts immediately)
            ChatView(viewModel: chatViewModel)

            // Mascot + Input bar
            HStack(alignment: .bottom, spacing: 6) {
                MascotGIFView(width: 32, height: 42)
                    .frame(width: 32, height: 42)
                    .offset(x: -8, y: -4)

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
            }
            .padding(.horizontal, 12)
            .padding(.bottom, 8)
            .onAppear { chatViewModel.checkMicPermission() }

            // Bottom lip — show/hide PiP
            Button(action: { chatViewModel.toggleVNCFeed() }) {
                HStack {
                    Spacer()
                    Image(systemName: chatViewModel.showVNCFeed ? "chevron.compact.up" : "chevron.compact.down")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.white.opacity(0.4))
                    Spacer()
                }
                .frame(height: 26)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .frame(width: 420, height: 560)
        .background(Color.ssNotchBlack)

            // Sign out button — top right overlay
            if showSignOutConfirm {
                Button(action: {
                    authManager.signOut()
                    showSignOutConfirm = false
                }) {
                    Text("Sign out?")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundColor(Color.ssError)
                }
                .buttonStyle(.plain)
                .padding(.top, 28)
                .padding(.trailing, 16)
                .transition(.opacity)
            } else {
                Button(action: { withAnimation(.ssMicro) { showSignOutConfirm = true } }) {
                    Image(systemName: "rectangle.portrait.and.arrow.right")
                        .font(.system(size: 10))
                        .foregroundColor(.white.opacity(0.25))
                }
                .buttonStyle(.plain)
                .padding(.top, 28)
                .padding(.trailing, 16)
            }
        } // ZStack
        .animation(.ssMicro, value: showSignOutConfirm)
    }

    // MARK: - Medium Expansion Helpers

    private var firstName: String {
        authManager.userName?.components(separatedBy: " ").first ?? "Twin"
    }

    private var displayText: String {
        if reduceMotion && isActiveState {
            return chatViewModel.twinState == .thinking ? "Thinking..." : "Working..."
        }
        switch chatViewModel.twinState {
        case .thinking, .working:
            return ThinkingWords.all[currentWordIndex % ThinkingWords.all.count]
        case .error:
            return "Oops"
        default:
            return "Other \(firstName) is Ready!"
        }
    }

    @ViewBuilder
    private var statusIndicator: some View {
        Circle()
            .fill(statusDotColor)
            .frame(width: 5, height: 5)
            .opacity(dotPulsePhase ? 0.3 : 1.0)
    }

    private var statusDotColor: Color {
        if !chatViewModel.isConnected { return Color.ssError }
        switch chatViewModel.twinState {
        case .idle:               return Color.ssSuccess
        case .thinking, .working: return Color.ssTwinGreen
        case .complete:           return Color.ssSuccess
        case .error:              return Color.ssError
        }
    }

    private var accessibilityStatusText: String {
        switch chatViewModel.twinState {
        case .thinking: return "Thinking"
        case .working:  return "Working"
        case .error:    return "Error"
        default:        return "\(firstName) is ready"
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
