import asyncio
from contextlib import suppress
import time
import unittest

import serial

from teleinfo_modbus_victron.config import Config
from teleinfo_modbus_victron.model import MeasurementStore
from teleinfo_modbus_victron.sources import tic_source, simulated_source
from tests.helpers import frame


async def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition timed out")
        await asyncio.sleep(.01)


class SourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_serial_disconnect_invalidates_and_reconnects(self):
        cfg = Config(allow_estimated_power=True, source="tic", device="test", reconnect_max=.01)
        store = MeasurementStore(cfg)
        disconnect = False
        allow_reconnect = False
        connections = []

        class Stream:
            def __init__(self):
                self.sent = False
                self.closed = False

            def read(self, count):
                if disconnect and self is connections[0]:
                    raise serial.SerialException("unplugged")
                if not self.sent:
                    self.sent = True
                    return frame()
                time.sleep(.01)
                return b""

            def close(self):
                self.closed = True

        def opener(config):
            if connections and not allow_reconnect:
                raise serial.SerialException("adapter not back yet")
            stream = Stream()
            connections.append(stream)
            return stream

        task = asyncio.create_task(tic_source(cfg, store, opener))
        try:
            await until(lambda: store.accepted == 1)
            disconnect = True
            await until(lambda: store.fresh() is None)
            self.assertEqual(store.accepted, 1)
            allow_reconnect = True
            await until(lambda: len(connections) >= 2 and store.accepted >= 2)
            self.assertTrue(connections[0].closed)
            self.assertIsNotNone(store.fresh())
            self.assertEqual(store.reconnections, 2)
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self.assertTrue(connections[-1].closed)

    async def test_simulator_stops_refreshing_and_expires(self):
        cfg = Config(allow_estimated_power=True, simulation_interval=.02, stale_after=.08,
                     simulation_power=-500)
        store = MeasurementStore(cfg)
        task = asyncio.create_task(simulated_source(cfg, store))
        await until(lambda: store.accepted > 0)
        self.assertEqual(store.fresh().estimated_power, -500)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await until(lambda: store.fresh() is None)

    async def test_invalid_frame_after_valid_frame_is_not_published_as_valid(self):
        cfg = Config(allow_estimated_power=True, source="tic", device="test")
        store = MeasurementStore(cfg)

        class Stream:
            sent = False
            def read(self, count):
                if not self.sent:
                    self.sent = True
                    return frame() + frame().replace(b"00936", b"00937")
                time.sleep(.01)
                return b""
            def close(self):
                pass

        task = asyncio.create_task(tic_source(cfg, store, lambda c: Stream()))
        try:
            await until(lambda: store.rejected > 0)
            self.assertEqual(store.accepted, 1)
            self.assertIsNone(store.fresh())
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
