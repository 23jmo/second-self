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
    // Figma chat colors
    static let ssUserOlive     = Color(hex: 0x9CA161) // User message bubble
    static let ssTwinOlive     = Color(hex: 0x3D3F1F) // Twin message bubble (darker)
    static let ssCream         = Color(hex: 0xFBFFD4)  // Timestamps, tool call pill bg
    static let ssToolBorder    = Color(hex: 0xAFB478)  // Tool call pill border
    static let ssInputBg       = Color(hex: 0x333338)  // Input bar background (brighter for contrast)
    static let ssRecordingRed  = Color(hex: 0xFF453A)  // Voice recording active indicator
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
// Rule: No linear easing. Ever. No hardcoded springs.

extension Animation {
    /// Primary panel transition spring: tight, minimal overshoot
    static let ssPanelSpring = Animation.spring(response: 0.3, dampingFraction: 0.85)
    /// Faster spring for content reveals (status line, VNC thumbnail, chips)
    static let ssContentReveal = Animation.spring(response: 0.25, dampingFraction: 0.88)
    /// Message entrance: gentle fade-in
    static let ssMessageEntrance = Animation.spring(response: 0.3, dampingFraction: 0.9)
    /// Micro-interactions: button press, focus glow, pill expand
    static let ssMicro = Animation.spring(response: 0.2, dampingFraction: 0.85)
    /// Character state transitions
    static let ssCharacterTransition = Animation.spring(response: 0.3, dampingFraction: 0.85)
    /// Glow pulse: slow, subtle
    static let ssGlowPulse = Animation.easeInOut(duration: 2.5)
    /// Scroll to latest message
    static let ssScrollSpring = Animation.spring(response: 0.3, dampingFraction: 0.9)
    /// Content dismiss: fade out for badges and transient UI
    static let ssContentDismiss = Animation.easeOut(duration: 0.5)
    /// LIVE indicator blink
    static let ssLiveBlink = Animation.easeInOut(duration: 1.0)
    /// Voice recording pulse: scale + opacity loop
    static let ssRecordingPulse = Animation.easeInOut(duration: 0.6).repeatForever(autoreverses: true)
}

// MARK: - Transition Tokens
// Subtle: mostly opacity with minimal spatial movement

extension AnyTransition {
    /// Message from Twin: fade in + tiny scale
    static let ssTwinMessage = AnyTransition.asymmetric(
        insertion: .opacity.combined(with: .scale(scale: 0.97)),
        removal: .opacity
    )
    /// Message from User: fade in + tiny scale
    static let ssUserMessage = AnyTransition.asymmetric(
        insertion: .opacity.combined(with: .scale(scale: 0.97)),
        removal: .opacity
    )
    /// Tool call pill: fade in + slight scale
    static let ssToolPill = AnyTransition.asymmetric(
        insertion: .opacity.combined(with: .scale(scale: 0.92)),
        removal: .opacity
    )
}

enum SSEEventType: String {
    case state
    case token
    case toolCall = "tool_call"
    case toolProgress = "tool_progress"
    case toolResult = "tool_result"
    case error
    case ping
    case component
    case componentStart = "component_start"
    case componentDelta = "component_delta"
    case componentEnd = "component_end"
    case suggestion
    case suggestionAccepted = "suggestion_accepted"
    case suggestionDismissed = "suggestion_dismissed"
}

enum ServerConfig {
    static let orchestratorPort = 8420
    static let agentServerPort = 8421
    static let backendPort = 8000
    static let orchestratorURL = "http://localhost:\(orchestratorPort)"
    static let backendURL = "http://localhost:\(backendPort)"
    static let agentStreamURL = "http://localhost:\(agentServerPort)/stream"
    static let chatEndpoint = "\(orchestratorURL)/chat"
    static let sessionEndpoint = "\(backendURL)/session/latest"
    static let eventsEndpoint = "\(orchestratorURL)/events"
    static let suggestionRespondEndpoint = "\(orchestratorURL)/suggestion/respond"
}

// MARK: - Thinking Words
// Whimsical words cycled in the medium expansion bar during thinking/working states.

enum ThinkingWords {
    static let all: [String] = [
        "Fnagling...",
        "Ruminating...",
        "Bamboozling...",
        "Cogitating...",
        "Moonwalking...",
        "Hypothesizing...",
        "Shipping...",
        "Cooking...",
        "Ideating...",
        "Ramtazzling...",
        "Lollygagging...",
        "Brodyshmodying...",
        "Hootin' n' hollerin'...",
        "Percolating...",
        "Discombobulating...",
        "Pontificating...",
        "Gallivanting...",
        "Skedaddling...",
        "Confabulating...",
        "Shenanigizing...",
        "Tomfoolering...",
        "Hullaballooing...",
        "Kerfuffling...",
        "Razzle-dazzling...",
        "Noodling...",
    ]
}
