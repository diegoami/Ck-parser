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
from pathlib import Path

from ck3graph.loader import holder_intervals
from ck3parser.arms import read_arms
from ck3parser.characters import find_characters
from ck3parser.dynasties import Dynasty, House, arms_id, find_dynasties, find_houses, house_name
from ck3parser.family import Family, own_family, read_index
from ck3parser.parser import Block, date_key
from ck3parser.pipeline import SnapshotView
from ck3parser.portraits import arms_name, portrait_name, save_checksum
from ck3parser.titles import TitleRecord

_DIACRITIC = re.compile(r"([A-Za-z])_")


def clean_name(raw: str) -> str:
    """``FranC_ois`` -> ``Francois``. Drops the diacritic marker, never guesses.

    The marker usually follows the letter it modifies (`BuR_islav` is Burislav),
    but a name whose *first* letter is modified carries it in front instead:
    `_Odgrim` is Ǫdgrim. Both are dropped and neither letter is guessed.
    """
    if not raw:
        return ""

    def fix(match: re.Match[str]) -> str:
        letter = match.group(1)
        return letter if match.start() == 0 else letter.lower()

    return _DIACRITIC.sub(fix, raw.lstrip("_"))


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
class Image:
    """One image the companion project is expected to harvest.

    The wiki links it whether or not it exists yet: `file` is a name both
    projects derive from the save's name (:mod:`ck3parser.portraits`), never a
    path, so neither side has to be told where the other put anything.
    """

    file: str
    save: str  #: the save it must be captured from, by base name
    checksum: str


@dataclass
class Portrait(Image):
    """A character's portrait as of one save. Three saves, three portraits."""

    character: int = 0
    save_date: str = ""


@dataclass
class Arms(Image):
    """A coat of arms, named after the recipe that draws it.

    It belongs to a **house** or a **title**, never both: a house sets `house`
    and a title sets `title`. The two can still share a file, because the name
    comes from the recipe rather than the owner, and a title often bears the
    arms of the house that holds it.

    `save` and `checksum` say where the recipe was read from, which is what
    `coat_of_arms_id` indexes; the file name does not depend on either, because
    the same arms are one image in every run (docs/PLAN.md §11).
    """

    coat_of_arms_id: int = 0
    house: int = 0  #: 0 when a title bears these arms
    title: str = ""  #: empty when a house bears these arms
    #: the recipe itself, so a companion can draw the arms instead of capturing
    definition: object = None

    @property
    def page(self) -> str:
        """The page that shows them, which is what the manifest points at."""
        return f"titles/{self.title}.html" if self.title else f"houses/{self.house}.html"


@dataclass
class Relative:
    """Someone a character is related to who has no page of their own.

    Family reaches well outside a lineage -- 2 784 of the 3 235 people the 1364
    lineage is related to hold none of its titles -- so they are fetched just
    far enough to be named, and nothing more.
    """

    id: int
    name: str = ""
    birth: str | None = None
    death: str | None = None

    @property
    def lifespan(self) -> str:
        if self.birth and self.death:
            return f"{self.birth} – {self.death}"
        return f"b. {self.birth}" if self.birth else ""


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
    portraits: list[Portrait] = field(default_factory=list)
    parents: list[int] = field(default_factory=list)
    siblings: list[int] = field(default_factory=list)
    spouses: list[int] = field(default_factory=list)
    former_spouses: list[int] = field(default_factory=list)
    children: list[int] = field(default_factory=list)
    real_father: int | None = None

    @property
    def has_family(self) -> bool:
        return bool(
            self.parents or self.siblings or self.spouses
            or self.former_spouses or self.children
        )

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


#: What `Vassalage.liege` is when the title answered to nobody at that date.
INDEPENDENT = None


