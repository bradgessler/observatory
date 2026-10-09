#!/bin/sh

set -e

FWUP_CONFIG=$NERVES_DEFCONFIG_DIR/fwup.conf

# fwup.conf is generated from fwup.conf.eex. The Docker build image has no
# Elixir, so on a Mac it is generated on the host beforehand and checked in:
#   elixir -e 'File.write!("fwup.conf", EEx.eval_file("fwup.conf.eex"))'
if command -v mix > /dev/null 2>&1; then
    (cd "$NERVES_DEFCONFIG_DIR" && ELIXIR_ERL_OPTIONS="+fnu" mix generate_fwup_conf)
elif [ ! -f "$FWUP_CONFIG" ]; then
    echo "ERROR: no fwup.conf, and no Elixir here to generate it from fwup.conf.eex."
    exit 1
fi

# Run the common post-image processing for nerves
$BR2_EXTERNAL_NERVES_PATH/board/nerves-common/post-createfs.sh $TARGET_DIR $FWUP_CONFIG
