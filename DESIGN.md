# Design System — Second Self

## Product Context
- **What this is:** macOS digital twin. An AI companion that runs as a second user session, visible through a notch-resident UI.
- **Who it's for:** Hackathon booth visitors, then power users who want an AI companion on their Mac.
- **Space:** AI computer-use agents, macOS notch utilities
- **Project type:** Native macOS app (SwiftUI)

## Aesthetic Direction
- **Direction:** Warm Minimal
- **Decoration level:** Intentional (subtle grain texture on dark surfaces, Twin character IS the decoration)
- **Mood:** Like having a roommate who lives in your computer. Warm, casual, slightly mischievous. Notion's warmth meets Alcove's fluidity meets Studio Ghibli's character design.
- **Reference:** Alcove (notch animations), Apple Intelligence (subtle glow)

## Typography
- **Display/Hero:** SF Pro Display Bold 28px — panel headers, greeting
- **Heading:** SF Pro Display Medium 18px — section titles
- **Body:** SF Pro Text Regular 14px — user messages, general text
- **Twin Voice:** SF Pro Text Italic 14px — Twin messages. The Twin speaks in italic. It has its own voice.
- **Meta:** SF Pro Text Regular 11px — timestamps, status text
- **Data/Code:** SF Mono Regular 12px — tool call output, technical data
- **Loading:** System fonts. No web font loading. Zero latency.

## Color
- **Approach:** Restrained. Olive-green is the ONLY accent in a monochromatic palette. No blue, no purple, no secondary accent. The Twin is the visual focus.

| Token | Hex | RGB (0-1) | Usage |
|-------|-----|-----------|-------|
| Notch Black | #000000 | 0, 0, 0 | Notch-connected surfaces, panel top gradient start |
| Twin Green | #B5B055 | 0.71, 0.69, 0.33 | Primary accent, character color, send button, tool calls |
| Surface Dark | #1C1C1E | 0.11, 0.11, 0.118 | Notch panels, Twin message bubbles |
| Surface Deeper | #0D0D0F | 0.051, 0.051, 0.059 | Deep backgrounds, chat area |
| User Bubble | #2C2C2E | 0.173, 0.173, 0.18 | User message background |
| Text Primary | #F5F5F7 | 0.96, 0.96, 0.97 | Main text, headings |
| Text Muted | #8E8E93 | 0.557, 0.557, 0.576 | Timestamps, metadata, placeholders |
| Border | #333333 | 0.2, 0.2, 0.2 | Twin bubble border, dividers |
| Working Glow | #B5B055 @ 20% | — | Apple Intelligence-style soft pulse on VNC PiP |
| Error | #FF453A | 1, 0.271, 0.227 | Error states |
| Success | #30D158 | 0.188, 0.82, 0.345 | Completion states |

## Spacing
- **Base unit:** 8px (macOS standard)
- **Density:** Comfortable in chat, compact in notch peek state
- **Chat padding:** 12px horizontal, 8px between messages
- **Panel padding:** 16px internal
- **Scale:** 2xs(2) xs(4) sm(8) md(16) lg(24) xl(32) 2xl(48) 3xl(64)

## Layout
- **Approach:** Notch-anchored. Everything radiates from the notch. Alcove-style.
- **Panel states:** Idle (notch pill + Twin peek) → Peek (hover, +status) → Expanded (Twin + VNC mini) → Full chat
- **Notch detection:** `NSScreen.safeAreaInsets.top` for height, computed width + fine-tune slider
- **Notch shape:** True black (#000000) top matching hardware, gradient to Surface Dark below
- **Non-notch fallback:** Floating black pill at top-center of screen
- **Max content width:** 420px (chat panel)
- **Border radius:** sm 8px (tool pills), md 12px (message bubbles, panels), lg 16px (chat panel outer), full 9999px (input bar, buttons)
- **Notch radius:** ~10pt top corners (matching hardware), 16pt bottom corners (design system)

## Motion
- **Approach:** Intentional, physical. Alcove-style.
- **Character:** Organic, weight-based. Overshoot on arrival, settle with slight bounce.
- **Panel spring:** `.ssPanelSpring` — `spring(response: 0.3, dampingFraction: 0.85)` — panel transitions, DynamicNotchKit conversion
- **Content reveal:** `.ssContentReveal` — `spring(response: 0.25, dampingFraction: 0.88)` — status line, VNC thumbnail, chips
- **Message entrance:** `.ssMessageEntrance` — `spring(response: 0.3, dampingFraction: 0.9)` — chat bubble fade-in
- **Micro-interaction:** `.ssMicro` — `spring(response: 0.2, dampingFraction: 0.85)` — button press, focus glow, pill expand
- **Character transition:** `.ssCharacterTransition` — `spring(response: 0.3, dampingFraction: 0.85)` — Twin state changes
- **Glow pulse:** `.ssGlowPulse` — `easeInOut(duration: 2.5)` — VNC PiP working glow
- **Scroll:** `.ssScrollSpring` — `spring(response: 0.3, dampingFraction: 0.9)` — auto-scroll to latest message
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out)
- **Duration:** typewriter 20-60ms/char (deferred), glow pulse 2s ease-in-out (opacity 0.1→0.3)
- **Rule:** No linear easing. Ever.
- **Rule:** All animations use named tokens from DesignTokens.swift. No hardcoded springs.

## Anti-Slop Rules
- No gradient glows on flat surfaces
- No neon, cyan, or "futuristic" color schemes
- Olive-green from Figma design system only, not electric green
- Animations feel physical (weight, inertia, overshoot), not digital (instant, linear)
- Alcove-style: character interacts with notch edge, not abstract glow effects
- The Twin character IS the decoration. Nothing competes with it.

## Figma Reference
- File: https://www.figma.com/design/Cp8tQcDUti7kjNvZ18GrnX/YHacks
- Page 1: Twin character poses, notch states (State 1-4), onboarding
- Page 3: Design system tokens, chat view mockup

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-28 | Initial design system | Created by /design-consultation. Warm Minimal aesthetic, olive monochrome palette, Alcove-style motion. |
| 2026-03-28 | Italic for Twin voice | Unconventional in chat UIs. Creates immediate visual differentiation without heavy styling. |
| 2026-03-28 | No custom fonts | Native macOS app. System fonts match the OS, zero loading, best performance. |
| 2026-03-28 | Single accent color | Olive-green only. No secondary accents. Makes the Twin the visual focus of every screen. |
| 2026-03-28 | Film grain texture | Subtle 2-3% opacity on dark surfaces. Adds warmth. Most notch apps are flat and sterile. |
| 2026-03-28 | 4-state notch model | Idle/peek/expanded/fullChat. Alcove-style: hover-to-peek, click-to-expand, auto-expand on Twin activity. |
| 2026-03-28 | True black notch top | #000000 at panel top matches hardware notch. Gradient to Surface Dark below. Erases HW/SW boundary. |
| 2026-03-28 | No exterior shadows | Removed hasShadow and glow shadows from notch-connected surfaces. Silhouette + black fill only. |
| 2026-03-28 | Fine-tune slider | UserDefaults-backed width adjustment slider in Settings. Covers per-model notch width variance. |
| 2026-03-28 | Persistent hosting view | One NSHostingView, never destroyed/recreated. SwiftUI handles all transitions internally. |