@dataclass
class Vassalage:
    """A stretch of snapshots that saw one title under the same liege.

    Unlike a :class:`Tenure`, this is **not** read out of a history: a save
    records who holds a title and since when, but not who its liege has been
    over time. All we ever have are observations at the snapshot dates, so a
    change is only ever known to have happened *between* two of them, and this
    says so rather than inventing a date (docs/PLAN.md §9).
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


def _runs_of(observed: dict[str, str | None], order: list[str]) -> list[Vassalage]:
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
    lieges: dict[str, str | None] = field(default_factory=dict)  #: snapshot date -> liege key
    arms: Arms | None = None
    first_seen: str | None = None
    last_seen: str | None = None

    @property
    def all_vassals(self) -> list[str]:
        return sorted({key for keys in self.vassals.values() for key in keys})

    def vassalage(self, snapshots: list[str]) -> list[Vassalage]:
        """Who this title answered to, as stretches between snapshots."""
        return _runs_of(self.lieges, snapshots)


@dataclass
class WikiHouse:
    """A house as the wiki shows it: its dynasty, and its arms to be harvested.

    A house can have no name of its own — 4 809 of the 1364 save's do not — and
    then the dynasty's name is the one to show.
    """

    house: House
    dynasty: Dynasty | None = None
    arms: Arms | None = None

    @property
    def id(self) -> int:
        return self.house.id

    @property
    def name(self) -> str:
        return house_name(self.house, self.dynasty)

    @property
    def head(self) -> int | None:
        """Its own head if it has one, else the dynasty's."""
        if self.house.head is not None:
            return self.house.head
        return self.dynasty.head if self.dynasty else None


@dataclass
class Wiki:
    run_id: str
    title_key: str
    snapshots: list[str] = field(default_factory=list)
    titles: dict[str, WikiTitle] = field(default_factory=dict)
    characters: dict[int, WikiCharacter] = field(default_factory=dict)
    houses: dict[int, WikiHouse] = field(default_factory=dict)
    relatives: dict[int, Relative] = field(default_factory=dict)  #: named, but no page
    saves: list[dict] = field(default_factory=list)  #: {file, checksum, date} per snapshot

    def person(self, character_id: int) -> WikiCharacter | Relative | None:
        return self.characters.get(character_id) or self.relatives.get(character_id)

    def members_of(self, house_id: int) -> list[WikiCharacter]:
        """The house's members, eldest first. Dates sort as dates, not as text."""
        return sorted(
            (c for c in self.characters.values() if c.house == house_id),
            key=lambda c: (date_key(c.birth) if c.birth else (0, 0, 0), c.id),
        )

    @property
    def wanted_portraits(self) -> list[Portrait]:
        """Every portrait the wiki links, in character then save order."""
        return [p for c in sorted(self.characters) for p in self.characters[c].portraits]

    @property
    def wanted_arms(self) -> list[Arms]:
        """Every coat of arms the wiki links: the titles' first, then the houses'."""
        titled = [self.titles[k].arms for k in sorted(self.titles) if self.titles[k].arms]
        housed = [self.houses[h].arms for h in sorted(self.houses) if self.houses[h].arms]
        return [*titled, *housed]


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
        person = self.person(character_id)
        return person.name if person and person.name else f"Character {character_id}"


def _merge_character(wiki: Wiki, cid: int, char: Block, date: str, save_file: str = "") -> None:
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
    name = Path(save_file).name
    # Only the living can be harvested: the companion switches to a character
    # with `play <id>`, which the game refuses for the dead, so asking for a
    # portrait of someone already buried is work nobody can do. `dead_data`
    # decides it, and matches `living_characters` exactly on the real saves --
    # someone who died on the save's own date still sits in `living` carrying
    # the block, and is not harvestable either (docs/PLAN.md §7).
    if name and dead is None and not any(p.save == name for p in record.portraits):
        # one portrait per save the character was alive in: the same person at
        # three dates is three images, which is the point
        record.portraits.append(
            Portrait(
                file=portrait_name(save_file, cid),
                save=name,
                checksum=save_checksum(save_file),
                character=cid,
                save_date=date,
            )
        )
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


def build_wiki(
    views: list[SnapshotView],
    title_key: str,
    with_family: bool = True,
    with_kin: bool = True,
) -> Wiki:
    """Merge snapshots, oldest first, into one picture of the lineage."""
    views = sorted(views, key=lambda v: date_key(v.fp.date))
    wiki = Wiki(run_id=views[0].fp.run_id if views else "", title_key=title_key)
    for view in views:
        wiki.snapshots.append(view.fp.date)
        for record in view.titles:
            title = _merge_title(wiki, record, view)
            de_jure = view.index.resolve(record.de_jure_liege)
            if de_jure is not None:
                title.de_jure_liege = de_jure.key
        root = wiki.titles[view.target.key]
        root.vassals[view.fp.date] = [r.key for r in view.vassals]
        for cid, char in view.characters.items():
            _merge_character(wiki, cid, char, view.fp.date, view.fp.file)
        wiki.saves.append(
            {"file": Path(view.fp.file).name, "checksum": save_checksum(view.fp.file), "date": view.fp.date}
        )
    _load_vassalage(wiki, views)
    if with_family:
        _load_family(wiki, views, with_kin=with_kin)
    # after the family, never before it: promoting the direct line brings in
    # characters of its own, and their houses have to be resolved too
    _load_houses(wiki, views)
    _load_title_arms(wiki, views)
    return wiki


