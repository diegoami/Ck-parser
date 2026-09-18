"""Finding individual characters in a save without reading every record."""

from __future__ import annotations

from .container import open_gamestate_text
from .parser import Block, PushbackLines, iter_children

#: Where character records live, in the order worth searching.
SECTIONS = (("living",), ("dead_unprunable",), ("characters", "dead_prunable"))


def find_characters(save_path: str, wanted: set[int], sections=SECTIONS) -> dict[int, Block]:
    """Stream the given sections once each, keeping only the wanted ids."""
    found: dict[int, Block] = {}
    if not wanted:
        return found
    for section in sections:
        missing = wanted - found.keys()
        if not missing:
            break
        with open_gamestate_text(save_path) as lines:
            for cid, char in iter_children(PushbackLines(lines), section):
                try:
                    cid_int = int(cid)
                except (TypeError, ValueError):
                    continue
                if cid_int in missing and isinstance(char, Block):
                    found[cid_int] = char
                    missing.discard(cid_int)
                    if not missing:
                        break
    return found


def living_characters(save_path: str, wanted: set[int]) -> dict[int, Block]:
    """The wanted ids that are in ``living`` and not already marked dead.

    Both conditions are needed: a character who died on the save's own date can
    still sit in ``living`` carrying a ``dead_data`` block.
    """
    found = find_characters(save_path, wanted, sections=(("living",),))
    return {cid: char for cid, char in found.items() if char.get("dead_data") is None}
