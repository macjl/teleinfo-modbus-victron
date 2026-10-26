"""Selectable meter TCP server on PyModbus's SimDevice/action data model."""
from collections import Counter
import logging

from pymodbus.constants import ExcCodes
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

from .config import Config
from . import abb_b21, em24
from .registers import encode_number
from .model import MeasurementStore

LOG = logging.getLogger(__name__)


class MeterServer:
    def __init__(self, config: Config, store: MeasurementStore):
        self.config = config
        self.store = store
        self.requests = Counter()
        self.errors = Counter()
        self.measurement_words = {r.address + i for r in self.contract.REGISTERS if r.measurement
                                  for i in range(r.count)}
        self.power_words = {r.address + i for r in self.contract.REGISTERS
                            if r.name in ("power_l1", "power_total") for i in range(r.count)}
        self.static = {}
        for name, words in self.identity_values(config).items():
            self._put(self.static, name, words)
        # Only the audited poll blocks and identity/configuration ranges exist.
        blocks = [SimData(address, count=count, datatype=DataType.REGISTERS)
                  for address, count in self.contract.ADDRESS_BLOCKS]
        self.device = SimDevice(self.contract.UNIT_ID, blocks, action=self.action)
        # SimCore falls back to device 0 for unknown IDs; make that path an
        # explicit rejection, including unit 0 with broadcasting disabled.
        self.reject_device = SimDevice(0, [SimData(0, count=65536, datatype=DataType.REGISTERS)],
                                       action=self.reject_unit)
        self.server = None

    async def reject_unit(self, function_code, start_address, address, count, current_registers, set_values):
        return self._error(ExcCodes.GATEWAY_NO_RESPONSE)

    def _put(self, words, name, values):
        base = self.contract.BY_NAME[name].address
        words.update({base + i: v for i, v in enumerate(values)})

    def _error(self, code):
        self.errors[int(code)] += 1
        return code

    async def action(self, function_code, start_address, address, count, current_registers, set_values):
        self.requests[(function_code, address, count)] += 1
        if self.requests[(function_code, address, count)] == 1:
            LOG.info("First Modbus request FC%02d address=0x%04X count=%d", function_code, address, count)
        LOG.debug("Modbus FC%02d address=0x%04X count=%d", function_code, address, count)
        if set_values is not None:
            return self.write_values(function_code, address, count, set_values)
        # PyModbus internally reads back FC06 before constructing its echo.
        if function_code not in (3, 6):
            return self._error(ExcCodes.ILLEGAL_FUNCTION)
        words = dict(self.static)
        for name, values in self.configuration_values().items():
            self._put(words, name, values)
        if any(a in self.measurement_words for a in range(address, address + count)):
            snapshot = self.store.fresh()
            if snapshot is None:
                return self._error(ExcCodes.DEVICE_FAILURE)
            if snapshot.estimated_power is None and any(
                    a in self.power_words for a in range(address, address + count)):
                return self._error(ExcCodes.DEVICE_FAILURE)
            for name, value in (("voltage_l1", snapshot.voltage), ("current_l1", snapshot.current),
                                ("power_l1", snapshot.estimated_power),
                                ("power_total", snapshot.estimated_power),
                                ("frequency", self.config.nominal_frequency)):
                if value is not None and name in self.contract.BY_NAME:
                    self._put(words, name, encode_number(value, self.contract.BY_NAME[name]))
            for name, value in (("energy_import", snapshot.energy_import_wh),
                                ("energy_import_l1", snapshot.energy_import_wh),
                                ("energy_export", snapshot.energy_export_wh)):
                if name in self.contract.BY_NAME:
                    self._put(words, name, self.contract.energy_wh_to_raw(value))
            for name, values in self.extra_measurement_values().items():
                self._put(words, name, values)
        # No await between reading one immutable snapshot and constructing response.
        for a in range(address, address + count):
            current_registers[a - start_address] = words.get(a, 0)
        return None

    def configuration_values(self):
        return {}

    def extra_measurement_values(self):
        return {}

    def write_values(self, function_code, address, count, values):
        return self._error(ExcCodes.ILLEGAL_ADDRESS if function_code in (6, 16)
                           else ExcCodes.ILLEGAL_FUNCTION)

    def trace_packet(self, sending: bool, packet: bytes) -> bytes:
        # Log only function/address/quantity, never source TIC data or serial text.
        if not sending and len(packet) >= 12:
            LOG.debug("TCP request unit=%d FC=%d address=0x%04X", packet[6], packet[7],
                      int.from_bytes(packet[8:10], "big"))
        return packet

    async def start(self):
        self.server = ModbusTcpServer([self.device, self.reject_device], address=(self.config.host, self.config.port),
                                      trace_packet=self.trace_packet,
                                      ignore_missing_devices=False, broadcast_enable=False)
        await self.server.serve_forever(background=True)

    async def stop(self):
        if self.server:
            await self.server.shutdown()


class EM24Server(MeterServer):
    contract = em24

    def __init__(self, config, store):
        self.application = em24.APPLICATION
        super().__init__(config, store)

    def identity_values(self, config):
        return {"model": (em24.MODEL_ID,), "phase_config": (em24.PHASE_CONFIG,),
                "hardware_version": em24.encode_version(0, 2, 0),
                "firmware_version": em24.encode_version(0, 2, 0),
                "serial": em24.encode_serial(config.serial), "switch_position": (3,)}

    def configuration_values(self):
        return {"application": (self.application,)}

    def write_values(self, function_code, address, count, values):
        if function_code not in (6, 16):
            return self._error(ExcCodes.ILLEGAL_FUNCTION)
        if count != 1 or address not in (0xA000, 0x1002):
            return self._error(ExcCodes.ILLEGAL_ADDRESS)
        value = values[0]
        if address == 0x1002 and value != em24.PHASE_CONFIG:
            return self._error(ExcCodes.ILLEGAL_VALUE)
        if address == 0xA000:
            if not 0 <= value <= em24.APPLICATION:
                return self._error(ExcCodes.ILLEGAL_VALUE)
            self.application = value
            LOG.info("EM24 application set to %d", value)
        return None


class ABBServer(MeterServer):
    contract = abb_b21

    def identity_values(self, config):
        return {"model": encode_number(abb_b21.MODEL_ID, abb_b21.BY_NAME["model"]),
                "serial": abb_b21.encode_serial(config.abb_serial),
                "firmware_version": abb_b21.firmware_words()}

    def extra_measurement_values(self):
        # TIC does not measure an instantaneous power factor. Use the official
        # invalid marker instead of advertising the estimator's learned ratio
        # as an independently measured quantity (both total and L1 become null).
        return {"power_factor": (0x7fff,)}


def create_server(config, store):
    server_class = {"em24": EM24Server, "abb_b21": ABBServer}[config.meter_profile]
    return server_class(config, store)
