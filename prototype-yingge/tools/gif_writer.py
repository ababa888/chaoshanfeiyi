"""最小 GIF89a 动画编码器（纯标准库 + pygame，不依赖 Pillow）。

只服务于 `gen_assets.py` 的好汉预览 GIF：
- 全局调色板（≤256 色），像素逐字节精确匹配，不做抖动。
- 每帧全画布重绘（disposal=1），无局部调色板、无半透明。
"""
from __future__ import annotations

import math
import struct

import pygame


def _lzw(indices: list[int], min_code_size: int) -> bytes:
    clear = 1 << min_code_size
    end = clear + 1
    table: dict[tuple[int, int], int] = {}
    next_code = end + 1
    code_size = min_code_size + 1
    out = bytearray()
    bits = 0
    nbits = 0

    def emit(code: int) -> None:
        nonlocal bits, nbits
        bits |= code << nbits
        nbits += code_size
        while nbits >= 8:
            out.append(bits & 0xFF)
            bits >>= 8
            nbits -= 8

    emit(clear)
    prefix = indices[0]
    for k in indices[1:]:
        key = (prefix, k)
        if key in table:
            prefix = table[key]
            continue
        emit(prefix)
        if next_code < 4096:
            table[key] = next_code
            next_code += 1
            # 编码端比解码端早建一档，必须晚一步加宽码长
            if next_code > (1 << code_size) and code_size < 12:
                code_size += 1
        else:
            emit(clear)
            table.clear()
            next_code = end + 1
            code_size = min_code_size + 1
        prefix = k
    emit(prefix)
    emit(end)
    if nbits:
        out.append(bits & 0xFF)
    return bytes(out)


def _sub_blocks(data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 255):
        chunk = data[i:i + 255]
        out.append(len(chunk))
        out.extend(chunk)
    out.append(0)
    return bytes(out)


def write_gif(path: str, frames: list[pygame.Surface],
              palette: list[tuple[int, int, int]],
              delays_ms: list[int]) -> tuple[int, int]:
    """写全帧动画 GIF，返回 (宽, 高)。frames 必须同尺寸且只含调色板颜色。"""
    if not frames:
        raise ValueError("no frames")
    w, h = frames[0].get_size()
    for f in frames:
        if f.get_size() != (w, h):
            raise ValueError("frame size mismatch")

    colors = list(dict.fromkeys(palette))
    if len(colors) > 256:
        raise ValueError("palette > 256")
    bits = max(1, math.ceil(math.log2(len(colors) + 1)))
    table = colors + [(0, 0, 0)] * ((1 << bits) - len(colors))

    lookup = {c: i for i, c in enumerate(colors)}
    nearest: dict[tuple[int, int, int], int] = {}

    def index_of(rgb: tuple[int, int, int]) -> int:
        i = lookup.get(rgb)
        if i is not None:
            return i
        i = nearest.get(rgb)
        if i is None:
            i = min(range(len(colors)),
                    key=lambda j: sum((rgb[k] - colors[j][k]) ** 2
                                      for k in range(3)))
            nearest[rgb] = i
        return i

    header = bytearray(b"GIF89a")
    header += struct.pack("<HH", w, h)
    header += bytes((0x80 | 0x70 | (bits - 1), 0, 0))
    for r, g, b in table:
        header += bytes((r, g, b))
    # NETSCAPE 循环扩展：无限循环
    header += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00"

    body = bytearray()
    for surf, delay in zip(frames, delays_ms):
        raw = pygame.image.tostring(surf, "RGB")
        idx = [index_of((raw[i], raw[i + 1], raw[i + 2]))
               for i in range(0, len(raw), 3)]
        body += b"\x21\xF9\x04" + bytes((0x04,))       # disposal=1，无透明
        cs = max(2, min(100, int(round(delay / 10.0))))
        body += struct.pack("<H", cs) + b"\x00\x00"
        body += b"\x2C" + struct.pack("<HHHH", 0, 0, w, h) + bytes((0,))
        body += bytes((bits,)) + _sub_blocks(_lzw(idx, bits))
    body += b"\x3B"

    with open(path, "wb") as f:
        f.write(bytes(header) + bytes(body))
    return w, h
