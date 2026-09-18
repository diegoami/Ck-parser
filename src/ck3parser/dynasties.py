"""Houses and dynasties, read out of a save.

A character carries a `dynasty_house` id. Houses live in
``dynasties.dynasty_house``; each names its parent dynasty, which lives in
``dynasties.dynasties`` and carries the `coat_of_arms_id`. Both sections are
large (49 891 houses and 48 099 dynasties in the 1364 save), so lookups are
targeted by id and streamed, never read whole.

Names are localization keys like `dynn_Strathearn` with an optional prefix key
like `dynnp_de`, so the same caveat as character names applies: this strips the
key prefix and nothing more (docs/PLAN.md §8). A dynasty that the game has
already localized carries a plain `localized_name` instead, and that is
preferred when it is there.

Verified on the 1364 save: of 48 099 dynasties, 45 689 have `coat_of_arms_id`,
41 128 a `name`, 2 210 a `localized_name`, 6 320 a `prefix`, and only 4 761 a
`key`. That `key` is the game's own identifier and is **not** a display name:
sometimes a number (`"2"`), sometimes a slug (`"welsh_ap_bleddri"`, `"bovisio"`),
so it is never shown. A **house**'s `key` is the opposite: `house_munso` is
exactly the name, and is the fallback for a house with no `name` of its own.

A house may carry its own `coat_of_arms_id`, and then that one wins; only a
house without one inherits its dynasty's.
"""

from __future__ import annotations

from dataclasses import dataclass

from .container import open_gamestate_text
from .parser import Block, PushbackLines, iter_children


def clean_key(raw: object, *prefixes: str) -> str:
    """``dynn_Strathearn`` -> ``Strathearn``; only the key prefix is removed."""
    text = str(raw or "")
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    return text.replace("_", " ").strip()


def titled(raw: object, *prefixes: str) -> str:
    """``heritage_east_african`` -> ``East African``. Cleans a key and capitalises.

    The key is lower case where the real name is not, so the words are
    capitalised. That is the same order of approximation as dropping a diacritic
    from a character name, and for the same reason: the game's localization
    files are not read here. Cultures, faiths and house keys all want it.
    """
    return clean_key(raw, *prefixes).title()


def _named(name: str, prefix: str) -> str:
    return f"{prefix} {name}".strip() if prefix else name


def from_house_key(key: str) -> str:
    """``house_munso`` -> ``Munso``.

    Only a house with no `name` of its own falls back to this. The key is lower
    case where the real name is not, so the words are capitalised — the same
    order of approximation as dropping diacritics from a character name, and
    for the same reason: the game's localization files are not read here.
    """
    return titled(key, "house_")


@dataclass
class Dynasty:
    id: int
    name: str = ""
    prefix: str = ""
    coat_of_arms_id: int | None = None
    head: int | None = None

    @property
    def display_name(self) -> str:
        return _named(self.name, self.prefix)


@dataclass
class House:
    id: int
    name: str = ""
    prefix: str = ""
    key: str = ""
    dynasty: int | None = None
    coat_of_arms_id: int | None = None
    head: int | None = None
    found_date: str | None = None
    motto: str = ""

    @property
    def display_name(self) -> str:
        return _named(self.name, self.prefix) or from_house_key(self.key)

    @property
    def founded(self) -> str | None:
        """The founding date, or None for a house the game shipped with.

        Unfounded houses are dated `9999.1.1`, which is a sentinel and not a
        date anyone wants to read (verified on the 1364 save).
        """
        return None if self.found_date in (None, "9999.1.1") else self.found_date


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _motto(raw: object) -> str:
    """The motto's localization key.

    A motto is usually a block, not a string: `{ key=motto_x_under_y_king
    variables={...} }`, where the variables fill placeholders in the key's
    localized text. Composing that needs the game's localization files, which
    this project does not read, so only the key is kept — and shown as a key,
    never dressed up as prose (verified on the 1364 save).
    """
    if isinstance(raw, Block):
        raw = raw.get("key")
    return str(raw or "") if isinstance(raw, (str, int)) else ""


def arms_id(house: House, dynasty: Dynasty | None) -> int | None:
    """Which coat of arms a house shows: its own if it has one, else its dynasty's.

    The one place this is decided. The wiki and the hand-off must agree, or the
    image a page links is not the image the companion is asked for.
    """
    if house.coat_of_arms_id is not None:
        return house.coat_of_arms_id
    return dynasty.coat_of_arms_id if dynasty else None


def house_name(house: House, dynasty: Dynasty | None) -> str:
    """What to call a house: its own name, else its dynasty's, else its id."""
    own = house.display_name
    inherited = dynasty.display_name if dynasty else ""
    return own or inherited or f"House {house.id}"


def find_houses(save_path: str, wanted: set[int]) -> dict[int, House]:
    """The wanted houses, streaming ``dynasties.dynasty_house`` once."""
    found: dict[int, House] = {}
    if not wanted:
        return found
    with open_gamestate_text(save_path) as lines:
        for key, block in iter_children(PushbackLines(lines), ("dynasties", "dynasty_house")):
            try:
                house_id = int(key)
            except (TypeError, ValueError):
                continue
            if house_id not in wanted or not isinstance(block, Block):
                continue
            found[house_id] = House(
                id=house_id,
                name=clean_key(block.get("name"), "dynn_"),
                prefix=clean_key(block.get("prefix"), "dynnp_"),
                key=str(block.get("key") or ""),
                dynasty=_int(block.get("dynasty")),
                coat_of_arms_id=_int(block.get("coat_of_arms_id")),
                head=_int(block.get("head_of_house")),
                found_date=str(block["found_date"]) if block.get("found_date") else None,
                motto=_motto(block.get("motto")),
            )
            if len(found) == len(wanted):
                break
    return found


def find_dynasties(save_path: str, wanted: set[int]) -> dict[int, Dynasty]:
    """The wanted dynasties, streaming ``dynasties.dynasties`` once."""
    found: dict[int, Dynasty] = {}
    if not wanted:
        return found
    with open_gamestate_text(save_path) as lines:
        for key, block in iter_children(PushbackLines(lines), ("dynasties", "dynasties")):
            try:
                dynasty_id = int(key)
            except (TypeError, ValueError):
                continue
            if dynasty_id not in wanted or not isinstance(block, Block):
                continue
            localized = str(block.get("localized_name") or "")
            found[dynasty_id] = Dynasty(
                id=dynasty_id,
                name=localized or clean_key(block.get("name"), "dynn_"),
                prefix="" if localized else clean_key(block.get("prefix"), "dynnp_"),
                coat_of_arms_id=_int(block.get("coat_of_arms_id")),
                head=_int(block.get("dynasty_head")),
            )
            if len(found) == len(wanted):
                break
    return found
