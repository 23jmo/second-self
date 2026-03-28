import SwiftUI

enum PanelState: Sendable {
    case collapsed
    case preview
    case expanded
}

@Observable
@MainActor
final class NotchViewModel {
    var panelState: PanelState = .collapsed
    var previewText: String = "Setting up..."
    var inputText: String = ""
    var inputPlaceholder: String = "Message SecondSelf..."
    var isStatusActive: Bool = false
    var isLoading: Bool = false
    var responseText: String = ""
    var actionsText: String = ""
    var sessionId: String = ""
    var isOnboarded: Bool = false

    var onStateChange: (@Sendable (PanelState) -> Void)?

    // MARK: - Auto-connect on launch

    func connectOnLaunch() {
        isLoading = true
        previewText = "Connecting..."

        Task {
            // Step 1: Check if user already logged in via browser (has Google tokens)
            do {
                let latest = try await APIClient.shared.fetchLatestSession()
                if latest.found, let sid = latest.session_id {
                    let name = latest.name ?? "you"

                    if latest.has_profile == true {
                        // Profile already built (browser ran /onboard) — ready immediately
                        sessionId = sid
                        isOnboarded = true
                        isStatusActive = true
                        previewText = "Ready — click to chat."
                        responseText = "Connected as \(name). Ask me to do something — send an email, schedule a meeting, look something up."
                        isLoading = false
                        return
                    }

                    // Browser session exists but no profile yet — run onboard with that session_id
                    // so the profile is cached under the same session that has Google tokens
                    previewText = "Building your profile..."
                    let onboardedSid = try await APIClient.shared.onboard(name: name, sessionId: sid)
                    sessionId = onboardedSid
                    isOnboarded = true
                    isStatusActive = true
                    previewText = "Ready — click to chat."
                    responseText = "Profile built for \(name). Ask me to do something — send an email, schedule a meeting, look something up."
                    isLoading = false
                    return
                }
            } catch {
                // Server might not be running yet — fall through to fallback
            }

            // Step 2: No browser session — onboard with just the name (Tavily only, no email/calendar tools)
            previewText = "No Google session. Building profile..."
            let userName = ProcessInfo.processInfo.environment["SECONDSELF_USER_NAME"]
                ?? NSFullUserName()
            do {
                let sid = try await APIClient.shared.onboard(name: userName)
                sessionId = sid
                isOnboarded = true
                isStatusActive = true
                previewText = "Ready — click to chat."
                responseText = "Profile built (Tavily only). Log in at localhost:8000/auth/login for full features (email, calendar)."
            } catch {
                previewText = "Could not connect to server."
                responseText = "Make sure the server is running: python -m src.server\nThen log in at localhost:8000/auth/login"
            }
            isLoading = false
        }
    }

    // MARK: - State Transitions

    func handleClick() {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
            switch panelState {
            case .collapsed:
                panelState = .expanded  // skip preview, go straight to expanded
            case .preview:
                panelState = .expanded
            case .expanded:
                break
            }
        }
        onStateChange?(panelState)
    }

    func collapse() {
        withAnimation(.spring(response: 0.3, dampingFraction: 0.85)) {
            panelState = .collapsed
        }
        onStateChange?(panelState)
    }

    func toggleExpanded() {
        withAnimation(.spring(response: 0.35, dampingFraction: 0.8)) {
            panelState = panelState == .expanded ? .collapsed : .expanded
        }
        onStateChange?(panelState)
    }

    // MARK: - Chat

    func sendMessage() {
        let message = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty else { return }
        guard !isLoading else { return }
        guard isOnboarded else {
            responseText = "Still setting up — please wait a moment."
            return
        }

        inputText = ""
        isLoading = true
        actionsText = ""
        previewText = "Working on it..."

        Task {
            do {
                let result = try await APIClient.shared.sendChatMessage(message, sessionId: sessionId)
                responseText = result.response
                if !result.actions_taken.isEmpty {
                    actionsText = result.actions_taken
                        .map { "[\($0.tool)] \($0.summary)" }
                        .joined(separator: "\n")
                }
                previewText = String(result.response.prefix(80))
            } catch {
                responseText = "Error: \(error.localizedDescription)"
                previewText = "Something went wrong."
            }
            isLoading = false
        }
    }
}
