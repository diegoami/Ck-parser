"""The ``.ck3`` container.

A save file is::

    SAV0102<8 hex><8 hex>\\n      first line; the last 8 hex digits are the byte
                                  length of the meta_data text that follows
    meta_data={ ... }\\n          plaintext Clausewitz block
    PK\\x03\\x04 ...               a zip archive with one member, ``gamestate``

Verified on three real saves (see docs/PLAN.md). The middle 8 hex digits are
not understood yet and are exposed untouched.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

from .parser import Block, parse_text

MAGIC = b"SAV0102"
ZIP_MAGIC = b"PK\x03\x04"
GAMESTATE_MEMBER = "gamestate"


class NotACk3Save(ValueError):
    pass


@dataclass
class SaveHeader:
    path: Path
    first_line: str
    meta_text: str
    meta: Block
    zip_offset: int

    @property
    def unknown_field(self) -> str:
        """The middle 8 hex digits of the first line (meaning unknown)."""
        return self.first_line[7:15]

    def get(self, key: str, default=None):
        return self.meta.get(key, default)


def read_header(path: str | Path) -> SaveHeader:
    """Read and parse the plaintext part of a ``.ck3`` file.

    Uses the length field on the first line; falls back to searching for the
    zip signature if the field does not line up (defensive: only the length
    interpretation has been verified, on three saves).
    """
    path = Path(path)
    with open(path, "rb") as f:
        first = f.readline()
        if not first.startswith(MAGIC):
            raise NotACk3Save(f"{path}: first line does not start with {MAGIC!r}")
        first_text = first.rstrip(b"\r\n").decode("ascii", "replace")
        try:
            declared = int(first_text[-8:], 16)
        except ValueError:
            declared = -1
        meta_bytes = f.read(declared) if declared >= 0 else b""
        probe = f.read(4)
        if declared < 0 or probe != ZIP_MAGIC:
            # Fall back: scan for the zip signature from the start of meta_data.
            f.seek(len(first))
            blob = f.read()
            pk = blob.find(ZIP_MAGIC)
            if pk < 0:
                raise NotACk3Save(f"{path}: no zip archive found after header")
            meta_bytes = blob[:pk]
            zip_offset = len(first) + pk
        else:
            zip_offset = len(first) + declared
    meta_text = meta_bytes.decode("utf-8", "replace")
    parsed = parse_text(meta_text)
    meta = parsed.get("meta_data")
    if not isinstance(meta, Block):
        raise NotACk3Save(f"{path}: header has no meta_data block")
    return SaveHeader(path=path, first_line=first_text, meta_text=meta_text, meta=meta, zip_offset=zip_offset)


class _Slice(io.RawIOBase):
    """A file-like view starting at ``offset`` of an underlying binary file."""

    def __init__(self, fh: BinaryIO, offset: int):
        self._fh = fh
        self._off = offset
        fh.seek(offset)

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, pos, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            return self._fh.seek(self._off + pos) - self._off
        if whence == io.SEEK_CUR:
            return self._fh.seek(pos, io.SEEK_CUR) - self._off
        return self._fh.seek(pos, io.SEEK_END) - self._off

    def tell(self):
        return self._fh.tell() - self._off

    def readinto(self, b):
        data = self._fh.read(len(b))
        b[: len(data)] = data
        return len(data)

    def close(self):
        try:
            self._fh.close()
        finally:
            super().close()


def open_gamestate(path: str | Path, zip_offset: int | None = None) -> BinaryIO:
    """Return a binary stream over the decompressing ``gamestate`` member.

    Nothing is extracted to disk; the caller reads as much as it needs.
    """
    if zip_offset is None:
        zip_offset = read_header(path).zip_offset
    fh = open(path, "rb")
    zf = zipfile.ZipFile(io.BufferedReader(_Slice(fh, zip_offset)))
    return zf.open(GAMESTATE_MEMBER)


def open_gamestate_text(path: str | Path, zip_offset: int | None = None) -> io.TextIOWrapper:
    return io.TextIOWrapper(open_gamestate(path, zip_offset), encoding="utf-8", errors="replace", newline="\n")


def extract_gamestate(path: str | Path, dest: str | Path, chunk_size: int = 1 << 22) -> Path:
    """Stream the ``gamestate`` member to ``dest`` and return its path."""
    dest = Path(dest)
    with open_gamestate(path) as src, open(dest, "wb") as out:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            out.write(chunk)
    return dest


def iter_gamestate_lines(path: str | Path) -> Iterator[str]:
    with open_gamestate_text(path) as f:
        yield from f


_HEX8 = re.compile(r"^[0-9a-f]{8}$")


def make_first_line(meta_text: bytes | str, unknown: str = "00000000") -> bytes:
    """Build a first line for a synthetic save (used by tests and fixtures)."""
    if isinstance(meta_text, str):
        meta_text = meta_text.encode("utf-8")
    if not _HEX8.match(unknown):
        raise ValueError("unknown field must be 8 lowercase hex digits")
    return MAGIC + unknown.encode() + f"{len(meta_text):08x}".encode() + b"\n"


def write_save(path: str | Path, meta_text: str, gamestate_text: str, unknown: str = "00000000") -> Path:
    """Write a synthetic ``.ck3`` file with the real container layout."""
    path = Path(path)
    meta_bytes = meta_text.encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(GAMESTATE_MEMBER, gamestate_text.encode("utf-8"))
    with open(path, "wb") as f:
        f.write(make_first_line(meta_bytes, unknown))
        f.write(meta_bytes)
        f.write(buf.getvalue())
    return path
