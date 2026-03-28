import SwiftUI

enum Theme {
    // Colors
    static let panelBackground = Color.black.opacity(0.85)
    static let pillBackground = Color(white: 0.12)
    static let pillBorder = Color(white: 0.25)
    static let primaryText = Color.white
    static let secondaryText = Color(white: 0.6)
    static let accentGreen = Color(red: 0.2, green: 0.85, blue: 0.4)
    static let accentBlue = Color(red: 0.3, green: 0.5, blue: 1.0)

    // Dimensions
    static let collapsedWidth: CGFloat = 220
    static let collapsedHeight: CGFloat = 38
    static let previewWidth: CGFloat = 320
    static let previewHeight: CGFloat = 120
    static let expandedWidth: CGFloat = 400
    static let expandedHeight: CGFloat = 520
    static let cornerRadius: CGFloat = 19
    static let expandedCornerRadius: CGFloat = 16
    static let inputPillHeight: CGFloat = 44

    // Fonts
    static let captionFont = Font.system(size: 11, weight: .medium)
    static let bodyFont = Font.system(size: 13, weight: .regular)
    static let titleFont = Font.system(size: 14, weight: .semibold)
}
