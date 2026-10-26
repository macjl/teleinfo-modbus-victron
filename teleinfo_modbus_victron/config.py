"""Flat, strictly validated YAML configuration; TIC_EM24_* overrides YAML."""
from dataclasses import dataclass, fields
import math
import os
from pathlib import Path


from .em24 import encode_serial
from .abb_b21 import encode_serial as encode_abb_serial
from .profiles import get_profile


@dataclass(frozen=True)
class Config:
    source: str = "simulated"
    device: str = ""
    host: str = "127.0.0.1"
    port: int = 1502
    serial: str = "TIC00000000001"
    meter_profile: str = "em24"
    abb_serial: int = 10000001
    stale_after: float = 5.0
    allow_estimated_power: bool = False
    power_method: str = "adaptive"
    power_window_seconds: float = 60.0
    power_window_wh: int = 10
    power_min_seconds: float = 15.0
    power_min_wh: int = 2
    power_smoothing_seconds: float = 15.0
    nominal_frequency: float = 50.0
    baudrate: int = 9600
    reconnect_max: float = 10.0
    max_voltage: float = 300.0
    max_current: float = 200.0
    max_apparent_power: float = 60000.0
    simulation_interval: float = 1.0
    simulation_power: float = 1234.5
    metrics_enabled: bool = False
    metrics_host: str = "127.0.0.1"
    metrics_port: int = 9108
    log_level: str = "INFO"

    def __post_init__(self):
        defaults = type(self)
        for f in fields(self):
            value, default = getattr(self, f.name), getattr(defaults, f.name)
            if isinstance(default, bool):
                valid = type(value) is bool
            elif isinstance(default, int):
                valid = type(value) is int
            elif isinstance(default, float):
                valid = type(value) in (int, float) and math.isfinite(value)
            else:
                valid = isinstance(value, str)
            if not valid:
                raise ValueError(f"invalid type/value for {f.name}")
        if self.source not in ("simulated", "tic"):
            raise ValueError("source must be simulated or tic")
        if self.source == "tic" and not self.device:
            raise ValueError("device is required for TIC (use /dev/serial/by-id/...)")
        if not self.allow_estimated_power:
            raise ValueError("set allow_estimated_power: true explicitly for experimental monitoring")
        if self.power_method not in ("adaptive", "apparent"):
            raise ValueError("power_method must be adaptive or apparent")
        if not 1 <= self.power_min_seconds <= self.power_window_seconds <= 3600:
            raise ValueError("require 1 <= power_min_seconds <= power_window_seconds <= 3600")
        if not 1 <= self.power_min_wh <= 100 or not 0 < self.power_smoothing_seconds <= 3600:
            raise ValueError("invalid power_min_wh or power_smoothing_seconds")
        if not self.power_min_wh <= self.power_window_wh <= 100000:
            raise ValueError("require power_min_wh <= power_window_wh <= 100000")
        encode_serial(self.serial)
        encode_abb_serial(self.abb_serial)
        get_profile(self.meter_profile)
        if not all(1 <= x <= 65535 for x in (self.port, self.metrics_port)):
            raise ValueError("ports must be 1..65535")
        if not self.host or not self.metrics_host:
            raise ValueError("listen hosts must not be empty")
        if self.baudrate != 9600:
            raise ValueError("only standard TIC at 9600 baud is supported")
        if not 45 <= self.nominal_frequency <= 65:
            raise ValueError("nominal_frequency must be 45..65 Hz (configured, not measured)")
        if any(x <= 0 for x in (self.stale_after, self.reconnect_max, self.max_voltage,
                                self.max_current, self.max_apparent_power, self.simulation_interval)):
            raise ValueError("timeouts, intervals and physical limits must be positive")
        if self.stale_after <= self.simulation_interval and self.source == "simulated":
            raise ValueError("stale_after must exceed simulation_interval")
        if abs(self.simulation_power) > self.max_apparent_power:
            raise ValueError("simulation_power exceeds max_apparent_power")
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise ValueError("invalid log_level")


def load_config(path: str | Path | None = None, environ=None) -> Config:
    import yaml  # Modbus YAML configuration is optional for the native GX runtime.

    data = {}
    if path:
        with open(path, encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("configuration must be a YAML mapping")
    names = {f.name for f in fields(Config)}
    if unknown := set(data) - names:
        raise ValueError(f"unknown configuration keys: {sorted(map(str, unknown))}")
    env = os.environ if environ is None else environ
    for key, value in env.items():
        if not key.startswith("TIC_EM24_"):
            continue
        name = key[len("TIC_EM24_"):].lower()
        if name not in names:
            raise ValueError(f"unknown environment variable: {key}")
        default = getattr(Config, name)
        data[name] = yaml.safe_load(value) if not isinstance(default, str) else value
    return Config(**data)
