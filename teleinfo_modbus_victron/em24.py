"""Executable single-phase contract, audited against the pinned Victron driver.

This module defines wire representations, not a running meter or TIC source.
Numeric values are in the units presented by Venus (not raw TIC Wh).
"""

from .registers import RegisterSpec, encode_number

MODEL_ID = 1648
UNIT_ID = 1
TCP_PORT = 502
PHASE_CONFIG = 3
APPLICATION = 7
# Derived from BaseDevice.pack_regs for TCP, with the 1P register set.
POLL_BLOCKS = ((0x0000, 80), (0xA100, 1))
ADDRESS_BLOCKS = ((0, 80), (0x0302, 1), (0x0304, 1), (0x1002, 1),
                  (0x5000, 7), (0xA000, 1), (0xA100, 1))
PRODUCT_NAME = "Carlo Gavazzi EM24 Ethernet"


REGISTERS = (
    RegisterSpec("model", 0x000B, 1, "u16"),
    RegisterSpec("phase_config", 0x1002, 1, "u16", path="/PhaseConfig", writable=True),
    RegisterSpec("application", 0xA000, 1, "u16", writable=True),
    RegisterSpec("hardware_version", 0x0302, 1, "version", path="/HardwareVersion"),
    RegisterSpec("firmware_version", 0x0304, 1, "version", path="/FirmwareVersion"),
    RegisterSpec("serial", 0x5000, 7, "ascii", path="/Serial"),
    RegisterSpec("voltage_l1", 0x0000, 2, "s32l", 10, "V", "/Ac/L1/Voltage", measurement=True),
    RegisterSpec("current_l1", 0x000C, 2, "s32l", 1000, "A", "/Ac/L1/Current", measurement=True),
    RegisterSpec("power_l1", 0x0012, 2, "s32l", 10, "W", "/Ac/L1/Power", measurement=True),
    RegisterSpec("power_total", 0x0028, 2, "s32l", 10, "W", "/Ac/Power", measurement=True),
    RegisterSpec("frequency", 0x0033, 1, "u16", 10, "Hz", "/Ac/Frequency", measurement=True),
    RegisterSpec("energy_import", 0x0034, 2, "s32l", 10, "kWh", "/Ac/Energy/Forward", measurement=True),
    RegisterSpec("energy_export", 0x004E, 2, "s32l", 10, "kWh", "/Ac/Energy/Reverse", measurement=True),
    RegisterSpec("energy_import_l1", 0x0040, 2, "s32l", 10, "kWh", "/Ac/L1/Energy/Forward", measurement=True),
    RegisterSpec("switch_position", 0xA100, 1, "u16", path="/SwitchPos"),
)
BY_NAME = {r.name: r for r in REGISTERS}


def energy_wh_to_raw(energy_wh: int) -> tuple[int, int]:
    """TIC Wh -> signed low-word-first EM24 0.1 kWh; quantization <100 Wh."""
    if type(energy_wh) is not int or energy_wh < 0:
        raise ValueError("energy counter must be a nonnegative integer Wh")
    raw = energy_wh // 100
    if raw > 2**31 - 1:
        raise ValueError("energy counter exceeds EM24 capacity")
    return (raw & 0xFFFF, (raw >> 16) & 0xFFFF)


def encode_serial(serial: str) -> tuple[int, ...]:
    """ASCII, MSB first per word, zero padded to 14 bytes.

    Restrict IDs to portable characters because Venus uses the serial in
    its D-Bus service name and settings path. Never silently truncate IDs.
    """
    if not 1 <= len(serial) <= 14 or not serial.isascii() or not all(
        c.isalnum() or c == "_" for c in serial
    ):
        raise ValueError("serial must be 1..14 ASCII letters, digits or underscores")
    data = serial.encode("ascii").ljust(14, b"\0")
    return tuple(int.from_bytes(data[i:i + 2], "big") for i in range(0, 14, 2))


def encode_version(major: int, minor: int, patch: int) -> tuple[int]:
    if any(type(x) is not int for x in (major, minor, patch)) or not (
        0 <= major <= 15 and 0 <= minor <= 15 and 0 <= patch <= 255
    ):
        raise ValueError("version needs 4-bit major, 4-bit minor, 8-bit patch")
    return ((major << 12) | (minor << 8) | patch,)
