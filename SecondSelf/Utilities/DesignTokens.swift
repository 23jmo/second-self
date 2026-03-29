import SwiftUI
import AppKit

// MARK: - Design Tokens
// Single source of truth for all design system values.
// See DESIGN.md for rationale behind each choice.

extension Color {
    static let ssTextPrimary   = Color(hex: 0xF5F5F7)
    static let ssTextSecondary = Color(hex: 0x8E8E93)
    static let ssSurface       = Color(hex: 0x1C1C1E)
    static let ssBackground    = Color(hex: 0x0D0D0F)
    static let ssUserBubble    = Color(hex: 0x2C2C2E)
    static let ssBorder        = Color(hex: 0x333333)
    static let ssTwinGreen     = Color(hex: 0xB5B055)
    static let ssError         = Color(hex: 0xFF453A)
    static let ssSuccess       = Color(hex: 0x30D158)
    /// True black matching the hardware notch. Used for notch-connected surfaces.
    static let ssNotchBlack    = Color(hex: 0x000000)
}

extension NSColor {
    static let ssTwinGreen   = NSColor(red: 0.71, green: 0.69, blue: 0.33, alpha: 1.0)
    static let ssBackground  = NSColor(red: 0.051, green: 0.051, blue: 0.059, alpha: 1.0)
    static let ssSurface     = NSColor(red: 0.11, green: 0.11, blue: 0.118, alpha: 1.0)
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

// MARK: - Motion Tokens
// Spring animations from DESIGN.md. Used everywhere instead of ad-hoc timing.

extension Animation {
    /// Primary panel transition spring: Alcove-style with overshoot
    static let ssPanelSpring = Animation.spring(response: 0.35, dampingFraction: 0.7)
    /// Faster spring for content reveals (status line, VNC thumbnail)
    static let ssContentReveal = Animation.spring(response: 0.25, dampingFraction: 0.8)
}

enum SSEEventType: String {
    case state
    case token
    case toolCall = "tool_call"
    case toolResult = "tool_result"
    case error
    case ping
}

enum ServerConfig {
    static let orchestratorPort = 8420
    static let agentServerPort = 8421
    static let orchestratorURL = "http://localhost:\(orchestratorPort)"
    static let agentStreamURL = "http://localhost:\(agentServerPort)/stream"
    static let chatEndpoint = "\(orchestratorURL)/chat"
}
