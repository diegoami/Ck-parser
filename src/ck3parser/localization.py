"""The game's own text for the keys a save uses (#31).

Much of what a save stores is a localization key: a character's first name
(`A_sa`, the underscore marking the diacritic), a cause of death
(`death_drinking_passive`), a title without a name of its own (`k_denmark`),
a templated culture, a faith named by its tag. The text lives in the game's
`localization/<language>/**/*.yml`, which a save does not carry.

Two sources, one interface (owner's decision on #31, option C):

* the game itself, read where it is installed (`Localization.from_game`);
* an **extract**: only the keys a set of chronicles used, written by
  `python -m ck3wiki.localize` into ck_wiki so builds without the game --
  ck_wiki's CI -- read the same text (`Localization.from_extract`).

Nothing is guessed. A key not found, or a template using an expression this
does not know, answers None, and the caller shows what it showed before:
the key, transcribed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

#: Bumped when the extract's shape changes.
SCHEMA = "ck3-localization/1"

#: ` key:0 "text"`, the version digit optional, a trailing `# comment` allowed
#: (`death_depressed` carries one, and a stricter pattern missed it)
_LINE = re.compile(r'^\s*([^\s:#"]+):\d*\s*"(.*)"\s*(?:#.*)?$')
_REF = re.compile(r"\$([^$\s]+)\$")
_EXPR = re.compile(r"\[([^\]]*)\]")
_TRAIT = re.compile(r"GetTrait\('([^']+)'\)\.GetName\(\s*CHARACTER\.Self\s*\)")
#: text formatting (`#bold ...#!`): not something a page can show faithfully
_MARKUP = re.compile(r"#[A-Za-z!]")

#: the character's own pronouns, by expression: (female, male)
_PRONOUNS = {
    "CHARACTER.GetHerHis": ("her", "his"),
    "CHARACTER.GetHerselfHimself": ("herself", "himself"),
    "CHARACTER.GetSheHe": ("she", "he"),
    "CHARACTER.GetHerHim": ("her", "him"),
}


def parse(text: str) -> dict[str, str]:
    """Keys and texts from one `.yml` file; the first definition of a key wins."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2).replace('\\"', '"').replace("\\n", "\n")
    return out


class Localization:
    """Key -> text, with every key it was asked for and answered recorded."""

    def __init__(self, table: dict[str, str], source: str = ""):
        self.table = table
        self.source = source
        #: the keys that answered, references included: what an extract keeps
        self.used: set[str] = set()

    @classmethod
    def from_game(cls, game_dir: Path, language: str = "english") -> Localization:
        """Every key in `<game>/localization/<language>`, subfolders included."""
        folder = Path(game_dir) / "localization" / language
        table: dict[str, str] = {}
        for f in sorted(folder.rglob("*.yml")):
            for key, text in parse(f.read_text(encoding="utf-8-sig", errors="replace")).items():
                table.setdefault(key, text)
        return cls(table, source=f"game: {folder}")

    @classmethod
    def from_extract(cls, path: Path) -> Localization:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise ValueError(f"{path} is not a {SCHEMA} extract")
        return cls(dict(data["keys"]), source=f"extract: {path}")

    def write_extract(self, path: Path) -> int:
        """The keys used so far, and only those. Returns how many."""
        keys = {k: self.table[k] for k in sorted(self.used)}
        Path(path).write_text(
            json.dumps({"schema": SCHEMA, "keys": keys}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        return len(keys)

    def text(self, key: str | None, _depth: int = 0) -> str | None:
        """The key's text with `$references$` resolved, or None."""
        if not key or key not in self.table or _depth > 5:
            return None
        text = self.table[key]
        for ref in set(_REF.findall(text)):
            inner = self.text(ref, _depth + 1)
            if inner is None:
                return None
            text = text.replace(f"${ref}$", inner)
        self.used.add(key)
        return text

    def render(self, key: str | None, female: bool | None = None, killer: str | None = None) -> str | None:
        """A template filled in, or None if anything in it cannot be filled.

        Knows the expressions causes of death use: the character's pronouns
        (from `female`), the killer's name (`killer`, when the save names one),
        and a trait's name. Anything else, or text formatting, gives None.
        """
        text = self.text(key)
        if text is None:
            return None

        def fill(match: re.Match[str]) -> str:
            expr = match.group(1).strip()
            if expr in _PRONOUNS and female is not None:
                return _PRONOUNS[expr][0 if female else 1]
            if expr == "TARGET_CHARACTER.GetUIName" and killer:
                return killer
            if expr == "TARGET_CHARACTER.GetUINamePossessive" and killer:
                return f"{killer}'s"
            trait = _TRAIT.fullmatch(expr)
            if trait:
                name = self.text(f"trait_{trait.group(1)}")
                if name is not None:
                    return name
            raise LookupError(expr)

        try:
            text = _EXPR.sub(fill, text)
        except LookupError:
            return None
        return None if _MARKUP.search(text) else text
