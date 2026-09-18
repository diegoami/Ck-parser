"""Cultures, read out of a save.

A character carries a numeric `culture`, an index into `culture_manager.cultures`
(301 entries in the 1364 save). The section is the third largest thing in a
gamestate at 122 126 lines, so lookups are targeted by id and streamed, never
read whole.

**A culture's `name` is display text only when the game has no template for
it.** Verified on the 1364 save: of 301 cultures, 190 carry a `culture_template`
and for *all 190* `name` is exactly that template — `welayta`, a localization
key. The other 111 carry no template, and for *all 111* `name` is real text with
a capital or a hyphen in it: `Malinke-Soninke`, `Perso-Bedouin`. Those are the
hybrid cultures made during the run, which the game has to write a name for
because it has none on file.

So a templated culture's name is cleaned the way a house key is — the words
capitalised, nothing guessed — and an untemplated one's is shown as it stands.

**A template does not mean the game shipped the culture, and `created` is a
separate question.** Of the 190 templated cultures: 156 carry the `1.1.1`
sentinel and so were there from the start; 24 were created before the run's
bookmark, which is the game's own pre-867 history; and **10 were created during
this very run**, because CK3 has templates for the cultures it expects to
diverge — Swedish came out of Norse on 950.5.2 in the Germania run. All 111
untemplated cultures were created during the run.

So `templated` answers "is the name a key", and `founded` answers "when did it
come into being". Neither answers the other, and the code no longer pretends
either does.

Heritage, language, ethos and martial custom are localization keys with their
own prefixes, and are cleaned the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .container import open_gamestate_text
from .dynasties import titled
from .parser import Block, PushbackLines, iter_children

SECTION = ("culture_manager", "cultures")

#: What `created` is for a culture that was there from the start of time.
#: The same kind of sentinel as a house's `9999.1.1`.
FROM_THE_START = "1.1.1"


@dataclass
class Culture:
    id: int
    name: str = ""
    template: str = ""
    heritage: str = ""
    language: str = ""
    ethos: str = ""
    martial_custom: str = ""
    created: str | None = None
    head: int | None = None
    parents: list[int] = field(default_factory=list)

    @property
    def templated(self) -> bool:
        """True when the game has a template for this culture, so `name` is a key.

        Not the same as "the game shipped it": 10 of the 190 templated cultures
        in the 1364 save were created during that very run. Use `founded` for
        when it came into being.
        """
        return bool(self.template)

    @property
    def display_name(self) -> str:
        """The key, tidied, when there is a template; the game's own text if not."""
        if not self.templated:
            return self.name or f"Culture {self.id}"
        return titled(self.name) or f"Culture {self.id}"

    @property
    def founded(self) -> str | None:
        """When it came into being, or None for one that was there from the start."""
        return None if self.created in (None, FROM_THE_START) else self.created


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _parents(block: Block) -> list[int]:
    """The cultures this one came out of. Repeated and list-shaped, like family."""
    out: list[int] = []
    for value in block.getall("parents"):
        if isinstance(value, int):
            out.append(value)
        elif isinstance(value, list):
            out.extend(v for v in value if isinstance(v, int))
    return sorted(dict.fromkeys(out))


def find_cultures(save_path: str, wanted: set[int]) -> dict[int, Culture]:
    """The wanted cultures, streaming ``culture_manager.cultures`` once."""
    found: dict[int, Culture] = {}
    if not wanted:
        return found
    with open_gamestate_text(save_path) as lines:
        for key, block in iter_children(PushbackLines(lines), SECTION):
            try:
                culture_id = int(key)
            except (TypeError, ValueError):
                continue
            if culture_id not in wanted or not isinstance(block, Block):
                continue
            template = block.get("culture_template")
            created = block.get("created")
            found[culture_id] = Culture(
                id=culture_id,
                name=str(block.get("name") or ""),
                template=str(template) if template is not None else "",
                heritage=titled(block.get("heritage"), "heritage_"),
                language=titled(block.get("language"), "language_"),
                ethos=titled(block.get("ethos"), "ethos_"),
                martial_custom=titled(block.get("martial_custom"), "martial_custom_"),
                created=str(created) if created is not None else None,
                head=_int(block.get("head")),
                parents=_parents(block),
            )
            if len(found) == len(wanted):
                break
    return found
