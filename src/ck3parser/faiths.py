"""Faiths, read out of a save.

A character carries a numeric `faith`, an index into `religion.faiths` (112
entries in the 1364 save). The section is small — 5 640 lines — but it is read
the same streamed, targeted way as everything else that touches a gamestate.

**A faith's `name` is there only when somebody named it.** Verified on the 1364
save: 9 of 112 faiths carry a `name`, and it is real text — `Ásatrú`,
`Bidaism`, `Immason`. The other 103 carry only `template` and `tag`, which are
localization keys (`norse_pagan`), and are cleaned the way a culture key is.

Five of those nine are **faiths founded during the run**: their `tag` is
`dynamic_faith_<id>` rather than the template they were reformed out of, and
they carry a `founder` character id. The other four are the originals, renamed
`Old Ásatrú` and so on by the game when the reformed faith took the name.

That `founder` is worth having: on the Germania run the played dynasty's own
Folmar founded `Immason`, which is the faith the realm — the Immasonian
Fylkirate — is named after. A chronicle that cannot say so is missing its own
title.
"""

from __future__ import annotations

from dataclasses import dataclass

from .container import open_gamestate_text
from .dynasties import titled
from .parser import Block, PushbackLines, iter_children

SECTION = ("religion", "faiths")

#: The `tag` a faith founded during the run carries instead of a game key.
DYNAMIC = "dynamic_faith_"


@dataclass
class Faith:
    id: int
    name: str = ""
    tag: str = ""
    template: str = ""
    religion: int | None = None
    founder: int | None = None
    adjective: str = ""
    adherent: str = ""

    @property
    def founded_in_run(self) -> bool:
        """True for a faith reformed during this playthrough."""
        return self.tag.startswith(DYNAMIC)

    @property
    def display_name(self) -> str:
        """Whoever named it wins; otherwise the key, tidied and never guessed."""
        return self.name or titled(self.tag or self.template) or f"Faith {self.id}"


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def find_faiths(save_path: str, wanted: set[int]) -> dict[int, Faith]:
    """The wanted faiths, streaming ``religion.faiths`` once."""
    found: dict[int, Faith] = {}
    if not wanted:
        return found
    with open_gamestate_text(save_path) as lines:
        for key, block in iter_children(PushbackLines(lines), SECTION):
            try:
                faith_id = int(key)
            except (TypeError, ValueError):
                continue
            if faith_id not in wanted or not isinstance(block, Block):
                continue
            found[faith_id] = Faith(
                id=faith_id,
                name=str(block.get("name") or ""),
                tag=str(block.get("tag") or ""),
                template=str(block.get("template") or ""),
                religion=_int(block.get("religion")),
                founder=_int(block.get("founder")),
                adjective=str(block.get("adjective") or ""),
                adherent=str(block.get("adherent") or ""),
            )
            if len(found) == len(wanted):
                break
    return found
