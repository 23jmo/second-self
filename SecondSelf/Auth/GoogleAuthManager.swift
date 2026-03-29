import Foundation
import AuthenticationServices
import AppKit

// MARK: - Google Auth Manager

/// Handles Auth0-based Google OAuth via ASWebAuthenticationSession.
/// Opens the local FastAPI endpoint (localhost:8000/auth/login) which redirects
/// to Auth0's /authorize endpoint for Google sign-in. After auth, polls for
/// the session in .session_store.json.
final class GoogleAuthManager: NSObject, ObservableObject, ASWebAuthenticationPresentationContextProviding {
    @Published var isAuthenticated: Bool = false
    @Published var isAuthenticating: Bool = false
    @Published var errorMessage: String?
    @Published var userName: String?

    /// Callback fired when auth succeeds — app delegate uses this to show the notch.
    var onAuthenticated: (() -> Void)?

    private var authSession: ASWebAuthenticationSession?
    private var pollTimer: Timer?
    private let sessionStorePath: String

    override init() {
        // Find .session_store.json relative to the executable (same as discoverEnvironment)
        let execURL = Bundle.main.executableURL ?? URL(fileURLWithPath: ProcessInfo.processInfo.arguments[0])
        var root = execURL.deletingLastPathComponent()
        for _ in 0..<10 {
            if FileManager.default.fileExists(atPath: root.appendingPathComponent("orchestrator/server.py").path) {
                break
            }
            root = root.deletingLastPathComponent()
        }
        self.sessionStorePath = root.appendingPathComponent(".session_store.json").path
        super.init()
        checkExistingSession()
    }

    // MARK: - Check Existing Session

    func checkExistingSession() {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: sessionStorePath)),
              let store = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              !store.isEmpty else {
            isAuthenticated = false
            return
        }

        // Get the latest session's name
        if let lastKey = store.keys.sorted().last,
           let session = store[lastKey] as? [String: Any],
           let name = session["name"] as? String {
            userName = name
            isAuthenticated = true
        }
    }

    // MARK: - Sign In

    @MainActor
    func signIn() {
        isAuthenticating = true
        errorMessage = nil

        // The FastAPI server at :8000 redirects to Auth0 for Google sign-in
        guard let authURL = URL(string: "http://localhost:8000/auth/login") else {
            errorMessage = "Invalid auth URL"
            isAuthenticating = false
            return
        }

        // Use ASWebAuthenticationSession — opens system browser sheet
        // The callback scheme doesn't matter much since the login page
        // POSTs to the backend directly. We use a custom scheme to close the browser.
        let session = ASWebAuthenticationSession(
            url: authURL,
            callbackURLScheme: "secondself"
        ) { [weak self] callbackURL, error in
            Task { @MainActor in
                self?.handleAuthResult(callbackURL: callbackURL, error: error)
            }
        }

        session.presentationContextProvider = self
        session.prefersEphemeralWebBrowserSession = false
        authSession = session

        if !session.start() {
            errorMessage = "Could not start auth session"
            isAuthenticating = false
        }

        // Also start polling — Auth0 redirects back to the backend which
        // saves tokens to .session_store.json. We detect that file change.
        startPollingForSession()
    }

    // MARK: - ASWebAuthenticationPresentationContextProviding

    @MainActor
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        NSApp.keyWindow ?? NSApp.windows.first ?? ASPresentationAnchor()
    }

    // MARK: - Handle Auth Result

    private func handleAuthResult(callbackURL: URL?, error: Error?) {
        // The browser might close without a callback (user closes tab).
        // That's fine — we're polling for the session file.
        if let error = error as? ASWebAuthenticationSessionError,
           error.code == .canceledLogin {
            // User cancelled — stop polling but don't show error
            isAuthenticating = false
            stopPolling()
            return
        }

        // If we got a callback, the session should already be saved by the backend.
        // Poll will pick it up.
    }

    // MARK: - Poll for Session

    private func startPollingForSession() {
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.checkForNewSession()
            }
        }

        // Timeout after 120 seconds
        DispatchQueue.main.asyncAfter(deadline: .now() + 120) { [weak self] in
            guard let self = self, self.isAuthenticating else { return }
            self.isAuthenticating = false
            self.errorMessage = "Sign-in timed out. Try again."
            self.stopPolling()
        }
    }

    private func stopPolling() {
        pollTimer?.invalidate()
        pollTimer = nil
    }

    private func checkForNewSession() {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: sessionStorePath)),
              let store = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              !store.isEmpty else {
            return
        }

        if let lastKey = store.keys.sorted().last,
           let session = store[lastKey] as? [String: Any],
           let name = session["name"] as? String {
            userName = name
            isAuthenticated = true
            isAuthenticating = false
            stopPolling()
            authSession?.cancel()
            authSession = nil
            onAuthenticated?()
            notifyOrchestratorOfAuth()
        }
    }

    /// Tell the orchestrator to reload Google OAuth token after sign-in.
    private func notifyOrchestratorOfAuth() {
        guard let url = URL(string: "\(ServerConfig.orchestratorURL)/auth/refresh") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 3
        URLSession.shared.dataTask(with: request) { _, _, error in
            if let error = error {
                print("[GoogleAuth] Could not notify orchestrator: \(error.localizedDescription)")
            } else {
                print("[GoogleAuth] Orchestrator token refreshed")
            }
        }.resume()
    }
}
