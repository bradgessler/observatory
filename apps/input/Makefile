# Builds priv/hidport against libhidapi (brew install hidapi / apt install libhidapi-dev).
CFLAGS  ?= -O2 -Wall
HIDAPI_CFLAGS := $(shell pkg-config --cflags hidapi 2>/dev/null || pkg-config --cflags hidapi-hidraw 2>/dev/null)
HIDAPI_LIBS   := $(shell pkg-config --libs hidapi 2>/dev/null || pkg-config --libs hidapi-hidraw 2>/dev/null || echo -lhidapi)
PRIV = $(MIX_APP_PATH)/priv
all: $(PRIV)/hidport
$(PRIV)/hidport: c_src/hidport.c
	@mkdir -p $(PRIV)
	$(CC) $(CFLAGS) $(HIDAPI_CFLAGS) c_src/hidport.c -o $@ $(HIDAPI_LIBS)
clean:
	rm -f $(PRIV)/hidport
.PHONY: all clean
