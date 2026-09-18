"""Coat-of-arms definitions, and naming an arms image by what it looks like.

`coat_of_arms.coat_of_arms_manager_database` maps an arms id to the recipe the
game draws from: a pattern, some colours, and one or more emblems.

    {pattern=pattern_solid.dds, color1=red, color2=red, color3=white,
     colored_emblem={color1=white, color2=white, texture=ce_eagle.dds,
                     instance={scale=[0.9, 0.9]}}}

That recipe **is** the picture's identity, and it is the only thing that is.
The id is an index inside one save, and whether the arms are fixed or generated
cannot be told from the dynasty they belong to: of 60 dynasties carrying the
game's own named key and present in two playthroughs, 57 had *different*
artwork, while 55 of 60 numerically-keyed ones matched. CK3 generates arms for
anything the game files do not author, and nothing in the save says which is
which (docs/PLAN.md §11).

So an image is named after a digest of its recipe. Identical artwork gets one
name in every run and every chronicle and is harvested once; different artwork
gets different names. Nothing has to be classified, and the companion can skip
harvesting altogether and compose the arms from the recipe, which the manifest
carries for exactly that reason.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .container import open_gamestate_text
from .parser import Block, PushbackLines, Quoted, iter_children

#: Where the recipes live.
SECTION = ("coat_of_arms", "coat_of_arms_manager_database")

#: How many hex characters of the digest to keep, as for save checksums.
DIGEST_LENGTH = 12


def as_pairs(value: object) -> object:
    """A definition as JSON-safe data, losing nothing.

    Keys repeat -- `colored_emblem` appears once per emblem -- so a block
    becomes a list of `[key, value]` pairs rather than an object. A dict would
    silently keep one emblem of three.
    """
    if isinstance(value, Block):
        return [[key, as_pairs(item)] for key, item in value.items()]
    if isinstance(value, list):
        return [as_pairs(item) for item in value]
    if isinstance(value, Quoted):
        return str(value)
    return value


def canonical(value: object) -> str:
    """One deterministic string for a definition, order preserved.

    Order is part of the recipe: emblems are drawn in the order they are listed,
    so two definitions that differ only in order are different pictures and must
    not collapse to one name.
    """
    if isinstance(value, Block):
        return "{" + ",".join(f"{key}={canonical(item)}" for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(canonical(item) for item in value) + "]"
    return str(value)


def digest(definition: object) -> str:
    """The name an arms image is known by, everywhere."""
    return hashlib.sha256(canonical(definition).encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


@dataclass
class CoatOfArms:
    id: int  #: the index in the save it was read from, never global
    digest: str  #: the same picture has the same digest in every save
    definition: object  #: JSON-safe, for a companion that would rather render it


def read_arms(save_path: str, wanted: set[int]) -> dict[int, CoatOfArms]:
    """The recipes for the wanted arms ids, streaming the section once."""
    found: dict[int, CoatOfArms] = {}
    if not wanted:
        return found
    with open_gamestate_text(save_path) as lines:
        for key, block in iter_children(PushbackLines(lines), SECTION):
            try:
                arms_id = int(key)
            except (TypeError, ValueError):
                continue
            if arms_id not in wanted or not isinstance(block, Block):
                continue
            found[arms_id] = CoatOfArms(
                id=arms_id, digest=digest(block), definition=as_pairs(block)
            )
            if len(found) == len(wanted):
                break
    return found
