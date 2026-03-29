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
    @State private var expandedWindow: NSWindow?

    private let thumbnailSize = CGSize(width: 140, height: 90)

    var body: some View {
        ZStack(alignment: .topLeading) {
            // Live desktop feed
            Group {
                if let image = streamer.currentFrame {
                    Image(nsImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                } else {
                    Rectangle()
                        .fill(Color.ssBackground)
                }
            }
            .frame(width: thumbnailSize.width, height: thumbnailSize.height)
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
                    ? Color.ssTwinGreen.opacity(0.3)
                    : Color.black.opacity(0.3),
                radius: twinState == .working ? 8 : 4
            )

            // LIVE indicator (only when actually streaming)
            if streamer.currentFrame != nil {
                HStack(spacing: 4) {
                    Circle()
                        .fill(Color.ssError)
                        .frame(width: 5, height: 5)
                    Text("LIVE")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundColor(Color.ssTextPrimary)
                }
                .padding(.horizontal, 6)
                .padding(.vertical, 3)
                .background(
                    Capsule()
                        .fill(Color.black.opacity(0.6))
                )
                .padding(6)
            }
        }
        .scaleEffect(isHovered ? 1.05 : 1.0)
        .animation(.spring(response: 0.3, dampingFraction: 0.7), value: isHovered)
        .onHover { hovering in
            isHovered = hovering
        }
        .onTapGesture {
            openExpandedVNCWindow()
        }
        .onAppear {
            streamer.start()
        }
        .onDisappear {
            streamer.stop()
        }
    }


    // MARK: - Expanded VNC Window

    private func openExpandedVNCWindow() {
        if expandedWindow != nil {
            expandedWindow?.makeKeyAndOrderFront(nil)
            return
        }

        let windowSize = CGSize(width: 800, height: 500)
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: windowSize),
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Second Self — Twin's Desktop"
        window.backgroundColor = NSColor(red: 0.05, green: 0.05, blue: 0.06, alpha: 1.0)
        window.isReleasedWhenClosed = false
        window.center()

        let hostingView = NSHostingView(
            rootView: ExpandedVNCView(streamer: streamer)
        )
        window.contentView = hostingView
        window.makeKeyAndOrderFront(nil)
        expandedWindow = window
    }
}

// MARK: - Expanded VNC View

struct ExpandedVNCView: View {
    @ObservedObject var streamer: MJPEGStreamer

    var body: some View {
        Group {
            if let image = streamer.currentFrame {
                Image(nsImage: image)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
            } else {
                VStack(spacing: 8) {
                    Text("Connecting to Twin's desktop...")
                        .font(.system(size: 14))
                        .foregroundColor(Color.ssTextSecondary)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.ssBackground)
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
    private let boundary = "--frame".data(using: .utf8)!
    private var isRunning = false

    private let ports = [ServerConfig.agentServerPort]
    private var currentPortIndex = 0
    private var retryTimer: Timer?

    private var frameCount = 0

    func start() {
        guard !isRunning else { return }
        isRunning = true
        print("[VNC-PiP] Starting MJPEG streamer...")
        connectToNextPort()
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

    private func connectToNextPort() {
        guard isRunning, currentPortIndex < ports.count else {
            // All ports tried, retry from beginning after delay
            currentPortIndex = 0
            retryTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: false) { [weak self] _ in
                self?.connectToNextPort()
            }
            return
        }

        let port = ports[currentPortIndex]
        let url = URL(string: "http://localhost:\(port)/stream")!
        print("[VNC-PiP] Trying port \(port)...")

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 3600
        session = URLSession(configuration: config, delegate: self, delegateQueue: .main)

        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        task = session?.dataTask(with: request)
        task?.resume()
    }

    // MARK: - URLSessionDataDelegate

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        buffer.append(data)
        if buffer.count < 1000 {
            print("[VNC-PiP] Received \(data.count) bytes (buffer: \(buffer.count))")
        }
        extractFrames()
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            print("[VNC-PiP] Stream error on port \(ports[min(currentPortIndex, ports.count-1)]): \(error.localizedDescription)")
        } else {
            print("[VNC-PiP] Stream ended cleanly")
        }
        if isRunning {
            currentPortIndex += 1
            buffer.removeAll()
            connectToNextPort()
        }
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping (URLSession.ResponseDisposition) -> Void
    ) {
        if let http = response as? HTTPURLResponse {
            print("[VNC-PiP] Connected! HTTP \(http.statusCode), Content-Type: \(http.allHeaderFields["Content-Type"] ?? "unknown")")
        }
        completionHandler(.allow)
    }

    // MARK: - JPEG Frame Extraction

    private func extractFrames() {
        while let jpegStart = buffer.firstRange(of: Data([0xFF, 0xD8])),
              let jpegEnd = buffer[jpegStart.lowerBound...].firstRange(of: Data([0xFF, 0xD9])) {

            let frameData = buffer[jpegStart.lowerBound...jpegEnd.upperBound - 1]

            if let image = NSImage(data: Data(frameData)) {
                currentFrame = image
                frameCount += 1
                if frameCount <= 3 || frameCount % 50 == 0 {
                    print("[VNC-PiP] Frame \(frameCount) decoded (\(frameData.count) bytes, \(Int(image.size.width))x\(Int(image.size.height)))")
                }
            } else {
                print("[VNC-PiP] Failed to decode JPEG frame (\(frameData.count) bytes)")
            }

            buffer.removeSubrange(..<jpegEnd.upperBound)
        }

        if buffer.count > 5_000_000 {
            print("[VNC-PiP] Buffer overflow, clearing")
            buffer.removeAll()
        }
    }
}
