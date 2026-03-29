import SwiftUI
import AppKit

// MARK: - VNC PiP View

/// Picture-in-picture VNC feed thumbnail.
/// Native MJPEG parser using URLSession (no WKWebView, no ATS issues).
/// Olive-green glow when Twin is working. Click to expand.
struct VNCPipView: View {
    let twinState: TwinState

    @StateObject private var streamer = MJPEGStreamer()
    @State private var isHovered: Bool = false
    @State private var glowPhase: Bool = false

    var body: some View {
        ZStack(alignment: .bottom) {
            // Live desktop feed
            Group {
                if let image = streamer.currentFrame {
                    Image(nsImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                } else {
                    Rectangle()
                        .fill(Color.ssBackground)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .stroke(
                        twinState == .working ? Color.ssTwinGreen : Color.ssBorder,
                        lineWidth: twinState == .working ? 1.5 : 0.5
                    )
            )
            .shadow(
                color: twinState == .working
                    ? Color.ssTwinGreen.opacity(glowPhase ? 0.3 : 0.1)
                    : Color.black.opacity(0.3),
                radius: twinState == .working ? 8 : 4
            )

            // Take Control button — launches TigerVNC on hover
            if isHovered {
                Button(action: { launchTigerVNC() }) {
                    Text("Take Control")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundColor(.white)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 5)
                        .background(Capsule().fill(Color.ssTwinGreen.opacity(0.85)))
                }
                .buttonStyle(.plain)
                .padding(.bottom, 8)
                .transition(.opacity)
            }
        }
        .animation(.ssMicro, value: isHovered)
        .animation(.ssGlowPulse.repeatForever(autoreverses: true), value: glowPhase)
        .onHover { hovering in
            isHovered = hovering
        }
        .onAppear {
            streamer.start()
            glowPhase = true
        }
        .onDisappear {
            streamer.stop()
        }
    }

    private func launchTigerVNC() {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        task.arguments = ["-a", "TigerVNC", "--args", "localhost:5901"]
        try? task.run()
    }
}

// MARK: - MJPEG Stream Parser

/// Connects to the agent-server MJPEG stream via URLSession.
/// Parses multipart/x-mixed-replace boundaries and extracts JPEG frames.
/// No WKWebView needed, no ATS restrictions.
final class MJPEGStreamer: NSObject, ObservableObject, URLSessionDataDelegate {
    @Published var currentFrame: NSImage?

    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var buffer = Data()
    private var isRunning = false
    private var retryTimer: Timer?
    private var frameCount = 0
    private var lastFrameID: ObjectIdentifier?

    // Pre-allocated JPEG markers (avoid heap alloc per frame)
    private static let jpegSOI = Data([0xFF, 0xD8])
    private static let jpegEOI = Data([0xFF, 0xD9])

    // Background queue for JPEG decoding (keep main thread free for UI)
    private let decodeQueue = DispatchQueue(label: "mjpeg.decode", qos: .userInitiated)

    func start() {
        guard !isRunning else { return }
        isRunning = true
        print("[VNC-PiP] Starting MJPEG streamer...")
        connect()
    }

    func stop() {
        isRunning = false
        task?.cancel()
        task = nil
        session?.invalidateAndCancel()
        session = nil
        retryTimer?.invalidate()
        retryTimer = nil
    }

    private func connect() {
        guard isRunning else { return }

        let url = URL(string: ServerConfig.agentStreamURL)!
        print("[VNC-PiP] Connecting to \(url)...")

        // Invalidate previous session to prevent leaks
        session?.invalidateAndCancel()

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 3600
        session = URLSession(configuration: config, delegate: self, delegateQueue: nil)

        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        task = session?.dataTask(with: request)
        task?.resume()
    }

    // MARK: - URLSessionDataDelegate

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        buffer.append(data)
        extractFrames()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            print("[VNC-PiP] Stream error: \(error.localizedDescription)")
        }
        if isRunning {
            buffer.removeAll()
            // Retry after delay
            DispatchQueue.main.async { [weak self] in
                self?.retryTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: false) { [weak self] _ in
                    self?.connect()
                }
            }
        }
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        if let http = response as? HTTPURLResponse {
            print("[VNC-PiP] Connected! HTTP \(http.statusCode)")
        }
        completionHandler(.allow)
    }

    // MARK: - JPEG Frame Extraction

    private func extractFrames() {
        while let jpegStart = buffer.firstRange(of: Self.jpegSOI),
              let jpegEnd = buffer[jpegStart.lowerBound...].firstRange(of: Self.jpegEOI) {

            let frameData = Data(buffer[jpegStart.lowerBound...jpegEnd.upperBound - 1])
            buffer.removeSubrange(..<jpegEnd.upperBound)

            // Decode JPEG off the main thread
            decodeQueue.async { [weak self] in
                guard let image = NSImage(data: frameData) else { return }
                DispatchQueue.main.async {
                    self?.currentFrame = image
                    self?.frameCount += 1
                    if let count = self?.frameCount, count <= 3 || count % 50 == 0 {
                        print("[VNC-PiP] Frame \(count) (\(frameData.count / 1024)KB)")
                    }
                }
            }
        }

        if buffer.count > 5_000_000 {
            buffer.removeAll()
        }
    }
}
