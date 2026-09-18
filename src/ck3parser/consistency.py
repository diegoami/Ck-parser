"""Tier-3 consistency checks between two snapshots of the same run.

Tiers 1 and 2 (:mod:`ck3parser.runs`) decide whether two saves belong to the
same run from their fingerprints and the played-ruler chain. Tier 3 is the
expensive confirmation, run against data the graph load has already parsed:
under the no-save-scumming assumption, everything an earlier snapshot records
about the past must still be recorded, unchanged, in a later one.

What is *not* a disagreement: a character or title present in the earlier
snapshot and absent from the later one. CK3 prunes dead characters and
destroyed dynamic titles over time, which is the whole reason for loading
older snapshots (docs/PLAN.md §4).

These are pure functions over parsed data so they can be unit tested without
a save file. Each returns human-readable warnings; an empty list means the two
snapshots agree.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .parser import Block, date_key
from .titles import TitleIndex

MAX_REPORTED = 10


def _truncate(warnings: list[str], kind: str) -> list[str]:
    if len(warnings) <= MAX_REPORTED:
        return warnings
    extra = len(warnings) - MAX_REPORTED
    return warnings[:MAX_REPORTED] + [f"... and {extra} more {kind} disagreement(s)"]


def check_title_history(
    earlier: TitleIndex,
    earlier_date: str,
    later: TitleIndex,
    keys: Iterable[str] | None = None,
) -> list[str]:
    """History of each title up to ``earlier_date`` must survive into ``later``.

    Only titles present in both are compared; ``keys`` narrows the comparison,
    and defaults to every title the two snapshots share.
    """
    if keys is None:
        keys = earlier.by_key.keys() & later.by_key.keys()
    cutoff = date_key(earlier_date)
    warnings: list[str] = []
    for key in sorted(keys):
        before, after = earlier.get(key), later.get(key)
        if before is None or after is None:
            continue
        expected = [e for e in before.history if date_key(e[0]) <= cutoff]
        actual = after.history[: len(expected)]
        if actual != expected:
            for index, entry in enumerate(expected):
                if index >= len(actual):
                    warnings.append(f"{key}: history entry {entry} at {entry[0]} is missing from the later snapshot")
                    break
                if actual[index] != entry:
                    warnings.append(f"{key}: history at {entry[0]} was {entry[1:]} and is now {actual[index][1:]}")
                    break
    return _truncate(warnings, "title history")


def death_dates(characters: Mapping[int, Block]) -> dict[int, str]:
    """``{character id: death date}`` for the dead among ``characters``."""
    out: dict[int, str] = {}
    for cid, char in characters.items():
        dead: Any = char.get("dead_data")
        if isinstance(dead, Block) and dead.get("date") is not None:
            out[cid] = str(dead["date"])
    return out


def check_deaths(
    earlier: Mapping[int, Block],
    later: Mapping[int, Block],
) -> list[str]:
    """Nobody may un-die or change death date between snapshots."""
    before, after = death_dates(earlier), death_dates(later)
    warnings: list[str] = []
    for cid, date in sorted(before.items()):
        if cid not in later:
            continue  # pruned from the later save, which is expected
        if cid not in after:
            warnings.append(f"character {cid} died {date} but is alive in the later snapshot")
        elif after[cid] != date:
            warnings.append(f"character {cid} died {date} but the later snapshot says {after[cid]}")
    return _truncate(warnings, "death")


def check_snapshots(
    earlier_index: TitleIndex,
    earlier_date: str,
    earlier_characters: Mapping[int, Block],
    later_index: TitleIndex,
    later_characters: Mapping[int, Block],
    keys: Iterable[str] | None = None,
) -> list[str]:
    """Run every tier-3 check over one consecutive pair."""
    return check_title_history(earlier_index, earlier_date, later_index, keys) + check_deaths(
        earlier_characters, later_characters
    )
