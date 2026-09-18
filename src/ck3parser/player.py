"""Who was being played, and what their wiki should be about.

A run's natural subject is the played character's **primary title**, which is
the first entry of their ``landed_data.domain``. That was checked across the
three sample saves and across a succession: all three give `e_germany`, the
player's empire, even though the ruler changed (docs/PLAN.md §9).

The played character's id is in the save's plaintext header, so finding the
title costs one scan of ``living`` and one of ``landed_titles``, not a full
read of the file.
"""

from __future__ import annotations

from .characters import living_characters
from .fingerprint import Fingerprint, fingerprint
from .parser import Block
from .titles import TitleIndex, build_index


def primary_title_key(
    save_path: str,
    fp: Fingerprint | None = None,
    index: TitleIndex | None = None,
) -> str | None:
    """The played character's primary title key, or None if it cannot be found."""
    fp = fp or fingerprint(save_path, with_sha256=False)
    if fp.played_character is None:
        return None
    character = living_characters(save_path, {fp.played_character}).get(fp.played_character)
    if character is None:
        return None
    landed = character.get("landed_data")
    domain = landed.get("domain") if isinstance(landed, Block) else None
    if not isinstance(domain, list) or not domain:
        return None
    index = index or build_index(save_path, keep_history=False)
    record = index.resolve(domain[0])
    return record.key if record is not None else None
