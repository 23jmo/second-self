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
        // Find .session_store.json — check known install locations first, then walk up from binary
        let fm = FileManager.default
        let home = NSHomeDirectory()
        let knownRoots = [
            "\(home)/second-self",
            "/usr/local/share/second-self",
        ]

        var foundRoot: String? = nil
        for root in knownRoots {
            if fm.fileExists(atPath: "\(root)/orchestrator/server.py") {
                foundRoot = root
                break
            }
        }

        // Fallback: walk up from binary (works in dev with swift run)
        if foundRoot == nil {
            let execURL = Bundle.main.executableURL ?? URL(fileURLWithPath: ProcessInfo.processInfo.arguments[0])
            var candidate = execURL.deletingLastPathComponent()
            for _ in 0..<10 {
                if fm.fileExists(atPath: candidate.appendingPathComponent("orchestrator/server.py").path) {
                    foundRoot = candidate.path
                    break
                }
                candidate = candidate.deletingLastPathComponent()
            }
        }

        self.sessionStorePath = (foundRoot ?? "\(home)/second-self") + "/.session_store.json"
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

        // Firebase login page handles Google OAuth popup, gets real access token
        guard let authURL = URL(string: "http://localhost:8000/auth/login") else {
            errorMessage = "Invalid auth URL"
            isAuthenticating = false
            return
        }

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

        // Poll for session file — Firebase login POSTs tokens to backend
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

    // MARK: - Sign Out

    func signOut() {
        // Clear session file
        try? "{}".data(using: .utf8)?.write(to: URL(fileURLWithPath: sessionStorePath))
        isAuthenticated = false
        userName = nil
        print("[GoogleAuth] Signed out")
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
