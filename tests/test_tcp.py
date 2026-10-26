import asyncio
import socket
import struct
import unittest

from teleinfo_modbus_victron.config import Config
from teleinfo_modbus_victron.em24 import BY_NAME, REGISTERS, encode_number, encode_serial, encode_version, energy_wh_to_raw
from teleinfo_modbus_victron.model import MeasurementStore
from teleinfo_modbus_victron.server import EM24Server
from teleinfo_modbus_victron.probe import probe
from tests.helpers import snapshot, TCPWireMixin
from tests.test_power import Trace


class TCPTests(TCPWireMixin, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.now = 100.0
        self.store = MeasurementStore(Config(allow_estimated_power=True), clock=lambda: self.now)
        self.bridge = EM24Server(Config(allow_estimated_power=True, port=port), self.store)
        await self.bridge.start()
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", port)
        self.transaction = 0

    async def asyncTearDown(self):
        self.writer.close()
        await self.writer.wait_closed()
        await self.bridge.stop()

    async def test_every_register_and_official_blocks(self):
        self.store.publish(snapshot(self.now))
        expected = {
            "model": (1648,), "phase_config": (3,), "application": (7,),
            "hardware_version": encode_version(0, 2, 0), "firmware_version": encode_version(0, 2, 0),
            "serial": encode_serial("TIC00000000001"), "switch_position": (3,),
            "energy_import": energy_wh_to_raw(12345678), "energy_import_l1": energy_wh_to_raw(12345678),
            "energy_export": energy_wh_to_raw(123400),
        }
        for name, value in (("voltage_l1", 230.1), ("current_l1", 1234.5/230.1),
                            ("power_l1", 1234.5), ("power_total", 1234.5), ("frequency", 50)):
            expected[name] = encode_number(value, BY_NAME[name])
        for reg in REGISTERS:
            with self.subTest(register=reg.name):
                self.assertEqual(self.words(await self.read(reg.address, reg.count)), expected[reg.name])
        words = self.words(await self.read(0, 80))
        self.assertEqual(len(words), 80)
        self.assertEqual(words[11], 1648)
        for reg in REGISTERS:
            if reg.address < 80:
                self.assertEqual(words[reg.address:reg.address+reg.count], expected[reg.name])
        self.assertEqual(self.words(await self.read(0xA100)), (3,))

    async def test_diagnostic_probe_retains_em24_auto_detection(self):
        self.store.publish(snapshot(self.now))
        for profile in ("auto", "em24"):
            report = await asyncio.to_thread(probe, "127.0.0.1", self.bridge.config.port, profile)
            self.assertEqual(report["profile"], "em24")
            self.assertEqual(report["serial"], "TIC00000000001")
            self.assertEqual(report["estimated_power_W"], 1234.5)

    async def test_expiration_partial_words_and_identity(self):
        self.assertEqual(await self.read(0, 80), b"\x83\x04")
        self.store.publish(snapshot(self.now))
        self.assertEqual((await self.read(0, 80))[0], 3)
        self.now += 5
        for reg in REGISTERS:
            if reg.measurement:
                for address in range(reg.address, reg.address + reg.count):
                    self.assertEqual(await self.read(address), b"\x83\x04")
        self.assertEqual(self.words(await self.read(0x000B)), (1648,))
        self.assertEqual(self.words(await self.read(0x5000, 7)), encode_serial("TIC00000000001"))
        self.store.publish(snapshot(self.now))
        self.assertEqual((await self.read(0, 80))[0], 3)
        self.store.reject("invalid checksum")
        self.assertEqual(await self.read(0, 80), b"\x83\x04")

    async def test_application_init_fc06_fc16_and_phase_config(self):
        for fc in (6, 16):
            for value in (0, 7):
                pdu = struct.pack(">BHH", 6, 0xA000, value) if fc == 6 else struct.pack(">BHHBH", 16, 0xA000, 1, 2, value)
                reply = await self.request(pdu)
                self.assertEqual(reply[0], fc)
                self.assertEqual(self.words(await self.read(0xA000)), (value,))
        self.assertEqual((await self.request(struct.pack(">BHH", 6, 0x1002, 3)))[0], 6)
        self.assertEqual(await self.request(struct.pack(">BHH", 6, 0x1002, 0)), b"\x86\x03")
        self.assertEqual(self.words(await self.read(0x1002)), (3,))
        self.assertEqual(await self.request(struct.pack(">BHH", 6, 0xA000, 8)), b"\x86\x03")
        # Unsupported FC23 must reject its write half without mutation.
        fc23 = struct.pack(">BHHHHBH", 23, 0xA000, 1, 0xA000, 1, 2, 0)
        self.assertEqual(await self.request(fc23), b"\x97\x01")
        self.assertEqual(self.words(await self.read(0xA000)), (7,))

    async def test_adaptive_estimation_warmup_reversal_and_expiration_on_wire(self):
        trace = Trace()
        self.bridge.store = trace.store
        trace.sample(400, 700)
        self.assertEqual(await self.read(0, 80), b"\x83\x04")
        for address in (0x12, 0x13, 0x28, 0x29):
            self.assertEqual(await self.read(address), b"\x83\x04")
        # The unavailable estimate does not turn raw measurements/identity stale.
        self.assertEqual(self.words(await self.read(0x000B)), (1648,))
        self.assertEqual(self.words(await self.read(0, 2)), encode_number(230.1, BY_NAME["voltage_l1"]))
        self.assertEqual(self.words(await self.read(0x34, 2)), energy_wh_to_raw(100000))
        last = trace.run(400, 700, 150)[-1]
        words = self.words(await self.read(0, 80))
        expected = encode_number(last.estimated_power, BY_NAME["power_total"])
        self.assertEqual(words[0x12:0x14], expected)
        self.assertEqual(words[0x28:0x2A], expected)
        self.assertEqual(words[0x34:0x36], energy_wh_to_raw(last.energy_import_wh))
        trace.sample(-600, 650)
        self.assertEqual(await self.read(0, 80), b"\x83\x04")
        last = trace.run(-600, 650, 150)[-1]
        words = self.words(await self.read(0, 80))
        self.assertEqual(words[0x28:0x2A], encode_number(last.estimated_power, BY_NAME["power_total"]))
        trace.now += trace.config.stale_after
        self.assertEqual(await self.read(0, 80), b"\x83\x04")
        self.assertEqual(self.words(await self.read(0x000B)), (1648,))
        trace.sample(-600, 650)
        self.assertEqual(await self.read(0, 80), b"\x83\x04")

    async def test_readonly_unknown_address_unit_and_functions(self):
        self.assertEqual(await self.request(struct.pack(">BHH", 6, 0x000B, 123)), b"\x86\x02")
        self.assertEqual(self.words(await self.read(0x000B)), (1648,))
        for address, count in ((0x0050, 1), (0x0302, 3), (0x5006, 2), (0xA001, 1)):
            self.assertEqual(await self.read(address, count), b"\x83\x02")
        self.assertEqual(await self.read(0x000B, unit=2), b"\x83\x0b")
        self.assertEqual(await self.read(0x000B, unit=0), b"\x83\x0b")
        self.assertEqual(await self.read(0x000B, fc=4), b"\x84\x01")
        # PyModbus rejects these during PDU decoding, before our action.
        self.assertTrue((await self.read(0, count=0))[0] & 0x80)
        self.assertTrue((await self.read(0, count=126))[0] & 0x80)

    async def test_export_sign_and_snapshot_atomicity(self):
        self.store.publish(snapshot(self.now, power=-1234.5))
        words = self.words(await self.read(0, 80))
        self.assertEqual(words[0x12:0x14], (0xCFC7, 0xFFFF))
        self.assertEqual(words[0x28:0x2A], words[0x12:0x14])

        async def update():
            for i in range(40):
                self.store.publish(snapshot(self.now, power=i, imported=12345678 + i*100))
                await asyncio.sleep(0)

        task = asyncio.create_task(update())
        for _ in range(40):
            words = self.words(await self.read(0, 80))
            self.assertEqual(words[0x12:0x14], words[0x28:0x2A])
            self.assertEqual(words[0x34:0x36], words[0x40:0x42])
        await task
