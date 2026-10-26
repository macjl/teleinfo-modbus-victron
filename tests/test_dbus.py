from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import MappingProxyType
import unittest

from teleinfo_modbus_victron.config import Config
from teleinfo_modbus_victron.dbus_app import SourceWorker
from teleinfo_modbus_victron.dbus_model import DBusConfig, EXTRA_FIELDS, NATIVE_PATHS, PowerFallback, load_dbus_config, render
from teleinfo_modbus_victron.model import MeasurementStore, normalize
from teleinfo_modbus_victron.tic import Group, parse_frame
from tests.helpers import frame, snapshot
from tests.test_power import Trace


class DBusModelTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.config = Config(allow_estimated_power=True)
        self.store = MeasurementStore(self.config, clock=lambda: self.now)

    def test_exact_wh_native_aliases_and_unmeasured_values(self):
        self.store.publish(snapshot(self.now, power=-500, exported=123401))
        values = render(self.store)
        self.assertEqual(values['/Ac/Power'], -500)
        self.assertEqual(values['/Ac/L1/Power'], -500)
        self.assertEqual(values['/Ac/Energy/Reverse'], 123.401)
        self.assertEqual(values['/Ac/L1/Energy/Reverse'], 123.401)
        self.assertEqual(values['/Ac/Energy/Forward'], values['/Ac/L1/Energy/Forward'])
        for path in ('/Ac/Frequency', '/Ac/PowerFactor', '/Ac/L1/PowerFactor'):
            self.assertIsNone(values[path])
        self.now += 1
        self.store.publish(snapshot(self.now, power=-500, exported=123402))
        self.assertAlmostEqual(render(self.store)['/Ac/Energy/Reverse'] - values['/Ac/Energy/Reverse'], .001)

    def test_tariff_units_status_bits_historical_timestamps_and_privacy(self):
        groups = parse_frame(frame(PREF='09', PCOUP='12', NGTF='TEST CONTRACT   ', LTARF='HC TEST   ',
                                  NTARF='02', EASF01='000012345', EASF02='000023456',
                                  STGE='000000C0', RELAIS='001')[1:-1])
        groups['CCASN'] = Group('00123', 'H261026100000')
        groups['ADSC'] = Group('PRIVATE')
        groups['PRM'] = Group('PRIVATE')
        self.store.publish(normalize(groups, self.config, self.now))
        values = render(self.store)
        self.assertEqual(values['/Tic/Contract/ReferencePowerVA'], 9000)
        self.assertEqual(values['/Tic/Contract/CutoffPowerVA'], 12000)
        self.assertEqual(values['/Tic/Contract/CurrentTariff'], 'HC TEST')
        self.assertEqual(values['/Tic/Contract/TariffIndex'], 2)
        self.assertEqual(values['/Tic/Energy/Supplier01Wh'], 12345)
        self.assertEqual(values['/Tic/Status/OverReferencePower'], 1)
        self.assertEqual(values['/Tic/Status/Overvoltage'], 1)
        self.assertEqual(values['/Tic/Status/DryContactClosed'], 1)
        self.assertEqual(values['/Tic/History/ImportPointW'], 123)
        self.assertEqual(values['/Tic/History/ImportPointW/Timestamp'], 'H261026100000')
        raw = json.loads(values['/Tic/Raw'])
        self.assertNotIn('ADSC', raw)
        self.assertNotIn('PRM', raw)
        self.assertEqual(raw['CCASN']['timestamp'], 'H261026100000')
        self.assertNotEqual(values['/Ac/Power'], 123)  # Historical point never used as instantaneous W.

    def test_absent_or_malformed_extras_do_not_reuse_old_values(self):
        first = replace(snapshot(self.now), extras=MappingProxyType({'PREF': Group('09'), 'STGE': Group('00000001')}))
        self.store.publish(first)
        self.assertEqual(render(self.store)['/Tic/Status/DryContactClosed'], 0)
        self.now += 1
        self.store.publish(replace(snapshot(self.now), extras=MappingProxyType({'PREF': Group('invalid')})))
        values = render(self.store)
        for path in EXTRA_FIELDS:
            self.assertIsNone(values[path])
        self.assertIsNone(values['/Tic/Status/DryContactClosed'])
        self.assertIsNone(values['/Tic/Contract/ReferencePowerVA/Timestamp'])

    def test_expiration_and_rejection_clear_native_and_custom_measurements(self):
        self.store.publish(replace(snapshot(self.now), extras=MappingProxyType({'PREF': Group('09')})))
        valid = render(self.store)
        self.now += self.config.stale_after
        expired = render(self.store)
        self.assertEqual(expired['/Connected'], 0)
        self.assertEqual(expired['/Tic/Status/PowerValid'], 0)
        for path in NATIVE_PATHS:
            self.assertIsNone(expired[path])
        self.assertIsNone(expired['/Tic/Raw'])
        self.assertIsNone(expired['/Tic/Contract/ReferencePowerVA'])
        self.assertEqual(expired['/Tic/Status/SourceAgeSeconds'], 5)
        self.store.publish(snapshot(self.now))
        self.assertEqual(render(self.store)['/Connected'], 1)
        self.store.reject('bad checksum')
        self.assertEqual(render(self.store)['/Tic/Status/Reason'], 'bad checksum')
        self.assertIsNone(render(self.store)['/Ac/L1/Voltage'])
        self.assertIsNotNone(valid['/Ac/L1/Voltage'])

    def test_warmup_keeps_fresh_energies_without_inventing_watts(self):
        cfg = Config(source='tic', device='test', allow_estimated_power=True)
        store = MeasurementStore(cfg, clock=lambda: self.now)
        store.publish(snapshot(self.now))
        values = render(store)
        self.assertEqual(values['/Connected'], 1)
        self.assertEqual(values['/Tic/Status/SourceValid'], 1)
        self.assertEqual(values['/Tic/Status/PowerValid'], 0)
        self.assertIsNone(values['/Ac/Power'])
        self.assertIsNotNone(values['/Ac/Energy/Forward'])

    def test_reversals_publish_unity_then_cached_factors_per_direction(self):
        trace = Trace()
        fallback = PowerFallback()

        def sample(watts, va):
            snapshot = trace.sample(watts, va)
            values = render(trace.store, fallback)
            self.assertEqual(values['/Tic/Status/PowerValid'], 1)
            self.assertEqual(values['/Ac/Power'], values['/Ac/L1/Power'])
            self.assertEqual(values['/Ac/Energy/Forward'], snapshot.energy_import_wh / 1000)
            self.assertEqual(values['/Ac/Energy/Reverse'], snapshot.energy_export_wh / 1000)
            self.assertIsNone(values['/Ac/PowerFactor'])
            self.assertIsNone(values['/Ac/L1/PowerFactor'])
            return values

        initial = sample(300, 700)
        self.assertEqual(initial['/Ac/Power'], 700)
        self.assertEqual(initial['/Tic/Estimator/Factor'], 1)
        self.assertEqual(initial['/Tic/Status/State'], 'warming_up_unity')
        self.assertEqual(initial['/Tic/Status/PowerProvisional'], 1)
        self.assertEqual(initial['/Tic/Status/PowerCalibrated'], 0)
        self.assertIsNone(trace.store.fresh().estimated_power)  # Estimator/Modbus stay independent.
        for _ in range(96):
            learned_import = sample(300, 700)
        self.assertAlmostEqual(learned_import['/Ac/Power'], 300, delta=20)
        self.assertEqual(learned_import['/Tic/Status/PowerProvisional'], 0)
        self.assertEqual(learned_import['/Tic/Status/PowerCalibrated'], 1)
        first_export = sample(-400, 550)
        self.assertEqual(first_export['/Ac/Power'], -550)  # Never borrow import's factor.
        self.assertEqual(first_export['/Tic/Estimator/FactorSource'], 'unity')
        for _ in range(96):
            learned_export = sample(-400, 550)
        self.assertAlmostEqual(learned_export['/Ac/Power'], -400, delta=20)
        next_import = sample(300, 700)
        self.assertEqual(next_import['/Tic/Status/State'], 'warming_up_cached')
        self.assertEqual(next_import['/Tic/Estimator/FactorSource'], 'cached')
        self.assertAlmostEqual(next_import['/Ac/Power'], learned_import['/Ac/Power'], delta=1)
        next_export = sample(-400, 550)
        self.assertAlmostEqual(next_export['/Ac/Power'], learned_export['/Ac/Power'], delta=1)
        self.assertEqual(next_export['/Tic/Status/PowerProvisional'], 1)

    def test_fallback_never_publishes_without_a_fresh_valid_tic_frame(self):
        for fault in ('expiry', 'checksum', 'disconnect'):
            with self.subTest(fault=fault):
                trace, fallback = Trace(), PowerFallback()
                for _ in range(96):
                    trace.sample(300, 700)
                    render(trace.store, fallback)
                if fault == 'expiry':
                    trace.now += trace.config.stale_after
                elif fault == 'checksum':
                    trace.store.reject('invalid TIC frame/checksum')
                else:
                    trace.store.invalidate('serial disconnected')
                invalid = render(trace.store, fallback)
                for path in NATIVE_PATHS:
                    self.assertIsNone(invalid[path])
                self.assertEqual(invalid['/Connected'], 0)
                self.assertEqual(invalid['/Tic/Status/PowerValid'], 0)
                self.assertEqual(invalid['/Tic/Status/PowerProvisional'], 0)
                self.assertIsNone(invalid['/Tic/Estimator/Factor'])
                trace.sample(300, 700)
                fresh = render(trace.store, fallback)
                self.assertEqual(fresh['/Connected'], 1)
                self.assertEqual(fresh['/Tic/Status/PowerProvisional'], 1)
                self.assertEqual(fresh['/Tic/Estimator/FactorSource'], 'cached')

    def test_fallback_can_be_disabled_and_zero_needs_no_provisional_factor(self):
        trace, fallback = Trace(), PowerFallback(enabled=False)
        trace.sample(300, 700)
        self.assertIsNone(render(trace.store, fallback)['/Ac/Power'])
        trace.sample(0, 0)
        zero = render(trace.store, PowerFallback())
        self.assertEqual(zero['/Ac/Power'], 0)
        self.assertEqual(zero['/Tic/Status/PowerProvisional'], 0)
        self.assertEqual(zero['/Tic/Status/PowerValid'], 1)

    def test_energy_limited_bound_does_not_replace_a_learned_coefficient(self):
        trace, fallback = Trace(), PowerFallback()
        for _ in range(120):
            trace.sample(400, 700)
            render(trace.store, fallback)
        learned = fallback.learned_factors[1]
        for _ in range(192):
            trace.sample(0, 700)
            render(trace.store, fallback)
        self.assertEqual(trace.store.fresh().power_estimate.state, 'energy_limited')
        self.assertEqual(fallback.learned_factors[1], learned)
        trace.sample(-400, 550)
        render(trace.store, fallback)
        trace.sample(400, 700)
        self.assertAlmostEqual(render(trace.store, fallback)['/Ac/Power'], learned * 700)


