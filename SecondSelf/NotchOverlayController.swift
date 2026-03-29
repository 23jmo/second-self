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
    private var suggestionCancellable: AnyCancellable?

    // Local monitor: clicks ON our panel (expand/collapse)
    // Global monitor: clicks on OTHER apps' windows (dismiss when expanded)
    private var localClickMonitor: Any?
    private var globalClickMonitor: Any?

    // Track current state: 0=compact, 1=status mini, 2=full chat
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

        // Configure DynamicNotchKit transitions: use our panel spring,
        // skip the 250ms hide→show flash when switching compact↔expanded
        dynamicNotch.transitionConfiguration = .init(
            conversionAnimation: .ssPanelSpring,
            skipIntermediateHides: true
        )

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
        installSuggestionObserver()
        installLocalClickMonitor()
        installGlobalClickMonitor()
    }

    // MARK: - 3-Stage Toggle

    /// Cycles: compact(0) → status mini(1) → full chat(2) → compact(0)
    func togglePanel() {
        let currentStage = chatViewModel.expansionStage

        switch currentStage {
        case 0:
            // Compact → status mini: expand DynamicNotchKit + set stage 1
            chatViewModel.expansionStage = 1
            Task {
                await dynamicNotch.expand()
                isExpanded = true
            }
        case 1:
            // Status mini → full chat: already expanded, just swap content
            chatViewModel.expansionStage = 2
            // Make the panel key so the text field can receive keyboard focus
            makeNotchPanelKey()
        default:
            // Full chat → compact
            collapse()
        }
    }

    func collapse() {
        // Staged collapse: content fades first (200ms), then notch shape compacts
        chatViewModel.expansionStage = 0
        Task {
            try? await Task.sleep(for: .milliseconds(200))
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

    /// Auto-expand to full chat when a proactive suggestion arrives while compact.
    private func installSuggestionObserver() {
        suggestionCancellable = chatViewModel.$currentSuggestion
            .compactMap { $0 }
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                guard let self = self, self.chatViewModel.expansionStage == 0 else { return }
                self.chatViewModel.expansionStage = 2
                Task {
                    await self.dynamicNotch.expand()
                    self.isExpanded = true
                }
            }
    }

    private func handleTwinStateChange(_ twinState: TwinState) {
        switch twinState {
        case .working:
            guard UserDefaults.standard.bool(forKey: "autoExpandOnActivity") else { return }
            autoCollapseTask?.cancel()
            if chatViewModel.expansionStage == 0 {
                chatViewModel.expansionStage = 1
                Task {
                    await dynamicNotch.expand()
                    isExpanded = true
                }
            }

        case .complete:
            // Only auto-collapse if we auto-expanded to status mini (stage 1).
            // If the user manually opened full chat (stage 2), leave it alone.
            if chatViewModel.expansionStage == 1 {
                autoCollapseTask?.cancel()
                autoCollapseTask = Task { [weak self] in
                    try? await Task.sleep(for: .seconds(3))
                    guard !Task.isCancelled else { return }
                    self?.collapse()
                }
            }

        default:
            break
        }
    }

    // MARK: - Click Monitors

    /// LOCAL monitor: sees clicks delivered to OUR app (i.e. clicks on the DynamicNotchKit panel).
    private func installLocalClickMonitor() {
        localClickMonitor = NSEvent.addLocalMonitorForEvents(
            matching: [.leftMouseDown]
        ) { [weak self] event in
            guard let self = self else { return event }

            let stage = self.chatViewModel.expansionStage

            switch stage {
            case 0:
                // Compact: any click on our panel → show status mini
                self.togglePanel()
                return nil

            case 1:
                // Status mini: click anywhere → go to full chat
                // (the onTapGesture on the view handles this too, but this catches edge cases)
                self.togglePanel()
                return nil

            case 2:
                // Full chat: click in notch area → collapse, otherwise pass through to chat UI
                let clickLocation = NSEvent.mouseLocation
                let notchRect = self.notchHitRect()
                if notchRect.contains(clickLocation) {
                    self.collapse()
                    return nil
                }
                return event

            default:
                return event
            }
        }
    }

    /// GLOBAL monitor: sees clicks delivered to OTHER apps.
    /// Used only for click-outside dismiss when expanded.
    private func installGlobalClickMonitor() {
        globalClickMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.leftMouseDown, .rightMouseDown]
        ) { [weak self] _ in
            guard let self = self, self.chatViewModel.expansionStage > 0 else { return }
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

    // MARK: - Panel Focus

    /// Makes the DynamicNotchKit panel the key window so text fields can receive focus.
    private func makeNotchPanelKey() {
        NSApp.activate(ignoringOtherApps: true)
        dynamicNotch.windowController?.window?.makeKeyAndOrderFront(nil)
    }

    deinit {
        twinStateCancellable?.cancel()
        autoCollapseTask?.cancel()
        if let m = localClickMonitor { NSEvent.removeMonitor(m) }
        if let m = globalClickMonitor { NSEvent.removeMonitor(m) }
    }
}