def _load_title_arms(wiki: Wiki, views: list[SnapshotView]) -> None:
    """Every title bears arms too -- all 12 915 of the 1364 save carry an id.

    Newest save first, as for houses, because a title the newest save has
    destroyed is still in an older one. A title and the house holding it often
    bear the same arms, and then they share a file: the name comes from the
    recipe, not from who bears it.
    """
    for view in reversed(views):
        missing = {key for key, title in wiki.titles.items() if title.arms is None}
        if not missing:
            return
        save_file = view.fp.file
        coats: dict[str, int] = {}
        for key in missing:
            record = view.index.get(key)
            if record is not None and record.coat_of_arms_id is not None:
                coats[key] = record.coat_of_arms_id
        recipes = read_arms(save_file, set(coats.values()))
        for key, coat in coats.items():
            recipe = recipes.get(coat)
            if recipe is None:
                continue
            wiki.titles[key].arms = Arms(
                file=arms_name(recipe.digest),
                save=Path(save_file).name,
                checksum=save_checksum(save_file),
                coat_of_arms_id=coat,
                title=key,
                definition=recipe.definition,
            )


def _merge_family(record: WikiCharacter, family: Family) -> None:
    """Union across snapshots: a later save knows of more children, never fewer.

    Nothing is ever dropped, for the same reason the rest of the wiki unions:
    an older snapshot is the only source for a child the newest one has pruned.
    """
    for field_name in ("parents", "siblings", "spouses", "former_spouses", "children"):
        merged = dict.fromkeys([*getattr(record, field_name), *getattr(family, field_name)])
        setattr(record, field_name, sorted(merged))
    # a marriage that ended is in `spouse` in the older save and
    # `former_spouses` in the newer one; unioning both would list the person
    # twice, and "former" is the later word on it
    record.spouses = [s for s in record.spouses if s not in set(record.former_spouses)]
    record.real_father = family.real_father or record.real_father


def direct_line(record: WikiCharacter) -> set[int]:
    """Parents, spouses and children: the people a dynastic chronicle is about.

    Siblings are deliberately left out. They are named on the page either way,
    and giving each one a page of their own buys 689 more for the Germania
    chronicle that are mostly dead ends (docs/PLAN.md §10).
    """
    kin = {*record.parents, *record.spouses, *record.former_spouses, *record.children}
    if record.real_father is not None:
        kin.add(record.real_father)
    return kin


def _load_family(wiki: Wiki, views: list[SnapshotView], with_kin: bool = True) -> None:
    """Read each snapshot's family, promote the direct line, name the rest.

    This is the expensive part of a build: parents exist in the save only as
    other people's child lists, so finding them means reading every character
    record, with no early exit (:mod:`ck3parser.family`). One pass per snapshot
    and no more, because the inversion is kept whole: promoting someone to a
    page afterwards needs no second read.
    """
    if not wiki.characters:
        return
    indexes = {view.fp.date: read_index(view.fp.file, set(wiki.characters)) for view in views}
    for view in views:
        index = indexes[view.fp.date]
        for cid in list(wiki.characters):
            _merge_family(wiki.characters[cid], index.family_of(cid))

    if with_kin:
        _promote(wiki, views, indexes)
    _name_the_rest(wiki, views)


