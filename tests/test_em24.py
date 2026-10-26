import struct
import unittest
from decimal import Decimal

from teleinfo_modbus_victron.em24 import (
    BY_NAME, REGISTERS, encode_number, encode_serial, encode_version, energy_wh_to_raw,
)


class WireContractTests(unittest.TestCase):
    def test_golden_vectors(self):
        for name, value, expected in (
            ("model", 1648, (0x0670,)),
            ("phase_config", 3, (3,)),
            ("application", 7, (7,)),
            ("voltage_l1", 230.1, (2301, 0)),
            ("current_l1", 12.345, (12345, 0)),
            ("power_l1", -1234.5, (0xCFC7, 0xFFFF)),
            ("power_total", 1234.5, (12345, 0)),
            ("frequency", 50, (500,)),
            ("energy_import", 12345.6, (0xE240, 1)),
            ("energy_export", 6543.2, (65432, 0)),
            ("energy_import_l1", 12345.6, (0xE240, 1)),
            ("switch_position", 3, (3,)),
        ):
            with self.subTest(name=name):
                self.assertEqual(encode_number(value, BY_NAME[name]), expected)

    def test_word_and_wire_byte_order(self):
        words = encode_number(Decimal("-1234.5"), BY_NAME["power_total"])
        self.assertEqual(struct.pack(">2H", *words), bytes.fromhex("cfc7ffff"))

    def test_signed_boundaries_and_truncation(self):
        spec = BY_NAME["power_total"]
        for raw in (-(2**31), -65536, -1, 0, 1, 65536, 2**31 - 1):
            with self.subTest(raw=raw):
                words = encode_number(Decimal(raw) / 10, spec)
                self.assertEqual(struct.unpack("<i", struct.pack("<2H", *words))[0], raw)
        self.assertEqual(encode_number(-0.19, spec), (65535, 65535))

    def test_reject_nonfinite_and_overflow(self):
        for value in (float("nan"), float("inf"), float("-inf"), 214748364.8, -214748364.9):
            with self.subTest(value=value), self.assertRaises(ValueError):
                encode_number(value, BY_NAME["power_total"])
        for value in (-1, 65536):
            with self.subTest(value=value), self.assertRaises(ValueError):
                encode_number(value, BY_NAME["model"])

    def test_energy_units_and_quantization(self):
        for wh, expected in ((0, (0, 0)), (99, (0, 0)), (100, (1, 0)),
                             (12345678, (0xE240, 1)), (214748364799, (65535, 32767))):
            with self.subTest(wh=wh):
                self.assertEqual(energy_wh_to_raw(wh), expected)
        for wh in (-1, 1.1, True, 214748364800):
            with self.subTest(wh=wh), self.assertRaises(ValueError):
                energy_wh_to_raw(wh)

    def test_serial_ascii_and_padding(self):
        self.assertEqual(encode_serial("TIC00000000001"),
                         (0x5449, 0x4330, 0x3030, 0x3030, 0x3030, 0x3030, 0x3031))
        self.assertEqual(encode_serial("A1"), (0x4131, 0, 0, 0, 0, 0, 0))
        for serial in ("", "x" * 15, "été", "a/b", "a\0", "a b"):
            with self.subTest(serial=serial), self.assertRaises(ValueError):
                encode_serial(serial)

    def test_versions(self):
        self.assertEqual(encode_version(1, 2, 34), (0x1222,))
        for version in ((16, 0, 0), (0, 16, 0), (0, 0, 256), (-1, 0, 0), (1.0, 0, 0)):
            with self.subTest(version=version), self.assertRaises(ValueError):
                encode_version(*version)

    def test_contract_has_no_overlap(self):
        self.assertEqual(len(REGISTERS), 15)
        addresses = [r.address + i for r in REGISTERS for i in range(r.count)]
        self.assertEqual(len(addresses), len(set(addresses)))


if __name__ == "__main__":
    unittest.main()
