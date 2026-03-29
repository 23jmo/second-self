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

    // Peeping mascot (hover, stage 0): upside-down face peeking from center
    private var peepingWindow: NSWindow?
    private var peepingVisible = false
    private var hoverTrackingMonitor: Any?

    // Dangling mascot (medium notch, stage 1): TwinPose2 at right edge
    private var danglingWindow: NSWindow?
    private var danglingVisible = false
    private var danglingStageCancellable: AnyCancellable?

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
        setupDanglingWindow()
        installDanglingStageObserver()
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
        // Cancel any active voice recording before collapsing
        chatViewModel.cancelVoiceRecording()

        // Hide floating VNC window when collapsing
        setVNCWindowVisible(false)

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
                // Full chat: pass all clicks through to SwiftUI content.
                // Dismiss is handled by the global monitor (click outside) and Escape key.
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
        // Generous padding so mascot triggers when cursor is near, not just on top
        return base.insetBy(dx: -80, dy: -60)
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

    // MARK: - Peeping Mascot (hover, stage 0)

    private let peepMascotHeight: CGFloat = 70

    private func setupPeepingWindow() {
        guard let screen = NSScreen.main else { return }
        let notchFrame = Self.screenNotchFrame(screen)
        let mascotWidth: CGFloat = 80

        let windowFrame = NSRect(
            x: notchFrame.midX - mascotWidth / 2,
            y: notchFrame.minY,
            width: mascotWidth,
            height: peepMascotHeight
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
        window.level = .statusBar - 1
        window.ignoresMouseEvents = true
        window.collectionBehavior = [.canJoinAllSpaces, .stationary]

        let hostingView = NSHostingView(
            rootView: PeepingMascot(barHeight: 0, isVisible: true)
                .frame(width: mascotWidth, height: peepMascotHeight)
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
            self?.handlePeepHover(mouseLocation: NSEvent.mouseLocation)
        }

        NSEvent.addLocalMonitorForEvents(matching: [.mouseMoved]) { [weak self] event in
            self?.handlePeepHover(mouseLocation: NSEvent.mouseLocation)
            return event
        }
    }

    private func handlePeepHover(mouseLocation: NSPoint) {
        guard chatViewModel.expansionStage == 0 else { return }
        let notchRect = notchHitRect()
        let isInNotchArea = notchRect.contains(mouseLocation)
        if isInNotchArea {
            if !peepingVisible {
                setPeepingVisible(true, cursorX: mouseLocation.x)
            } else {
                updatePeepingX(cursorX: mouseLocation.x)
            }
        } else if peepingVisible {
            setPeepingVisible(false)
        }
    }

    /// Smoothly lean the peeping mascot toward the cursor (dampened, not 1:1).
    private func updatePeepingX(cursorX: CGFloat) {
        guard let window = peepingWindow, let screen = NSScreen.main else { return }
        let notchFrame = Self.screenNotchFrame(screen)
        let mascotWidth: CGFloat = 80
        let visibleY = notchFrame.minY - 30

        // Lerp 30% toward cursor from center — leans, doesn't follow
        let centerX = notchFrame.midX - mascotWidth / 2
        let fullX = cursorX - mascotWidth / 2
        let targetX = (centerX + (fullX - centerX) * 0.3)
            .clampedTo(min: notchFrame.minX, max: notchFrame.maxX - mascotWidth)

        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.45
            context.timingFunction = CAMediaTimingFunction(controlPoints: 0.25, 0.1, 0.25, 1.0)
            window.animator().setFrame(
                NSRect(x: targetX, y: visibleY, width: mascotWidth, height: peepMascotHeight),
                display: true
            )
        }
    }

    private func setPeepingVisible(_ visible: Bool, cursorX: CGFloat? = nil) {
        peepingVisible = visible
        guard let window = peepingWindow, let screen = NSScreen.main else { return }

        let notchFrame = Self.screenNotchFrame(screen)
        let mascotWidth: CGFloat = 80
        let hiddenY = notchFrame.minY
        let visibleY = notchFrame.minY - 30

        // Dampen cursor influence — lean 30% toward cursor from center
        let centerX = notchFrame.midX - mascotWidth / 2
        let xPosition: CGFloat
        if let cx = cursorX {
            let fullX = cx - mascotWidth / 2
            xPosition = (centerX + (fullX - centerX) * 0.3)
                .clampedTo(min: notchFrame.minX, max: notchFrame.maxX - mascotWidth)
        } else {
            xPosition = centerX
        }

        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.35
            context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            window.animator().alphaValue = visible ? 1.0 : 0.0
            window.animator().setFrame(
                NSRect(
                    x: xPosition,
                    y: visible ? visibleY : hiddenY,
                    width: mascotWidth,
                    height: self.peepMascotHeight
                ),
                display: true
            )
        }
    }

    // MARK: - Dangling Mascot (medium notch, stage 1)

    private let dangleWidth: CGFloat = 50
    private let dangleHeight: CGFloat = 72

    private func setupDanglingWindow() {
        guard let screen = NSScreen.main else { return }
        let notchFrame = Self.screenNotchFrame(screen)

        let windowFrame = NSRect(
            x: notchFrame.midX,
            y: notchFrame.minY,
            width: dangleWidth,
            height: dangleHeight
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
        window.level = .statusBar + 1
        window.ignoresMouseEvents = true
        window.collectionBehavior = [.canJoinAllSpaces, .stationary]

        let hostingView = NSHostingView(
            rootView: DanglingMascotView()
                .frame(width: dangleWidth, height: dangleHeight)
        )
        hostingView.layer?.backgroundColor = .clear
        window.contentView = hostingView
        window.alphaValue = 0
        window.orderFront(nil)
        danglingWindow = window
    }

    /// Watches expansion stage: show dangling mascot at stage 1, hide otherwise.
    private func installDanglingStageObserver() {
        danglingStageCancellable = chatViewModel.$expansionStage
            .receive(on: DispatchQueue.main)
            .sink { [weak self] stage in
                guard let self = self else { return }
                if stage == 1 {
                    self.setDanglingVisible(true)
                } else if self.danglingVisible {
                    self.setDanglingVisible(false)
                }
            }
    }

    private func setDanglingVisible(_ visible: Bool) {
        danglingVisible = visible
        guard let window = danglingWindow, let screen = NSScreen.main else {
            print("[DANGLE] guard failed: window=\(danglingWindow != nil) screen=\(NSScreen.main != nil)")
            return
        }

        let notchFrame = Self.screenNotchFrame(screen)

        // Position at right edge of the medium notch bar (360pt wide, centered)
        // Hands should touch the bottom of the notch bar — so top of mascot aligns with bar bottom
        let xPosition = notchFrame.midX + 180 - dangleWidth + 5
        let barBottom = notchFrame.minY
        let visibleY = barBottom - dangleHeight + 8
        let hiddenY = barBottom

        print("[DANGLE] visible=\(visible) notch=\(notchFrame) barBottom=\(barBottom) visibleY=\(visibleY) x=\(xPosition) level=\(window.level.rawValue)")

        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.4
            context.timingFunction = CAMediaTimingFunction(controlPoints: 0.175, 0.885, 0.32, 1.1)
            window.animator().alphaValue = visible ? 1.0 : 0.0
            window.animator().setFrame(
                NSRect(
                    x: xPosition,
                    y: visible ? visibleY : hiddenY,
                    width: self.dangleWidth,
                    height: self.dangleHeight
                ),
                display: true
            )
        }
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
        danglingStageCancellable?.cancel()
        if let m = localClickMonitor { NSEvent.removeMonitor(m) }
        if let m = globalClickMonitor { NSEvent.removeMonitor(m) }
        if let m = hoverTrackingMonitor { NSEvent.removeMonitor(m) }
        peepingWindow?.close()
        danglingWindow?.close()
        vncWindow?.close()
    }
}

// MARK: - Helpers

private extension CGFloat {
    func clampedTo(min lower: CGFloat, max upper: CGFloat) -> CGFloat {
        Swift.min(Swift.max(self, lower), upper)
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
