import SwiftUI
import AppKit

// MARK: - Panel State

enum PanelState: Equatable {
    case collapsed   // Twin head peek below notch (~60x40)
    case expanded    // Twin body + status line (~300x120)
    case fullChat    // Full chat interface (~420x560)

    var size: CGSize {
        switch self {
        case .collapsed: return CGSize(width: 60, height: 40)
        case .expanded:  return CGSize(width: 300, height: 120)
        case .fullChat:  return CGSize(width: 420, height: 560)
        }
    }
}

// MARK: - Transparent NSPanel Subclass

final class OverlayPanel: NSPanel {
    override var canBecomeKey: Bool { true }

    override init(
        contentRect: NSRect,
        styleMask style: NSWindow.StyleMask,
        backing backingStoreType: NSWindow.BackingStoreType,
        defer flag: Bool
    ) {
        super.init(
            contentRect: contentRect,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        // Float above everything, including the menu bar
        level = NSWindow.Level(rawValue: NSWindow.Level.statusBar.rawValue + 1)
        collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        isMovableByWindowBackground = false

        // Don't steal focus from other apps
        hidesOnDeactivate = false
    }
}

// MARK: - Panel State Manager
// Observable wrapper so SwiftUI can react to panelState changes without
// recreating the entire NSHostingView on every transition.

final class PanelStateManager: ObservableObject {
    @Published var panelState: PanelState = .collapsed
}

// MARK: - Notch Overlay Controller

final class NotchOverlayController: NSObject, NSWindowDelegate {
    private var panel: OverlayPanel!
    private var chatViewModel: ChatViewModel
    private let stateManager = PanelStateManager()

    var panelState: PanelState { stateManager.panelState }

    // Event monitors
    private var clickOutsideMonitor: Any?
    private var escapeKeyMonitor: Any?
    private var escapeKeyLocalMonitor: Any?

    override init() {
        self.chatViewModel = ChatViewModel()
        super.init()
        setupPanel()
        positionPanel()
        panel.orderFrontRegardless()
        installClickOutsideMonitor()
        installEscapeKeyMonitor()
    }

    // MARK: - Panel Setup

    private func setupPanel() {
        let initialSize = PanelState.collapsed.size
        let frame = NSRect(origin: .zero, size: initialSize)

        panel = OverlayPanel(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.delegate = self

        // Create the NSHostingView ONCE. SwiftUI observes stateManager reactively.
        let hostingView = NSHostingView(
            rootView: NotchOverlayView(
                stateManager: stateManager,
                chatViewModel: chatViewModel,
                onCollapsedTap: { [weak self] in self?.transitionTo(.expanded) },
                onExpandedTap: { [weak self] in self?.transitionTo(.fullChat) },
                onClose: { [weak self] in self?.transitionTo(.collapsed) }
            )
        )
        hostingView.frame = NSRect(origin: .zero, size: initialSize)
        panel.contentView = hostingView
    }

    // MARK: - Positioning

    /// Compute the panel frame for a given state, anchored below the notch/menu bar
    private func frameForState(_ state: PanelState) -> NSRect {
        guard let screen = NSScreen.main else { return .zero }
        let screenFrame = screen.frame
        let visibleFrame = screen.visibleFrame
        let menuBarHeight = screenFrame.maxY - visibleFrame.maxY
        let size = state.size
        let originX = screenFrame.midX - size.width / 2
        let originY = screenFrame.maxY - menuBarHeight - size.height
        return NSRect(x: originX, y: originY, width: size.width, height: size.height)
    }

    private func positionPanel() {
        panel.setFrame(frameForState(panelState), display: true)
    }

    // MARK: - State Transitions

    func transitionTo(_ newState: PanelState) {
        guard newState != panelState else { return }

        // Reset VNC expanded state when leaving fullChat
        if stateManager.panelState == .fullChat && newState != .fullChat {
            chatViewModel.isVNCExpanded = false
        }

        stateManager.panelState = newState

        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.35
            context.timingFunction = CAMediaTimingFunction(
                controlPoints: 0.34, 1.56, 0.64, 1.0 // spring-like overshoot
            )
            context.allowsImplicitAnimation = true
            panel.animator().setFrame(frameForState(newState), display: true)
        }

        // Resize the hosting view to match (SwiftUI handles content reactively)
        panel.contentView?.frame = NSRect(origin: .zero, size: newState.size)
    }

