################################################################################
#
# astrometry-net
#
################################################################################

ASTROMETRY_NET_VERSION = 0.97
ASTROMETRY_NET_SOURCE = astrometry.net-$(ASTROMETRY_NET_VERSION).tar.gz
ASTROMETRY_NET_SITE = https://github.com/dstndstn/astrometry.net/releases/download/$(ASTROMETRY_NET_VERSION)
# BSD-3-Clause for astrometry.net's own code; linked with GSL, which is GPL
ASTROMETRY_NET_LICENSE = BSD-3-Clause, GPL-3.0+ (GSL)
ASTROMETRY_NET_LICENSE_FILES = LICENSE
ASTROMETRY_NET_DEPENDENCIES = bzip2 cfitsio gsl zlib host-pkgconf

# Cross-compiling: the target compiler and flags (ARCH_FLAGS replaces its
# -march=native), pkg-config from the host for cfitsio and GSL, Buildroot's
# GSL (SYSTEM_GSL=yes: the bundled gsl-an runs a configure that has to
# execute target programs, which a cross build can't), and no netpbm or
# Python: its one feature test fails harmlessly when it can't run a target
# binary, which means "no netpbm".
ASTROMETRY_NET_MAKE_OPTS = \
	CC="$(TARGET_CC)" AR="$(TARGET_AR)" RANLIB="$(TARGET_RANLIB)" \
	ARCH_FLAGS="$(TARGET_CFLAGS)" \
	PKG_CONFIG="$(PKG_CONFIG_HOST_BINARY)" \
	SYSTEM_GSL=yes PYTHON=true NETPBM_INC= NETPBM_LIB=

define ASTROMETRY_NET_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE1) -C $(@D) $(ASTROMETRY_NET_MAKE_OPTS) config
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) $(ASTROMETRY_NET_MAKE_OPTS) qfits-an util libkd catalogs
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D)/solver $(ASTROMETRY_NET_MAKE_OPTS) solve-field astrometry-engine image2xy
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D)/util $(ASTROMETRY_NET_MAKE_OPTS) an-pnmtofits wcsinfo
endef

# just the programs the solve pipeline runs; indexes and config live on /data
define ASTROMETRY_NET_INSTALL_TARGET_CMDS
	for p in solver/solve-field solver/astrometry-engine solver/image2xy util/an-pnmtofits util/wcsinfo; do \
		$(INSTALL) -D -m 0755 $(@D)/$$p $(TARGET_DIR)/usr/bin/$$(basename $$p) || exit 1; \
	done
endef

$(eval $(generic-package))
