from dataclasses import replace
import tempfile
from pathlib import Path
import unittest

from teleinfo_modbus_victron.config import Config, load_config
from teleinfo_modbus_victron.model import MeasurementStore, normalize
from teleinfo_modbus_victron.tic import TICParser, parse_frame
from tests.helpers import frame, group, snapshot


class ParserTests(unittest.TestCase):
    def test_stream_fragmentation_noise_and_multiple_frames(self):
        parser = TICParser()
        events = []
        for byte in b"noise" + frame() + frame():
            events += parser.feed(bytes([byte]))
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["SINSTS"].value, "00936")
        self.assertEqual(parser.invalid_frames, 0)

    def test_timestamp_and_empty_date(self):
        parsed = parse_frame(group("DATE", "", "H261026010000") + group("CCASN", "00123", "H261026000000"))
        self.assertEqual(parsed["DATE"].timestamp, "H261026010000")
        self.assertEqual(parsed["CCASN"].value, "00123")

    def test_checksum_includes_last_tab(self):
        body = b"VTIC\t02\t"
        correct = group("VTIC", "02")
        wrong = correct[:-2] + bytes([(sum(body[:-1]) & 63) + 32]) + b"\r"
        with self.assertRaises(ValueError):
            parse_frame(wrong)

    def test_corrupt_group_rejects_whole_frame_and_preserves_event_order(self):
        bad = frame().replace(b"00936", b"00937")
        parser = TICParser()
        events = parser.feed(frame() + bad)
        self.assertIsNotNone(events[0])
        self.assertIsNone(events[1])
        self.assertEqual((parser.valid_frames, parser.invalid_frames), (1, 1))
        self.assertIsNotNone(parser.feed(frame())[0])

    def test_abort_oversize_restart_and_duplicates(self):
        parser = TICParser(max_frame_size=200)
        self.assertEqual(parser.feed(b"\x02partial\x04"), [None])
        self.assertEqual(parser.feed(b"\x02" + b"x"*201), [None])
        self.assertEqual(parser.feed(b"\x02partial" + frame()), [None, parse_frame(frame()[1:-1])])
        with self.assertRaises(ValueError):
            parse_frame(group("VTIC", "02") * 2)


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.config = Config(allow_estimated_power=True)
        self.now = 100.0
        self.store = MeasurementStore(self.config, clock=lambda: self.now)

    def test_expiration_exact_boundary_and_recovery(self):
        self.assertIsNone(self.store.fresh())
        self.store.publish(snapshot(self.now))
        self.now += 4.999
        self.assertIsNotNone(self.store.fresh())
        self.now += .0011
        self.assertIsNone(self.store.fresh())
        self.store.publish(snapshot(self.now))
        self.assertIsNotNone(self.store.fresh())

    def test_normalize_fields_and_remove_identifiers(self):
        data = parse_frame(frame(ADSC="123456789012", PRM="12345678901234")[1:-1])
        measured = normalize(data, self.config, self.now)
        self.assertEqual(measured.estimated_power, 936)
        self.assertEqual(measured.energy_import_wh, 39688557)
        self.assertNotIn("ADSC", measured.extras)
        with self.assertRaises(TypeError):
            measured.extras["x"] = 1

    def test_missing_injection_not_zero_and_limits(self):
        fields = parse_frame(frame()[1:-1])
        del fields["SINSTI"]
        with self.assertRaises(ValueError):
            normalize(fields, self.config)
        for changes in (dict(SINSTI="00001"), dict(URMS1="999"), dict(IRMS1="999"),
                        dict(EAST="-1"), dict(SINSTS="99999"), dict(VTIC="01"),
                        dict(IRMS1="000", SINSTS="00936")):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize(parse_frame(frame(**changes)[1:-1]), self.config)

    def test_counter_decrease_reject_and_recovery(self):
        self.store.publish(snapshot(self.now))
        with self.assertRaises(ValueError):
            self.store.publish(snapshot(self.now, imported=1))
        self.store.reject("bad frame")
        self.assertIsNone(self.store.fresh())
        self.store.publish(snapshot(self.now, imported=12345679))
        self.assertIsNotNone(self.store.fresh())

    def test_nonfinite_and_time_rejected(self):
        for s in (snapshot(self.now+1), replace(snapshot(self.now), voltage=float("nan")),
                  replace(snapshot(self.now), energy_import_wh=True)):
            with self.subTest(s=s), self.assertRaises(ValueError):
                self.store.publish(s)


class ConfigTests(unittest.TestCase):
    def test_explicit_estimate_acknowledgment(self):
        with self.assertRaises(ValueError):
            Config()

    def test_yaml_env_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("allow_estimated_power: true\nport: 1502\nserial: '001234'\n")
            cfg = load_config(path, {"TIC_EM24_PORT": "1503", "TIC_EM24_POWER_WINDOW_WH": "20"})
            self.assertEqual(cfg.port, 1503)
            self.assertEqual(cfg.serial, "001234")
            self.assertEqual(cfg.power_window_wh, 20)

    def test_invalid_config_fails_early(self):
        for changes in (dict(device="", source="tic"), dict(port=True), dict(stale_after=float("inf")),
                        dict(metrics_enabled="false"), dict(baudrate=1200), dict(nominal_frequency=0)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Config(allow_estimated_power=True, **changes)
        with self.assertRaises(ValueError):
            load_config(environ={"TIC_EM24_UNKNOWN": "x"})
