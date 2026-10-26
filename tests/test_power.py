from dataclasses import replace
import math
import unittest

from teleinfo_modbus_victron.config import Config
from teleinfo_modbus_victron.model import MeasurementStore
from tests.helpers import snapshot


class Trace:
    """Independent physical truth: integrate W into quantized Wh, emit TIC VA."""

    def __init__(self, interval=1.25, **config):
        self.now = 100.0
        self.interval = interval
        self.imported = .37
        self.exported = .81
        self.config = Config(allow_estimated_power=True, source="tic", device="test", **config)
        self.store = MeasurementStore(self.config, clock=lambda: self.now)

    def sample(self, watts, va):
        self.now += self.interval
        self.imported += max(watts, 0) * self.interval / 3600
        self.exported += max(-watts, 0) * self.interval / 3600
        self.store.publish(snapshot(self.now, power=math.copysign(va, watts),
                                    imported=100000 + int(self.imported),
                                    exported=10000 + int(self.exported)))
        return self.store.fresh()

    def run(self, watts, va, seconds):
        return [self.sample(watts, va) for _ in range(math.ceil(seconds/self.interval))]


class PowerTests(unittest.TestCase):
    def test_hybrid_history_uses_first_target_but_keeps_both_minimums(self):
        for watts, va, bounds in ((300, 700, (60, 80)), (1000, 1200, (30, 42)),
                                  (3000, 3500, (15, 18)), (7000, 7500, (15, 18)),
                                  (-3000, 3500, (15, 18))):
            with self.subTest(watts=watts):
                trace = Trace()
                samples = trace.run(watts, va, 300)
                for sample in samples[-40:]:
                    estimate = sample.power_estimate
                    self.assertGreaterEqual(estimate.window_seconds, bounds[0])
                    self.assertLessEqual(estimate.window_seconds, bounds[1])
                    self.assertGreaterEqual(estimate.window_wh, 2)
                    self.assertTrue(estimate.window_seconds >= 60 or estimate.window_wh >= 10)
                    self.assertLessEqual(estimate.smoothing_seconds, 15)
                if abs(watts) >= 3000:
                    self.assertAlmostEqual(samples[-1].power_estimate.smoothing_seconds, 7.5)

    def test_minimum_time_and_minimum_energy_are_both_mandatory(self):
        fast = Trace()
        samples = fast.run(7000, 7500, 14)
        self.assertTrue(all(s.estimated_power is None for s in samples))
        first = next(s for s in fast.run(7000, 7500, 10) if s.estimated_power is not None)
        self.assertGreaterEqual(first.power_estimate.window_seconds, 15)

        slow = Trace()
        samples = slow.run(50, 200, 150)
        self.assertTrue(all(s.estimated_power is None for s in samples))
        first = next(s for s in slow.run(50, 200, 100) if s.estimated_power is not None)
        self.assertGreaterEqual(first.power_estimate.window_wh, 2)
        self.assertGreater(first.power_estimate.window_seconds, 60)

    def test_high_power_factor_change_converges_faster_than_time_only_history(self):
        settled = []
        for target_wh in (10, 100000):
            trace = Trace(power_window_wh=target_wh)
            trace.run(3000, 7000, 180)
            # Same VA, different active power: fast following of S cannot hide
            # a factor that is slow to relearn. Require 10 s continuously good.
            samples = trace.run(6000, 7000, 120)
            first = next(i for i in range(len(samples)-8)
                         if all(abs(s.estimated_power - 6000) <= 300 for s in samples[i:i+8]))
            settled.append((first + 1) * trace.interval)
        self.assertLessEqual(settled[0], 35)
        self.assertGreater(settled[1], 60)
        self.assertLess(settled[0], settled[1]/2)

    def test_custom_targets_and_uneven_frame_cadence(self):
        trace = Trace(power_window_seconds=30, power_window_wh=4, power_min_seconds=10)
        estimates = []
        for i in range(240):
            trace.interval = (.8, 1.6, 1.1, 1.4)[i % 4]
            estimates.append(trace.sample(1000, 1500))
        for sample in estimates[-30:]:
            estimate = sample.power_estimate
            self.assertGreaterEqual(estimate.window_seconds, 10)
            self.assertLess(estimate.window_seconds, 22)
            self.assertGreaterEqual(estimate.window_wh, 4)
            self.assertAlmostEqual(sample.estimated_power, 1000, delta=80)

    def test_low_power_factor_and_export_converge_at_different_frame_rates(self):
        for interval in (.5, 1.25, 2.3):
            for watts, va in ((300, 667), (400, 700), (-400, 550), (3000, 3100)):
                with self.subTest(interval=interval, watts=watts):
                    trace = Trace(interval)
                    samples = trace.run(watts, va, 180)
                    self.assertIsNone(samples[0].estimated_power)
                    last = samples[-1]
                    self.assertAlmostEqual(last.estimated_power, watts, delta=abs(watts)*.035)
                    self.assertAlmostEqual(last.power_estimate.factor, abs(watts)/va, delta=.035)
                    self.assertGreaterEqual(last.power_estimate.window_seconds, 15)
                    self.assertEqual(last.energy_import_wh, 100000 + int(trace.imported))

    def test_initial_partial_wh_is_not_a_calibration(self):
        trace = Trace()
        trace.imported = .99
        first = trace.sample(400, 700)
        self.assertIsNone(first.estimated_power)
        for result in trace.run(400, 700, 10):
            self.assertIsNone(result.estimated_power)
        self.assertIsNotNone(trace.run(400, 700, 40)[-1].estimated_power)

    def test_low_power_extends_window_to_observe_enough_energy(self):
        trace = Trace()
        last = trace.run(40, 200, 400)[-1]
        self.assertAlmostEqual(last.estimated_power, 40, delta=2)
        self.assertGreater(last.power_estimate.window_seconds, 60)

    def test_changes_in_power_factor_with_constant_va_and_load_steps(self):
        trace = Trace()
        trace.run(300, 700, 150)
        self.assertAlmostEqual(trace.run(600, 700, 150)[-1].estimated_power, 600, delta=20)
        step = trace.sample(3000, 3200)
        self.assertGreater(step.estimated_power, 2000)
        self.assertAlmostEqual(trace.run(3000, 3200, 150)[-1].estimated_power, 3000, delta=90)
        # A smaller VA reading constrains the output immediately.
        step = trace.sample(30, 50)
        self.assertLessEqual(step.estimated_power, 50)
        self.assertAlmostEqual(trace.run(30, 50, 450)[-1].estimated_power, 30, delta=3)

    def test_reversal_relearns_instead_of_reusing_import_factor(self):
        trace = Trace()
        trace.run(300, 700, 120)
        reversed_sample = trace.sample(-600, 650)
        self.assertIsNone(reversed_sample.estimated_power)
        self.assertEqual(reversed_sample.power_estimate.state, "warming_up")
        self.assertAlmostEqual(trace.run(-600, 650, 120)[-1].estimated_power, -600, delta=25)
        self.assertIsNone(trace.sample(300, 700).estimated_power)

    def test_unchanged_wh_bounds_output_instead_of_holding_power_forever(self):
        trace = Trace()
        trace.run(400, 700, 150)
        last = trace.run(0, 700, 240)[-1]
        self.assertEqual(last.power_estimate.state, "energy_limited")
        self.assertGreater(last.estimated_power, 0)
        self.assertLess(last.estimated_power, 21)
        self.assertGreater(last.power_estimate.calibration_age_seconds, 200)
        recovered = trace.run(400, 700, 180)[-1]
        self.assertAlmostEqual(recovered.estimated_power, 400, delta=20)

    def test_zero_apparent_is_immediately_zero_and_reentry_relearns(self):
        trace = Trace()
        trace.run(400, 700, 100)
        last = trace.sample(0, 0)
        self.assertEqual(last.estimated_power, 0)
        self.assertEqual(last.power_estimate.state, "zero_apparent")
        self.assertIsNone(trace.sample(400, 700).estimated_power)

    def test_gap_checksum_error_and_disconnect_each_clear_learning(self):
        for fault in ("gap", "checksum", "disconnect"):
            with self.subTest(fault=fault):
                trace = Trace()
                trace.run(400, 700, 100)
                if fault == "gap":
                    trace.now += trace.config.stale_after
                    self.assertIsNone(trace.store.fresh())
                elif fault == "checksum":
                    trace.store.reject("invalid TIC frame/checksum")
                else:
                    trace.store.invalidate("serial disconnected")
                self.assertIsNone(trace.store.fresh())
                last = trace.sample(400, 700)
                self.assertIsNone(last.estimated_power)
                self.assertAlmostEqual(trace.run(400, 700, 100)[-1].estimated_power, 400, delta=20)

    def test_gross_counter_jump_and_duplicate_timestamp_are_rejected(self):
        trace = Trace()
        trace.run(400, 700, 100)
        old = trace.store.fresh()
        trace.now += 1
        with self.assertRaisesRegex(ValueError, "energy increment"):
            trace.store.publish(replace(old, received_at=trace.now,
                                        energy_import_wh=old.energy_import_wh + 100))
        trace.store.reject("counter jump")
        self.assertIsNone(trace.sample(400, 700).estimated_power)
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            trace.store.publish(trace.store.fresh())

    def test_legacy_apparent_mode_is_explicit_and_has_no_learning(self):
        trace = Trace(power_method="apparent")
        result = trace.sample(400, 700)
        self.assertEqual(result.estimated_power, 700)
        self.assertIsNone(result.power_estimate)

    def test_bad_estimator_configuration_is_rejected(self):
        for changes in (dict(power_method="magic"), dict(power_min_wh=0),
                        dict(power_min_wh=True), dict(power_min_seconds=61),
                        dict(power_window_wh=0), dict(power_window_wh=1),
                        dict(power_window_wh=True), dict(power_window_wh=100001),
                        dict(power_window_seconds=0), dict(power_smoothing_seconds=0)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Config(allow_estimated_power=True, **changes)
