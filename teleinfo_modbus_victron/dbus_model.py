"""Native grid paths and custom TIC data. No D-Bus, YAML or Modbus dependency."""
from dataclasses import dataclass, field, fields
import json
from pathlib import Path
import re

from .config import Config

VERSION = "0.4.0a1"


@dataclass(frozen=True)
class DBusConfig:
    device: str
    instance: int = 43
    identity: str = "linky_tic"
    serial: str = "LINKYTIC000001"  # Synthetic, never the Linky ADSC/PRM.
    custom_name: str = "Linky TIC — estimation"
    claim_serial: bool = True
    velib_path: str = ""  # Empty: locate the firmware-provided library.
    measurement: dict = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.device, str) or not self.device.startswith('/dev/') or '\n' in self.device:
            raise ValueError('device must be an explicitly observed /dev/ path')
        if type(self.instance) is not int or not 0 <= self.instance <= 999:
            raise ValueError('instance must be 0..999')
        if not isinstance(self.identity, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,47}', self.identity):
            raise ValueError('identity must be a stable D-Bus identifier')
        if not isinstance(self.serial, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', self.serial):
            raise ValueError('serial must be a synthetic identifier of at most 48 characters')
        if not isinstance(self.custom_name, str) or not 1 <= len(self.custom_name) <= 80:
            raise ValueError('invalid custom_name')
        if type(self.claim_serial) is not bool or not isinstance(self.velib_path, str):
            raise ValueError('invalid claim_serial or velib_path')
        if not isinstance(self.measurement, dict):
            raise ValueError('measurement must be an object')
        allowed = {'stale_after', 'reconnect_max', 'max_voltage', 'max_current',
                   'max_apparent_power', 'power_method', 'power_window_seconds',
                   'power_window_wh', 'power_min_seconds', 'power_min_wh',
                   'power_smoothing_seconds'}
        if unknown := set(self.measurement) - allowed:
            raise ValueError(f'unknown measurement options: {sorted(unknown)}')
        self.source_config()  # Reuse the existing validation and estimator settings.

    @property
    def service_name(self):
        return 'com.victronenergy.grid.' + self.identity

    def source_config(self):
        return Config(source='tic', device=self.device, allow_estimated_power=True,
                      meter_profile='abb_b21', **self.measurement)


def load_dbus_config(path):
    with Path(path).open(encoding='utf-8') as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError('D-Bus configuration must be an object')
    if unknown := set(data) - {f.name for f in fields(DBusConfig)}:
        raise ValueError(f'unknown D-Bus options: {sorted(unknown)}')
    return DBusConfig(**data)


# Extra paths are our API, not standard GX display fields. Values absent from a
# current frame are None, even if they were present in a previous frame.
EXTRA_FIELDS = {
    '/Tic/Contract/Name': ('NGTF', 'text', 1),
    '/Tic/Contract/CurrentTariff': ('LTARF', 'text', 1),
    '/Tic/Contract/TariffIndex': ('NTARF', 'int', 1),
    '/Tic/Contract/ReferencePowerVA': ('PREF', 'int', 1000),
    '/Tic/Contract/CutoffPowerVA': ('PCOUP', 'int', 1000),
    '/Tic/Contract/CurrentDayProfile': ('NJOURF', 'int', 1),
    '/Tic/Contract/NextDayProfile': ('NJOURF+1', 'int', 1),
    '/Tic/Contract/NextDaySchedule': ('PJOURF+1', 'text', 1),
    '/Tic/Contract/NextPeakSchedule': ('PPOINTE', 'text', 1),
    '/Tic/Status/Register': ('STGE', 'hex', 1),
    '/Tic/Status/Relays': ('RELAIS', 'int', 1),
    '/Tic/Voltage/AverageL1V': ('UMOY1', 'int', 1),
    '/Tic/Power/MaxImportVA': ('SMAXSN', 'int', 1),
    '/Tic/Power/PreviousMaxImportVA': ('SMAXSN-1', 'int', 1),
    '/Tic/Power/MaxExportVA': ('SMAXIN', 'int', 1),
    '/Tic/Power/PreviousMaxExportVA': ('SMAXIN-1', 'int', 1),
    '/Tic/History/ImportPointW': ('CCASN', 'int', 1),
    '/Tic/History/PreviousImportPointW': ('CCASN-1', 'int', 1),
    '/Tic/History/ExportPointW': ('CCAIN', 'int', 1),
    '/Tic/History/PreviousExportPointW': ('CCAIN-1', 'int', 1),
    '/Tic/Message/Short': ('MSG1', 'text', 1),
    '/Tic/Message/Brief': ('MSG2', 'text', 1),
}
EXTRA_FIELDS.update({f'/Tic/Energy/Supplier{i:02d}Wh': (f'EASF{i:02d}', 'int', 1)
                     for i in range(1, 11)})
EXTRA_FIELDS.update({f'/Tic/Energy/Distributor{i:02d}Wh': (f'EASD{i:02d}', 'int', 1)
                     for i in range(1, 5)})
EXTRA_FIELDS.update({f'/Tic/Energy/ReactiveQ{i}Varh': (f'ERQ{i}', 'int', 1)
                     for i in range(1, 5)})
NATIVE_PATHS = ('/Ac/Power', '/Ac/L1/Power', '/Ac/L1/Voltage', '/Ac/L1/Current',
                '/Ac/Energy/Forward', '/Ac/L1/Energy/Forward',
                '/Ac/Energy/Reverse', '/Ac/L1/Energy/Reverse',
                '/Ac/Frequency', '/Ac/PowerFactor', '/Ac/L1/PowerFactor')
CUSTOM_MEASUREMENTS = ('/Tic/Power/ApparentImportVA', '/Tic/Power/ApparentExportVA',
                       '/Tic/Status/OverReferencePower', '/Tic/Status/Overvoltage',
                       '/Tic/Status/DryContactClosed', '/Tic/Raw',
                       '/Tic/Estimator/Factor', '/Tic/Estimator/EnergyMeanW',
                       '/Tic/Estimator/WindowSeconds', '/Tic/Estimator/WindowWh',
                       '/Tic/Estimator/SmoothingSeconds', '/Tic/Estimator/CalibrationAgeSeconds')


def _extra(group, kind, scale):
    if group is None:
        return None
    value = group.value.strip()
    if kind == 'text':
        return value
    if kind == 'hex':
        return int(value, 16) if re.fullmatch('[0-9A-Fa-f]{8}', value) else None
    return int(value) * scale if value.isascii() and value.isdecimal() else None


def render(store):
    """One immutable, fresh snapshot per update; no cached physical values."""
    snapshot = store.fresh()
    result = {path: None for path in (*NATIVE_PATHS, *CUSTOM_MEASUREMENTS, *EXTRA_FIELDS)}
    result.update({path + '/Timestamp': None for path in EXTRA_FIELDS})
    result.update({'/Connected': int(snapshot is not None),
                   '/Tic/Status/SourceValid': int(snapshot is not None),
                   '/Tic/Status/PowerValid': int(snapshot is not None and snapshot.estimated_power is not None),
                   '/Tic/Status/SourceAgeSeconds': store.age(),
                   '/Tic/Status/ReceivedUtc': None,
                   '/Tic/Status/State': 'unavailable',
                   '/Tic/Status/Reason': store.reason if snapshot else ('expired' if store.reason == 'valid' else store.reason)})
    if snapshot is None:
        return result
    power = snapshot.estimated_power
    result.update({'/Ac/Power': power, '/Ac/L1/Power': power,
                   '/Ac/L1/Voltage': float(snapshot.voltage), '/Ac/L1/Current': float(snapshot.current),
                   '/Ac/Energy/Forward': snapshot.energy_import_wh / 1000,
                   '/Ac/L1/Energy/Forward': snapshot.energy_import_wh / 1000,
                   '/Ac/Energy/Reverse': snapshot.energy_export_wh / 1000,
                   '/Ac/L1/Energy/Reverse': snapshot.energy_export_wh / 1000,
                   '/Tic/Power/ApparentImportVA': snapshot.apparent_import,
                   '/Tic/Power/ApparentExportVA': snapshot.apparent_export,
                   '/Tic/Status/ReceivedUtc': snapshot.received_utc,
                   '/Tic/Raw': json.dumps({k: {'value': v.value, 'timestamp': v.timestamp}
                                          for k, v in snapshot.extras.items()
                                          if k not in ('ADSC', 'PRM')}, ensure_ascii=True, separators=(',', ':'))})
    for path, (label, kind, scale) in EXTRA_FIELDS.items():
        group = snapshot.extras.get(label)
        result[path] = _extra(group, kind, scale)
        result[path + '/Timestamp'] = group.timestamp if group and result[path] is not None else None
    status = result['/Tic/Status/Register']
    if status is not None:
        result['/Tic/Status/OverReferencePower'] = int(bool(status & (1 << 7)))
        result['/Tic/Status/Overvoltage'] = int(bool(status & (1 << 6)))
        result['/Tic/Status/DryContactClosed'] = int(not status & 1)
    estimate = snapshot.power_estimate
    result['/Tic/Status/State'] = estimate.state if estimate else 'apparent'
    if estimate:
        result.update({'/Tic/Estimator/Factor': estimate.factor,
                       '/Tic/Estimator/EnergyMeanW': estimate.energy_mean_watts,
                       '/Tic/Estimator/WindowSeconds': estimate.window_seconds,
                       '/Tic/Estimator/WindowWh': estimate.window_wh,
                       '/Tic/Estimator/SmoothingSeconds': estimate.smoothing_seconds,
                       '/Tic/Estimator/CalibrationAgeSeconds': estimate.calibration_age_seconds})
    return result
