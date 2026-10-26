"""Bounded incremental standard TIC framing and checksums (Enedis CPT_002E).

Group checksum covers the label through the last HT, including that HT.
An invalid group rejects its entire frame; EOT/oversize/STX resynchronize.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Group:
    value: str
    timestamp: str | None = None


def parse_frame(body: bytes) -> dict[str, Group]:
    if not body or not body.endswith(b"\r"):
        raise ValueError("incomplete TIC frame")
    result = {}
    for line in body[:-1].split(b"\r"):
        if not line.startswith(b"\n") or len(line) < 5 or line[-2] != 9:
            raise ValueError("invalid TIC group structure")
        if line[-1] != (sum(line[1:-1]) & 0x3F) + 0x20:
            raise ValueError("TIC checksum mismatch")
        parts = line[1:-2].split(b"\t")
        if len(parts) not in (2, 3):
            raise ValueError("invalid TIC field count")
        try:
            label = parts[0].decode("ascii")
            value = parts[-1].decode("ascii")
            timestamp = parts[1].decode("ascii") if len(parts) == 3 else None
        except UnicodeDecodeError as exc:
            raise ValueError("non-ASCII TIC group") from exc
        if not re.fullmatch(r"[A-Z][A-Z0-9+\-]{0,15}", label) or label in result:
            raise ValueError("invalid or duplicate TIC label")
        if any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise ValueError("invalid TIC value characters")
        if timestamp is not None and not re.fullmatch(r"[HEhe]\d{12}", timestamp):
            raise ValueError("invalid TIC timestamp")
        if not value and label != "DATE":
            raise ValueError("empty TIC value")
        result[label] = Group(value, timestamp)
    return result


class TICParser:
    def __init__(self, max_frame_size: int = 16384):
        self.max_frame_size = max_frame_size
        self.buffer: bytearray | None = None
        self.valid_frames = 0
        self.invalid_frames = 0

    def feed(self, chunk: bytes) -> list[dict[str, Group] | None]:
        frames = []
        for char in chunk:
            if char == 2:
                if self.buffer is not None:
                    self.invalid_frames += 1
                    frames.append(None)
                self.buffer = bytearray()
            elif char == 4:
                if self.buffer is not None:
                    self.invalid_frames += 1
                    frames.append(None)
                self.buffer = None
            elif char == 3:
                if self.buffer is None:
                    continue
                try:
                    frames.append(parse_frame(bytes(self.buffer)))
                    self.valid_frames += 1
                except ValueError:
                    self.invalid_frames += 1
                    frames.append(None)
                self.buffer = None
            elif self.buffer is not None:
                self.buffer.append(char)
                if len(self.buffer) > self.max_frame_size:
                    self.invalid_frames += 1
                    frames.append(None)
                    self.buffer = None
        return frames