    func togglePanel() {
        switch panelState {
        case .collapsed:
            transitionTo(.expanded)
        case .expanded, .fullChat:
            transitionTo(.collapsed)
        }
    }

    // MARK: - Click Outside

    private func installClickOutsideMonitor() {
        clickOutsideMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.leftMouseDown, .rightMouseDown]
        ) { [weak self] event in
            guard let self = self, self.stateManager.panelState != .collapsed else { return }

            // Check if the click is outside our panel
            let clickLocation = NSEvent.mouseLocation
            if !self.panel.frame.contains(clickLocation) {
                self.transitionTo(.collapsed)
            }
        }
    }

    // MARK: - Escape Key

    private func installEscapeKeyMonitor() {
        // Global monitor: fires when app is NOT frontmost
        escapeKeyMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: .keyDown
        ) { [weak self] event in
            guard let self = self, event.keyCode == 53 else { return }
            if self.chatViewModel.isVNCExpanded {
                self.chatViewModel.isVNCExpanded = false
            }
        }
        // Local monitor: fires when panel has focus (canBecomeKey = true)
        escapeKeyLocalMonitor = NSEvent.addLocalMonitorForEvents(
            matching: .keyDown
        ) { [weak self] event in
            guard event.keyCode == 53 else { return event }
            if let self = self, self.chatViewModel.isVNCExpanded {
                self.chatViewModel.isVNCExpanded = false
                return nil // consume the event
            }
            return event
        }
    }

    deinit {
        if let monitor = clickOutsideMonitor {
            NSEvent.removeMonitor(monitor)
        }
        if let monitor = escapeKeyMonitor {
            NSEvent.removeMonitor(monitor)
        }
        if let monitor = escapeKeyLocalMonitor {
            NSEvent.removeMonitor(monitor)
        }
    }
}

// MARK: - Root SwiftUI Overlay View

struct NotchOverlayView: View {
    @ObservedObject var stateManager: PanelStateManager
    @ObservedObject var chatViewModel: ChatViewModel
    let onCollapsedTap: () -> Void
    let onExpandedTap: () -> Void
    let onClose: () -> Void

    var body: some View {
        ZStack {
            switch stateManager.panelState {
            case .collapsed:
                CollapsedView(onTap: onCollapsedTap)
            case .expanded:
                ExpandedView(
                    twinState: chatViewModel.twinState,
                    isConnected: chatViewModel.isConnected,
                    onTap: onExpandedTap
                )
            case .fullChat:
                FullChatView(
                    chatViewModel: chatViewModel,
                    onClose: onClose
                )
            }
        }
        .frame(
            width: stateManager.panelState.size.width,
            height: stateManager.panelState.size.height
        )
        .animation(.spring(response: 0.35, dampingFraction: 0.7), value: stateManager.panelState)
    }
}

// MARK: - Collapsed View (Twin Head Peek)

struct CollapsedView: View {
    let onTap: () -> Void

    var body: some View {
        ZStack {
            // Small olive-green circle as the Twin head
            Circle()
                .fill(Color(nsColor: NSColor(red: 0.71, green: 0.69, blue: 0.33, alpha: 1.0)))
                .frame(width: 24, height: 24)
                .shadow(color: Color(nsColor: NSColor(red: 0.71, green: 0.69, blue: 0.33, alpha: 0.3)), radius: 6)
        }
        .frame(width: 60, height: 40)
        .contentShape(Rectangle())
        .onTapGesture(perform: onTap)
        .accessibilityLabel("Second Self Twin - click to expand")
    }
}

