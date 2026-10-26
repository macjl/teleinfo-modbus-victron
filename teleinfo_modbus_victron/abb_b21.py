"""ABB B21 wire contract audited against Victron's native abb.py driver.

Aliases describe the GX driver's bindings: the server sends one counter at
one address, which that driver publishes both globally and on phase L1.
"""
from .registers import RegisterSpec, encode_number

MODEL_ID = 0x42323120  # ASCII 'B21 ', unsigned 32-bit, high word first.
UNIT_ID = 1
PRODUCT_NAME = "ABB B21 Energy Meter"
FIRMWARE = "TIC-0.3.0"
INFO_BLOCKS = ((0x8900, 16),)
POLL_BLOCKS = ((0x5000, 8), (0x5B00, 59))
ADDRESS_BLOCKS = POLL_BLOCKS + INFO_BLOCKS + ((0x8960, 2),)

REGISTERS = (
    RegisterSpec("model", 0x8960, 2, "u32b"),
    RegisterSpec("serial", 0x8900, 2, "s32b", path="/Serial"),
    RegisterSpec("firmware_version", 0x8908, 8, "ascii", path="/FirmwareVersion"),
    RegisterSpec("energy_import", 0x5000, 4, "u64b", 100, "kWh", "/Ac/Energy/Forward",
                 measurement=True, aliases=("/Ac/L1/Energy/Forward",)),
    RegisterSpec("energy_export", 0x5004, 4, "u64b", 100, "kWh", "/Ac/Energy/Reverse",
                 measurement=True, aliases=("/Ac/L1/Energy/Reverse",)),
    RegisterSpec("voltage_l1", 0x5B00, 2, "u32b", 10, "V", "/Ac/L1/Voltage", measurement=True),
    RegisterSpec("current_l1", 0x5B0C, 2, "u32b", 100, "A", "/Ac/L1/Current", measurement=True),
    RegisterSpec("power_total", 0x5B14, 2, "s32b", 100, "W", "/Ac/Power",
                 measurement=True, aliases=("/Ac/L1/Power",)),
    RegisterSpec("frequency", 0x5B2C, 1, "u16", 100, "Hz", "/Ac/Frequency", measurement=True),
    RegisterSpec("power_factor", 0x5B3A, 1, "s16", 1000, "", "/Ac/PowerFactor",
                 measurement=True, aliases=("/Ac/L1/PowerFactor",)),
)
BY_NAME = {r.name: r for r in REGISTERS}


def energy_wh_to_raw(energy_wh: int) -> tuple[int, ...]:
    """Original TIC Wh -> ABB 0.01 kWh, exactly quantized in integer arithmetic."""
    if type(energy_wh) is not int or energy_wh < 0:
        raise ValueError("energy counter must be a nonnegative integer Wh")
    raw = energy_wh // 10
    if raw >= 0xffffffffffffffff:  # All-ones is the official invalid marker.
        raise ValueError("energy counter exceeds ABB capacity")
    return tuple((raw >> shift) & 0xffff for shift in (48, 32, 16, 0))


def encode_serial(serial: int) -> tuple[int, ...]:
    if type(serial) is not int or not 1 <= serial <= 0x7fffffff:
        raise ValueError("abb_serial must be an integer in 1..2147483647")
    return encode_number(serial, BY_NAME["serial"])


def firmware_words() -> tuple[int, ...]:
    data = FIRMWARE.encode("ascii").ljust(16, b"\0")
    return tuple(int.from_bytes(data[i:i+2], "big") for i in range(0, 16, 2))
