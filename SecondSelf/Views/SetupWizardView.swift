import SwiftUI

/// First-run setup wizard shown in the notch panel.
/// Shows live status of each service and guides the user through manual steps.
struct SetupWizardView: View {
    @ObservedObject var authManager: GoogleAuthManager
    var onSetupComplete: (() -> Void)?

    @State private var currentStep: SetupStep = .checking
    @State private var statusLines: [StatusLine] = []
    @State private var pollTask: Task<Void, Never>?

    enum SetupStep {
        case checking
        case needsLogin
        case needsPermission
        case ready
    }

    struct StatusLine: Identifiable {
        let id = UUID()
        let icon: String
        let text: String
        let ok: Bool
    }

    var body: some View {
        VStack(spacing: 0) {
            Spacer().frame(height: 16)

            VStack(spacing: 8) {
                MascotGIFView(width: 48, height: 62)
                    .frame(width: 48, height: 62)

                Text("Second Self")
                    .font(.system(size: 20, weight: .bold))
                    .foregroundColor(Color.ssTextPrimary)
            }

            Spacer().frame(height: 12)

            Group {
                switch currentStep {
                case .checking:
                    checkingContent
                case .needsLogin:
                    needsLoginContent
                case .needsPermission:
                    needsPermissionContent
                case .ready:
                    readyContent
                }
            }
            .padding(.horizontal, 20)

            Spacer()
        }
        .frame(width: 420, height: 420)
        .background(Color.ssNotchBlack)
        .environment(\.colorScheme, .dark)
        .task { await runChecks() }
        .onDisappear { pollTask?.cancel() }
    }

    // MARK: - Step: Checking

    private var checkingContent: some View {
        VStack(spacing: 10) {
            ForEach(statusLines) { line in
                HStack(spacing: 8) {
                    Image(systemName: line.icon)
                        .font(.system(size: 11))
                        .foregroundColor(line.ok ? Color.ssSuccess : Color.ssTextSecondary)
                        .frame(width: 16)
                    Text(line.text)
                        .font(.system(size: 12, weight: .medium, design: .monospaced))
                        .foregroundColor(Color.ssTextPrimary)
                    Spacer()
                }
            }

            if statusLines.count < 4 {
                HStack(spacing: 8) {
                    ProgressView()
                        .controlSize(.mini)
                    Text("Checking...")
                        .font(.system(size: 12))
                        .foregroundColor(Color.ssTextSecondary)
                    Spacer()
                }
                .padding(.top, 4)
            }
        }
    }

    // MARK: - Step: Needs Login

    private var needsLoginContent: some View {
        VStack(spacing: 14) {
            stepBadge(number: 1, total: 2)

            Text("Create a GUI session")
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(Color.ssTextPrimary)

            statusSummary

            VStack(alignment: .leading, spacing: 6) {
                instructionRow(icon: "1.circle", text: "Click your name in the menu bar")
                instructionRow(icon: "2.circle", text: "Switch to 'secondself'")
                instructionRow(icon: "3.circle", text: "Password: secondself")
                instructionRow(icon: "4.circle", text: "Switch back to your account")
            }
            .padding(.horizontal, 4)

            Text("This creates a desktop for your twin. Only needed once.")
                .font(.system(size: 11))
                .foregroundColor(Color.ssTextSecondary)
                .multilineTextAlignment(.center)

            Button(action: openUserSettings) {
                HStack(spacing: 6) {
                    Image(systemName: "person.2.fill")
                        .font(.system(size: 12))
                    Text("Open User Switching")
                        .font(.system(size: 13, weight: .semibold))
                }
                .foregroundColor(.white)
                .padding(.horizontal, 20)
                .padding(.vertical, 10)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.ssTwinGreen))
            }
            .buttonStyle(.plain)

