// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "SecondSelf",
    platforms: [
        .macOS(.v14)
    ],
    dependencies: [
        .package(url: "https://github.com/MrKai77/DynamicNotchKit", branch: "main")
    ],
    targets: [
        .executableTarget(
            name: "SecondSelf",
            dependencies: ["DynamicNotchKit"],
            path: ".",
            exclude: ["Info.plist", "Package.swift", "Tests", "SecondSelf.entitlements"],
            resources: [
                .process("Assets.xcassets"),
                .copy("Resources")
            ]
        ),
    ]
)
