import SwiftUI
import AppKit

// MARK: - App Entry Point
// macOS notch-resident digital twin app. No dock icon (LSUIElement = true).
// Global hotkey Cmd+Shift+T toggles the chat panel.

@main
struct SecondSelfApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Settings {
            EmptyView()
        }
    }
}

// MARK: - App Delegate

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var overlayController: NotchOverlayController?
    private var globalHotkeyMonitor: Any?
    private var subprocesses: [Process] = []
    private var repoRoot: URL?
    private var pythonPath: String?
    private var envVars: [String: String] = [:]

    private var authManager: GoogleAuthManager?

    // Menu bar status item
    private var statusItem: NSStatusItem?
    private var logEntries: [String] = []
    private let maxLogEntries = 30

    /// Shared accessor for .env variables. Available after applicationDidFinishLaunching.
    /// Used by ElevenLabsService to read ELEVENLABS_API_KEY without duplicating .env parsing.
    static private(set) var sharedEnvVars: [String: String] = [:]

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        // Register default settings
        UserDefaults.standard.register(defaults: [
            "autoExpandOnActivity": true
        ])

        // Discover repo root, python, and env vars once
        discoverEnvironment()

        // Kill stale processes from previous runs
        cleanupStaleProcesses()

        // Verify secondself user exists (first-time install check)
        checkSecondSelfUser()

        // Clear agent browser session for a fresh start
        clearAgentBrowser()

        // Start the FastAPI auth server (needed for Google sign-in page)
        launchModule(module: "uvicorn", args: ["src.server:app", "--host", "127.0.0.1", "--port", "8000"], label: "Auth Server")

        // Create auth manager
        let auth = GoogleAuthManager()
        authManager = auth

        // When auth succeeds, start the orchestrator
        auth.onAuthenticated = { [weak self] in
            Task { @MainActor in
                self?.launchPython(script: "orchestrator/server.py", label: "Orchestrator")
                self?.statusLog("Orchestrator started after sign-in")
            }
        }

        // If already signed in, start orchestrator immediately
        if auth.isAuthenticated {
            statusLog("Session: \(auth.userName ?? "unknown")")
            launchPython(script: "orchestrator/server.py", label: "Orchestrator")
        } else {
            statusLog("No session, sign-in required")
        }

        // Always create the notch — it shows sign-in, setup wizard, or chat
        let setupNeeded = needsFirstRunSetup
        Task { @MainActor in
            let controller = NotchOverlayController(authManager: auth)
            overlayController = controller
            if setupNeeded {
                controller.chatViewModel.needsSetup = true
            }
        }

        // Register global hotkey: Cmd+Shift+T
        globalHotkeyMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: .keyDown
        ) { [weak self] event in
            self?.handleGlobalKeyEvent(event)
        }
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            self?.handleGlobalKeyEvent(event)
            return event
        }

        // Menu bar status icon
        setupStatusItem()

        // Redirect prints to the log buffer
        statusLog("App launched")
        statusLog("Repo: \(repoRoot?.path ?? "not found")")
        statusLog("Python: \(pythonPath ?? "not found")")
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let monitor = globalHotkeyMonitor {
            NSEvent.removeMonitor(monitor)
        }
        for p in subprocesses {
            p.terminate()
            p.waitUntilExit()
        }
    }

    // MARK: - Menu Bar Status Item

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem?.button {
            button.image = NSImage(systemSymbolName: "brain.head.profile", accessibilityDescription: "Second Self")
            button.image?.size = NSSize(width: 18, height: 18)
            button.image?.isTemplate = true
        }
        rebuildMenu()
    }

    private func rebuildMenu() {
        let menu = NSMenu()

        // Status header
        let header = NSMenuItem(title: "Second Self", action: nil, keyEquivalent: "")
        header.isEnabled = false
        menu.addItem(header)
        menu.addItem(NSMenuItem.separator())

        // Connection status
        let orchestratorStatus = checkPort(8420) ? "Orchestrator: running" : "Orchestrator: stopped"
        let agentStatus = checkPort(8421) ? "Agent Server: running" : "Agent Server: stopped"
        let authStatus = checkPort(8000) ? "Auth Server: running" : "Auth Server: stopped"

        for label in [orchestratorStatus, agentStatus, authStatus] {
            let item = NSMenuItem(title: label, action: nil, keyEquivalent: "")
            item.isEnabled = false
            if label.contains("running") {
                item.image = NSImage(systemSymbolName: "circle.fill", accessibilityDescription: nil)
                item.image?.isTemplate = false
                // Green tint via attributed title
            } else {
                item.image = NSImage(systemSymbolName: "circle", accessibilityDescription: nil)
            }
            menu.addItem(item)
        }

        menu.addItem(NSMenuItem.separator())

        // Recent logs
        let logsHeader = NSMenuItem(title: "Recent Logs", action: nil, keyEquivalent: "")
        logsHeader.isEnabled = false
        menu.addItem(logsHeader)

        let recentLogs = logEntries.suffix(10)
        if recentLogs.isEmpty {
            let empty = NSMenuItem(title: "  (no logs yet)", action: nil, keyEquivalent: "")
            empty.isEnabled = false
            menu.addItem(empty)
        } else {
            for entry in recentLogs {
                let item = NSMenuItem(title: "  \(entry)", action: nil, keyEquivalent: "")
                item.isEnabled = false
                item.attributedTitle = NSAttributedString(
                    string: "  \(entry)",
                    attributes: [.font: NSFont.monospacedSystemFont(ofSize: 10, weight: .regular)]
                )
                menu.addItem(item)
            }
        }

        menu.addItem(NSMenuItem.separator())

        // Actions
        menu.addItem(NSMenuItem(title: "Toggle Panel", action: #selector(togglePanel), keyEquivalent: "t"))
        menu.addItem(NSMenuItem(title: "Refresh Status", action: #selector(refreshStatus), keyEquivalent: "r"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit Second Self", action: #selector(quitApp), keyEquivalent: "q"))

        statusItem?.menu = menu
    }

    func statusLog(_ message: String) {
        let timestamp = DateFormatter.localizedString(from: Date(), dateStyle: .none, timeStyle: .medium)
        let entry = "\(timestamp) \(message)"
        logEntries.append(entry)
        if logEntries.count > maxLogEntries {
            logEntries.removeFirst()
        }
        print("[SecondSelf] \(message)")
        // Rebuild menu to show new log
        DispatchQueue.main.async { [weak self] in
            self?.rebuildMenu()
        }
    }

    private func checkPort(_ port: Int) -> Bool {
        let sock = socket(AF_INET, SOCK_STREAM, 0)
        guard sock >= 0 else { return false }
        defer { close(sock) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(port).bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let result = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(sock, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return result == 0
    }

    @objc private func togglePanel() {
        Task { @MainActor in
            overlayController?.togglePanel()
        }
    }

    @objc private func refreshStatus() {
        statusLog("Status refreshed")
        rebuildMenu()
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }

    // MARK: - Startup Cleanup

    private func cleanupStaleProcesses() {
        print("[SecondSelf] Cleaning up stale processes...")

        // Kill old orchestrators on :8420
        killProcesses(matching: "orchestrator/server.py")

        // Kill old auth servers on :8000
        killProcesses(matching: "uvicorn src.server:app")

        // Kill anything holding port 8420 or 8000
        killPort(8420)
        killPort(8000)

        // Brief pause for sockets to release
        Thread.sleep(forTimeInterval: 0.5)
        statusLog("Cleanup done")
    }

    private func killProcesses(matching pattern: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        process.arguments = ["-f", pattern]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try? process.run()
        process.waitUntilExit()
    }

    private func killPort(_ port: Int) {
        // Use lsof to find PID on port, then kill it
        let lsof = Process()
        lsof.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        lsof.arguments = ["-ti", ":\(port)"]
        let pipe = Pipe()
        lsof.standardOutput = pipe
        lsof.standardError = FileHandle.nullDevice
        try? lsof.run()
        lsof.waitUntilExit()

        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !output.isEmpty else { return }

        for pidStr in output.components(separatedBy: .newlines) {
            if let pid = Int32(pidStr.trimmingCharacters(in: .whitespaces)) {
                kill(pid, SIGTERM)
            }
        }
    }

    /// Returns true if first-run setup is needed (user missing or agent not healthy).
    /// The setup wizard is shown in the notch panel via NotchOverlayController.
    private func checkSecondSelfUser() {
        let check = Process()
        check.executableURL = URL(fileURLWithPath: "/usr/bin/id")
        check.arguments = ["secondself"]
        check.standardOutput = FileHandle.nullDevice
        check.standardError = FileHandle.nullDevice
        try? check.run()
        check.waitUntilExit()

        if check.terminationStatus != 0 {
            statusLog("secondself user not found — setup wizard will show")
        } else {
            statusLog("secondself user found")
        }
    }

    /// Whether the first-run setup wizard should be shown.
    /// Only checks UserDefaults + user existence (fast, no network).
    var needsFirstRunSetup: Bool {
        if UserDefaults.standard.bool(forKey: "setupComplete") { return false }

        // Check if secondself user exists (fast shell check)
        let check = Process()
        check.executableURL = URL(fileURLWithPath: "/usr/bin/id")
        check.arguments = ["secondself"]
        check.standardOutput = FileHandle.nullDevice
        check.standardError = FileHandle.nullDevice
        do {
            try check.run()
            check.waitUntilExit()
        } catch {
            return true
        }

        return check.terminationStatus != 0
    }

    private func clearAgentBrowser() {
        // Tell agent-server to close any stale browser session
        guard let url = URL(string: "http://localhost:8421/browser/close") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = "{}".data(using: .utf8)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request) { _, _, error in
            if let error = error {
                print("[SecondSelf] Browser clear skipped (agent-server may not be running): \(error.localizedDescription)")
            } else {
                print("[SecondSelf] Agent browser session cleared ✓")
            }
        }.resume()
    }

    // MARK: - Environment Discovery

    private func discoverEnvironment() {
        // Check well-known locations for the repo, then walk up from binary
        let fm = FileManager.default
        let home = NSHomeDirectory()
        let knownPaths = [
            "\(home)/second-self",
            "/usr/local/share/second-self",
            Bundle.main.resourceURL?.appendingPathComponent("repo").path,
        ].compactMap { $0 }

        var root: URL?
        for path in knownPaths {
            if fm.fileExists(atPath: "\(path)/orchestrator/server.py") {
                root = URL(fileURLWithPath: path)
                break
            }
        }

        // Fallback: walk up from binary (works in dev with swift run)
        if root == nil {
            let execURL = Bundle.main.executableURL ?? URL(fileURLWithPath: ProcessInfo.processInfo.arguments[0])
            var candidate = execURL.deletingLastPathComponent()
            for _ in 0..<10 {
                if fm.fileExists(atPath: candidate.appendingPathComponent("orchestrator/server.py").path) {
                    root = candidate
                    break
                }
                candidate = candidate.deletingLastPathComponent()
            }
        }

        repoRoot = root ?? URL(fileURLWithPath: "\(home)/second-self")

        envVars = ProcessInfo.processInfo.environment
        let envPath = repoRoot!.appendingPathComponent(".env")
        if let contents = try? String(contentsOf: envPath, encoding: .utf8) {
            for line in contents.components(separatedBy: .newlines) {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                if trimmed.isEmpty || trimmed.hasPrefix("#") { continue }
                let parts = trimmed.split(separator: "=", maxSplits: 1)
                if parts.count == 2 {
                    envVars[String(parts[0])] = String(parts[1])
                }
            }
        }

        // Expose env vars to other services (e.g. ElevenLabsService reads ELEVENLABS_API_KEY)
        AppDelegate.sharedEnvVars = envVars

        let userHome = envVars["HOME"] ?? NSHomeDirectory()
        let candidates = [
            "/usr/local/share/second-self/python/bin/python3",
            "\(userHome)/.pyenv/versions/3.11.8/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3"
        ]
        pythonPath = candidates.first { FileManager.default.fileExists(atPath: $0) } ?? "/usr/bin/python3"
    }

    // MARK: - Launch Python Subprocess

    private func launchPython(script: String, label: String) {
        guard let root = repoRoot, let python = pythonPath else { return }

        let scriptPath = root.appendingPathComponent(script)
        guard FileManager.default.fileExists(atPath: scriptPath.path) else {
            print("[SecondSelf] \(script) not found, skipping")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [scriptPath.path]
        process.currentDirectoryURL = root
        process.environment = envVars
        process.standardOutput = FileHandle.standardOutput
        process.standardError = FileHandle.standardError

        do {
            try process.run()
            subprocesses.append(process)
            statusLog("\(label) started (PID \(process.processIdentifier))")
        } catch {
            statusLog("Failed to start \(label): \(error)")
        }
    }

    private func launchModule(module: String, args: [String], label: String) {
        guard let root = repoRoot, let python = pythonPath else { return }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-m", module] + args
        process.currentDirectoryURL = root
        process.environment = envVars
        process.standardOutput = FileHandle.standardOutput
        process.standardError = FileHandle.standardError

        do {
            try process.run()
            subprocesses.append(process)
            statusLog("\(label) started (PID \(process.processIdentifier))")
        } catch {
            statusLog("Failed to start \(label): \(error)")
        }
    }

    private func handleGlobalKeyEvent(_ event: NSEvent) {
        // Cmd+Shift+T: toggle panel
        let requiredFlags: NSEvent.ModifierFlags = [.command, .shift]
        let keyT: UInt16 = 17
        if event.modifierFlags.contains(requiredFlags) && event.keyCode == keyT {
            Task { @MainActor in
                overlayController?.togglePanel()
            }
            return
        }

        // Escape: collapse to compact
        let keyEscape: UInt16 = 53
        if event.keyCode == keyEscape {
            Task { @MainActor in
                overlayController?.collapse()
            }
        }
    }
}
