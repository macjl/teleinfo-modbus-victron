#!/usr/bin/env python3
"""Opt-in audit of pinned upstream code; no D-Bus, Modbus or GX required.

Downloads public sources into memory (or reads --source-dir), verifies their
Git blob hashes, then executes only the audited AST definitions used below.
No third-party source is copied into the distributed Python package.
"""

import argparse
import ast
from collections.abc import Iterable
from copy import copy
import hashlib
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from teleinfo_modbus_victron.em24 import (  # noqa: E402
    APPLICATION, BY_NAME, MODEL_ID, PHASE_CONFIG, POLL_BLOCKS, REGISTERS,
    UNIT_ID, encode_number, encode_serial, encode_version, energy_wh_to_raw,
)
from teleinfo_modbus_victron import abb_b21  # noqa: E402


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def definitions(source, names, namespace):
    nodes = [node for node in ast.parse(source).body
             if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    require({node.name for node in nodes} == set(names), "upstream definitions missing")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<pinned-upstream>", "exec"), namespace)


def audit(sources):
    ns = {"struct": struct, "copy": copy, "Iterable": Iterable}
    definitions(sources["register.py"],
                ["Reg", "Reg_num", "Reg_u16", "Reg_s32l", "Reg_text"], ns)
    handler = []
    ns["device"] = SimpleNamespace(CustomName=type("CustomName", (), {}),
                                   EnergyMeter=type("EnergyMeter", (), {}))
    ns["probe"] = SimpleNamespace(ModelRegister=lambda reg, models, **kw:
                                 SimpleNamespace(reg=reg, models=models, **kw),
                                 add_handler=handler.append)
    # Execute the audited EM24 module without its imports of Venus services.
    tree = ast.parse(sources["carlo_gavazzi.py"])
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, "<pinned-carlo-gavazzi>", "exec"), ns)
    require(len(handler) == 1, "unexpected number of EM24 probe handlers")
    probe = handler[0]
    require(probe.reg.base == 0x000B and probe.reg.count == 1, "model probe changed")
    require(probe.methods == ["tcp"] and probe.units == [UNIT_ID], "discovery changed")
    require(probe.models[MODEL_ID]["handler"] is ns["EM24_Meter"], "model handler changed")

    for initial_app in (0, APPLICATION):
        meter = ns["EM24_Meter"]()
        app = initial_app
        events = []
        meter.info = {}

        def read(reg):
            events.append(("read", reg.base, reg.count))
            if reg.base == 0xA000:
                reg.decode([app])
            elif reg.base == 0x1002:
                reg.decode([PHASE_CONFIG])
            elif reg.base == 0x5000:
                reg.decode(encode_serial("TIC00000000001"))
            else:
                reg.decode(encode_version(1, 2, 34))
            return reg.value

        def write(reg, value):
            nonlocal app
            events.append(("write", reg.base, value))
            app = value

        def read_info():
            for reg in meter.info_regs:
                read(reg)
                meter.info[reg.name] = reg

        meter.read_register, meter.write_register, meter.read_info = read, write, read_info
        meter.device_init()
        expected = [("read", 0xA000, 1)]
        if initial_app != APPLICATION:
            expected += [("write", 0xA000, APPLICATION), ("read", 0xA000, 1)]
        expected += [("read", addr, count) for addr, count in
                     ((0x0302, 1), (0x0304, 1), (0x1002, 1), (0x5000, 7))]
        require(events == expected, "initialization sequence changed")
        require(meter.nr_phases == 1, "single-phase interpretation changed")
        observed = {r.name: (r.base, r.count, getattr(r, "scale", 1))
                    for r in meter.info_regs + meter.data_regs}
        wanted = {r.path: (r.address, r.count, r.scale)
                  for r in REGISTERS if r.path is not None}
        require(observed == wanted, "register map differs from official driver")
        require(meter.info["/HardwareVersion"].value == "1.2.34", "version encoding differs")
        require(meter.info["/Serial"].value == "TIC00000000001", "serial encoding differs")
        definitions(sources["device.py"],
                    ["RegList", "contains_any", "pack_list", "modbus_overhead"], ns)
        hole = (ns["modbus_overhead"]("tcp") + 1) // 2
        packed = ns["pack_list"](list(meter.data_regs), "holding", hole, None)
        blocks = tuple((g[0].base, g[-1].base + g[-1].count - g[0].base) for g in packed)
        require(blocks == POLL_BLOCKS, f"polling blocks differ: {blocks!r}")

    for name, value in (("voltage_l1", 230.1), ("current_l1", 12.345),
                        ("power_total", -1234.5), ("frequency", 50),
                        ("energy_import", 12345.6)):
        spec = BY_NAME[name]
        cls = ns["Reg_s32l" if spec.encoding == "s32l" else "Reg_u16"]
        reg = cls(spec.address, scale=spec.scale)
        reg.decode(encode_number(value, spec))
        require(reg.value == value, f"official decoder disagrees for {name}")
    energy = ns["Reg_s32l"](0x0034, scale=10)
    energy.decode(energy_wh_to_raw(12345678))
    require(energy.value == 12345.6, "Wh/kWh conversion differs")


