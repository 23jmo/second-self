import AppKit
import SwiftUI

@MainActor
final class NotchPanel: NSPanel {
    private let viewModel: NotchViewModel

    init(viewModel: NotchViewModel) {
        self.viewModel = viewModel

        let initialRect = NSRect(x: 0, y: 0, width: 220, height: 38)

        super.init(
            contentRect: initialRect,
            styleMask: [.nonactivatingPanel, .fullSizeContentView, .borderless],
            backing: .buffered,
            defer: false
        )

        configurePanel()
        installSwiftUIContent()
        positionAtNotch()
    }

    // MARK: - Panel Configuration

    private func configurePanel() {
        isFloatingPanel = true
        level = .floating
        collectionBehavior = [
            .canJoinAllSpaces,
            .fullScreenAuxiliary,
            .stationary,
        ]
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
        isMovableByWindowBackground = false
        hidesOnDeactivate = false
        animationBehavior = .utilityWindow
    }

    // MARK: - SwiftUI Content

    private func installSwiftUIContent() {
        viewModel.onStateChange = { [weak self] _ in
            Task { @MainActor in
                self?.positionAtNotch()
            }
        }

        let rootView = NotchView(viewModel: viewModel)
            .ignoresSafeArea()
        contentView = NSHostingView(rootView: rootView)
    }

    // MARK: - Positioning

    func positionAtNotch() {
        guard let screen = NSScreen.main else { return }
        let geo = ScreenGeometry(screen: screen)
        let size = sizeForCurrentState()

        let origin = NSPoint(
            x: geo.notchCenterX - size.width / 2,
            y: screen.frame.maxY - size.height
        )

        setFrame(NSRect(origin: origin, size: size), display: true, animate: true)
    }

    func sizeForCurrentState() -> NSSize {
        switch viewModel.panelState {
        case .collapsed:
            return NSSize(width: Theme.collapsedWidth, height: Theme.collapsedHeight + PeepingMascot.hangHeight)
        case .preview:
            return NSSize(width: Theme.previewWidth, height: Theme.previewHeight)
        case .expanded:
            return NSSize(width: Theme.expandedWidth, height: Theme.expandedHeight)
        }
    }

    // MARK: - Key/Focus Behavior

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}
