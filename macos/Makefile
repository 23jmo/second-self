SOURCES := $(shell find Sources/SecondSelf -name '*.swift')
BUILD_DIR := .build
BINARY := $(BUILD_DIR)/SecondSelf
SDK := $(shell xcrun --sdk macosx --show-sdk-path)

.PHONY: build run clean

build: $(BINARY)

$(BINARY): $(SOURCES) Resources/Info.plist
	@mkdir -p $(BUILD_DIR)
	swiftc \
		$(SOURCES) \
		-o $(BINARY) \
		-sdk $(SDK) \
		-target arm64-apple-macosx14.0 \
		-swift-version 5 \
		-Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker Resources/Info.plist \
		-framework AppKit \
		-framework SwiftUI

run: build
	./$(BINARY)

clean:
	rm -rf $(BUILD_DIR)
