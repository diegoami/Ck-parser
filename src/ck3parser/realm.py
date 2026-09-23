"""A ruler's realm at one snapshot: what they hold, and what is held under them.

The realm is the closure of the ruler's own titles over the de facto vassal
tree of one save (`TitleIndex.vassals`). It is computed per snapshot and only
per snapshot: a save says who each title's liege **is**, never who it has been,
so between two snapshots all that can be said is that something changed
between them (docs/PLAN.md §9). No realm is ever interpolated.

**Depth is vassal rank**, counted in *holders*, not in titles: 0 when the
ruler holds the title, 1 when a direct vassal does, 2 when a vassal's vassal
does, and so on. A duke's county held under his own duchy is still depth 1 --
the duchy and the county have the same holder, so no rank is crossed. The
title tree is deeper than the chain of people (a county sits under a duchy
under a kingdom), and conflating the two gave a wrong figure once
(#40): the 1358 realm has 1 004 counties at title depth 2-3 but 778 at vassal
rank 2 or more.

It sits in `ck3parser` beside `vassalage`, for the same reason: the wiki uses
it now and the graph loader may later, and the graph cannot import the wiki.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .titles import TitleIndex


@dataclass(frozen=True)
class RealmTitle:
    """One title of a realm, and how it is held."""

    key: str
    tier: str | None
    holder: int | None
    #: vassal rank: 0 the ruler holds it, 1 a direct vassal, 2+ further down
    depth: int
    #: the holders from the ruler down to this title's holder, ruler first;
    #: one entry per rank, so ``len(chain) == depth + 1``
    chain: tuple[int, ...]


@dataclass
class Realm:
    ruler: int
    date: str | None
    titles: dict[str, RealmTitle] = field(default_factory=dict)
    #: every title key the save has at all, in the realm or not: what tells a
    #: title that left the realm from one that is gone from the save
    in_save: frozenset[str] = frozenset()

    def of_tier(self, tier: str = "county") -> dict[str, RealmTitle]:
        return {k: t for k, t in self.titles.items() if t.tier == tier}

    def by_depth(self, tier: str = "county") -> Counter:
        """How many titles of this tier sit at each vassal rank."""
        return Counter(t.depth for t in self.of_tier(tier).values())


def realm(index: TitleIndex, ruler: int, date: str | None = None) -> Realm:
    """Everything `ruler` holds, and everything held under it, in one save.

    Each title is reached once: de facto liege links form a forest, and a title
    already placed is not placed again, which also keeps a malformed save with a
    cycle from looping.
    """
    out = Realm(ruler=ruler, date=date, in_save=frozenset(index.by_key))
    stack = [(record, (ruler,)) for record in index.by_idx.values() if record.holder == ruler]
    while stack:
        record, chain = stack.pop()
        if record.key in out.titles:
            continue
        # an unheld title passes its liege's chain down unchanged
        if record.holder is not None and record.holder != chain[-1]:
            chain = chain + (record.holder,)
        out.titles[record.key] = RealmTitle(
            key=record.key, tier=record.tier, holder=record.holder, depth=len(chain) - 1, chain=chain
        )
        for vassal in index.vassals.get(record.idx, []):
            stack.append((index.by_idx[vassal], chain))
    return out


@dataclass(frozen=True)
class RealmChange:
    """A title that entered or left a realm between two snapshots.

    `after` and `before` bound the change; it happened somewhere between them,
    and no date inside the window is ever claimed (§9).
    """

    key: str
    #: "gained": in the later realm, not the earlier one;
    #: "left": in the earlier realm, and in the later save but outside the realm;
    #: "gone": in the earlier realm, and in no later save at all -- destroyed or
    #: pruned, the save does not say which, so it is never called a loss
    kind: str
    after: str | None
    before: str | None


def changes(earlier: Realm, later: Realm, tier: str | None = "county") -> list[RealmChange]:
    """What entered and left the realm between two snapshots, sorted by key."""
    def keys(r: Realm) -> set[str]:
        return {k for k, t in r.titles.items() if tier is None or t.tier == tier}

    was, now = keys(earlier), keys(later)
    out = [RealmChange(k, "gained", earlier.date, later.date) for k in now - was]
    for k in was - now:
        kind = "left" if k in later.in_save else "gone"
        out.append(RealmChange(k, kind, earlier.date, later.date))
    return sorted(out, key=lambda c: c.key)
