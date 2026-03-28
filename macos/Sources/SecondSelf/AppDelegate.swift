import AppKit
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var notchPanel: NotchPanel!
    private let viewModel = NotchViewModel()

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMenuBar()
        setupNotchPanel()

        // Connect to existing browser session (Google tokens) or fall back to Tavily-only onboard
        viewModel.connectOnLaunch()
    }

    // MARK: - Menu Bar

    private func setupMenuBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.title = "SS"
        }

        let menu = NSMenu()
        menu.addItem(withTitle: "Toggle Panel", action: #selector(togglePanel), keyEquivalent: "s")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit SecondSelf", action: #selector(quitApp), keyEquivalent: "q")
        statusItem.menu = menu
    }

    // MARK: - Notch Panel

    private func setupNotchPanel() {
        notchPanel = NotchPanel(viewModel: viewModel)
        notchPanel.orderFront(nil)
    }

    // MARK: - Actions

    @objc private func togglePanel() {
        if notchPanel.isVisible {
            notchPanel.orderOut(nil)
            viewModel.collapse()
        } else {
            notchPanel.orderFront(nil)
        }
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }
}
