"""Reads PNG tEXt/zTXt/iTXt text chunks - the mechanism ComfyUI (and most
Stable Diffusion tools) use to embed generation metadata directly in the
image file. Hand-rolled rather than pulling in Pillow: PNG's text-chunk
layout is simple and well documented, and the app's only dependency stays PySide6.
"""

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def read_png_text_chunks(path):
    """Returns {keyword: text} for every text chunk in the file, or {} if
    it's not a PNG / has none. ComfyUI writes a 'prompt' chunk (the executed
    API-format graph) and a 'workflow' chunk (the UI-format graph) as plain
    tEXt; A1111-family tools write a 'parameters' chunk the same way."""
    result = {}
    try:
        with open(path, "rb") as f:
            if f.read(8) != PNG_SIGNATURE:
                return result
            while True:
                length_bytes = f.read(4)
                if len(length_bytes) < 4:
                    break
                length = struct.unpack(">I", length_bytes)[0]
                chunk_type = f.read(4).decode("ascii", errors="replace")
                data = f.read(length)
                f.read(4)  # CRC - not verified, corruption would fail JSON parsing anyway
                if chunk_type == "tEXt":
                    _parse_text_chunk(data, result)
                elif chunk_type == "zTXt":
                    _parse_ztxt_chunk(data, result)
                elif chunk_type == "iTXt":
                    _parse_itxt_chunk(data, result)
                elif chunk_type == "IEND":
                    break
    except OSError:
        return {}
    return result


def _parse_text_chunk(data, result):
    if b"\x00" not in data:
        return
    key, _, value = data.partition(b"\x00")
    result[key.decode("latin-1", errors="replace")] = value.decode("latin-1", errors="replace")


def _parse_ztxt_chunk(data, result):
    if b"\x00" not in data:
        return
    key, _, rest = data.partition(b"\x00")
    if not rest:
        return
    compressed = rest[1:]  # rest[0] is the compression method byte (always 0 = zlib)
    try:
        value = zlib.decompress(compressed).decode("utf-8", errors="replace")
    except (zlib.error, OSError):
        return
    result[key.decode("latin-1", errors="replace")] = value


def _parse_itxt_chunk(data, result):
    try:
        null1 = data.index(b"\x00")
        keyword = data[:null1]
        compression_flag = data[null1 + 1]
        rest = data[null1 + 3:]  # skip compression flag + compression method bytes
        null2 = rest.index(b"\x00")
        rest2 = rest[null2 + 1:]  # skip language tag
        null3 = rest2.index(b"\x00")
        text_bytes = rest2[null3 + 1:]  # skip translated keyword
        if compression_flag == 1:
            text_bytes = zlib.decompress(text_bytes)
        result[keyword.decode("utf-8", errors="replace")] = text_bytes.decode("utf-8", errors="replace")
    except (ValueError, IndexError, zlib.error):
        return
