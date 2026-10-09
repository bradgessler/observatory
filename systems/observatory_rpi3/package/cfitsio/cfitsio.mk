################################################################################
#
# cfitsio
#
################################################################################

CFITSIO_VERSION = 4.7.0
CFITSIO_SITE = https://heasarc.gsfc.nasa.gov/FTP/software/fitsio/c
CFITSIO_LICENSE = CFITSIO
CFITSIO_LICENSE_FILES = licenses/License.txt
CFITSIO_INSTALL_STAGING = YES
CFITSIO_DEPENDENCIES = zlib
# no network access to remote FITS files from a telescope box
CFITSIO_CONF_OPTS = --disable-curl --enable-reentrant

$(eval $(autotools-package))
