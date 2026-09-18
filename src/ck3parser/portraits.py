"""Naming the images the companion project harvests.

The wiki links an image for every character in every save it appears in, and
for every house's coat of arms, whether or not the file exists yet. The
companion project (`diegoami/ck_portrait_generator`) harvests the missing ones,
so both sides have to derive the same name without talking to each other:

    portrait:  sha256(save file's base name)[:12] + "_" + character id + ".png"
    arms:      sha256(save file's base name)[:12] + "_arms_" + coat of arms id + ".png"

The **name** of the save file is hashed, not its contents, so either side can
compute it without opening 70 MB, and the companion only has to keep a map from
save file name to checksum. Hashing rather than using the name directly keeps
the file names short and free of spaces and punctuation.

Keying on the save rather than the date is what gives a character one portrait
per save: the same person at three dates is three images, which is the point
(docs/PLAN.md §7). Scoping arms by save matters for a different reason: a
`coat_of_arms_id` is an index inside one run, so the same number means different
arms in a different playthrough.
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


def arms_name(save_file: str | Path, coat_of_arms_id: int) -> str:
    """The coat of arms of one house, as the save it was read from numbers it."""
    return f"{save_checksum(save_file)}_arms_{coat_of_arms_id}.png"
