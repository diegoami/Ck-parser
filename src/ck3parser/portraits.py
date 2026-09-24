"""Naming the images the companion project harvests.

The wiki links an image for every character in every save it appears in, and
for every house's coat of arms, whether or not the file exists yet. The
companion project (`diegoami/ck_portrait_generator`) harvests the missing ones,
so both sides have to derive the same name without talking to each other:

    portrait:  sha256(save file's base name)[:12] + "_" + character id + ".png"
    arms:      "arms_" + sha256(the coat of arms' own recipe)[:12] + ".png"

The **name** of the save file is hashed, not its contents, so either side can
compute it without opening 70 MB, and the companion only has to keep a map from
save file name to checksum. Hashing rather than using the name directly keeps
the file names short and free of spaces and punctuation.

Keying on the save rather than the date is what gives a character one portrait
per save: the same person at three dates is three images, which is the point
(docs/PLAN.md §7).

Arms are not keyed on the save at all, because they are not keyed on anything
the save numbers. A `coat_of_arms_id` is an index inside one run, so it cannot
name an image across runs, and whether a given coat of arms is fixed or
generated cannot be told from the dynasty carrying it. What identifies the
picture is the recipe the game draws it from, so that is what names it
(:mod:`ck3parser.arms`). The same arms are then one file everywhere and are
harvested once.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: How many hex characters of the digest to keep. 12 is ~10^14 combinations,
#: far beyond the number of saves anyone will publish, and stays readable.
CHECKSUM_LENGTH = 12

#: Where a chronicle keeps its images, relative to the chronicle's own root.
IMAGE_DIR = "portraits"


def save_checksum(save_file: str | Path) -> str:
    """The save's identity in an image file name: a hash of its base name."""
    name = Path(save_file).name
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:CHECKSUM_LENGTH]


def portrait_name(save_file: str | Path, character_id: int) -> str:
    """The portrait of one character as of one save."""
    return f"{save_checksum(save_file)}_{character_id}.png"


def realm_map_name(save_file: str | Path, title_key: str) -> str:
    """The subject title's realm on the map, as of one save (docs/PLAN.md §16).

    Keyed on the save like a portrait, because a realm is a snapshot's; and on
    the title, because the realm is the title holder's, whoever that is.
    Rendered by `ck3wiki.maps` from the game's own map files, not harvested.
    """
    return f"realm_{save_checksum(save_file)}_{title_key}.png"


def arms_name(digest: str) -> str:
    """One coat of arms, named after the recipe that draws it.

    `digest` comes from :func:`ck3parser.arms.digest`, so identical artwork has
    one name in every save and every chronicle.
    """
    return f"arms_{digest}.png"
