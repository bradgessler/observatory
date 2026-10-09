# The observatory's own Buildroot packages (package/*): the plate solver and
# what it needs. Found from this file's own directory, so it doesn't depend
# on how NERVES_DEFCONFIG_DIR happens to end.
OBSERVATORY_SYSTEM_DIR := $(dir $(lastword $(MAKEFILE_LIST)))
include $(sort $(wildcard $(OBSERVATORY_SYSTEM_DIR)package/*/*.mk))