class DBusConfigurationTests(unittest.TestCase):
    def test_json_and_strict_separation_from_modbus_configuration(self):
        cfg = load_dbus_config('config.dbus.example.json')
        self.assertEqual(cfg.service_name, 'com.victronenergy.grid.linky_tic')
        self.assertEqual(cfg.source_config().power_min_wh, 2)
        self.assertEqual(cfg.source_config().power_min_seconds, 15)
        self.assertTrue(cfg.warmup_fallback)
        for changes in ({'identity': 'bad/name'}, {'instance': True}, {'instance': 1000},
                        {'device': 'ttyUSB0'}, {'claim_serial': 'true'}, {'warmup_fallback': 'true'},
                        {'measurement': {'port': 502}}, {'measurement': {'stale_after': 0}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                DBusConfig(**({'device': '/dev/test'} | changes))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text('{"device":"/dev/test","unknown":true}')
            with self.assertRaises(ValueError):
                load_dbus_config(path)
        subprocess.run([sys.executable, '-c',
                        'import sys; from teleinfo_modbus_victron.dbus_model import DBusConfig; '
                        'DBusConfig(device="/dev/test"); '
                        'assert not any(x in sys.modules for x in ("yaml", "pymodbus", "dbus", "gi"))'], check=True)

    def test_installer_boot_hook_is_idempotent_and_preserves_other_commands(self):
        spec = importlib.util.spec_from_file_location('install_gx', 'tools/install_gx.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = '#!/bin/sh\necho existing-startup\nexit 0\n'
        hooked = module.boot_hook(original)
        self.assertEqual(hooked, module.boot_hook(hooked))
        self.assertIn('echo existing-startup\nexit 0', hooked)
        self.assertLess(hooked.index('/data/dbus-linky-tic/boot.sh'), hooked.index('exit 0'))
        rule = module.adapter_rule({'ID_VENDOR_ID': '0403', 'ID_MODEL_ID': '6015', 'ID_SERIAL_SHORT': 'SYNTHETIC'})
        self.assertIn('ENV{ID_SERIAL_SHORT}=="SYNTHETIC"', rule)
        self.assertIn('ENV{VE_SERVICE}="ignore"', rule)
        with self.assertRaises(ValueError):
            module.adapter_rule({'ID_VENDOR_ID': '0403', 'ID_MODEL_ID': '6015'})

    def test_reader_failure_invalidates_instead_of_leaving_a_live_stale_service(self):
        store = MeasurementStore(Config(allow_estimated_power=True))
        def failed_opener(cfg):
            raise RuntimeError('unexpected reader failure')
        worker = SourceWorker(store.config, store, failed_opener)
        worker.start()
        deadline = time.monotonic() + 2
        while worker.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        worker.stop()
        self.assertIsInstance(worker.failure, RuntimeError)
        self.assertIsNone(store.fresh())
        self.assertEqual(store.reason, 'reader failed')
