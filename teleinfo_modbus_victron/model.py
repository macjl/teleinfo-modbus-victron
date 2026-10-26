"""Immutable measurement snapshots and monotonic freshness checks."""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
import threading
import time
from types import MappingProxyType
from typing import Mapping

from .config import Config
from .registers import encode_number
from .profiles import get_profile
from .tic import Group
from .power import PowerEstimate, PowerEstimator


@dataclass(frozen=True)
class Snapshot:
    received_at: float
    received_utc: str
    voltage: float
    current: float
    apparent_import: float
    apparent_export: float
    energy_import_wh: int
    energy_export_wh: int
    extras: Mapping[str, Group]
    power_estimate: PowerEstimate | None = None

    @property
    def estimated_power(self) -> float | None:
        if self.power_estimate is not None:
            return self.power_estimate.watts
        return self.apparent_import - self.apparent_export


def normalize(groups: dict[str, Group], config: Config, now: float | None = None) -> Snapshot:
    def number(name):
        value = groups[name].value
        if not value or not value.isascii() or not value.isdecimal():
            raise ValueError(f"{name} must be an unsigned integer")
        return int(value)

    try:
        if groups["VTIC"].value != "02":
            raise ValueError("unsupported TIC version")
        values = [number(k) for k in ("URMS1", "IRMS1", "SINSTS", "SINSTI", "EAST", "EAIT")]
    except KeyError as exc:
        raise ValueError(f"missing TIC field: {exc.args[0]}") from exc
    # Identifiers are not kept in normalized snapshots or metrics.
    extras = MappingProxyType({k: v for k, v in groups.items() if k not in ("ADSC", "PRM")})
    snapshot = Snapshot(time.monotonic() if now is None else now,
                        datetime.now(timezone.utc).isoformat(), *values, extras)
    validate(snapshot, config)
    return snapshot


def validate(s: Snapshot, config: Config):
    for value, limit in ((s.voltage, config.max_voltage), (s.current, config.max_current),
                         (s.apparent_import, config.max_apparent_power),
                         (s.apparent_export, config.max_apparent_power)):
        if not math.isfinite(value) or not 0 <= value <= limit:
            raise ValueError("measurement outside configured physical limits")
    if not math.isfinite(s.received_at):
        raise ValueError("invalid reception time")
    if s.apparent_import and s.apparent_export:
        raise ValueError("simultaneous import and export in single-phase TIC")
    if (s.apparent_import or s.apparent_export) and s.voltage == 0:
        raise ValueError("nonzero apparent power with zero voltage")
    # IRMS1 is integer A; leave room for rounding and asynchronous RMS updates.
    if max(s.apparent_import, s.apparent_export) > s.voltage * (s.current + 2) * 1.1:
        raise ValueError("apparent power inconsistent with RMS voltage/current")
    profile = get_profile(config.meter_profile)
    profile.energy_wh_to_raw(s.energy_import_wh)
    profile.energy_wh_to_raw(s.energy_export_wh)
    for name, value in (("voltage_l1", s.voltage), ("current_l1", s.current),
                        ("power_total", s.apparent_import - s.apparent_export)):
        encode_number(value, profile.BY_NAME[name])


class MeasurementStore:
    def __init__(self, config: Config, clock=time.monotonic):
        self.config = config
        self.clock = clock
        self._lock = threading.Lock()
        self._snapshot: Snapshot | None = None
        self._baseline: Snapshot | None = None
        self._estimator = PowerEstimator(config)
        self.reason = "waiting for first valid frame"
        self.accepted = 0
        self.rejected = 0
        self.reconnections = 0

    def publish(self, snapshot: Snapshot):
        validate(snapshot, self.config)
        with self._lock:
            old = self._baseline
            if old and (snapshot.energy_import_wh < old.energy_import_wh
                        or snapshot.energy_export_wh < old.energy_export_wh):
                raise ValueError("energy counter decreased; check meter identity/reset")
            if snapshot.received_at > self.clock() or (old and snapshot.received_at < old.received_at):
                raise ValueError("reception timestamp moved backwards or is in the future")
            if self.config.source == "tic" and self.config.power_method == "adaptive":
                try:
                    snapshot = replace(snapshot, power_estimate=self._estimator.update(
                        snapshot.received_at, snapshot.apparent_import, snapshot.apparent_export,
                        snapshot.energy_import_wh, snapshot.energy_export_wh))
                except ValueError:
                    self._estimator.reset()
                    raise
            self._snapshot = self._baseline = snapshot
            self.reason = "valid"
            self.accepted += 1

    def reject(self, reason: str):
        with self._lock:
            self._snapshot = None
            self._estimator.reset()
            self.reason = reason
            self.rejected += 1

    def invalidate(self, reason: str):
        with self._lock:
            self._snapshot = None
            self._estimator.reset()
            self.reason = reason

    def fresh(self) -> Snapshot | None:
        with self._lock:
            s = self._snapshot
            if s and 0 <= self.clock() - s.received_at < self.config.stale_after:
                return s
            return None

    def age(self) -> float | None:
        with self._lock:
            return None if self._baseline is None else max(0, self.clock() - self._baseline.received_at)