// MARK: - Expanded View (Twin Body + Status)

struct ExpandedView: View {
    let twinState: TwinState
    let isConnected: Bool
    let onTap: () -> Void

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 12) {
                TwinCharacterView(twinState: twinState, compact: true)
                    .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Second Self")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(Color.ssTextPrimary)

                    HStack(spacing: 4) {
                        Circle()
                            .fill(isConnected ? Color.ssSuccess : Color.ssError)
                            .frame(width: 6, height: 6)
                        Text(statusText)
                            .font(.system(size: 11))
                            .foregroundColor(Color.ssTextSecondary)
                    }
                }

                Spacer()
            }
            .padding(.horizontal, 16)
        }
        .frame(width: 300, height: 120)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(Color.ssBorder, lineWidth: 0.5)
                )
        )
        .contentShape(Rectangle())
        .onTapGesture(perform: onTap)
    }

    private var statusText: String {
        if !isConnected { return "Connecting to Twin..." }
        switch twinState {
        case .idle:      return "Ready"
        case .thinking:  return "Thinking..."
        case .working:   return "Working..."
        case .complete:  return "Done"
        case .error:     return "Error"
        }
    }
}

// MARK: - Full Chat View (Wrapper)

struct FullChatView: View {
    @ObservedObject var chatViewModel: ChatViewModel
    let onClose: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            // Header bar: swaps between chat header and VNC header
            if chatViewModel.isVNCExpanded {
                // VNC expanded header
                HStack {
                    Button(action: { chatViewModel.isVNCExpanded = false }) {
                        Image(systemName: "chevron.left")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundColor(Color.ssTextSecondary)
                    }
                    .buttonStyle(.plain)

                    TwinCharacterView(twinState: chatViewModel.twinState, compact: true)
                        .frame(width: 24, height: 24)

                    Text("Twin's Desktop")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(Color.ssTextPrimary)

                    Spacer()

                    Circle()
                        .fill(chatViewModel.isConnected ? Color.ssSuccess : Color.ssError)
                        .frame(width: 6, height: 6)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(Color.ssBackground)
            } else {
                // Chat header
                HStack {
                    TwinCharacterView(twinState: chatViewModel.twinState, compact: true)
                        .frame(width: 32, height: 32)

                    Text("Second Self")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(Color.ssTextPrimary)

                    Spacer()

                    Circle()
                        .fill(chatViewModel.isConnected ? Color.ssSuccess : Color.ssError)
                        .frame(width: 6, height: 6)

                    Button(action: onClose) {
                        Image(systemName: "chevron.up")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundColor(Color.ssTextSecondary)
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(Color.ssBackground)
            }

            Divider()
                .background(Color.ssBorder)

            // Content: swap between chat and VNC expanded
            if chatViewModel.isVNCExpanded {
                VNCExpandedContentView(
                    streamer: chatViewModel.mjpegStreamer,
                    twinState: chatViewModel.twinState,
                    currentToolAction: chatViewModel.currentToolAction,
                    onBack: { chatViewModel.isVNCExpanded = false }
                )
            } else {
                ChatView(viewModel: chatViewModel)
            }
        }
        .frame(width: 420, height: 560)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color.ssSurface)
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(Color.ssBorder, lineWidth: 0.5)
                )
        )
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .animation(.spring(response: 0.35, dampingFraction: 0.7), value: chatViewModel.isVNCExpanded)
        .onAppear {
            chatViewModel.mjpegStreamer.start()
        }
        .onDisappear {
            chatViewModel.mjpegStreamer.stop()
        }
    }
}

// MARK: - Color Hex Extension

extension Color {
    init(hex: UInt32, opacity: Double = 1.0) {
        let red = Double((hex >> 16) & 0xFF) / 255.0
        let green = Double((hex >> 8) & 0xFF) / 255.0
        let blue = Double(hex & 0xFF) / 255.0
        self.init(.sRGB, red: red, green: green, blue: blue, opacity: opacity)
    }
}
