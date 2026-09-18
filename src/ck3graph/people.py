"""One streaming pass over a save's character records, for the graph.

The wiki finds parents by **inverting** every child list, because a save stores
parentage downward only: `family_data` lists `child` and never `father` or
`mother` (docs/PLAN.md §10). That inversion costs a full pass and about 80 MB,
and it exists purely so Python can look *up* from a child.

A graph does not need it. `(:Character)-[:PARENT_OF]->(:Character)` is written
straight off each record's own child list, and Cypher walks the edge in either
direction:

    MATCH (c)<-[:PARENT_OF]-(parent)          // up, no inversion
    MATCH (c)-[:PARENT_OF*2]->(grandchild)    // down, any depth

So this module streams the character sections once, yielding what one record
contributes, and never holds more than one record at a time. The loader writes
it in batches as it arrives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from ck3parser.container import open_gamestate_text
from ck3parser.family import SECTIONS, own_family
from ck3parser.parser import Block, PushbackLines, iter_children

from .loader import character_props


@dataclass
class Person:
    """What one character record contributes to the graph."""

    id: int
    props: dict = field(default_factory=dict)
    children: list[int] = field(default_factory=list)
    spouses: list[int] = field(default_factory=list)
    former_spouses: list[int] = field(default_factory=list)
    #: A bastard's true father, when the save admits to one. Kept apart from
    #: `PARENT_OF` exactly as :mod:`ck3parser.family` keeps it apart from
    #: `parents`: the game distinguishes them, and so does the graph.
    real_father: int | None = None

    @property
    def house(self) -> int | None:
        value = self.props.get("dynasty_house")
        return value if isinstance(value, int) else None


def stream_people(save_path: str) -> Iterator[Person]:
    """Every character of one save, in section order, one record at a time.

    All three character sections are read and none may be skipped: a parent can
    be alive, dead-unprunable or dead-prunable. Nothing is filtered out here —
    a character with no house and no titles is still somebody's parent, and
    dropping them would break the very paths the graph exists to walk.
    """
    for section in SECTIONS:
        with open_gamestate_text(save_path) as lines:
            for key, char in iter_children(PushbackLines(lines), section):
                if not isinstance(char, Block):
                    continue
                try:
                    cid = int(key)
                except (TypeError, ValueError):
                    continue
                person = Person(id=cid, props=character_props(cid, char))
                family = char.get("family_data")
                if isinstance(family, Block):
                    own = own_family(cid, family)
                    person.children = own.children
                    person.spouses = own.spouses
                    person.former_spouses = own.former_spouses
                    person.real_father = own.real_father
                yield person
