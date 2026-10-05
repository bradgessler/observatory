# Builds priv/usbport: on Linux against the kernel's usbfs (no library), on macOS against libusb
# (brew install libusb). A machine without either still builds the rest: USB cameras are simply off
# there, and Camera.Discovery says so in one line instead of crashing.
CFLAGS ?= -O2 -Wall
UNAME := $(shell uname -s)
LIBUSB_CFLAGS := $(shell pkg-config --cflags libusb-1.0 2>/dev/null)
LIBUSB_LIBS := $(shell pkg-config --libs libusb-1.0 2>/dev/null)
PRIV = $(MIX_APP_PATH)/priv
all: $(PRIV)/usbport
# Which compiler made it is part of the rule: a laptop build left in the Pi's _build (or the other
# way round) is remade, never shipped.
CC_USED = $(PRIV)/.usbport-cc
$(CC_USED): FORCE
	@mkdir -p $(PRIV)
	@echo '$(CC) $(CROSSCOMPILE) $(UNAME)' | cmp -s - $@ || echo '$(CC) $(CROSSCOMPILE) $(UNAME)' > $@
$(PRIV)/usbport: c_src/usbport.c $(CC_USED)
	@mkdir -p $(PRIV)
	@if [ -n "$(CROSSCOMPILE)" ] || [ "$(UNAME)" = "Linux" ]; then \
	  $(CC) $(CFLAGS) c_src/usbport.c -o $@ || (rm -f $@; echo "camera: usbport did not build here, so USB cameras are off"); \
	elif [ -n "$(LIBUSB_LIBS)" ]; then \
	  $(CC) $(CFLAGS) -DHAVE_LIBUSB $(LIBUSB_CFLAGS) c_src/usbport.c -o $@ $(LIBUSB_LIBS) || (rm -f $@; echo "camera: usbport did not build here, so USB cameras are off"); \
	else \
	  echo "camera: no libusb on this machine (brew install libusb), so USB cameras are off here"; \
	fi
clean:
	rm -f $(PRIV)/usbport $(CC_USED)
.PHONY: all clean FORCE
FORCE:
