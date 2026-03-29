// swift-tools-version: 6.1
import PackageDescription

let package = Package(
    name: "SecondSelf",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "SecondSelf",
            path: "Sources/SecondSelf",
            linkerSettings: [
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", "Resources/Info.plist",
                ])
            ]
        )
    ]
)
