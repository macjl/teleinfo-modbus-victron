#!/bin/sh
# Restore only our service and adapter rule after reboot / firmware update.
set -eu
base=/data/dbus-linky-tic
mkdir -p /run/udev/rules.d
ln -sf "$base/99-linky-tic.rules" /run/udev/rules.d/99-linky-tic.rules
udevadm control --reload-rules
if [ -w /opt/victronenergy/service ]; then
    ln -sfn "$base/service" /opt/victronenergy/service/dbus-linky-tic
fi
ln -sfn "$base/service" /service/dbus-linky-tic
