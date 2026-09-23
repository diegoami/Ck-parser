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
from ck3parser.cultures import Culture, find_cultures
from ck3parser.dynasties import Dynasty, House, arms_id, find_dynasties, find_houses, house_name
from ck3parser.faiths import Faith, find_faiths
from ck3parser.family import Family, own_family
from ck3parser.parser import Block, date_key, to_date
from ck3parser.pipeline import SnapshotView
from ck3parser.portraits import arms_name, portrait_name, save_checksum
from ck3parser.realm import changes as realm_changes
from ck3parser.realm import realm as compute_realm
from ck3parser.titles import TitleRecord
from ck3parser.vassalage import INDEPENDENT, Vassalage, stretches

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
    #: the end the title's history gave, when the holder's death came first and
    #: `end` was brought back to it; None when the two agree
    recorded_end: str | None = None

    def sort_key(self) -> tuple[int, int, int]:
        return date_key(self.start) if self.start else (0, 0, 0)


@dataclass
class RealmKingdom:
    """A realm's counties within one de jure kingdom, by vassal rank."""

    key: str | None  #: None for counties with no de jure kingdom
    name: str
    held: int = 0  #: rank 0: the ruler's own
    vassals: int = 0  #: rank 1: a direct vassal's
    deeper: int = 0  #: rank 2 and below

    @property
    def total(self) -> int:
        return self.held + self.vassals + self.deeper


@dataclass
class RealmCounty:
    """A county that entered or left the realm, between two snapshots (§16)."""

    key: str
    name: str
    kind: str  #: "gained", "left" or "gone" (ck3parser.realm.RealmChange)
    after: str
    before: str


@dataclass
class WikiRealm:
    """The subject title's holder's realm at one snapshot, as the page shows it.

    A summary rather than the realm itself: 1 000 counties a save times every
    snapshot is more than a page needs, and every number here is computed from
    `ck3parser.realm`, never counted twice.
    """

    date: str
    ruler: int
    by_rank: dict[int, int]  #: counties at each vassal rank
    kingdoms: list[RealmKingdom]  #: largest first
    changes: list[RealmCounty]  #: against the previous snapshot; empty for the first

    @property
    def counties(self) -> int:
        return sum(self.by_rank.values())


@dataclass
class Gap:
    """A stretch between two tenures of a title with no holder recorded.

    Never filled in: a save's history before the bookmark is sparse, and the
    successor it skips is not ours to guess (docs/PLAN.md §9).
    """

    start: str
    end: str


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
    female: bool = False

    @property
    def lifespan(self) -> str:
        if self.birth and self.death:
            return f"{self.birth} – {self.death}"
        return f"b. {self.birth}" if self.birth else ""


#: why a character has a page, most important first: held a title of the
#: wiki; the direct line of someone who did; the ring beyond it, titled.
#: One role each, and the first that applies wins: someone can be both a
#: ruler and a ruler's son, and is then an ever-holder. The order is kept by
#: construction -- ever-holders are merged before the direct line is promoted,
#: and the direct line before the ring beyond it, and a role is only set when
#: a character is first added.
ROLES = ("ever-holder", "kin", "titled-kin")

#: highest first, the order a list of someone's titles reads in
TIER_ORDER = {"empire": 0, "kingdom": 1, "duchy": 2, "county": 3, "barony": 4}


@dataclass
class Holding:
    """A title someone held in a snapshot, whether or not the wiki is about it.

    Only the *current* holder of each title in each save: a save names who holds
    a title now and, for the past, only who held the titles it keeps history
    for. `seen` lists the snapshots that said so.
    """

    key: str
    name: str
    tier: str | None = None
    seen: list[str] = field(default_factory=list)

    def sort_key(self) -> tuple[int, str]:
        return (TIER_ORDER.get(self.tier or "", 9), self.name)


