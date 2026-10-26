# Changelog

## 0.4.0a3 — 2026-10-26

- Native D-Bus PowerGuard consumption limits derived from current-frame PCOUP:
  total active-power ceiling and single-phase RMS current using measured URMS1.
- Dynamic voltage/contract updates, read-only paths, invalid limits and inactive
  flag on missing, rejected or expired inputs; configurable publication.
- The W ceiling alone does not enforce a VA limit. Native EVCS forwarding and
  actual charge limitation remain unverified; no EVCS settings are changed.
- 74 automated tests, including changing voltage/contract, import/export,
  missing/malformed inputs, zero voltage, disabled publication and source faults.

## 0.4.0a2 — 2026-10-26

- Native D-Bus provisional power during initial/reversal warm-up: reuse the last
  learned coefficient for the same direction, or 1 if unknown.
- Separate availability, provisional/calibrated flags and factor-source diagnostics.
- Fresh validated TIC remains mandatory; measured power-factor fields stay invalid.
- Optional strict warm-up behavior via `warmup_fallback: false`; Modbus unchanged.
- 70 automated tests, including both reversal directions, recovery and expiration.

## 0.4.0a1 — 2026-10-26

- Native Venus OS D-Bus grid meter with direct TIC USB acquisition.
- Exact 1 Wh energy steps in native Total/L1 paths, with no meter emulation.
- Separate custom TIC contract, tariff, energy, status and historical data paths.
- Persistent GX installation, firmware-provided libraries, adapter-specific
  serial ownership, bounded logs, and explicit invalidation of expired data.
- Existing Modbus profiles and adaptive estimator retained; 66 automated tests.
- Active power remains estimated; ESS is still unqualified.

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
