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

    // Peeping mascot: separate transparent window below the notch
    private var peepingWindow: NSWindow?
    private var peepingVisible = false
    private var hoverTrackingMonitor: Any?

    // Floating VNC window below the notch panel
    private var vncWindow: NSWindow?
    private var vncCancellable: AnyCancellable?

    private(set) var authManager: GoogleAuthManager

    init(authManager: GoogleAuthManager) {
        let viewModel = ChatViewModel()
        self.chatViewModel = viewModel
        self.authManager = authManager

        self.dynamicNotch = DynamicNotch(
            hoverBehavior: [.keepVisible, .hapticFeedback],
            style: .auto
        ) {
            ExpandedNotchContent(chatViewModel: viewModel, authManager: authManager)
        } compactLeading: {
            CompactLeadingContent(chatViewModel: viewModel, authManager: authManager)
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
        setupPeepingWindow()
        installHoverTracking()
        setupVNCWindow(viewModel: viewModel)
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
            // Slide in the dangling mascot at the right edge
            setPeepingVisible(true, position: .rightEdge)
        case 1:
            // Status mini → full chat: already expanded, just swap content
            chatViewModel.expansionStage = 2
            // Hide dangling mascot when entering full chat
            setPeepingVisible(false)
            // Make the panel key so the text field can receive keyboard focus
            makeNotchPanelKey()
        default:
            // Full chat → compact
            collapse()
        }
    }

    func collapse() {
        // Cancel any active voice recording before collapsing
        chatViewModel.cancelVoiceRecording()

        // Hide floating VNC window when collapsing
        setVNCWindowVisible(false)

        // Hide dangling mascot
        setPeepingVisible(false)

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
                setPeepingVisible(true, position: .rightEdge)
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

    // MARK: - Peeping Mascot

    private let mascotWidth: CGFloat = 50
    private let mascotHeight: CGFloat = 72

    private func setupPeepingWindow() {
        guard let screen = NSScreen.main else { return }
        let notchFrame = Self.screenNotchFrame(screen)

        // Start hidden behind the notch bottom edge
        let windowFrame = NSRect(
            x: notchFrame.midX - mascotWidth / 2,
            y: notchFrame.minY,
            width: mascotWidth,
            height: mascotHeight
        )

        let window = NSWindow(
            contentRect: windowFrame,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = false
        window.level = .statusBar + 1  // In front of the notch panel
        window.ignoresMouseEvents = true
        window.collectionBehavior = [.canJoinAllSpaces, .stationary]

        let hostingView = NSHostingView(
            rootView: DanglingMascotView()
                .frame(width: mascotWidth, height: mascotHeight)
        )
        hostingView.layer?.backgroundColor = .clear
        window.contentView = hostingView
        window.alphaValue = 0
        window.orderFront(nil)
        peepingWindow = window
    }

    private func installHoverTracking() {
        hoverTrackingMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.mouseMoved]
        ) { [weak self] event in
            guard let self = self, self.chatViewModel.expansionStage == 0 else {
                // Don't dismiss if stage 1 — the mascot is intentionally shown there
                if self?.peepingVisible == true && self?.chatViewModel.expansionStage != 1 {
                    self?.setPeepingVisible(false)
                }
                return
            }
            let mouseLocation = NSEvent.mouseLocation
            let notchRect = self.notchHitRect()
            let isInNotchArea = notchRect.contains(mouseLocation)

            if isInNotchArea && !self.peepingVisible {
                self.setPeepingVisible(true, position: .center)
            } else if !isInNotchArea && self.peepingVisible {
                self.setPeepingVisible(false)
            }
        }

        // Also track local mouse moved (when our app is active)
        NSEvent.addLocalMonitorForEvents(matching: [.mouseMoved]) { [weak self] event in
            guard let self = self, self.chatViewModel.expansionStage == 0 else {
                if self?.peepingVisible == true && self?.chatViewModel.expansionStage != 1 {
                    self?.setPeepingVisible(false)
                }
                return event
            }
            let mouseLocation = NSEvent.mouseLocation
            let notchRect = self.notchHitRect()
            let isInNotchArea = notchRect.contains(mouseLocation)

            if isInNotchArea && !self.peepingVisible {
                self.setPeepingVisible(true, position: .center)
            } else if !isInNotchArea && self.peepingVisible {
                self.setPeepingVisible(false)
            }
            return event
        }
    }

    /// Where to position the dangling mascot relative to the notch.
    private enum PeepPosition {
        case center     // For compact hover
        case rightEdge  // For medium notch (stage 1)
    }

    private func setPeepingVisible(_ visible: Bool, position: PeepPosition = .center) {
        peepingVisible = visible
        guard let window = peepingWindow, let screen = NSScreen.main else {
            print("[PEEP] ❌ guard failed: window=\(peepingWindow != nil) screen=\(NSScreen.main != nil)")
            return
        }

        let notchFrame = Self.screenNotchFrame(screen)

        // Both positions use the notch frame as anchor (no panel frame reading)
        let xPosition: CGFloat
        switch position {
        case .center:
            xPosition = notchFrame.midX - mascotWidth / 2
        case .rightEdge:
            // Right side of the medium notch bar (360pt wide, centered on notch)
            xPosition = notchFrame.midX + 180 - mascotWidth + 5
        }

        // The notch bar's bottom edge in screen coordinates.
        // The mascot hangs just below this edge, sliding in from behind.
        let barBottom = notchFrame.minY
        let visibleY = barBottom - mascotHeight + 8  // overlap 8pt so arms appear to grip the edge
        let hiddenY = barBottom  // tucked behind the bar

        let targetY = visible ? visibleY : hiddenY
        print("[PEEP] visible=\(visible) pos=\(position) notch=\(notchFrame) barBottom=\(barBottom) targetY=\(targetY) x=\(xPosition) windowLevel=\(window.level.rawValue)")

        window.animator().alphaValue = visible ? 1.0 : 0.0
        window.animator().setFrame(
            NSRect(
                x: xPosition,
                y: targetY,
                width: mascotWidth,
                height: mascotHeight
            ),
            display: true
        )
    }

    // MARK: - Floating VNC Window

    private let vncWidth: CGFloat = 448
    private let vncHeight: CGFloat = 308

    /// Read the actual bottom edge of the DynamicNotchKit panel window.
    private func notchPanelBottomY() -> CGFloat {
        if let panelWindow = dynamicNotch.windowController?.window {
            return panelWindow.frame.minY
        }
        // Fallback: estimate from screen geometry
        guard let screen = NSScreen.main else { return 0 }
        return screen.frame.maxY - screen.safeAreaInsets.top - 560
    }

    private func setupVNCWindow(viewModel: ChatViewModel) {
        guard let screen = NSScreen.main else { return }

        // Start hidden behind the panel
        let panelBottom = notchPanelBottomY()
        let windowFrame = NSRect(
            x: screen.frame.midX - vncWidth / 2,
            y: panelBottom,
            width: vncWidth,
            height: vncHeight
        )

        let window = NSWindow(
            contentRect: windowFrame,
            styleMask: [.borderless],
            backing: .buffered,
            defer: false
        )
        window.isOpaque = false
        window.backgroundColor = .clear
        window.hasShadow = true
        window.level = .statusBar - 1  // Below the notch panel so overlap tucks behind
        window.collectionBehavior = [.canJoinAllSpaces, .stationary]

        let hostingView = NSHostingView(
            rootView: FloatingVNCContent(chatViewModel: viewModel) { [weak self] in
                self?.chatViewModel.dismissVNCFeed()
                self?.collapse()
            }
            .frame(width: vncWidth, height: vncHeight)
        )
        window.contentView = hostingView
        window.alphaValue = 0
        window.orderFront(nil)
        vncWindow = window

        // Show/hide when showVNCFeed changes (only when chat panel is open)
        vncCancellable = viewModel.$showVNCFeed
            .receive(on: DispatchQueue.main)
            .sink { [weak self] showVNC in
                guard let self else { return }
                let shouldShow = showVNC && self.chatViewModel.expansionStage >= 2
                self.setVNCWindowVisible(shouldShow)
            }
    }

    private func setVNCWindowVisible(_ visible: Bool) {
        guard let window = vncWindow, let screen = NSScreen.main else { return }

        // Read the live panel bottom edge; overlap by 6pt so the seam disappears
        let panelBottom = notchPanelBottomY()
        let overlap: CGFloat = 13
        let visibleY = panelBottom - vncHeight + overlap
        let hiddenY = panelBottom

        let targetFrame = NSRect(
            x: screen.frame.midX - vncWidth / 2,
            y: visible ? visibleY : hiddenY,
            width: vncWidth,
            height: vncHeight
        )

        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.35
            context.timingFunction = CAMediaTimingFunction(controlPoints: 0.175, 0.885, 0.32, 1.1)
            window.animator().setFrame(targetFrame, display: true)
            window.animator().alphaValue = visible ? 1.0 : 0.0
        }
    }

    deinit {
        twinStateCancellable?.cancel()
        autoCollapseTask?.cancel()
        vncCancellable?.cancel()
        if let m = localClickMonitor { NSEvent.removeMonitor(m) }
        if let m = globalClickMonitor { NSEvent.removeMonitor(m) }
        if let m = hoverTrackingMonitor { NSEvent.removeMonitor(m) }
        peepingWindow?.close()
        vncWindow?.close()
    }
}

// MARK: - Floating VNC Content

/// SwiftUI content for the floating VNC window below the notch panel.
struct FloatingVNCContent: View {
    @ObservedObject var chatViewModel: ChatViewModel
    var onTakeControl: (() -> Void)?

    var body: some View {
        VStack(spacing: 0) {
            // VNC stream
            if chatViewModel.showVNCFeed {
                VNCPipView(twinState: chatViewModel.twinState, onTakeControl: onTakeControl)
                    .padding(.horizontal, 6)
                    .padding(.top, 2)
            }

            // Bottom lip with shelve button
            Button(action: { chatViewModel.dismissVNCFeed() }) {
                HStack {
                    Spacer()
                    Image(systemName: "chevron.compact.up")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.white.opacity(0.4))
                    Spacer()
                }
                .frame(height: 26)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .background(Color.ssNotchBlack)
        .clipShape(UnevenRoundedRectangle(topLeadingRadius: 0, bottomLeadingRadius: 12, bottomTrailingRadius: 12, topTrailingRadius: 0))
        .environment(\.colorScheme, .dark)
    }
}