@dataclass
class WikiCharacter:
    id: int
    name: str = ""
    birth: str | None = None
    death: str | None = None
    death_reason: str | None = None
    female: bool = False
    house: int | None = None
    #: indices into this save's own culture and faith tables, resolved later
    culture: int | None = None
    faith: int | None = None
    seen: list[str] = field(default_factory=list)  #: snapshot dates this record came from
    portraits: list[Portrait] = field(default_factory=list)
    parents: list[int] = field(default_factory=list)
    siblings: list[int] = field(default_factory=list)
    spouses: list[int] = field(default_factory=list)
    former_spouses: list[int] = field(default_factory=list)
    children: list[int] = field(default_factory=list)
    real_father: int | None = None
    #: why this character has a page: ROLES, in the order they are worth
    #: harvesting (docs/PLAN.md §7, the queue)
    role: str = "ever-holder"

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
    first_seen: str | None = None  #: first snapshot with the title in the lineage
    last_seen: str | None = None  #: last snapshot with the title in the lineage
    #: last snapshot with the title in the save at all, lineage or not: the
    #: newest word on who holds it (docs/PLAN.md §9, "following a title")
    last_recorded: str | None = None

    @property
    def all_vassals(self) -> list[str]:
        return sorted({key for keys in self.vassals.values() for key in keys})

    def vassalage(self, snapshots: list[str]) -> list[Vassalage]:
        """Who this title answered to, as stretches between snapshots."""
        return stretches(self.lieges, snapshots)


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
    cultures: dict[int, Culture] = field(default_factory=dict)
    faiths: dict[int, Faith] = field(default_factory=dict)
    relatives: dict[int, Relative] = field(default_factory=dict)  #: named, but no page
    #: every title each character held at some snapshot, lineage or not
    holdings: dict[int, dict[str, Holding]] = field(default_factory=dict)
    #: the subject title's holder's realm at each snapshot, oldest first (§16)
    realms: list[WikiRealm] = field(default_factory=list)
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

    def is_current(self, title: WikiTitle, tenure: Tenure) -> bool:
        """Open in the newest snapshot, not merely open when the title was last seen."""
        return tenure.open and title.last_recorded == (self.snapshots[-1] if self.snapshots else None)

    def succession(self, title: WikiTitle) -> list[Tenure | Gap]:
        """The title's tenures in order, with a `Gap` wherever nobody is recorded.

        A handover the next day is the game's own convention -- a ruler dies and
        the heir's entry is dated the day after -- so only more than one day
        between two tenures is a gap.
        """
        out: list[Tenure | Gap] = []
        previous: Tenure | None = None
        for tenure in title.tenures:
            if previous is not None and previous.end and tenure.start:
                ended, began = to_date(previous.end), to_date(tenure.start)
                if ended and began and (began - ended).days > 1:
                    out.append(Gap(previous.end, tenure.start))
            out.append(tenure)
            if previous is None or not previous.end or (
                tenure.end and date_key(tenure.end) > date_key(previous.end)
            ):
                previous = tenure
        return out

    def gap_after(self, title: WikiTitle, tenure: Tenure) -> Gap | None:
        """The gap that follows this tenure, if nobody is recorded right after it."""
        items = self.succession(title)
        for here, following in zip(items, items[1:]):
            if here is tenure and isinstance(following, Gap):
                return following
        return None

    def held_elsewhere(self, character_id: int) -> list[Holding]:
        """What this character held outside the lineage, highest tier first."""
        held = self.holdings.get(character_id, {})
        return sorted((h for k, h in held.items() if k not in self.titles), key=Holding.sort_key)

    def named(self, character_id: int) -> str:
        person = self.person(character_id)
        return person.name if person and person.name else f"Character {character_id}"


def _merge_character(
    wiki: Wiki, cid: int, char: Block, date: str, save_file: str = "", role: str = "ever-holder"
) -> None:
    dead = char.get("dead_data")
    existing = wiki.characters.get(cid)
    record = existing or WikiCharacter(id=cid, role=role)
    record.name = clean_name(str(char.get("first_name") or "")) or record.name
    record.birth = record.birth or (str(char["birth"]) if char.get("birth") is not None else None)
    record.female = bool(char.get("female", record.female))
    house = char.get("dynasty_house")
    record.house = house if isinstance(house, int) else record.house
    # a character can convert or assimilate, so the newest save's answer wins,
    # exactly as the newest save's house does
    for attr in ("culture", "faith"):
        value = char.get(attr)
        if isinstance(value, int):
            setattr(record, attr, value)
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
    title.first_seen = min(filter(None, [title.first_seen, view.fp.date]), key=date_key)
    title.last_seen = max(filter(None, [title.last_seen, view.fp.date]), key=date_key)
    _merge_history(title, record, view)
    wiki.titles[record.key] = title
    return title


