"""Read-only diagnostic client, separate from the bridge's TCP server role."""
import argparse
from datetime import datetime, timezone
import json
import struct

from pymodbus.client import ModbusTcpClient
from . import abb_b21


def probe(host, port=502, profile="auto"):
    if profile not in ("auto", "em24", "abb_b21"):
        raise ValueError("profile must be auto, em24 or abb_b21")
    with ModbusTcpClient(host, port=port, timeout=2, retries=0) as client:
        def read(address, count):
            result = client.read_holding_registers(address, count=count, device_id=1)
            if result.isError():
                raise ValueError(f"Modbus error at 0x{address:04X}: {result}")
            return result.registers

        if profile == "auto":
            try:
                words = read(0x8960, 2)
                found_abb = struct.unpack(">I", struct.pack(">2H", *words))[0] == abb_b21.MODEL_ID
            except ValueError:
                found_abb = False
            profile = "abb_b21" if found_abb else "em24"

        if profile == "abb_b21":
            model = struct.unpack(">I", struct.pack(">2H", *read(0x8960, 2)))[0]
            if model != abb_b21.MODEL_ID:
                raise ValueError("unexpected ABB B21 model")
            info = read(0x8900, 16)
            serial = str(struct.unpack(">i", struct.pack(">2H", *info[:2]))[0])
            firmware = struct.pack(">8H", *info[8:16]).rstrip(b"\0").decode("ascii")
            energy = read(0x5000, 8)
            values = read(0x5B00, 59)

            def number(address, fmt, count, scale):
                start = address - 0x5B00
                return struct.unpack(fmt, struct.pack(">" + "H"*count, *values[start:start+count]))[0]/scale

            imported = struct.unpack(">Q", struct.pack(">4H", *energy[:4]))[0]/100
            exported = struct.unpack(">Q", struct.pack(">4H", *energy[4:]))[0]/100
            # Both aliases use the very same counters in the native GX driver.
            return dict(sampled_utc=datetime.now(timezone.utc).isoformat(), profile=profile,
                        model=model, phases=1, serial=serial, firmware=firmware,
                        voltage_V=number(0x5B00, ">I", 2, 10),
                        current_A=number(0x5B0C, ">I", 2, 100),
                        estimated_power_W=number(0x5B14, ">i", 2, 100),
                        configured_frequency_Hz=number(0x5B2C, ">H", 1, 100),
                        import_kWh=imported, import_l1_kWh=imported,
                        export_kWh=exported, export_l1_kWh=exported,
                        power_factor=None if values[0x3A] == 0x7fff
                        else number(0x5B3A, ">h", 1, 1000))

        model, phase, application = (read(addr, 1)[0] for addr in (0x000B, 0x1002, 0xA000))
        if (model, phase, application) != (1648, 3, 7):
            raise ValueError("unexpected EM24 model, phase configuration or application")
        serial = struct.pack(">7H", *read(0x5000, 7)).rstrip(b"\0").decode("ascii")
        values = read(0, 80)
        read(0xA100, 1)
        def number(address, scale):
            return struct.unpack("<i", struct.pack("<2H", *values[address:address+2]))[0] / scale

        return dict(sampled_utc=datetime.now(timezone.utc).isoformat(), profile=profile, model=model,
                    phase_config=phase, application=application, serial=serial,
                    voltage_V=number(0, 10), current_A=number(12, 1000),
                    estimated_power_W=number(40, 10), configured_frequency_Hz=values[51]/10,
                    import_kWh=number(52, 10), export_kWh=number(78, 10))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--profile", choices=("auto", "abb_b21", "em24"), default="auto")
    args = parser.parse_args()
    try:
        print(json.dumps(probe(args.host, args.port, args.profile), indent=2))
    except Exception as exc:
        parser.exit(1, f"Meter probe failed: {exc}\n")


if __name__ == "__main__":
    main()
