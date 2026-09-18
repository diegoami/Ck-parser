"""Who a title answered to, as stretches between snapshots.

A save says who a title's liege **is**; it never says who it has been. There is
no vassalage history to read, the way there is a holder history (docs/PLAN.md
§9). All we ever have are observations at the snapshot dates, so a change of
liege is only ever known to have happened *between* two of them.

This module collapses those observations into stretches that say so. It sits in
`ck3parser` rather than in the wiki because the graph writes the same stretches
as edges, and the wiki already imports the graph loader: putting it the other
way round would be a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass

#: What `Vassalage.liege` is when the title answered to nobody at that date.
INDEPENDENT = None


@dataclass
class Vassalage:
    """A stretch of snapshots that saw one title under the same liege.

    Unlike a tenure, this is **not** read out of a history: a save records who
    holds a title and since when, but not who its liege has been over time. All
    we ever have are observations at the snapshot dates, so a change is only
    ever known to have happened *between* two of them, and this says so rather
    than inventing a date (docs/PLAN.md §9).
    """

    liege: str | None  #: the liege's key, or None for independent
    first: str  #: first snapshot that saw this
    last: str  #: last snapshot that saw this
    after: str | None = None  #: the snapshot before it, if any: it began after this
    before: str | None = None  #: the snapshot after it, if any: it ended before this

    @property
    def open(self) -> bool:
        """Still true when we last looked."""
        return self.before is None

    @property
    def began(self) -> str:
        """The window the link began in, or `by X` when nothing bounds it below."""
        return f"{self.after} – {self.first}" if self.after else f"by {self.first}"

    @property
    def ended(self) -> str:
        """The window the link ended in; empty while it is still open."""
        return f"{self.last} – {self.before}" if self.before else ""


def stretches(observed: dict[str, str | None], order: list[str]) -> list[Vassalage]:
    """Collapse per-snapshot observations into stretches, with their bounds.

    `order` is every snapshot of the run, oldest first, so a snapshot the title
    was absent from breaks a stretch just as a change of liege does: we did not
    see it under anyone, and saying otherwise would bridge a gap we cannot see
    across.
    """
    out: list[Vassalage] = []
    previous: str | None = None  #: the snapshot before the current stretch
    current: Vassalage | None = None
    for date in order:
        if date not in observed:
            if current is not None:
                current.before = date
                current = None
            previous = date
            continue
        liege = observed[date]
        if current is not None and current.liege == liege:
            current.last = date
        else:
            if current is not None:
                current.before = date
            current = Vassalage(liege=liege, first=date, last=date, after=previous)
            out.append(current)
        previous = date
    return out
