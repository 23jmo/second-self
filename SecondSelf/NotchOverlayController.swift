import SwiftUI
import AppKit

// MARK: - Panel State

enum PanelState {
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

// MARK: - Notch Overlay Controller

final class NotchOverlayController: NSObject, NSWindowDelegate {
    private var panel: OverlayPanel!
    private var chatViewModel: ChatViewModel
    private(set) var panelState: PanelState = .collapsed

    // Click-outside monitor
    private var clickOutsideMonitor: Any?

    override init() {
        self.chatViewModel = ChatViewModel()
        super.init()
        setupPanel()
        positionPanel()
        panel.orderFrontRegardless()
        installClickOutsideMonitor()
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

        updatePanelContent()
    }

    private func updatePanelContent() {
        let hostingView = NSHostingView(
            rootView: NotchOverlayView(
                panelState: panelState,
                chatViewModel: chatViewModel,
                onCollapsedTap: { [weak self] in self?.transitionTo(.expanded) },
                onExpandedTap: { [weak self] in self?.transitionTo(.fullChat) },
                onClose: { [weak self] in self?.transitionTo(.collapsed) }
            )
        )
        hostingView.frame = NSRect(origin: .zero, size: panelState.size)
        panel.contentView = hostingView
    }

    // MARK: - Positioning

    private func positionPanel() {
        guard let screen = NSScreen.main else { return }
        let screenFrame = screen.frame
        let visibleFrame = screen.visibleFrame
        let size = panelState.size

        // The menu bar height tells us where the notch ends
        // visibleFrame.maxY is the bottom of the menu bar
        // screenFrame.maxY is the absolute top of the screen (behind the notch)
        let menuBarHeight = screenFrame.maxY - visibleFrame.maxY
        // Position just below the menu bar / notch area
        let originX = screenFrame.midX - size.width / 2
        let originY = screenFrame.maxY - menuBarHeight - size.height

        panel.setFrame(
            NSRect(x: originX, y: originY, width: size.width, height: size.height),
            display: true
        )
    }

    // MARK: - State Transitions

    func transitionTo(_ newState: PanelState) {
        guard newState != panelState else { return }
        panelState = newState

        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.35
            context.timingFunction = CAMediaTimingFunction(
                controlPoints: 0.34, 1.56, 0.64, 1.0 // spring-like overshoot
            )
            context.allowsImplicitAnimation = true

            guard let screen = NSScreen.main else { return }
            let screenFrame = screen.frame
            let visibleFrame = screen.visibleFrame
            let menuBarHeight = screenFrame.maxY - visibleFrame.maxY
            let size = newState.size
            let originX = screenFrame.midX - size.width / 2
            let originY = screenFrame.maxY - menuBarHeight - size.height

            panel.animator().setFrame(
                NSRect(x: originX, y: originY, width: size.width, height: size.height),
                display: true
            )
        }

        // Update content after animation starts
        updatePanelContent()
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
            guard let self = self, self.panelState != .collapsed else { return }

            // Check if the click is outside our panel
            let clickLocation = NSEvent.mouseLocation
            if !self.panel.frame.contains(clickLocation) {
                self.transitionTo(.collapsed)
            }
        }
    }

    deinit {
        if let monitor = clickOutsideMonitor {
            NSEvent.removeMonitor(monitor)
        }
    }
}

// MARK: - Root SwiftUI Overlay View

struct NotchOverlayView: View {
    let panelState: PanelState
    @ObservedObject var chatViewModel: ChatViewModel
    let onCollapsedTap: () -> Void
    let onExpandedTap: () -> Void
    let onClose: () -> Void

    var body: some View {
        ZStack {
            switch panelState {
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
            width: panelState.size.width,
            height: panelState.size.height
        )
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
                        .foregroundColor(Color(hex: 0xF5F5F7))

                    HStack(spacing: 4) {
                        Circle()
                            .fill(isConnected ? Color(hex: 0x30D158) : Color(hex: 0xFF453A))
                            .frame(width: 6, height: 6)
                        Text(statusText)
                            .font(.system(size: 11))
                            .foregroundColor(Color(hex: 0x8E8E93))
                    }
                }

                Spacer()
            }
            .padding(.horizontal, 16)
        }
        .frame(width: 300, height: 120)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color(hex: 0x1C1C1E))
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(Color(hex: 0x333333), lineWidth: 0.5)
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
            // Header bar
            HStack {
                TwinCharacterView(twinState: chatViewModel.twinState, compact: true)
                    .frame(width: 32, height: 32)

                Text("Second Self")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(Color(hex: 0xF5F5F7))

                Spacer()

                // Connection status dot
                Circle()
                    .fill(chatViewModel.isConnected ? Color(hex: 0x30D158) : Color(hex: 0xFF453A))
                    .frame(width: 6, height: 6)

                // Close button
                Button(action: onClose) {
                    Image(systemName: "chevron.up")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(Color(hex: 0x8E8E93))
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color(hex: 0x0D0D0F))

            Divider()
                .background(Color(hex: 0x333333))

            // Chat messages + input
            ChatView(viewModel: chatViewModel)
        }
        .frame(width: 420, height: 560)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color(hex: 0x1C1C1E))
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(Color(hex: 0x333333), lineWidth: 0.5)
                )
        )
        .clipShape(RoundedRectangle(cornerRadius: 16))
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
