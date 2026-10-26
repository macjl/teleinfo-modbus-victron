import asyncio
from decimal import Decimal
import socket
import struct
import unittest

from teleinfo_modbus_victron import abb_b21 as abb
from teleinfo_modbus_victron.config import Config, load_config
from teleinfo_modbus_victron.model import MeasurementStore
from teleinfo_modbus_victron.probe import probe
from teleinfo_modbus_victron.registers import encode_number
from teleinfo_modbus_victron.server import ABBServer, create_server
from tests.helpers import TCPWireMixin, snapshot
from tests.test_power import Trace


class ABBWireTests(unittest.TestCase):
    def test_golden_vectors_and_big_word_order(self):
        for name, value, words in (
            ("model", 0x42323120, (0x4232, 0x3120)),
            ("serial", 10000001, (0x0098, 0x9681)),
            ("voltage_l1", 230.1, (0, 2301)),
            ("current_l1", 12.34, (0, 1234)),
            ("power_total", -1234.56, (0xfffe, 0x1dc0)),
            ("frequency", 50, (5000,)),
            ("energy_import", Decimal("12345.67"), (0, 0, 0x12, 0xd687)),
        ):
            with self.subTest(name=name):
                self.assertEqual(encode_number(value, abb.BY_NAME[name]), words)
        self.assertEqual(struct.pack(">2H", *encode_number(-1234.56, abb.BY_NAME["power_total"])),
                         bytes.fromhex("fffe1dc0"))

    def test_exact_energy_quantization_and_uint64_boundaries(self):
        for wh in (0, 9, 10, 12345678, 655360, 42949672960, (2**64-1)*10-1):
            with self.subTest(wh=wh):
                raw = struct.unpack(">Q", struct.pack(">4H", *abb.energy_wh_to_raw(wh)))[0]
                self.assertEqual(raw, wh//10)
                self.assertLessEqual(raw*10, wh)
                self.assertLess(wh - raw*10, 10)
        for value in (-1, True, 1.1, (2**64-1)*10):
            with self.subTest(value=value), self.assertRaises(ValueError):
                abb.energy_wh_to_raw(value)

    def test_numeric_serial_and_profile_configuration(self):
        for value in (1, 10000001, 2147483647):
            cfg = Config(allow_estimated_power=True, meter_profile="abb_b21", abb_serial=value)
            self.assertEqual(struct.unpack(">i", struct.pack(">2H", *abb.encode_serial(cfg.abb_serial)))[0], value)
        for kwargs in (dict(meter_profile="b23"), dict(abb_serial=0), dict(abb_serial=True),
                       dict(abb_serial="10000001"), dict(abb_serial=2147483648)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Config(allow_estimated_power=True, **kwargs)
        cfg = load_config(environ={"TIC_EM24_ALLOW_ESTIMATED_POWER": "true",
                                   "TIC_EM24_METER_PROFILE": "abb_b21", "TIC_EM24_ABB_SERIAL": "42"})
        self.assertEqual((cfg.meter_profile, cfg.abb_serial), ("abb_b21", 42))

    def test_profile_specific_limits_and_no_overlap(self):
        abb_config = Config(allow_estimated_power=True, meter_profile="abb_b21")
        em_config = Config(allow_estimated_power=True)
        # This fits ABB's counter but exceeds the EM24 signed 32-bit format.
        large = snapshot(100, imported=214748364800)
        abb_store = MeasurementStore(abb_config, clock=lambda: 100)
        abb_store.publish(large)
        with self.assertRaises(ValueError):
            MeasurementStore(em_config, clock=lambda: 100).publish(large)
        addresses = [reg.address+i for reg in abb.REGISTERS for i in range(reg.count)]
        self.assertEqual(len(addresses), len(set(addresses)))
        self.assertIn("/Ac/L1/Energy/Reverse", abb.BY_NAME["energy_export"].aliases)

    def test_signed_power_boundaries_truncation_and_invalid_values(self):
        spec = abb.BY_NAME["power_total"]
        for raw in (-2**31, -1, 0, 1, 2**31-1):
            words = encode_number(Decimal(raw)/100, spec)
            self.assertEqual(struct.unpack(">i", struct.pack(">2H", *words))[0], raw)
        self.assertEqual(encode_number(-.019, spec), (65535, 65535))
        for value in (float("nan"), float("inf"), Decimal("21474836.48")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                encode_number(value, spec)


class ABBTCPTests(TCPWireMixin, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.now = 100.0
        self.config = Config(allow_estimated_power=True, meter_profile="abb_b21", port=self.port)
        self.store = MeasurementStore(self.config, clock=lambda: self.now)
        self.bridge = create_server(self.config, self.store)
        self.assertIsInstance(self.bridge, ABBServer)
        await self.bridge.start()
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.transaction = 0

    async def asyncTearDown(self):
        self.writer.close()
        await self.writer.wait_closed()
        await self.bridge.stop()

    async def test_discovery_identity_each_register_and_packed_polls(self):
        # Discovery must work before the TIC/estimator has any valid data.
        self.assertEqual(self.words(await self.read(0x8960, 2)), (0x4232, 0x3120))
        info = self.words(await self.read(0x8900, 16))
        self.assertEqual(struct.unpack(">i", struct.pack(">2H", *info[:2]))[0], 10000001)
        self.assertEqual(struct.pack(">8H", *info[8:]).rstrip(b"\0").decode(), "TIC-0.3.0")
        self.store.publish(snapshot(self.now, power=-1234.56, exported=123459))
        expected = {"model": (0x4232, 0x3120), "serial": (0x0098, 0x9681),
                    "firmware_version": abb.firmware_words(),
                    "voltage_l1": (0, 2301), "current_l1": (0, 536),
                    "power_total": (0xfffe, 0x1dc0), "frequency": (5000,),
                    "energy_import": (0, 0, 0x12, 0xd687),
                    "energy_export": (0, 0, 0, 12345), "power_factor": (0x7fff,)}
        for reg in abb.REGISTERS:
            with self.subTest(name=reg.name):
                self.assertEqual(self.words(await self.read(reg.address, reg.count)), expected[reg.name])
        for address, count in abb.POLL_BLOCKS:
            words = self.words(await self.read(address, count))
            for reg in abb.REGISTERS:
                if address <= reg.address < address+count:
                    offset = reg.address-address
                    self.assertEqual(words[offset:offset+reg.count], expected[reg.name])

    async def test_freshness_every_measurement_word_and_recovery(self):
        self.assertEqual(await self.read(0x5000, 8), b"\x83\x04")
        self.store.publish(snapshot(self.now))
        self.assertEqual((await self.read(0x5000, 8))[0], 3)
        self.now += 5
        for reg in abb.REGISTERS:
            if reg.measurement:
                for word in range(reg.address, reg.address+reg.count):
                    self.assertEqual(await self.read(word), b"\x83\x04")
        self.assertEqual(self.words(await self.read(0x8960, 2)), (0x4232, 0x3120))
        self.store.publish(snapshot(self.now))
        self.assertEqual((await self.read(0x5B00, 59))[0], 3)
        self.store.reject("checksum")
        self.assertEqual(await self.read(0x5004, 4), b"\x83\x04")

    async def test_warmup_and_reversal_keep_energy_available(self):
        trace = Trace(meter_profile="abb_b21")
        self.bridge.store = trace.store
        trace.sample(400, 700)
        self.assertEqual(await self.read(0x5B14, 2), b"\x83\x04")
        self.assertEqual(await self.read(0x5B00, 59), b"\x83\x04")
        self.assertEqual((await self.read(0x5000, 8))[0], 3)
        self.assertEqual(self.words(await self.read(0x5B3A)), (0x7fff,))
        result = trace.run(400, 700, 100)[-1]
        power = self.words(await self.read(0x5B14, 2))
        self.assertAlmostEqual(struct.unpack(">i", struct.pack(">2H", *power))[0]/100,
                               result.estimated_power, delta=.01)
        trace.sample(-600, 700)
        self.assertEqual(await self.read(0x5B14, 2), b"\x83\x04")
        self.assertEqual((await self.read(0x5004, 4))[0], 3)
        trace.run(-600, 700, 100)
        power = self.words(await self.read(0x5B14, 2))
        self.assertLess(struct.unpack(">i", struct.pack(">2H", *power))[0], 0)
        trace.store.invalidate("serial disconnected")
        self.assertEqual(await self.read(0x5004, 4), b"\x83\x04")

    async def test_readonly_units_functions_and_inactive_em24_identity(self):
        self.store.publish(snapshot(self.now))
        original = self.words(await self.read(0x5000, 8))
        self.assertEqual(await self.request(struct.pack(">BHH", 6, 0x5004, 0)), b"\x86\x02")
        fc16 = struct.pack(">BHHBH", 16, 0x5004, 1, 2, 0)
        self.assertEqual(await self.request(fc16), b"\x90\x02")
        fc23 = struct.pack(">BHHHHBH", 23, 0x5004, 1, 0x5004, 1, 2, 0)
        self.assertEqual(await self.request(fc23), b"\x97\x01")
        self.assertEqual(self.words(await self.read(0x5000, 8)), original)
        for address, count in ((0x000B, 1), (0x1002, 1), (0xA000, 1), (0x8961, 2), (0x5007, 2)):
            self.assertEqual(await self.read(address, count), b"\x83\x02")
        for unit in (0, 2):
            self.assertEqual(await self.read(0x8960, 2, unit=unit), b"\x83\x0b")
        self.assertEqual(await self.read(0x8960, 2, fc=4), b"\x84\x01")

    async def test_energy_pair_is_atomic_and_probe_detects_abb(self):
        self.store.publish(snapshot(self.now))
        report = await asyncio.to_thread(probe, "127.0.0.1", self.port)
        self.assertEqual(report["profile"], "abb_b21")
        self.assertEqual(report["serial"], "10000001")
        self.assertEqual(report["export_kWh"], 123.4)
        self.assertEqual(report["export_l1_kWh"], report["export_kWh"])
        self.assertIsNone(report["power_factor"])

        async def update():
            for i in range(40):
                self.store.publish(snapshot(self.now, imported=20000000+i*10, exported=10000000+i*10))
                await asyncio.sleep(0)

        task = asyncio.create_task(update())
        for _ in range(40):
            words = self.words(await self.read(0x5000, 8))
            imported, exported = struct.unpack(">QQ", struct.pack(">8H", *words))
            self.assertIn((imported, exported), ((1234567, 12340),
                                               *[(2000000+i, 1000000+i) for i in range(40)]))
        await task