def _promote(wiki: Wiki, views: list[SnapshotView], indexes: dict) -> None:
    """Give the direct line pages of their own, and portraits where they lived.

    Holding a title is what put the others in; these are here by blood or
    marriage, so they get the same page and the same portrait rule -- a slot
    only for the saves they were alive in.
    """
    kin: set[int] = set()
    for record in list(wiki.characters.values()):
        kin |= direct_line(record)
    kin -= wiki.characters.keys()
    if not kin:
        return
    for view in views:
        index = indexes[view.fp.date]
        for cid, char in find_characters(view.fp.file, kin).items():
            _merge_character(wiki, cid, char, view.fp.date, view.fp.file)
            family = char.get("family_data")
            if isinstance(family, Block):
                _merge_family(wiki.characters[cid], own_family(cid, family))
            _merge_family(wiki.characters[cid], index.family_of(cid))


def _name_the_rest(wiki: Wiki, views: list[SnapshotView]) -> None:
    """Everyone the family still reaches who has no page: named, nothing more."""
    outside: set[int] = set()
    for record in wiki.characters.values():
        outside.update(
            record.parents, record.siblings, record.spouses,
            record.former_spouses, record.children,
        )
        if record.real_father is not None:
            outside.add(record.real_father)
    outside -= wiki.characters.keys()
    for view in reversed(views):
        missing = outside - wiki.relatives.keys()
        if not missing:
            break
        for cid, char in find_characters(view.fp.file, missing).items():
            dead = char.get("dead_data")
            wiki.relatives[cid] = Relative(
                id=cid,
                name=clean_name(str(char.get("first_name") or "")),
                birth=str(char["birth"]) if char.get("birth") is not None else None,
                death=str(dead["date"]) if isinstance(dead, Block) and dead.get("date") else None,
            )


def _load_vassalage(wiki: Wiki, views: list[SnapshotView]) -> None:
    """Ask every snapshot who each title answered to, not just the lineage.

    A title is only in a snapshot's *lineage* while it is a direct vassal of the
    subject, but it is in that snapshot's `index` as long as it exists at all.
    So a vassal that left is not simply lost: the save still says who took it,
    and that is worth more than recording its liege as the subject because that
    is how it was selected.

    Absence is not the same as independence and is never recorded as a liege: a
    title missing from a save was destroyed, or pruned, and we do not know
    which.
    """
    for view in views:
        for key, title in wiki.titles.items():
            record = view.index.get(key)
            if record is None:
                continue
            liege = view.index.resolve(record.de_facto_liege)
            title.lieges[view.fp.date] = liege.key if liege else INDEPENDENT
    # the infobox wants the current answer, which is the newest one we have
    for title in wiki.titles.values():
        seen = sorted(title.lieges, key=date_key)
        title.liege = title.lieges[seen[-1]] if seen else title.liege


def _load_houses(wiki: Wiki, views: list[SnapshotView]) -> None:
    """Resolve the houses the wiki's characters belong to, and their dynasties.

    Newest save first, then older ones for whatever it could not resolve: a run
    prunes, so a house every living member has left may only still be in an old
    snapshot. Each house records the save it was read from, because a
    `coat_of_arms_id` indexes that save; the arms *image* does not, because it
    is named after the recipe (:mod:`ck3parser.arms`).
    """
    wanted = {c.house for c in wiki.characters.values() if c.house is not None}
    if not wanted or not views:
        return
    houses: dict[int, WikiHouse] = {}
    for view in reversed(views):
        missing = wanted - houses.keys()
        if not missing:
            break
        save_file = view.fp.file
        found = find_houses(save_file, missing)
        dynasties = find_dynasties(
            save_file, {h.dynasty for h in found.values() if h.dynasty is not None}
        )
        coats = {}
        for house_id, house in found.items():
            dynasty = dynasties.get(house.dynasty) if house.dynasty is not None else None
            coats[house_id] = (house, dynasty, arms_id(house, dynasty))
        recipes = read_arms(save_file, {c for _, _, c in coats.values() if c is not None})
        for house_id, (house, dynasty, coat) in coats.items():
            recipe = recipes.get(coat) if coat is not None else None
            # no recipe, no name: the id alone cannot identify a picture, and a
            # name that does not identify one would ask for the same image twice
            arms = None
            if recipe is not None:
                arms = Arms(
                    file=arms_name(recipe.digest),
                    save=Path(save_file).name,
                    checksum=save_checksum(save_file),
                    coat_of_arms_id=coat,
                    house=house_id,
                    definition=recipe.definition,
                )
            houses[house_id] = WikiHouse(house=house, dynasty=dynasty, arms=arms)
    wiki.houses = dict(sorted(houses.items()))
