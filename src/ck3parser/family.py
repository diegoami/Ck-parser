"""Parents, siblings, spouses and children.

The save stores parentage **downward only**. A character's `family_data` lists
their `child`ren, their `spouse`s and their `former_spouses`, and never their
father or mother: verified by scanning all 281 916 characters of the 1364 save,
of which exactly none carry a `father` or `mother` key (docs/PLAN.md §10).

So parents are found by inverting: read every character's child list and note
who claimed whom. That cannot exit early the way a targeted lookup can, because
a parent may sit anywhere in any section — which is the whole cost of this
module, one full pass over the character sections, ~37 s on a 280 MB save.

It is worth paying. Inverting only within a lineage finds parents for 447 of
its 666 characters; inverting the whole save finds them for 590, and gives both
parents rather than one for 536 of those. The rest are founders, or have
parents the save has pruned.

Siblings come free with it: whenever a child list mentions someone wanted, the
whole list is kept, so half-siblings through either parent are included.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .container import open_gamestate_text
from .parser import Block, PushbackLines, iter_children

#: Where character records live. All three are read; none may be skipped,
#: because a parent can be alive, dead-unprunable or dead-prunable.
SECTIONS = (("living",), ("dead_unprunable",), ("characters", "dead_prunable"))


@dataclass
class Family:
    """One character's immediate family, as one save records it."""

    id: int
    parents: list[int] = field(default_factory=list)
    children: list[int] = field(default_factory=list)
    spouses: list[int] = field(default_factory=list)
    former_spouses: list[int] = field(default_factory=list)
    primary_spouse: int | None = None
    #: A bastard's true father, when the save admits to one. Never merged into
    #: `parents`: the game keeps it apart, and so does this.
    real_father: int | None = None
    siblings: list[int] = field(default_factory=list)

    @property
    def everyone(self) -> list[int]:
        """Every id this record mentions, for fetching their names."""
        out = [*self.parents, *self.children, *self.spouses, *self.former_spouses, *self.siblings]
        if self.primary_spouse is not None:
            out.append(self.primary_spouse)
        if self.real_father is not None:
            out.append(self.real_father)
        return sorted(set(out))


def _ints(values: list) -> list[int]:
    """Flatten what a repeated key gives back: scalars, lists, or both."""
    out: list[int] = []
    for value in values:
        if isinstance(value, int):
            out.append(value)
        elif isinstance(value, list):
            out.extend(v for v in value if isinstance(v, int))
    return out


def own_family(cid: int, family: Block) -> Family:
    primary = family.get("primary_spouse")
    real_father = family.get("real_father")
    spouses = _ints(family.getall("spouse"))
    return Family(
        id=cid,
        children=_ints(family.getall("child")),
        spouses=sorted(dict.fromkeys(spouses)),
        former_spouses=sorted(dict.fromkeys(_ints(family.getall("former_spouses")))),
        primary_spouse=primary if isinstance(primary, int) else None,
        real_father=real_father if isinstance(real_father, int) else None,
    )


@dataclass
class FamilyIndex:
    """Who claimed whom, for everyone in one save, plus the wanted ones' records.

    The inversion is kept **whole** rather than narrowed to the characters asked
    for. That costs about 80 MB on a 280 MB save -- 201 498 children and 164 612
    parents -- and it is what lets the wiki widen afterwards without paying a
    second full pass: once someone is promoted to a page of their own, their
    parents, children and siblings are already here.
    """

    #: parent -> the children they claim
    brood: dict[int, list[int]] = field(default_factory=dict)
    #: child -> whoever claimed them
    parents: dict[int, list[int]] = field(default_factory=dict)
    #: the records asked for by name; a promoted character has none until fetched
    own: dict[int, Family] = field(default_factory=dict)

    def family_of(self, cid: int) -> Family:
        """One character's family, from their own record where there is one.

        Spouses live only on a character's own record, so someone the index was
        not asked about has none here. Their parents, children and siblings come
        from the inversion and are complete.
        """
        record = self.own.get(cid) or Family(id=cid, children=list(self.brood.get(cid, [])))
        record.parents = sorted(self.parents.get(cid, []))
        kin = {sib for parent in record.parents for sib in self.brood.get(parent, [])}
        kin.discard(cid)
        record.siblings = sorted(kin)
        return record


def read_index(save_path: str, wanted: set[int]) -> FamilyIndex:
    """Invert every child list in one pass per section, keeping the whole map.

    The pass cannot stop early: a parent is only found by reading the record
    that claims the child, and that record may be anywhere.
    """
    index = FamilyIndex()
    for section in SECTIONS:
        with open_gamestate_text(save_path) as lines:
            for key, char in iter_children(PushbackLines(lines), section):
                if not isinstance(char, Block):
                    continue
                family = char.get("family_data")
                if not isinstance(family, Block):
                    continue
                try:
                    cid = int(key)
                except (TypeError, ValueError):
                    continue
                if cid in wanted:
                    index.own[cid] = own_family(cid, family)
                children = _ints(family.getall("child"))
                if not children:
                    continue
                index.brood[cid] = children
                for kid in children:
                    index.parents.setdefault(kid, []).append(cid)
    return index


def read_family(save_path: str, wanted: set[int]) -> dict[int, Family]:
    """The immediate family of each wanted character, in one pass per section."""
    if not wanted:
        return {}
    index = read_index(save_path, wanted)
    return {cid: index.family_of(cid) for cid in wanted}
