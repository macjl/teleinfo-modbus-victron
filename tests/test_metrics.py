import unittest

from teleinfo_modbus_victron.config import Config
from teleinfo_modbus_victron.model import MeasurementStore
from tests.helpers import snapshot
from tests.test_power import Trace

try:
    from teleinfo_modbus_victron.metrics import Collector
except ImportError:
    Collector = None


@unittest.skipIf(Collector is None, "optional metrics extra is not installed")
class MetricsTests(unittest.TestCase):
    def test_estimator_warmup_quality_and_expiration(self):
        trace = Trace()
        trace.sample(400, 700)
        collector = Collector(trace.store)
        metrics = {m.name: m for m in collector.collect()}
        self.assertEqual(metrics["tic_em24_source_valid"].samples[0].value, 1)
        self.assertEqual(metrics["tic_em24_power_estimate_valid"].samples[0].value, 0)
        self.assertNotIn("tic_em24_power_estimate_watts", metrics)
        self.assertIn("tic_em24_energy_import_wh", metrics)
        self.assertEqual(metrics["tic_em24_power_estimate_state"].samples[0].labels, {"state": "warming_up"})
        last = trace.run(400, 700, 150)[-1]
        metrics = {m.name: m for m in collector.collect()}
        self.assertEqual(metrics["tic_em24_power_estimate_valid"].samples[0].value, 1)
        self.assertEqual(metrics["tic_em24_power_estimate_watts"].samples[0].value, last.estimated_power)
        self.assertIn("tic_em24_power_calibration_age_seconds", metrics)
        self.assertEqual(metrics["tic_em24_power_window_wh"].samples[0].value, last.power_estimate.window_wh)
        self.assertEqual(metrics["tic_em24_power_smoothing_seconds"].samples[0].value,
                         last.power_estimate.smoothing_seconds)
        self.assertAlmostEqual(metrics["tic_em24_power_factor_estimate"].samples[0].value, 400/700, delta=.03)
        trace.now += 5
        metrics = {m.name: m for m in collector.collect()}
        self.assertEqual(metrics["tic_em24_power_estimate_valid"].samples[0].value, 0)
        for name in ("power_estimate_watts", "power_factor_estimate", "power_energy_mean_watts",
                     "power_calibration_age_seconds", "power_estimate_state",
                     "power_window_wh", "power_smoothing_seconds"):
            self.assertNotIn(f"tic_em24_{name}", metrics)

    def test_expired_measurements_are_omitted(self):
        now = [100.0]
        store = MeasurementStore(Config(allow_estimated_power=True), clock=lambda: now[0])
        store.publish(snapshot(now[0]))
        collector = Collector(store)
        metrics = {m.name: m for m in collector.collect()}
        self.assertIn("tic_em24_power_estimate_watts", metrics)
        now[0] += 5
        metrics = {m.name: m for m in collector.collect()}
        self.assertNotIn("tic_em24_power_estimate_watts", metrics)
        self.assertEqual(metrics["tic_em24_source_valid"].samples[0].value, 0)
