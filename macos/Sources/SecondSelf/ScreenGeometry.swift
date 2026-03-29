import AppKit

struct ScreenGeometry: Sendable {
    let screenFrame: NSRect
    let hasNotch: Bool
    let notchCenterX: CGFloat
    let notchWidth: CGFloat
    let menuBarHeight: CGFloat

    init(screen: NSScreen) {
        self.screenFrame = screen.frame
        let safeAreaInsets = screen.safeAreaInsets

        // A nonzero top safe area inset indicates a notch
        self.hasNotch = safeAreaInsets.top > 0

        if hasNotch {
            // auxiliaryTopLeftArea and auxiliaryTopRightArea define the usable
            // areas flanking the notch. The gap between them IS the notch.
            if let leftArea = screen.auxiliaryTopLeftArea,
               let rightArea = screen.auxiliaryTopRightArea {
                let notchLeft = leftArea.maxX
                let notchRight = rightArea.minX
                self.notchWidth = notchRight - notchLeft
                self.notchCenterX = screen.frame.minX + notchLeft + (notchRight - notchLeft) / 2
            } else {
                self.notchWidth = 200
                self.notchCenterX = screen.frame.midX
            }
            self.menuBarHeight = safeAreaInsets.top
        } else {
            // Non-notch Mac: center at top
            self.notchWidth = 0
            self.notchCenterX = screen.frame.midX
            self.menuBarHeight = 25
        }
    }
}
