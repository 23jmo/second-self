import SwiftUI

/// First-run setup wizard shown in the notch panel when the secondself user
/// needs a GUI session or Screen Recording permission.
/// Guides the user through the one unavoidable manual step.
struct SetupWizardView: View {
    @ObservedObject var authManager: GoogleAuthManager
    var onSetupComplete: (() -> Void)?
    @State private var currentStep: SetupStep = .checking
    @State private var agentHealthy = false
    @State private var pollTimer: Timer?

    enum SetupStep {
        case checking       // Initial health check
        case needsLogin     // secondself user needs a GUI session
        case needsPermission // Screen Recording not granted
        case ready          // All good
    }

    var body: some View {
        VStack(spacing: 0) {
            Spacer().frame(height: 16)

            // Mascot + title
            VStack(spacing: 8) {
                MascotGIFView(width: 48, height: 62)
                    .frame(width: 48, height: 62)

                Text("Second Self")
                    .font(.system(size: 20, weight: .bold))
                    .foregroundColor(Color.ssTextPrimary)
            }

            Spacer().frame(height: 16)

            // Step content
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
        .frame(width: 420, height: 400)
        .background(Color.ssNotchBlack)
        .environment(\.colorScheme, .dark)
        .onAppear { runHealthCheck() }
        .onDisappear { pollTimer?.invalidate() }
    }

    // MARK: - Step: Checking

    private var checkingContent: some View {
        VStack(spacing: 12) {
            ProgressView()
                .progressViewStyle(.circular)
                .scaleEffect(0.9)
            Text("Checking setup...")
                .font(.system(size: 13))
                .foregroundColor(Color.ssTextSecondary)
        }
    }

    // MARK: - Step: Needs Login

    private var needsLoginContent: some View {
        VStack(spacing: 16) {
            stepBadge(number: 1, total: 2)

            Text("Create a GUI session")
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(Color.ssTextPrimary)

            VStack(alignment: .leading, spacing: 8) {
                instructionRow(icon: "person.crop.circle", text: "Click your name in the menu bar")
                instructionRow(icon: "arrow.right.arrow.left", text: "Switch to 'secondself'")
                instructionRow(icon: "key", text: "Password: secondself")
                instructionRow(icon: "arrow.uturn.backward", text: "Switch back to your account")
            }
            .padding(.horizontal, 8)

            Text("This creates a desktop session for your digital twin.\nOnly needed once.")
                .font(.system(size: 11))
                .foregroundColor(Color.ssTextSecondary)
                .multilineTextAlignment(.center)

            Button(action: openFastUserSwitching) {
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

            Button("Check again") { runHealthCheck() }
                .font(.system(size: 12))
                .foregroundColor(Color.ssTwinGreen)
                .buttonStyle(.plain)
        }
    }

    // MARK: - Step: Needs Permission

    private var needsPermissionContent: some View {
        VStack(spacing: 16) {
            stepBadge(number: 2, total: 2)

            Text("Grant Screen Recording")
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(Color.ssTextPrimary)

            VStack(alignment: .leading, spacing: 8) {
                instructionRow(icon: "person.crop.circle", text: "Switch to 'secondself' user")
                instructionRow(icon: "gearshape", text: "Open System Settings")
                instructionRow(icon: "eye", text: "Privacy > Screen Recording")
                instructionRow(icon: "checkmark.circle", text: "Enable python3")
                instructionRow(icon: "arrow.uturn.backward", text: "Switch back")
            }
            .padding(.horizontal, 8)

            HStack(spacing: 12) {
                Button(action: openFastUserSwitching) {
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
                        Text("Open Settings")
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

            // Polling indicator
            HStack(spacing: 6) {
                if !agentHealthy {
                    ProgressView()
                        .controlSize(.mini)
                        .tint(Color.ssTextSecondary)
                    Text("Waiting for permission...")
                        .font(.system(size: 11))
                        .foregroundColor(Color.ssTextSecondary)
                }
            }
        }
    }

    // MARK: - Step: Ready

    private var readyContent: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 40))
                .foregroundColor(Color.ssSuccess)

            Text("All set!")
                .font(.system(size: 18, weight: .bold))
                .foregroundColor(Color.ssTextPrimary)

            Text("Your digital twin is ready.\nSign in to get started.")
                .font(.system(size: 13))
                .foregroundColor(Color.ssTextSecondary)
                .multilineTextAlignment(.center)
        }
    }

    // MARK: - Helpers

    private func stepBadge(number: Int, total: Int) -> some View {
        Text("Step \(number) of \(total)")
            .font(.system(size: 10, weight: .medium))
            .foregroundColor(Color.ssTwinGreen)
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(
                Capsule().fill(Color.ssTwinGreen.opacity(0.15))
            )
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

    private func openFastUserSwitching() {
        // Open the user switching menu via ControlCenter
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preferences.users")!)
    }

    private func openScreenRecordingSettings() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!)
    }

    private func runHealthCheck() {
        currentStep = .checking

        // Check if secondself user exists
        let userExists = checkUserExists()
        if !userExists {
            // postinstall should have created the user — something is wrong
            currentStep = .needsLogin
            return
        }

        // Check if agent server is healthy (implies GUI session + Screen Recording)
        checkAgentHealth { healthy in
            DispatchQueue.main.async {
                if healthy {
                    self.agentHealthy = true
                    self.currentStep = .ready
                    // Auto-dismiss after 2 seconds
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                        self.markSetupComplete()
                    }
                } else {
                    // Check if there's a GUI session for secondself
                    let hasGUISession = self.checkGUISession()
                    if !hasGUISession {
                        self.currentStep = .needsLogin
                    } else {
                        self.currentStep = .needsPermission
                    }
                    self.startPolling()
                }
            }
        }
    }

    private func checkUserExists() -> Bool {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/id")
        process.arguments = ["secondself"]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try? process.run()
        process.waitUntilExit()
        return process.terminationStatus == 0
    }

    private func checkGUISession() -> Bool {
        // Check if WindowServer has multiple sessions (implies secondself is logged in)
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/bin/ps")
        process.arguments = ["aux"]
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        try? process.run()
        process.waitUntilExit()

        let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let wsCount = output.components(separatedBy: "\n").filter { $0.contains("WindowServer") && !$0.contains("grep") }.count
        return wsCount >= 2
    }

    private func checkAgentHealth(completion: @escaping (Bool) -> Void) {
        guard let url = URL(string: "http://localhost:8421/health") else {
            completion(false)
            return
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 3

        URLSession.shared.dataTask(with: request) { data, response, error in
            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200,
                  let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  json["status"] as? String == "ok" else {
                completion(false)
                return
            }
            completion(true)
        }.resume()
    }

    private func startPolling() {
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { _ in
            checkAgentHealth { healthy in
                DispatchQueue.main.async {
                    if healthy {
                        self.pollTimer?.invalidate()
                        self.agentHealthy = true
                        self.currentStep = .ready
                        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                            self.markSetupComplete()
                        }
                    }
                }
            }
        }
    }

    private func markSetupComplete() {
        UserDefaults.standard.set(true, forKey: "setupComplete")
        onSetupComplete?()
    }
}
