"""Which version of the game an install is, and whether a save may use its files (#58).

Anything generated from the game's own files -- realm maps, the game's text
-- must come from **the version that wrote the save** (owner's requirement,
#58). Provinces are renumbered, baronies added and text rewritten between
patches, and output built from the wrong version looks right and is wrong.
Strict: a mismatch is skipped, naming both versions, with no override.

The install's version is `rawVersion` in `<CK3>/launcher/launcher-settings.json`
(older layouts keep the file at the install root), read the way the companion
reads it (`ck_portrait_generator/harvest/install.py`). A save's is its header's
`version`, which `Fingerprint.version` already carries -- possibly the version
its run *started* on rather than the one that wrote it (docs/PLAN.md §5,
unverified); it is the best a save says, and the companion compares the same.
"""

from __future__ import annotations

import json
from pathlib import Path


def game_version(game_dir: Path) -> str | None:
    """`rawVersion` of the install whose `game` directory this is, or None."""
    root = Path(game_dir).parent
    for candidate in (root / "launcher" / "launcher-settings.json", root / "launcher-settings.json"):
        try:
            # written with a UTF-8 byte-order mark
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        version = data.get("rawVersion") if isinstance(data, dict) else None
        if isinstance(version, str) and version:
            return version
    return None


def mismatch(install: str | None, save: str | None) -> str | None:
    """Why a save may not use this install's files, or None if it may.

    An unknown version on either side is a mismatch too: nothing can say the
    files are the right ones.
    """
    if not install:
        return "the install's version is unknown (no launcher-settings.json)"
    if not save:
        return "the save's version is unknown"
    if install != save:
        return f"the save was made on {save}, the install is {install}"
    return None
