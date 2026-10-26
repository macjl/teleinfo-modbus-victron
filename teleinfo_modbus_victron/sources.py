"""Serial and simulated acquisition, independently of the Modbus transport."""
import asyncio
from datetime import datetime, timezone
import logging
import time
from types import MappingProxyType

import serial

from .config import Config
from .model import MeasurementStore, Snapshot, normalize
from .tic import TICParser

LOG = logging.getLogger(__name__)


def open_serial(config: Config):
    stream = serial.Serial(port=None, baudrate=config.baudrate, bytesize=serial.SEVENBITS,
                           parity=serial.PARITY_EVEN, stopbits=serial.STOPBITS_ONE,
                           timeout=0.25, exclusive=True)
    stream.dtr = False
    stream.rts = False
    stream.port = config.device
    try:
        stream.open()
        stream.reset_input_buffer()
    except BaseException:
        stream.close()
        raise
    return stream


async def tic_source(config: Config, store: MeasurementStore, opener=open_serial):
    delay = 1.0
    last_issue = None
    while True:
        stream = None
        try:
            # No cancellation point between obtaining the handle and the finally
            # block responsible for closing it. Reads run outside the event loop.
            stream = opener(config)
            store.reconnections += 1
            parser = TICParser()
            last_byte = time.monotonic()
            LOG.info("TIC serial opened at 9600 7E1")
            while True:
                chunk = await asyncio.to_thread(stream.read, 512)
                if chunk:
                    last_byte = time.monotonic()
                elif time.monotonic() - last_byte > max(config.stale_after, 2):
                    raise serial.SerialException("no serial data before timeout")
                frames = parser.feed(chunk)
                for frame in frames:
                    if frame is None:
                        store.reject("invalid TIC frame/checksum")
                        continue
                    try:
                        store.publish(normalize(frame, config))
                        delay = 1.0
                        last_issue = None
                    except ValueError as exc:
                        store.reject(str(exc))
                        if last_issue != str(exc):
                            LOG.warning("TIC measurement rejected: %s", exc)
                            last_issue = str(exc)
        except (serial.SerialException, OSError) as exc:
            store.invalidate("serial disconnected")
            if last_issue != str(exc):
                LOG.warning("TIC serial unavailable: %s; reconnecting", exc)
                last_issue = str(exc)
        finally:
            if stream is not None:
                stream.close()
        await asyncio.sleep(min(delay, config.reconnect_max))
        delay = min(delay * 2, config.reconnect_max)


async def simulated_source(config: Config, store: MeasurementStore):
    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        power = config.simulation_power
        store.publish(Snapshot(
            time.monotonic(), datetime.now(timezone.utc).isoformat(),
            230.1, abs(power) / 230.1, max(power, 0), max(-power, 0),
            12345678 + int(max(power, 0) * elapsed / 3600),
            123400 + int(max(-power, 0) * elapsed / 3600), MappingProxyType({}),
        ))
        await asyncio.sleep(config.simulation_interval)
