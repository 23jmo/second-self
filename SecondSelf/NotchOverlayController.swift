import SwiftUI
import AppKit
import Combine
import DynamicNotchKit

// MARK: - Notch Overlay Controller

/// Manages the DynamicNotchKit-powered notch overlay.
/// Handles auto-expand on Twin activity and hotkey toggling.
@MainActor
final class NotchOverlayController: NSObject {
    private(set) var chatViewModel: ChatViewModel
    private var dynamicNotch: DynamicNotch<ExpandedNotchContent, CompactLeadingContent, CompactTrailingContent>

    // Auto-expand / auto-collapse
    private var twinStateCancellable: AnyCancellable?
    private var autoCollapseTask: Task<Void, Never>?

    // Local monitor: clicks ON our panel (expand/collapse)
    // Global monitor: clicks on OTHER apps' windows (dismiss when expanded)
    private var localClickMonitor: Any?
    private var globalClickMonitor: Any?

    // Track current state for toggle
    private var isExpanded = false

    override init() {
        let viewModel = ChatViewModel()
        self.chatViewModel = viewModel

        self.dynamicNotch = DynamicNotch(
            hoverBehavior: [.keepVisible, .hapticFeedback],
            style: .auto
        ) {
            ExpandedNotchContent(chatViewModel: viewModel)
        } compactLeading: {
            CompactLeadingContent(chatViewModel: viewModel)
        } compactTrailing: {
            CompactTrailingContent(chatViewModel: viewModel)
        }

        super.init()

        // Wire tap callbacks through the shared view model
        viewModel.onNotchTap = { [weak self] in
            self?.togglePanel()
        }
        viewModel.onNotchClose = { [weak self] in
            self?.collapse()
        }

        // Show compact state on launch (Twin visible beside notch)
        Task {
            await dynamicNotch.compact()
        }

        installTwinStateObserver()
        installLocalClickMonitor()
        installGlobalClickMonitor()
    }

    // MARK: - Toggle (for hotkey)

    func togglePanel() {
        Task {
            if isExpanded {
                await dynamicNotch.compact()
                isExpanded = false
            } else {
                await dynamicNotch.expand()
                isExpanded = true
            }
        }
    }

    func collapse() {
        Task {
            await dynamicNotch.compact()
            isExpanded = false
        }
    }

    // MARK: - Auto-Expand on Twin Activity

    private func installTwinStateObserver() {
        twinStateCancellable = chatViewModel.$twinState
            .receive(on: DispatchQueue.main)
            .sink { [weak self] newState in
                self?.handleTwinStateChange(newState)
            }
    }

    private func handleTwinStateChange(_ twinState: TwinState) {
        switch twinState {
        case .working:
            guard UserDefaults.standard.bool(forKey: "autoExpandOnActivity") else { return }
            autoCollapseTask?.cancel()
            Task {
                await dynamicNotch.expand()
                isExpanded = true
            }

        case .complete:
            // Hold expanded for 3 seconds, then compact
            autoCollapseTask?.cancel()
            autoCollapseTask = Task {
                try? await Task.sleep(for: .seconds(3))
                guard !Task.isCancelled else { return }
                await dynamicNotch.compact()
                isExpanded = false
            }

        default:
            break
        }
    }

    // MARK: - Click Monitors

    /// LOCAL monitor: sees clicks delivered to OUR app (i.e. clicks on the DynamicNotchKit panel).
    /// This is the one that handles click-to-expand and click-notch-to-collapse.
    private func installLocalClickMonitor() {
        localClickMonitor = NSEvent.addLocalMonitorForEvents(
            matching: [.leftMouseDown]
        ) { [weak self] event in
            guard let self = self else { return event }

            if self.isExpanded {
                // Check if click is in the notch/header region (top of panel) to collapse
                let clickLocation = NSEvent.mouseLocation
                let notchRect = self.notchHitRect()
                if notchRect.contains(clickLocation) {
                    self.collapse()
                    return nil // consume
                }
                // Otherwise let the event through to SwiftUI (chat, input, buttons)
                return event
            } else {
                // Compact state: any click on our panel should expand
                self.togglePanel()
                return nil // consume
            }
        }
    }

    /// GLOBAL monitor: sees clicks delivered to OTHER apps.
    /// Used only for click-outside dismiss when expanded.
    private func installGlobalClickMonitor() {
        globalClickMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.leftMouseDown, .rightMouseDown]
        ) { [weak self] _ in
            guard let self = self, self.isExpanded else { return }
            self.collapse()
        }
    }

    /// The notch hit rect: the physical notch area + padding for compact content.
    private func notchHitRect() -> NSRect {
        guard let screen = NSScreen.main else { return .zero }
        let base = Self.screenNotchFrame(screen)
        // Pad to include compact leading/trailing content flanking the notch
        return base.insetBy(dx: -40, dy: -4)
    }

    /// The expanded content hit rect: notch area extended downward by the content height.
    private func expandedHitRect() -> NSRect {
        guard let screen = NSScreen.main else { return .zero }
        let notch = Self.screenNotchFrame(screen)
        let expandedWidth: CGFloat = 420
        let expandedHeight: CGFloat = 520

        return NSRect(
            x: notch.midX - expandedWidth / 2,
            y: notch.minY - expandedHeight + notch.height,
            width: expandedWidth,
            height: expandedHeight
        )
    }

    /// Compute the notch frame using the same logic as DynamicNotchKit:
    /// auxiliaryTopLeftArea + auxiliaryTopRightArea for width, safeAreaInsets.top for height.
    /// Falls back to a centered menu bar rect on non-notch screens.
    private static func screenNotchFrame(_ screen: NSScreen) -> NSRect {
        if let leftWidth = screen.auxiliaryTopLeftArea?.width,
           let rightWidth = screen.auxiliaryTopRightArea?.width {
            let notchHeight = screen.safeAreaInsets.top
            let notchWidth = screen.frame.width - leftWidth - rightWidth
            return NSRect(
                x: screen.frame.midX - notchWidth / 2,
                y: screen.frame.maxY - notchHeight,
                width: notchWidth,
                height: notchHeight
            )
        } else {
            // Non-notch fallback: centered 300pt rect at top of screen
            let menuBarHeight = screen.frame.maxY - screen.visibleFrame.maxY
            return NSRect(
                x: screen.frame.midX - 150,
                y: screen.frame.maxY - menuBarHeight,
                width: 300,
                height: menuBarHeight
            )
        }
    }

    deinit {
        twinStateCancellable?.cancel()
        autoCollapseTask?.cancel()
        if let m = localClickMonitor { NSEvent.removeMonitor(m) }
        if let m = globalClickMonitor { NSEvent.removeMonitor(m) }
    }
}