def _merge_history(title: WikiTitle, record: TitleRecord, view: SnapshotView) -> None:
    """Add what one snapshot's record says about who held the title, and when.

    Used both for the lineage and for a title of the wiki that one snapshot
    has outside it: the history is the title's own, whoever its liege is.
    """
    if title.last_recorded is None or date_key(view.fp.date) >= date_key(title.last_recorded):
        title.last_recorded = view.fp.date
        title.holder = record.holder if record.holder is not None else title.holder

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


def _end_reigns_at_death(wiki: Wiki) -> None:
    """Close a tenure at its holder's death when the history runs on past it.

    A title's history closes a tenure only at its next entry, and before the
    bookmark those are sparse: `e_hre` goes from Heinrich (died 936.7.2) to the
    next entry in 962.2.2, which read naively has him reign 26 years dead. The
    death is the better end; the years after it become a `Gap`, never a guessed
    successor. 316 tenures across the three release chronicles, most of them the
    one-day handover the game always records, which `succession` does not count
    as a gap. An open tenure is left alone: the newest save says who holds it.
    """
    for title in wiki.titles.values():
        for tenure in title.tenures:
            holder = wiki.characters.get(tenure.holder)
            death = holder.death if holder else None
            if tenure.open or not death or not tenure.end:
                continue
            if date_key(tenure.end) > date_key(death) and (
                not tenure.start or date_key(death) >= date_key(tenure.start)
            ):
                tenure.recorded_end = tenure.recorded_end or tenure.end
                tenure.end = death


def _follow_titles(wiki: Wiki, views: list[SnapshotView]) -> None:
    """Read every title of the wiki from every snapshot that has it, lineage or not.

    A title can leave the lineage and stay in the save: Denmark was an
    immediate vassal of Germania only in the 1358 save, and read from the
    lineage alone, Asa's tenure stayed open four years after her death. The
    1361 and 1364 saves still hold Denmark, with its whole history; this reads
    it. The holders it turns up held a title of the wiki, so they are
    ever-holders like the rest and get pages. A title *absent* from a later save
    was destroyed or pruned and the save does not say which, so nothing is
    inferred from absence: its last tenure stays open, dated by `last_recorded`.
    """
    known = {t.holder for title in wiki.titles.values() for t in title.tenures}
    for view in views:
        inside = set(view.keys)
        for key, title in wiki.titles.items():
            record = None if key in inside else view.index.get(key)
            if record is not None:
                _merge_history(title, record, view)
    found = {t.holder for title in wiki.titles.values() for t in title.tenures} - known
    found -= wiki.characters.keys()
    for view in views:
        for cid, char in view.find_characters(found).items():
            _merge_character(wiki, cid, char, view.fp.date, view.fp.file)