def audit_abb(sources, reader=None):
    ns = {"struct": struct, "copy": copy, "Iterable": Iterable}
    definitions(sources["register.py"],
                ["Reg", "Reg_num", "Reg_s16", "Reg_u16", "Reg_s32b", "Reg_u32b", "Reg_u64b", "Reg_text"], ns)
    handlers = []
    ns["device"] = SimpleNamespace(CustomName=type("CustomName", (), {}),
                                   EnergyMeter=type("EnergyMeter", (), {}))
    ns["probe"] = SimpleNamespace(ModelRegister=lambda reg, models, **kw:
                                 SimpleNamespace(reg=reg, models=models, **kw),
                                 add_handler=handlers.append)
    tree = ast.parse(sources["abb.py"])
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, "<pinned-abb>", "exec"), ns)
    require(len(handlers) == 1, "unexpected number of ABB probe handlers")
    probe = handlers[0]
    require(probe.reg.base == 0x8960 and probe.reg.count == 2, "ABB model probe changed")
    require(probe.methods == ["rtu", "tcp"] and probe.units == [1, 2], "ABB discovery changed")
    require(probe.models[abb_b21.MODEL_ID]["handler"] is ns["ABB_Meter_1P"], "ABB B21 handler changed")
    meter = ns["ABB_Meter_1P"]()
    meter.device_init()
    require(meter.nr_phases == 1, "ABB B21 is not single-phase")
    observed = {r.name: (r.base, r.count, getattr(r, "scale", 1))
                for r in meter.info_regs + meter.data_regs}
    wanted = {path: (r.address, r.count, r.scale) for r in abb_b21.REGISTERS
              for path in ((r.path,) + r.aliases) if path is not None}
    require(observed == wanted, "ABB register map / total and L1 aliases differ")
    definitions(sources["device.py"],
                ["RegList", "contains_any", "pack_list", "modbus_overhead"], ns)
    hole = (ns["modbus_overhead"]("tcp") + 1)//2
    packed = ns["pack_list"](list(meter.data_regs), "holding", hole, None)
    blocks = tuple((g[0].base, g[-1].base + g[-1].count - g[0].base) for g in packed)
    require(blocks == abb_b21.POLL_BLOCKS, f"ABB polling blocks differ: {blocks!r}")

    live = reader is not None
    if not live:
        # Known physical vectors, independently decoded by the official classes.
        words = {}
        values = {"model": abb_b21.MODEL_ID, "serial": 10000001,
                  "voltage_l1": 230.1, "current_l1": 12.34,
                  "power_total": -1234.56, "frequency": 50}
        encoded = {name: encode_number(value, abb_b21.BY_NAME[name]) for name, value in values.items()}
        encoded.update(firmware_version=abb_b21.firmware_words(),
                       energy_import=abb_b21.energy_wh_to_raw(12345678),
                       energy_export=abb_b21.energy_wh_to_raw(123450), power_factor=(0x7fff,))
        for name, values in encoded.items():
            address = abb_b21.BY_NAME[name].address
            words.update({address+i: word for i, word in enumerate(values)})
        reader = lambda address, count: [words.get(a, 0) for a in range(address, address+count)]

    probe.reg.decode(reader(probe.reg.base, probe.reg.count))
    require(probe.reg.value == abb_b21.MODEL_ID, "live ABB model does not match")
    decoded = {}
    for reg in meter.info_regs:
        reg.decode(reader(reg.base, reg.count))
        decoded[reg.name] = reg.value
    for group in packed:
        start = group[0].base
        count = group[-1].base+group[-1].count-start
        data = reader(start, count)
        for reg in group:
            reg.decode(data[reg.base-start:reg.base-start+reg.count])
            decoded[reg.name] = reg.value
    for suffix in ("Forward", "Reverse"):
        require(decoded[f"/Ac/Energy/{suffix}"] == decoded[f"/Ac/L1/Energy/{suffix}"],
                f"ABB {suffix} total/L1 mismatch")
    require(decoded["/Ac/Power"] == decoded["/Ac/L1/Power"], "ABB total/L1 power mismatch")
    require(decoded["/Ac/PowerFactor"] is None and decoded["/Ac/L1/PowerFactor"] is None,
            "ABB unknown power factor is not null")
    if not live:
        for path, expected in (("/Ac/Energy/Forward", 12345.67), ("/Ac/Energy/Reverse", 123.45),
                               ("/Serial", "10000001"), ("/Ac/Power", -1234.56),
                               ("/Ac/L1/Voltage", 230.1), ("/Ac/L1/Current", 12.34)):
            require(decoded[path] == expected, f"ABB official decoder disagrees: {path}")
    return decoded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="use an existing pinned source tree offline")
    parser.add_argument("--abb-host", help="also read a live ABB B21 server using the pinned official decoders")
    parser.add_argument("--port", type=int, default=502)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "docs/upstream.json").read_text())
    sources = {}
    for name, expected_hash in manifest["files"].items():
        if args.source_dir:
            data = (args.source_dir / name).read_bytes()
        else:
            url = f"https://raw.githubusercontent.com/victronenergy/dbus-modbus-client/{manifest['commit']}/{name}"
            with urlopen(url, timeout=20) as response:
                data = response.read()
        blob = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
        require(hashlib.sha1(blob).hexdigest() == expected_hash, f"Git blob hash differs: {name}")
        sources[name] = data.decode("utf-8")
    audit(sources)
    audit_abb(sources)
    print(f"OK — {len(sources)} sources verified at {manifest['commit']}")
    print("EM24 discovery/initialization and ABB B21 discovery, register maps, polling blocks and decoders verified.")
    if args.abb_host:
        from pymodbus.client import ModbusTcpClient
        with ModbusTcpClient(args.abb_host, port=args.port, timeout=2, retries=0) as client:
            def read(address, count):
                result = client.read_holding_registers(address, count=count, device_id=1)
                require(not result.isError(), f"live read failed at 0x{address:04X}: {result}")
                return result.registers
            report = audit_abb(sources, read)
        print("Live TCP decoded with official ABB classes: " + json.dumps(report, sort_keys=True))
    print("These checks do not replace validation on the actual GX / D-Bus / display.")


if __name__ == "__main__":
    main()
