# teleinfo-modbus-victron

[Documentation en français](README.md)

Python gateway from a French single-phase Linky meter's **standard TIC USB
interface** to a **Modbus TCP server**, emulating an **ABB B21** energy meter
or, optionally, a Carlo Gavazzi EM24 Ethernet.

**The Victron GX is the Modbus client.** No custom driver needs to be installed
on Venus OS. MQTT is not required.

Version **0.3.0a1** is an experimental monitoring release. Native discovery
and displayed readings have been confirmed on a Raspberry Pi 4 running
**Venus OS 3.85**, first with EM24 and then with ABB B21. The ABB profile also
displays reverse energy on L1. This is validation on one installation, not
universal compatibility or ESS qualification. See the
[validation report, in French](docs/venus-validation.md).

## Measurement limits

- Linky standard TIC provides apparent power in VA, not instantaneous active
  power in W. The default estimator learns a W/VA ratio from measured Wh
  increments and applies it to current apparent power.
- The adaptive history targets **10 Wh OR 60 seconds**, whichever comes first,
  while requiring **both 15 seconds AND 2 Wh**. Initial learning, reversals,
  low loads and changing load characteristics introduce delay.
- This is an independent implementation inspired by the
  [F1ATB solar router](https://github.com/F1ATB/Solar-Router-F1ATB), not a copy
  of its firmware. See the [algorithm and limitations](docs/power-estimator.md).
- **ESS control and native Victron solar charging control are not qualified.**
- Import/export energy comes from measured `EAST`/`EAIT` counters. ABB exposes
  10 Wh steps, versus 100 Wh for EM24. Export means energy injected into the
  grid, not total PV generation.
- Frequency is configured, not measured. Instantaneous power factor is
  unavailable in the ABB profile.
- The server rejects stale measurements with Modbus exception 04; Venus OS may
  temporarily retain its own cached display. End-to-end fault timing still
  needs validation.

## Quick start with simulated data

Requires Linux and Python 3.11 or newer:

```sh
git clone https://github.com/macjl/teleinfo-modbus-victron.git
cd teleinfo-modbus-victron
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[metrics]'
.venv/bin/teleinfo-modbus --config config.example.yaml --check-config
.venv/bin/teleinfo-modbus --config config.example.yaml
```

The example serves ABB B21 on `127.0.0.1:1502`, Unit ID **1**. In another terminal:

```sh
.venv/bin/python -m teleinfo_modbus_victron.probe --host 127.0.0.1 --port 1502
```

The probe is a separate diagnostic client. The gateway itself remains a server.
Use `meter_profile: em24` to select the alternative profile.

## USB and Docker on Linux

Identify the actual device and its group first:

```sh
ls -l /dev/serial/by-id/
getent group dialout
```

For a new installation, copy `.env.example` to `.env`. Set `MODBUS_BIND` to the
Linux host's LAN IPv4 address, `TIC_DEVICE` to the observed stable device path,
and `TIC_DIALOUT_GID` to the device group's numeric GID. Then run:

```sh
docker compose -f compose.yaml -f compose.tic.yaml up -d --build
docker compose -f compose.yaml -f compose.tic.yaml logs --tail 50
```

This publishes host TCP **502** to container port 1502. The container runs as a
non-root user with a read-only filesystem. It reads TIC at **9600 baud, 7E1**.
Do not run another reader against the same USB device. After physical USB
reconnection, Docker may require `up -d --force-recreate` with the same files.

Required fields are `VTIC=02`, `URMS1`, `IRMS1`, `SINSTS`, `SINSTI`, `EAST`
and `EAIT`. A missing injection field is not silently replaced with zero.
Historical TIC mode, three-phase meters and direct GX D-Bus publishing are
not implemented in this version.

For native Python deployment, copy the example to `config.local.yaml`, set
`source: tic`, `device`, `host` and `port`, and use the same CLI. A sample
systemd unit is included. See [deployment details](docs/deployment-debian.md).

## Victron GX setup

1. In the GX Modbus devices menu, scan for devices on the same LAN.
2. Enable the discovered ABB B21, Unit ID **1**, serial **10000001** by default.
3. Verify its role is **Grid**, with single-phase L1 readings.
4. Give it a descriptive name such as **Linky TIC — estimated power**.
5. If migrating from the EM24 profile, disable the old meter to avoid duplicates.

Choose a unique, stable `abb_serial` if running multiple gateways. The GX's
own Modbus TCP server is a separate feature and is not needed for this setup.
The [GX setup guide](docs/gx-setup.md) includes migration and rollback instructions.

## Configuration and development

YAML settings can be overridden with `TIC_EM24_<SETTING>` environment variables.
The historical prefix remains valid for both profiles. Prometheus is optional
and disabled by default. `.env` and `*.local.*` files are excluded from Git.

```sh
.venv/bin/python -m unittest discover -v
.venv/bin/python tools/check_upstream.py
```

The 58 tests cover both wire maps, TCP operations, parsing, freshness,
reconnection, estimation and metrics. The upstream audit verifies pinned
Victron sources and official register decoders; it needs internet access
unless `--source-dir` points to a matching local checkout.

Contributions and hardware reports are welcome. Please read
[CONTRIBUTING.md](CONTRIBUTING.md) before sharing captures or installation data.

MIT license. Independent project, unaffiliated with Victron Energy, ABB,
Carlo Gavazzi or Enedis.