def build_wiki(
    views: list[SnapshotView],
    title_key: str,
    with_family: bool = True,
    with_kin: bool = True,
    with_siblings: bool = True,
    with_titled_kin: bool = True,
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
    # before the family: the holders it finds are ever-holders, whose kin count
    _follow_titles(wiki, views)
    _end_reigns_at_death(wiki)
    _load_vassalage(wiki, views)
    _load_holdings(wiki, views)
    if with_family:
        _load_family(
            wiki, views, with_kin=with_kin, with_siblings=with_siblings,
            with_titled_kin=with_titled_kin,
        )
    # after the family, never before it: promoting the direct line brings in
    # characters of its own, and their houses have to be resolved too
    _load_houses(wiki, views)
    _load_title_arms(wiki, views)
    _load_cultures_and_faiths(wiki, views)
    _load_realms(wiki, views)
    return wiki


def _de_jure_kingdom(index, record) -> tuple[str | None, str]:
    """The kingdom a title belongs to on the map, whoever holds it."""
    seen = set()
    while record is not None and record.idx not in seen:
        if record.tier == "kingdom":
            return record.key, record.display_name
        seen.add(record.idx)
        record = index.resolve(record.de_jure_liege)
    return None, "No de jure kingdom"


def _load_realms(wiki: Wiki, views: list[SnapshotView]) -> None:
    """The subject title's holder's realm at each snapshot, and what changed.

    Per snapshot and only per snapshot: a save says who each title's liege is,
    never who it was, so a change is reported as the window between two saves
    and nothing is drawn in between (docs/PLAN.md §9, §16). The realm follows
    the title across a succession, so consecutive realms can be two people's.
    """
    previous = None
    previous_names: dict[str, str] = {}
    for view in views:
        ruler = view.target.holder
        if ruler is None:
            continue
        current = compute_realm(view.index, ruler, view.fp.date)
        counties = current.of_tier("county")
        kingdoms: dict[str | None, RealmKingdom] = {}
        for key, title in counties.items():
            kkey, kname = _de_jure_kingdom(view.index, view.index.get(key))
            row = kingdoms.setdefault(kkey, RealmKingdom(key=kkey, name=kname))
            if title.depth == 0:
                row.held += 1
            elif title.depth == 1:
                row.vassals += 1
            else:
                row.deeper += 1
        names = {key: view.index.get(key).display_name for key in counties}
        moved = []
        if previous is not None:
            for change in realm_changes(previous, current):
                name = names.get(change.key) or previous_names.get(change.key) or change.key
                if change.key in current.in_save and change.key not in names:
                    name = view.index.get(change.key).display_name
                moved.append(RealmCounty(change.key, name, change.kind, change.after, change.before))
        wiki.realms.append(WikiRealm(
            date=view.fp.date,
            ruler=ruler,
            by_rank=dict(sorted(current.by_depth("county").items())),
            kingdoms=sorted(kingdoms.values(), key=lambda k: (-k.total, k.name)),
            changes=moved,
        ))
        previous, previous_names = current, names


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


def direct_line(record: WikiCharacter, with_siblings: bool = True) -> set[int]:
    """The people a dynastic chronicle is about, who each get a page.

    Parents, spouses and children always. Siblings too, because a succession is
    usually a quarrel between them: the brother who was passed over is the
    reason a reign happened at all, and a chronicle that names him without a
    page cannot say what became of him. They are the widest ring that earns
    its pages whole; the ring beyond gets pages only where it holds a title
    (docs/PLAN.md §10). `--no-siblings` drops back to the narrow line.
    """
    kin = {*record.parents, *record.spouses, *record.former_spouses, *record.children}
    if with_siblings:
        kin |= set(record.siblings)
    if record.real_father is not None:
        kin.add(record.real_father)
    return kin


def _load_holdings(wiki: Wiki, views: list[SnapshotView]) -> None:
    """Who held what in each snapshot, across the whole save, not just the lineage.

    One walk over each save's title index, which is already in memory. It is
    what lets a page say what someone held outside the chronicle, and what
    decides who in the family's second ring earns a page (docs/PLAN.md §10).
    """
    for view in views:
        for record in view.index.by_idx.values():
            if record.holder is None:
                continue
            held = wiki.holdings.setdefault(record.holder, {})
            holding = held.get(record.key)
            if holding is None:
                holding = held[record.key] = Holding(
                    key=record.key, name=record.display_name, tier=record.tier
                )
            if view.fp.date not in holding.seen:
                holding.seen.append(view.fp.date)


def _load_family(
    wiki: Wiki,
    views: list[SnapshotView],
    with_kin: bool = True,
    with_siblings: bool = True,
    with_titled_kin: bool = True,
) -> None:
    """Read each snapshot's family, promote the direct line, name the rest.

    This is the expensive part of a build: parents exist in the save only as
    other people's child lists, so finding them means reading every character
    record, with no early exit (:mod:`ck3parser.family`). One pass per snapshot
    and no more, because the inversion is kept whole: promoting someone to a
    page afterwards needs no second read.
    """
    if not wiki.characters:
        return
    indexes = {view.fp.date: view.family_index(set(wiki.characters)) for view in views}
    for view in views:
        index = indexes[view.fp.date]
        for cid in list(wiki.characters):
            _merge_family(wiki.characters[cid], index.family_of(cid))

    if with_kin:
        _promote(wiki, views, indexes, _ring(wiki, with_siblings), "kin")
        if with_titled_kin:
            # one ring further, and only for those who hold a title themselves:
            # the whole ring is ~13 000 people of whom 98.6% hold nothing
            _promote(
                wiki, views, indexes, _ring(wiki, with_siblings) & wiki.holdings.keys(), "titled-kin"
            )
    _name_the_rest(wiki, views)


def _ring(wiki: Wiki, with_siblings: bool = True) -> set[int]:
    """Everyone in the direct line of somebody with a page, who has none yet."""
    kin: set[int] = set()
    for record in wiki.characters.values():
        kin |= direct_line(record, with_siblings=with_siblings)
    return kin - wiki.characters.keys()


def _promote(
    wiki: Wiki, views: list[SnapshotView], indexes: dict, kin: set[int], role: str = "kin"
) -> None:
    """Give these relatives pages of their own, and portraits where they lived.

    Holding a title is what put the others in; these are here by blood or
    marriage, so they get the same page and the same portrait rule -- a slot
    only for the saves they were alive in. Called twice: once for the whole
    direct line of the title-holders, once for the titled part of the ring
    beyond it.
    """
    if not kin:
        return
    for view in views:
        index = indexes[view.fp.date]
        for cid, char in view.find_characters(kin).items():
            _merge_character(wiki, cid, char, view.fp.date, view.fp.file, role)
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
        for cid, char in view.find_characters(missing).items():
            dead = char.get("dead_data")
            wiki.relatives[cid] = Relative(
                id=cid,
                name=clean_name(str(char.get("first_name") or "")),
                birth=str(char["birth"]) if char.get("birth") is not None else None,
                death=str(dead["date"]) if isinstance(dead, Block) and dead.get("date") else None,
                female=bool(char.get("female")),
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


def _load_cultures_and_faiths(wiki: Wiki, views: list[SnapshotView]) -> None:
    """Resolve the cultures and faiths the wiki's characters hold.

    Newest save first, then older ones for whatever is left, the same way houses
    are resolved: both are indexed **per save**, so a culture or faith the newest
    snapshot never mentions can still be read out of an older one.

    Run after the family pass, never before it: promoting the direct line brings
    in characters of its own, and they have a culture and a faith too.

    A faith's founder and a culture's head are ordinary character ids, so they
    are named like anyone else the wiki reaches but does not give a page.
    """
    wanted_cultures = {c.culture for c in wiki.characters.values() if c.culture is not None}
    wanted_faiths = {c.faith for c in wiki.characters.values() if c.faith is not None}
    if not views or not (wanted_cultures or wanted_faiths):
        return
    for view in reversed(views):
        missing_cultures = wanted_cultures - wiki.cultures.keys()
        missing_faiths = wanted_faiths - wiki.faiths.keys()
        if not (missing_cultures or missing_faiths):
            break
        wiki.cultures.update(find_cultures(view.fp.file, missing_cultures))
        wiki.faiths.update(find_faiths(view.fp.file, missing_faiths))
    _name_the_founders(wiki, views)


def _name_the_founders(wiki: Wiki, views: list[SnapshotView]) -> None:
    """Whoever founded a faith or heads a culture, named but given no page.

    A faith founded during the run carries its founder's id, and on the Germania
    run that is the played dynasty's own Folmar, who founded the faith the realm
    is named after. Saying so needs nothing but his name.
    """
    outside = {f.founder for f in wiki.faiths.values() if f.founder is not None}
    outside |= {c.head for c in wiki.cultures.values() if c.head is not None}
    outside -= wiki.characters.keys()
    outside -= wiki.relatives.keys()
    for view in reversed(views):
        missing = outside - wiki.relatives.keys()
        if not missing:
            break
        for cid, char in view.find_characters(missing).items():
            dead = char.get("dead_data")
            wiki.relatives[cid] = Relative(
                id=cid,
                name=clean_name(str(char.get("first_name") or "")),
                birth=str(char["birth"]) if char.get("birth") is not None else None,
                death=str(dead["date"]) if isinstance(dead, Block) and dead.get("date") else None,
                female=bool(char.get("female")),
            )
