"""Referenced-vs-filler character heuristic.

A large share of ``dead_unprunable`` is bulk-generated filler: placeholder
characters with identical birth/death dates that no title, dynasty or family
ever references. The rule for the first pass:

    keep a character if its id is referenced by any title holder/history entry,
    any ``family_data`` link of a kept character, or the played-character legacy;
    otherwise drop it.

This is a stub in the sense that the reference sources are the ones listed
above only. Extend ``collect_referenced_ids`` as new sections are parsed.
"""

from __future__ import annotations

from typing import Iterable

from .parser import Block

_FAMILY_KEYS = ("spouse", "former_spouses", "child", "children", "father", "real_father", "mother", "primary_spouse", "concubine")


def title_holder_ids(title: Block) -> set[int]:
    ids: set[int] = set()
    holder = title.get("holder")
    if isinstance(holder, int):
        ids.add(holder)
    history = title.get("history")
    if isinstance(history, Block):
        for _, value in history:
            if isinstance(value, int):
                ids.add(value)
            elif isinstance(value, Block):
                h = value.get("holder")
                if isinstance(h, int):
                    ids.add(h)
    return ids


def family_ids(character: Block) -> set[int]:
    ids: set[int] = set()
    fam = character.get("family_data")
    if isinstance(fam, Block):
        for key, value in fam:
            if key in _FAMILY_KEYS:
                if isinstance(value, int):
                    ids.add(value)
                elif isinstance(value, list):
                    ids.update(v for v in value if isinstance(v, int))
    return ids


def collect_referenced_ids(titles: Iterable[Block], legacy_ids: Iterable[int] = ()) -> set[int]:
    ids = set(legacy_ids)
    for title in titles:
        ids |= title_holder_ids(title)
    return ids


def is_filler(char_id: int, character: Block, referenced: set[int]) -> bool:
    """True when the character is not referenced and has no dynasty house."""
    if char_id in referenced:
        return False
    return character.get("dynasty_house") is None


def filter_characters(characters: Iterable[tuple[int, Block]], referenced: set[int]) -> Iterable[tuple[int, Block]]:
    """Yield the characters to keep, expanding ``referenced`` with their family links."""
    for char_id, character in characters:
        if is_filler(char_id, character, referenced):
            continue
        referenced |= family_ids(character)
        yield char_id, character
