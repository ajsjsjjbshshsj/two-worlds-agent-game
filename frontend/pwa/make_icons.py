"""Original TwoWorlds paired circles/bridge icons, dedicated to CC0-1.0.

Standard-library PNG generation; no remote assets, fonts or account data.
Run: python pwa/make_icons.py
"""

from pathlib import Path
import math
import struct
import zlib


def icon(size):
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            coverage = 0
            for dx, dy in ((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)):
                px, py = (x + dx) / size, (y + dy) / size
                rings = (
                    min(
                        abs(math.hypot(px - cx, py - 0.5) - 0.155)
                        for cx in (0.35, 0.65)
                    )
                    < 0.009
                )
                bridge = 0.37 < px < 0.63 and abs(py - 0.5) < 0.01
                coverage += rings or bridge
            rows.extend(
                round(a + (b - a) * coverage / 4)
                for a, b in zip((9, 23, 37), (227, 189, 122))
            )

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "public" / "pwa"
    root.mkdir(parents=True, exist_ok=True)
    for name, size in [
        ("icon-192.png", 192),
        ("icon-512.png", 512),
        ("maskable-512.png", 512),
        ("apple-touch-icon.png", 180),
    ]:
        (root / name).write_bytes(icon(size))
