from datetime import datetime, timezone
from types import MappingProxyType
import asyncio
import struct

from teleinfo_modbus_victron.model import Snapshot


def group(label, value, timestamp=None):
    body = (label + "\t" + ((timestamp + "\t") if timestamp else "") + value + "\t").encode("ascii")
    return b"\n" + body + bytes([(sum(body) & 0x3F) + 0x20]) + b"\r"


def frame(**overrides):
    values = dict(VTIC="02", URMS1="231", IRMS1="004", SINSTS="00936", SINSTI="00000",
                  EAST="039688557", EAIT="011444279")
    values.update(overrides)
    return b"\x02" + b"".join(group(k, v) for k, v in values.items()) + b"\x03"


def snapshot(now, power=1234.5, imported=12345678, exported=123400):
    return Snapshot(now, datetime.now(timezone.utc).isoformat(), 230.1, abs(power)/230.1,
                    max(power, 0), max(-power, 0), imported, exported, MappingProxyType({}))


class TCPWireMixin:
    async def request(self, pdu, unit=1):
        self.transaction += 1
        self.writer.write(struct.pack(">HHHB", self.transaction, 0, len(pdu)+1, unit) + pdu)
        await self.writer.drain()
        header = await asyncio.wait_for(self.reader.readexactly(7), 2)
        transaction, protocol, length, received_unit = struct.unpack(">HHHB", header)
        self.assertEqual((transaction, protocol, received_unit), (self.transaction, 0, unit))
        return await asyncio.wait_for(self.reader.readexactly(length-1), 2)

    async def read(self, address, count=1, unit=1, fc=3):
        return await self.request(struct.pack(">BHH", fc, address, count), unit)

    @staticmethod
    def words(pdu):
        return struct.unpack(">" + "H"*(pdu[1]//2), pdu[2:])