            Button("Recheck") { Task { await runChecks() } }
                .font(.system(size: 12))
                .foregroundColor(Color.ssTwinGreen)
                .buttonStyle(.plain)
        }
    }

    // MARK: - Step: Needs Permission

    private var needsPermissionContent: some View {
        VStack(spacing: 14) {
            stepBadge(number: 2, total: 2)

            Text("Grant Screen Recording")
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(Color.ssTextPrimary)

            statusSummary

            VStack(alignment: .leading, spacing: 6) {
                instructionRow(icon: "1.circle", text: "Switch to 'secondself' user")
                instructionRow(icon: "2.circle", text: "System Settings > Privacy > Screen Recording")
                instructionRow(icon: "3.circle", text: "Enable python3")
                instructionRow(icon: "4.circle", text: "Switch back to your account")
            }
            .padding(.horizontal, 4)

            HStack(spacing: 12) {
                Button(action: openUserSettings) {
                    HStack(spacing: 6) {
                        Image(systemName: "person.2.fill")
                            .font(.system(size: 12))
                        Text("Switch User")
                            .font(.system(size: 13, weight: .semibold))
                    }
                    .foregroundColor(.white)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.ssTwinGreen))
                }
                .buttonStyle(.plain)

                Button(action: openScreenRecordingSettings) {
                    HStack(spacing: 6) {
                        Image(systemName: "gearshape")
                            .font(.system(size: 12))
                        Text("Settings")
                            .font(.system(size: 13, weight: .semibold))
                    }
                    .foregroundColor(Color.ssTwinGreen)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.ssTwinGreen, lineWidth: 1)
                    )
                }
                .buttonStyle(.plain)
            }

            HStack(spacing: 6) {
                ProgressView().controlSize(.mini).tint(Color.ssTextSecondary)
                Text("Polling agent server...")
                    .font(.system(size: 11))
                    .foregroundColor(Color.ssTextSecondary)
            }
        }
    }

    // MARK: - Step: Ready

    private var readyContent: some View {
        VStack(spacing: 14) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 40))
                .foregroundColor(Color.ssSuccess)

            Text("All set!")
                .font(.system(size: 18, weight: .bold))
                .foregroundColor(Color.ssTextPrimary)

            statusSummary

            Text("Your digital twin is ready.\nSign in to get started.")
                .font(.system(size: 13))
                .foregroundColor(Color.ssTextSecondary)
                .multilineTextAlignment(.center)
        }
    }

    // MARK: - Shared status summary

    private var statusSummary: some View {
        VStack(spacing: 4) {
            ForEach(statusLines) { line in
                HStack(spacing: 6) {
                    Image(systemName: line.ok ? "checkmark.circle.fill" : "xmark.circle")
                        .font(.system(size: 10))
                        .foregroundColor(line.ok ? Color.ssSuccess : Color.ssError)
                    Text(line.text)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Color.ssTextSecondary)
                    Spacer()
                }
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.05)))
    }

    // MARK: - Helpers

    private func stepBadge(number: Int, total: Int) -> some View {
        Text("Step \(number) of \(total)")
            .font(.system(size: 10, weight: .medium))
            .foregroundColor(Color.ssTwinGreen)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(Capsule().fill(Color.ssTwinGreen.opacity(0.15)))
    }

    private func instructionRow(icon: String, text: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 12))
                .foregroundColor(Color.ssTwinGreen)
                .frame(width: 18)
            Text(text)
                .font(.system(size: 12))
                .foregroundColor(Color.ssTextPrimary)
        }
    }

    // MARK: - Actions

    private func openUserSettings() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preferences.users")!)
    }

    private func openScreenRecordingSettings() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!)
    }

    // MARK: - Async checks (no Process on main thread, no semaphores)

    @MainActor
    private func runChecks() async {
        currentStep = .checking
        statusLines = []

        // 1. Check secondself user
        let userExists = await checkUserExistsAsync()
        statusLines.append(StatusLine(
            icon: userExists ? "checkmark.circle.fill" : "xmark.circle",
            text: userExists ? "secondself user exists" : "secondself user missing",
            ok: userExists
        ))
        try? await Task.sleep(for: .milliseconds(300))

        // 2. Check GUI session
        let hasGUI = await checkGUISessionAsync()
        statusLines.append(StatusLine(
            icon: hasGUI ? "checkmark.circle.fill" : "xmark.circle",
            text: hasGUI ? "GUI session active" : "GUI session needed",
            ok: hasGUI
        ))
        try? await Task.sleep(for: .milliseconds(300))

        // 3. Check agent server
        let agentOk = await checkAgentHealthAsync()
        statusLines.append(StatusLine(
            icon: agentOk ? "checkmark.circle.fill" : "xmark.circle",
            text: agentOk ? "Agent server healthy" : "Agent server not responding",
            ok: agentOk
        ))
        try? await Task.sleep(for: .milliseconds(300))

        // 4. Check Chrome/Chromium
        let chromeOk = await checkChromeAsync()
        statusLines.append(StatusLine(
            icon: chromeOk ? "checkmark.circle.fill" : "xmark.circle",
            text: chromeOk ? "Chrome CDP ready" : "Chrome not running",
            ok: chromeOk
        ))
        try? await Task.sleep(for: .milliseconds(300))

        // Determine step
        if agentOk {
            currentStep = .ready
            Task {
                try? await Task.sleep(for: .seconds(2))
                markSetupComplete()
            }
        } else if !userExists || !hasGUI {
            currentStep = .needsLogin
            startPolling()
        } else {
            currentStep = .needsPermission
            startPolling()
        }
    }

    private func checkUserExistsAsync() async -> Bool {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/id")
                process.arguments = ["secondself"]
                process.standardOutput = FileHandle.nullDevice
                process.standardError = FileHandle.nullDevice
                do {
                    try process.run()
                    process.waitUntilExit()
                    continuation.resume(returning: process.terminationStatus == 0)
                } catch {
                    continuation.resume(returning: false)
                }
            }
        }
    }

    private func checkGUISessionAsync() async -> Bool {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                let pipe = Pipe()
                process.executableURL = URL(fileURLWithPath: "/bin/ps")
                process.arguments = ["aux"]
                process.standardOutput = pipe
                process.standardError = FileHandle.nullDevice
                do {
                    try process.run()
                    process.waitUntilExit()
                    let data = pipe.fileHandleForReading.readDataToEndOfFile()
                    let output = String(data: data, encoding: .utf8) ?? ""
                    let wsCount = output.components(separatedBy: "\n")
                        .filter { $0.contains("WindowServer") && !$0.contains("grep") }.count
                    continuation.resume(returning: wsCount >= 2)
                } catch {
                    continuation.resume(returning: false)
                }
            }
        }
    }

    private func checkAgentHealthAsync() async -> Bool {
        guard let url = URL(string: "http://localhost:8421/health") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = 3
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  json["status"] as? String == "ok" else { return false }
            return true
        } catch {
            return false
        }
    }

    private func checkChromeAsync() async -> Bool {
        guard let url = URL(string: "http://localhost:9222/json/version") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = 3
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                guard !Task.isCancelled else { break }
                let healthy = await checkAgentHealthAsync()
                if healthy {
                    await MainActor.run {
                        // Refresh all status lines
                        Task { await runChecks() }
                    }
                    break
                }
            }
        }
    }

    private func markSetupComplete() {
        UserDefaults.standard.set(true, forKey: "setupComplete")
        onSetupComplete?()
    }
}
