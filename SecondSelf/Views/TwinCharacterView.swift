import SwiftUI

// MARK: - Twin Character View

/// The Twin mascot rendered from Figma SVG assets.
/// Pose 1: idle (arms out, friendly)
/// Pose 2: thinking/working (arms up, waving)
/// Pose 3: complete/presenting (arm extended)
/// Animates based on TwinState with design token springs.
struct TwinCharacterView: View {
    let twinState: TwinState
    var compact: Bool = false

    @State private var breatheScale: CGFloat = 1.0
    @State private var bobOffset: CGFloat = 0
    @State private var wiggleRotation: Double = 0
    @State private var bounceScale: CGFloat = 1.0

    private var poseName: String {
        switch twinState {
        case .idle, .error:   return "TwinPose1"
        case .thinking:       return "TwinPose2"
        case .working:        return "TwinPose2"
        case .complete:       return "TwinPose3"
        }
    }

    var body: some View {
        Image(poseName)
            .resizable()
            .aspectRatio(contentMode: .fit)
            .scaleEffect(breatheScale * bounceScale)
            .offset(y: bobOffset)
            .rotationEffect(.degrees(wiggleRotation))
            .onAppear {
                applyAnimation(for: twinState)
            }
            .onChange(of: twinState) { newState in
                resetAnimations()
                applyAnimation(for: newState)
            }
    }

    // MARK: - Animations

    private func applyAnimation(for state: TwinState) {
        switch state {
        case .idle:
            // Very subtle breathing
            withAnimation(
                .spring(response: 1.2, dampingFraction: 0.85)
                .repeatForever(autoreverses: true)
            ) {
                breatheScale = 1.01
            }

        case .thinking:
            // Gentle vertical bob
            withAnimation(
                .spring(response: 1.0, dampingFraction: 0.85)
                .repeatForever(autoreverses: true)
            ) {
                bobOffset = -1.5
            }

        case .working:
            // Subtle rotation wiggle
            withAnimation(
                .ssCharacterTransition
                .repeatForever(autoreverses: true)
            ) {
                wiggleRotation = 1.5
            }

        case .complete:
            // Gentle bounce
            withAnimation(.ssCharacterTransition) {
                bounceScale = 1.05
            }
            Task { @MainActor in
                try? await Task.sleep(for: .seconds(0.3))
                withAnimation(.ssCharacterTransition) {
                    bounceScale = 1.0
                }
            }

        case .error:
            break
        }
    }

    private func resetAnimations() {
        // Animate back to neutral instead of snapping
        withAnimation(.ssCharacterTransition) {
            breatheScale = 1.0
            bobOffset = 0
            wiggleRotation = 0
            bounceScale = 1.0
        }
    }
}
