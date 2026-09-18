"""One run's history, merged from every snapshot that covers it.

A save prunes dead characters and destroyed titles as a run goes on, so the
newest save is not a superset of the older ones (docs/PLAN.md §4). The wiki is
therefore built from the **union** of the snapshots, oldest first, exactly as
the graph loader merges them: later snapshots refine what earlier ones said and
never remove it.

Names are a known approximation. A save stores `first_name` as a localization
*key*, not display text, and marks diacritics with an underscore: `FranC_ois`
is François, `O_zgul` is Özgül. Decoding that properly needs the game's
localization files, which this project deliberately does not read, so
:func:`clean_name` only drops the marker rather than inventing a letter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ck3graph.loader import holder_intervals
from ck3parser.parser import Block, date_key
from ck3parser.pipeline import SnapshotView
from ck3parser.titles import TitleRecord

_DIACRITIC = re.compile(r"([A-Za-z])_")


def clean_name(raw: str) -> str:
    """``FranC_ois`` -> ``Francois``. Drops the diacritic marker, never guesses."""
    if not raw:
        return ""

    def fix(match: re.Match[str]) -> str:
        letter = match.group(1)
        return letter if match.start() == 0 else letter.lower()

    return _DIACRITIC.sub(fix, raw)


@dataclass
class Tenure:
    holder: int
    start: str | None
    end: str | None
    reason: str | None
    open: bool

    def sort_key(self) -> tuple[int, int, int]:
        return date_key(self.start) if self.start else (0, 0, 0)


@dataclass
class WikiCharacter:
    id: int
    name: str = ""
    birth: str | None = None
    death: str | None = None
    death_reason: str | None = None
    female: bool = False
    house: int | None = None
    seen: list[str] = field(default_factory=list)  #: snapshot dates this record came from

    @property
    def alive_at_last_sight(self) -> bool:
        return self.death is None

    @property
    def lifespan(self) -> str:
        if self.birth and self.death:
            return f"{self.birth} – {self.death}"
        if self.birth:
            return f"b. {self.birth}"
        return "dates unknown"


@dataclass
class WikiTitle:
    key: str
    name: str = ""
    tier: str | None = None
    holder: int | None = None
    tenures: list[Tenure] = field(default_factory=list)
    liege: str | None = None
    de_jure_liege: str | None = None
    vassals: dict[str, list[str]] = field(default_factory=dict)  #: snapshot date -> vassal keys
    first_seen: str | None = None
    last_seen: str | None = None

    @property
    def all_vassals(self) -> list[str]:
        return sorted({key for keys in self.vassals.values() for key in keys})


@dataclass
class Wiki:
    run_id: str
    title_key: str
    snapshots: list[str] = field(default_factory=list)
    titles: dict[str, WikiTitle] = field(default_factory=dict)
    characters: dict[int, WikiCharacter] = field(default_factory=dict)

    @property
    def root(self) -> WikiTitle | None:
        return self.titles.get(self.title_key)

    def held_by(self, character_id: int) -> list[tuple[WikiTitle, Tenure]]:
        """Every tenure this character held, earliest first."""
        out = [
            (title, tenure)
            for title in self.titles.values()
            for tenure in title.tenures
            if tenure.holder == character_id
        ]
        out.sort(key=lambda pair: pair[1].sort_key())
        return out

    def named(self, character_id: int) -> str:
        character = self.characters.get(character_id)
        return character.name if character and character.name else f"Character {character_id}"


def _merge_character(wiki: Wiki, cid: int, char: Block, date: str) -> None:
    dead = char.get("dead_data")
    existing = wiki.characters.get(cid)
    record = existing or WikiCharacter(id=cid)
    record.name = clean_name(str(char.get("first_name") or "")) or record.name
    record.birth = record.birth or (str(char["birth"]) if char.get("birth") is not None else None)
    record.female = bool(char.get("female", record.female))
    house = char.get("dynasty_house")
    record.house = house if isinstance(house, int) else record.house
    if isinstance(dead, Block) and dead.get("date") is not None:
        record.death = str(dead["date"])
        reason = dead.get("reason")
        record.death_reason = str(reason) if reason else record.death_reason
    if date not in record.seen:
        record.seen.append(date)
    wiki.characters[cid] = record


def _merge_title(wiki: Wiki, record: TitleRecord, view: SnapshotView) -> WikiTitle:
    title = wiki.titles.get(record.key) or WikiTitle(key=record.key)
    title.name = record.display_name
    title.tier = record.tier or title.tier
    title.holder = record.holder if record.holder is not None else title.holder
    title.first_seen = min(filter(None, [title.first_seen, view.fp.date]), key=date_key)
    title.last_seen = max(filter(None, [title.last_seen, view.fp.date]), key=date_key)

    intervals = holder_intervals(
        record.history, end_date=view.fp.date, current_holder=record.holder, holder_since=record.date
    )
    by_start = {(t.holder, t.start): t for t in title.tenures}
    for interval in intervals:
        key = (interval["holder"], interval["from"])
        existing = by_start.get(key)
        tenure = Tenure(
            holder=interval["holder"],
            start=interval["from"],
            end=interval["to"],
            reason=interval.get("reason"),
            open=interval["open"],
        )
        # A tenure one snapshot saw open and another saw closed is closed. While
        # it is still open, the latest snapshot has the best end date: an open
        # reign runs to whenever we last looked, so keeping the earlier one
        # would freeze the current ruler at an old save's date.
        if existing is None:
            by_start[key] = tenure
        elif existing.open and not tenure.open:
            by_start[key] = tenure
        elif existing.open and tenure.open:
            if tenure.end and (not existing.end or date_key(tenure.end) > date_key(existing.end)):
                by_start[key] = tenure
    title.tenures = sorted(by_start.values(), key=Tenure.sort_key)
    wiki.titles[record.key] = title
    return title


def build_wiki(views: list[SnapshotView], title_key: str) -> Wiki:
    """Merge snapshots, oldest first, into one picture of the lineage."""
    views = sorted(views, key=lambda v: date_key(v.fp.date))
    wiki = Wiki(run_id=views[0].fp.run_id if views else "", title_key=title_key)
    for view in views:
        wiki.snapshots.append(view.fp.date)
        for record in view.titles:
            title = _merge_title(wiki, record, view)
            if record is view.target:
                liege = view.index.resolve(record.de_facto_liege)
                title.liege = liege.key if liege else title.liege
            else:
                title.liege = view.target.key
            de_jure = view.index.resolve(record.de_jure_liege)
            if de_jure is not None:
                title.de_jure_liege = de_jure.key
        root = wiki.titles[view.target.key]
        root.vassals[view.fp.date] = [r.key for r in view.vassals]
        for cid, char in view.characters.items():
            _merge_character(wiki, cid, char, view.fp.date)
    return wiki
