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

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        // Register default settings
        UserDefaults.standard.register(defaults: [
            "autoExpandOnActivity": true
        ])

        // Discover repo root, python, and env vars once
        discoverEnvironment()

        // Start the FastAPI auth server (needed for Google sign-in page)
        launchModule(module: "uvicorn", args: ["src.server:app", "--host", "127.0.0.1", "--port", "8000"], label: "Auth Server")

        // Create auth manager
        let auth = GoogleAuthManager()
        authManager = auth

        // When auth succeeds, start the orchestrator
        auth.onAuthenticated = { [weak self] in
            Task { @MainActor in
                self?.launchPython(script: "orchestrator/server.py", label: "Orchestrator")
                print("[SecondSelf] Orchestrator started after sign-in")
            }
        }

        // If already signed in, start orchestrator immediately
        if auth.isAuthenticated {
            print("[SecondSelf] Session found for: \(auth.userName ?? "unknown")")
            launchPython(script: "orchestrator/server.py", label: "Orchestrator")
        } else {
            print("[SecondSelf] No session found, sign-in required via notch")
        }

        // Always create the notch — it shows sign-in or chat based on auth state
        Task { @MainActor in
            overlayController = NotchOverlayController(authManager: auth)
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

    // MARK: - Environment Discovery

    private func discoverEnvironment() {
        let execURL = Bundle.main.executableURL ?? URL(fileURLWithPath: ProcessInfo.processInfo.arguments[0])
        var root = execURL.deletingLastPathComponent()
        for _ in 0..<10 {
            if FileManager.default.fileExists(atPath: root.appendingPathComponent("orchestrator/server.py").path) {
                break
            }
            root = root.deletingLastPathComponent()
        }
        repoRoot = root

        envVars = ProcessInfo.processInfo.environment
        let envPath = root.appendingPathComponent(".env")
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

        let home = envVars["HOME"] ?? NSHomeDirectory()
        let candidates = [
            "\(home)/.pyenv/versions/3.11.8/bin/python3",
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
            print("[SecondSelf] \(label) started (PID \(process.processIdentifier))")
        } catch {
            print("[SecondSelf] Failed to start \(label): \(error)")
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
            print("[SecondSelf] \(label) started (PID \(process.processIdentifier))")
        } catch {
            print("[SecondSelf] Failed to start \(label): \(error)")
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
