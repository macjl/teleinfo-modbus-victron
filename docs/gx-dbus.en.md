# Native Linky TIC driver on Venus OS

[Documentation complète en français](gx-dbus.md)

The native driver reads the USB adapter directly on GX and registers
`com.victronenergy.grid.linky_tic`. It uses the GX firmware's D-Bus, GLib and
pyserial libraries. It does not patch an existing Victron driver or require
MQTT, Docker, pip or Modbus emulation on GX.

Version **0.4.0b1** is a **monitoring beta**. Its runtime behavior matches the
0.4.0a3 driver that has operated for several days on the reference Raspberry
Pi 4 running Venus OS **3.85**. Other firmware/hardware combinations, ESS
regulation and automatic EVCS limiting remain unqualified.

## Requirements

- Root SSH access to a GX running Venus OS, with modifications enabled.
- A USB TIC adapter connected to a **single-phase Linky in standard mode**.
- Current frames containing `VTIC=02`, `URMS1`, `IRMS1`, `SINSTS`, `SINSTI`,
  `EAST` and `EAIT`. Missing export information is never assumed to be zero.
- A stable, explicitly observed `/dev/serial/by-id/…` path and a free grid
  device instance. Historical TIC mode and three-phase meters are unsupported.
- Firmware-provided `serial`, `dbus`, `gi` and `velib_python` modules.

Use only one reader for the USB adapter. Move it from a Linux gateway if
migrating, then stop that gateway and disable only its obsolete GX meter entry.

## Install

Run these commands as root on the GX. Alternatively download the archive and
checksum file elsewhere, then copy both to the GX.

```sh
cd /tmp
wget -O teleinfo-modbus-victron-0.4.0b1.tar.gz \
  https://github.com/macjl/teleinfo-modbus-victron/releases/download/v0.4.0b1/teleinfo-modbus-victron-0.4.0b1.tar.gz
wget -O SHA256SUMS \
  https://github.com/macjl/teleinfo-modbus-victron/releases/download/v0.4.0b1/SHA256SUMS
sha256sum -c SHA256SUMS
tar -xzf teleinfo-modbus-victron-0.4.0b1.tar.gz
cd teleinfo-modbus-victron-0.4.0b1
ls -l /dev/serial/by-id/
python3 tools/install_gx.py \
  --device /dev/serial/by-id/REPLACE_WITH_OBSERVED_ADAPTER_ID \
  --instance 43 --no-start
```

Replace the device placeholder with the **observed** path. Choose an instance
unused by other grid meters; 43 is an example. The installer checks firmware
libraries, preserves existing configuration and identity settings, and stores
the runtime under `/data/dbus-linky-tic`.

Review `/data/dbus-linky-tic/config.json`, based on
[config.dbus.example.json](../config.dbus.example.json), then validate and start:

```sh
cd /data/dbus-linky-tic/app
python3 -m teleinfo_modbus_victron.dbus_app \
  --config /data/dbus-linky-tic/config.json --check-config
rm /data/dbus-linky-tic/service/down
svc -u /service/dbus-linky-tic
svstat /service/dbus-linky-tic
tail -n 30 /var/log/dbus-linky-tic/current | tai64nlocal
```

The service appears as **Linky TIC Energy Meter**, with the persistent custom
name and instance in `com.victronenergy.settings`. The installer creates a
daemontools service, bounded logs, an adapter-specific serial ownership rule
and an identified `/data/rc.local` boot hook. Existing boot commands are kept.
No full GX reboot is required by the installer.

## Readings and limits

| Data | Paths / behavior |
| --- | --- |
| Estimated grid W | `/Ac/Power`, `/Ac/L1/Power`; positive import, negative export |
| RMS voltage/current | `/Ac/L1/Voltage`, `/Ac/L1/Current` |
| Import/export energy | `/Ac/Energy/Forward`, `/Ac/Energy/Reverse` and matching L1 paths; kWh with 1 Wh steps |
| Connection | `/Connected`; 0 on source loss or expiry |
| Contract/tariff/status | Custom `/Tic/…` paths; [full mapping](gx-dbus.md) |
| PowerGuard consumption | Active-power ceiling from PCOUP; L1 RMS-current ceiling from PCOUP / measured URMS1 |

Linky standard TIC does **not** provide instantaneous active power. The
adaptive estimator learns a W/VA coefficient from measured Wh, with a target
of **10 Wh OR 60 s** and mandatory minimums of **15 s AND 2 Wh**.
With `warmup_fallback: true`, fresh VA use the last learned coefficient for
the same direction, or 1 if unknown, while learning. Import/export caches
are separate and reset when the process restarts. See
[the estimator](power-estimator.md) and the [native diagnostics](gx-dbus.md).

PowerGuard publication is enabled by `powerguard_from_cutoff: true`.
`PCOUP` is in kVA: the total W ceiling follows `P ≤ S`; only the RMS-current
constraint also expresses the apparent-power limit with non-unity power
factor. Both limits are read-only and recomputed using each current frame.
Their publication **does not prove that EVCS automatically applies them**.
The driver neither commands EVCS nor configures an ESS controller.

Native frequency and power-factor fields remain unavailable. Custom TIC
paths are current state, not an archive, and are not automatically displayed
or historized by GX/VRM. They can be consumed by a suitable Node-RED D-Bus
reader. Linky ADSC/PRM identifiers are excluded from the custom payload.

Invalid, disconnected or expired source data become unavailable; the default
expiry is 5 s, with D-Bus publication every 250 ms. Energy, tariff and
PowerGuard values expire as well. The latter becomes inactive with invalid
limits. A consumer must handle this state explicitly; it does not guarantee
that an EV charger stops.

The separate Linux/Modbus mode has its own optional Prometheus endpoint.
The native GX driver does not install a system-wide Prometheus exporter.

## Check and stop

```sh
dbus -y com.victronenergy.grid.linky_tic /Connected GetValue
dbus -y com.victronenergy.grid.linky_tic /Ac/L1/Power GetValue
dbus -y com.victronenergy.grid.linky_tic /Tic/Status/State GetValue
dbus -y com.victronenergy.grid.linky_tic /Tic/Status/PowerProvisional GetValue
```

`Connected=1` means a fresh source. A published power value can still be
provisional: check `/Tic/Status/PowerProvisional` and `PowerCalibrated`.

To stop the driver persistently:

```sh
touch /data/dbus-linky-tic/service/down
svc -d /service/dbus-linky-tic
```

The native boot hook recreates links without forcing a `svc -u`, so `down`
continues to apply after reboot. Keep `/data/dbus-linky-tic` for recovery.
Restoring serial probes or migrating back to Modbus also requires undoing
this driver's adapter rule and boot hook; see [rollback details](gx-dbus.md#migration-et-retour-arrière).
