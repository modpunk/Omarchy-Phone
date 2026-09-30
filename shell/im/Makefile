# Builds shell/bin/ophone-im from the vendored input-method-unstable-v2
# protocol + ophone-im.c. Needs wayland-scanner and a C compiler at build
# time (image build only); the resulting binary only links libwayland-client,
# which the shell already depends on via quickshell, so no new runtime
# package is needed.
CC        ?= cc
CFLAGS    ?= -O2 -Wall -Wextra
WAYLAND_SCANNER ?= wayland-scanner
PKG_CONFIG      ?= pkg-config

BUILD := build
BIN   := ../bin/ophone-im
PROTO := protocol/input-method-unstable-v2.xml

WL_CFLAGS := $(shell $(PKG_CONFIG) --cflags wayland-client)
WL_LIBS   := $(shell $(PKG_CONFIG) --libs wayland-client)

.PHONY: all clean
all: $(BIN)

$(BUILD)/input-method-unstable-v2-client-protocol.h: $(PROTO)
	@mkdir -p $(BUILD)
	$(WAYLAND_SCANNER) client-header $< $@

$(BUILD)/input-method-unstable-v2-protocol.c: $(PROTO)
	@mkdir -p $(BUILD)
	$(WAYLAND_SCANNER) private-code $< $@

$(BIN): ophone-im.c $(BUILD)/input-method-unstable-v2-client-protocol.h $(BUILD)/input-method-unstable-v2-protocol.c
	@mkdir -p ../bin
	$(CC) $(CFLAGS) -I$(BUILD) -o $@ ophone-im.c $(BUILD)/input-method-unstable-v2-protocol.c $(WL_CFLAGS) $(WL_LIBS)

clean:
	rm -rf $(BUILD) $(BIN)
