"""Profile pictures: what the service takes, read from the image's own bytes
(never from what the client says it is). PNG, JPEG or WebP only (no SVG: a
picture can't carry a script), small, and of a sensible size."""

from __future__ import annotations

from .errors import InvalidImage

MAX_AVATAR_BYTES = 256 * 1024
MAX_AVATAR_SIDE = 1024  # pixels, each way (the portal sends 256 x 256)

# the JPEG frame headers that say the image's size (not DHT C4, JPG C8, DAC CC)
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # (fill bytes)
            i += 1
            continue
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:  # (markers without a length)
            i += 2
            continue
        if marker in _SOF:
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        return int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def image_size(data: bytes, kind: str) -> tuple[int, int] | None:
    """(width, height), from the image's header."""
    if kind == "image/png":
        if len(data) < 24 or data[12:16] != b"IHDR":
            return None
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if kind == "image/jpeg":
        return _jpeg_size(data)
    if kind == "image/webp":
        return _webp_size(data)
    return None


def check_avatar(data: bytes) -> str:
    """The picture's type (image/png, image/jpeg, image/webp), or InvalidImage."""
    if not data:
        raise InvalidImage("send an image")
    if len(data) > MAX_AVATAR_BYTES:
        raise InvalidImage(f"a profile picture is {MAX_AVATAR_BYTES // 1024} KB at most")
    kind = image_type(data)
    if kind is None:
        raise InvalidImage("a profile picture is a PNG, JPEG or WebP image")
    size = image_size(data, kind)
    if size is None:
        raise InvalidImage("this image can't be read")
    if not (1 <= size[0] <= MAX_AVATAR_SIDE and 1 <= size[1] <= MAX_AVATAR_SIDE):
        raise InvalidImage(f"a profile picture is {MAX_AVATAR_SIDE} pixels wide and high at most")
    return kind
