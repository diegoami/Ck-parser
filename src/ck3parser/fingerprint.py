"""Tier-1 fingerprint: everything needed to group and order a save, read from
the plaintext header plus the first few KB of the decompressing ``gamestate``.

On the sample saves this needs ~32 KB of decompressed data and ~3 ms per file.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .container import open_gamestate, read_header
from .parser import Block, parse_text

_TOP_KEYS = ("date", "bookmark_date", "first_start", "random_seed", "random_count")


def _stable_hash(items: list) -> str:
    return hashlib.sha1(json.dumps(sorted(str(x) for x in items)).encode()).hexdigest()[:16]


@dataclass
class Fingerprint:
    file: str
    size: int
    sha256: str | None
    version: str | None
    date: str | None
    meta_real_date: str | None
    bookmark_date: str | None
    first_start: bool | None
    random_seed: int | None
    random_count: int | None
    ironman: bool | None
    player_name: str | None
    title_name: str | None
    house_name: str | None
    played_character: int | None
    dlcs_hash: str
    rules_hash: str
    header_unknown: str

    @property
    def run_key(self) -> tuple:
        """What tells one playthrough from another.

        The seed and the game version carry it: `version` is the version the run
        was *started* on rather than the one it was last saved with (§5), so it
        is a property of the run and cannot drift mid-run. The bookmark, rules
        and DLC set are included because two runs that differ in any of them are
        not the same playthrough either.
        """
        return (self.random_seed, self.version, self.bookmark_date, self.rules_hash, self.dlcs_hash)

    @property
    def chain_key(self) -> tuple:
        """The run key without the DLC set: what grouping buckets on (#30).

        A player can enable or disable a DLC mid-playthrough and keep playing
        the same game, so a changed DLC set alone does not make another run.
        Inside a bucket, `runs` accepts a change of DLC set only where the
        legacy chain proves the two saves are one playthrough.
        """
        return (self.random_seed, self.version, self.bookmark_date, self.rules_hash)

    @property
    def run_id(self) -> str:
        return (
            f"{self.random_seed}-{self.version}-{self.bookmark_date}"
            f"-{self.rules_hash[:6]}-{self.dlcs_hash[:6]}"
        )

    @property
    def run_slug(self) -> str:
        """A short, filesystem and URL safe name for this run: seed and version."""
        version = re.sub(r"[^0-9A-Za-z]+", "-", str(self.version or "unknown")).strip("-")
        return f"{self.random_seed}-{version}"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Fingerprint":
        return cls(**d)


def sha256_of(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_gamestate_prelude(path: str | Path, zip_offset: int, stop_key: str = "random_count", limit: int = 1 << 20) -> str:
    """Decompress the gamestate only until ``stop_key=`` has been seen."""
    needle = f"\n{stop_key}=".encode()
    buf = b""
    with open_gamestate(path, zip_offset) as g:
        while needle not in buf and len(buf) < limit:
            chunk = g.read(8192)
            if not chunk:
                break
            buf += chunk
    # cut at the end of the line containing the needle so the parser sees a complete pair
    i = buf.find(needle)
    if i >= 0:
        j = buf.find(b"\n", i + 1)
        if j >= 0:
            buf = buf[: j + 1]
    return buf.decode("utf-8", "replace")


def _top_scalars(prelude: str) -> dict[str, Any]:
    """Pull the few top-level scalars from the prelude without a full parse."""
    out: dict[str, Any] = {}
    for line in prelude.splitlines():
        if "=" in line and not line.startswith(("\t", " ", "}")):
            key, _, value = line.partition("=")
            if key in _TOP_KEYS:
                v: Any = value.strip()
                if v.isdigit():
                    v = int(v)
                elif v in ("yes", "no"):
                    v = v == "yes"
                out[key] = v
    return out


def fingerprint(path: str | Path, with_sha256: bool = True) -> Fingerprint:
    path = Path(path)
    header = read_header(path)
    meta: Block = header.meta
    top = _top_scalars(read_gamestate_prelude(path, header.zip_offset))
    portrait = meta.get("meta_main_portrait")
    played = portrait.get("id") if isinstance(portrait, Block) else None
    rules = meta.get("game_rules")
    settings = rules.get("settings", []) if isinstance(rules, Block) else []
    dlcs = meta.get("dlcs", []) or []
    return Fingerprint(
        file=str(path),
        size=path.stat().st_size,
        sha256=sha256_of(path) if with_sha256 else None,
        version=meta.get("version"),
        date=top.get("date") or meta.get("meta_date"),
        meta_real_date=meta.get("meta_real_date"),
        bookmark_date=top.get("bookmark_date"),
        first_start=top.get("first_start"),
        random_seed=top.get("random_seed"),
        random_count=top.get("random_count"),
        ironman=meta.get("ironman"),
        player_name=meta.get("meta_player_name"),
        title_name=meta.get("meta_title_name"),
        house_name=meta.get("meta_house_name"),
        played_character=played,
        dlcs_hash=_stable_hash(list(dlcs)),
        rules_hash=_stable_hash(list(settings)),
        header_unknown=header.unknown_field,
    )
