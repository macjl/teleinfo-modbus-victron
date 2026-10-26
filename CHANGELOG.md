# Changelog

## 0.3.0a1 — 2026-10-26

First public release of the current monitoring gateway.

- ABB B21 Modbus TCP profile, with import and reverse energy exposed by the
  native Victron driver in both total and L1 paths, at 10 Wh resolution.
- Alternative EM24 Ethernet profile, including its discovery and application
  initialization registers, retained at 100 Wh energy resolution.
- Standard single-phase Linky TIC reader, checksum validation, reconnection,
  consistency checks and measurement expiration.
- Adaptive active-power estimate inspired by F1ATB: 10 Wh OR 60 s target,
  with mandatory 15 s AND 2 Wh minimums and adaptive smoothing.
- Simulated source, diagnostic client, optional Prometheus metrics,
  YAML/environment configuration, native Python and Docker deployment.
- Pinned official Victron source audit and 58 automated tests.
- Native GX discovery and displayed readings confirmed on a Raspberry Pi 4
  running Venus OS 3.85; ABB reverse energy L1 confirmed.

Active power remains estimated. ESS control, complete end-to-end fault timing
and VRM history continuity are not qualified. Direct GX D-Bus publishing is
not part of this release.
