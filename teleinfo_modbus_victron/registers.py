"""Explicit wire formats shared by the supported meter profiles."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class RegisterSpec:
    name: str
    address: int
    count: int
    encoding: Literal["u16", "s16", "s32l", "s32b", "u32b", "u64b", "version", "ascii"]
    scale: int = 1
    unit: str = ""
    path: str | None = None
    writable: bool = False
    measurement: bool = False
    aliases: tuple[str, ...] = ()


def encode_number(value: int | float | Decimal, spec: RegisterSpec) -> tuple[int, ...]:
    """Scale and truncate toward zero, reject overflow, then order 16-bit words.

    Each word is transmitted MSB first. Only s32l places the low word first.
    """
    formats = {"u16": (16, False), "s16": (16, True), "s32l": (32, True),
               "s32b": (32, True), "u32b": (32, False), "u64b": (64, False)}
    if spec.encoding not in formats:
        raise ValueError("not a numeric register")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("measurement must be finite")
    raw = int(number * spec.scale)
    bits, signed = formats[spec.encoding]
    low, high = (-(2**(bits-1)), 2**(bits-1)-1) if signed else (0, 2**bits-1)
    if not low <= raw <= high:
        raise ValueError("scaled measurement outside register range")
    shifts = range(bits//16) if spec.encoding == "s32l" else reversed(range(bits//16))
    return tuple((raw >> (16*i)) & 0xffff for i in shifts)
