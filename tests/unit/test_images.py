from __future__ import annotations

import struct
import zlib

import pytest

from balatro_social.domain import MAX_AVATAR_BYTES, InvalidImage, check_avatar, image_size, image_type


def png(width: int, height: int) -> bytes:
    """A real PNG (grey pixels), to send like the portal does."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + b"\x80" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def jpeg(width: int, height: int) -> bytes:
    """A JPEG's start: APP0, then the frame header with its size (all the check reads)."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def webp_lossless(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    body = b"VP8L" + struct.pack("<I", 5) + b"\x2f" + struct.pack("<I", bits)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def webp_extended(width: int, height: int) -> bytes:
    body = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") \
        + (height - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def test_pictures_are_read_from_their_bytes() -> None:
    for data, kind, size in ((png(3, 2), "image/png", (3, 2)), (jpeg(640, 480), "image/jpeg", (640, 480)),
                             (webp_lossless(256, 256), "image/webp", (256, 256)),
                             (webp_extended(300, 200), "image/webp", (300, 200))):
        assert image_type(data) == kind and image_size(data, kind) == size
        assert check_avatar(data) == kind


def test_other_files_are_refused() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    for wrong in (b"", svg, b"GIF89a....", b"hello", png(2000, 10), jpeg(10, 4096), b"\x89PNG\r\n\x1a\n" + b"\x00" * 8,
                  png(10, 10) + b"\x00" * MAX_AVATAR_BYTES):
        with pytest.raises(InvalidImage):
            check_avatar(wrong)
