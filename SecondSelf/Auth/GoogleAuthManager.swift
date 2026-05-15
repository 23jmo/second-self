import Foundation
import AppKit

// MARK: - Google Auth Manager

/// Handles Firebase-routed Google OAuth.
/// Opens the local FastAPI login page (localhost:8000/auth/login) in the user's
/// default browser, then polls for the session in .session_store.json.
final class GoogleAuthManager: NSObject, ObservableObject {
    @Published var isAuthenticated: Bool = false
    @Published var isAuthenticating: Bool = false
    @Published var errorMessage: String?
    @Published var userName: String?

    /// Callback fired when auth succeeds — app delegate uses this to start the orchestrator.
    var onAuthenticated: (() -> Void)?

    private var pollTimer: Timer?
    private let sessionStorePath: String
    /// Session count when sign-in started — used to detect new sessions during polling.
    private var sessionCountAtSignInStart: Int = 0

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

        // Open login page in the user's real browser — ASWebAuthenticationSession's
        // sandboxed browser blocks Firebase popups and loses redirect state,
        // so we use the default browser which handles OAuth correctly.
        guard let authURL = URL(string: "http://localhost:8000/auth/login") else {
            errorMessage = "Invalid auth URL"
            isAuthenticating = false
            return
        }

        // Snapshot current session count so polling detects only NEW sessions
        sessionCountAtSignInStart = currentSessionCount()

        NSWorkspace.shared.open(authURL)

        // Poll for session file — login page POSTs tokens to backend,
        // which writes .session_store.json. We detect it here.
        startPollingForSession()
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

    private func currentSessionCount() -> Int {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: sessionStorePath)),
              let store = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return 0
        }
        return store.count
    }

    private func checkForNewSession() {
        guard let data = try? Data(contentsOf: URL(fileURLWithPath: sessionStorePath)),
              let store = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              store.count > sessionCountAtSignInStart else {
            return
        }

        // A new session appeared — grab the latest one
        if let lastKey = store.keys.sorted().last,
           let session = store[lastKey] as? [String: Any],
           let name = session["name"] as? String {
            userName = name
            isAuthenticated = true
            isAuthenticating = false
            stopPolling()
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
