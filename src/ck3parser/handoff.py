"""The character hand-off to the portrait harvester.

`diegoami/ck_portrait_generator` captures each character's real in-game
portrait by switching to them with the console. Its decisions put the other
half of the job here: *"how tool 1 decides which characters are 'interesting',
and the shape of the hand-off file"* is this project's call, and it consumes a
plain character-id list and nothing more (docs/PLAN.md §7).

Two constraints come from how it works, not from taste:

* ``play <id>`` only works on a **living** character, so a list is scoped to
  one save's date. That is the feature, not a limit: successive saves give the
  same person at different ages.
* Its manifest keys on ``(character id, save date)`` and it harvests one save
  at a time, so this writes **one file per snapshot** rather than a union.

"Interesting" in v1 means the lineage the wiki is built from: everyone who has
ever held the target title or one of its immediate vassals, narrowed to those
alive at that snapshot's date.

Output matches what the harvester already reads: a CSV whose `character_id`
column is the only one it requires, or with ``--ids-only`` the bare
one-id-per-line form its ``--ids-file`` takes. Character names are deliberately
absent; the harvester drops them on principle.

Alongside each snapshot's characters go the **houses** those characters belong
to, with the `coat_of_arms_id` their dynasty carries. A coat of arms is an image
to be harvested just as a portrait is, and its id is an index inside one save,
so it is written per snapshot and named from that save
(:mod:`ck3parser.portraits`). House names are not people's names and are kept.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from .arms import CoatOfArms, read_arms
from .dynasties import Dynasty, House, arms_id, find_dynasties, find_houses, house_name
from .parser import Block
from .portraits import arms_name, portrait_name
from .pipeline import gather, resolve_saves
from .titles import TitleRecord

#: Columns written. `character_id` is the only one the harvester needs; the
#: rest land in its `extra` dict, so adding one here cannot break it.
COLUMNS = ("character_id", "birth_year", "sex", "dynasty_house", "save_date", "portrait_file")

#: Columns of the house list written beside each snapshot's characters.
HOUSE_COLUMNS = (
    "house_id", "dynasty_id", "coat_of_arms_id", "name", "dynasty_name",
    "found_date", "motto", "save_date", "arms_file",
)


@dataclass
class HandoffCharacter:
    character_id: int
    birth_year: int | None
    sex: str | None
    dynasty_house: int | None
    save_date: str
    portrait_file: str = ""

    def row(self) -> dict[str, object]:
        return {k: ("" if v is None else v) for k, v in asdict(self).items()}


@dataclass
class HandoffHouse:
    house_id: int
    dynasty_id: int | None
    coat_of_arms_id: int | None
    name: str
    dynasty_name: str
    found_date: str | None
    motto: str
    save_date: str
    arms_file: str = ""

    def row(self) -> dict[str, object]:
        return {k: ("" if v is None else v) for k, v in asdict(self).items()}


def _year(date: object) -> int | None:
    try:
        return int(str(date).split(".")[0])
    except (AttributeError, ValueError):
        return None


def describe(cid: int, char: Block, save_date: str, save_path: str = "") -> HandoffCharacter:
    house = char.get("dynasty_house")
    return HandoffCharacter(
        character_id=cid,
        birth_year=_year(char.get("birth")),
        sex="female" if char.get("female") else "male",
        dynasty_house=house if isinstance(house, int) else None,
        save_date=save_date,
        portrait_file=portrait_name(save_path, cid) if save_path else "",
    )


def describe_house(
    house: House, dynasty: Dynasty | None, save_date: str, recipe: CoatOfArms | None = None
) -> HandoffHouse:
    """One house's row. `recipe` names the arms image, because the id cannot.

    A `coat_of_arms_id` indexes one save, so the same number is different arms
    in another playthrough. The recipe the game draws from is what identifies
    the picture, and its digest is the file name both projects derive
    (:mod:`ck3parser.arms`).
    """
    return HandoffHouse(
        house_id=house.id,
        dynasty_id=house.dynasty,
        coat_of_arms_id=arms_id(house, dynasty),
        name=house_name(house, dynasty),
        dynasty_name=dynasty.display_name if dynasty else "",
        found_date=house.founded,
        motto=house.motto,
        save_date=save_date,
        arms_file=arms_name(recipe.digest) if recipe is not None else "",
    )


def houses_of(save_path: str, characters: list[HandoffCharacter], save_date: str) -> list[HandoffHouse]:
    """The houses these characters belong to, with their dynasty's arms id."""
    wanted = {c.dynasty_house for c in characters if c.dynasty_house is not None}
    houses = find_houses(save_path, wanted)
    dynasties = find_dynasties(
        save_path, {h.dynasty for h in houses.values() if h.dynasty is not None}
    )
    pairs = {}
    for house_id in sorted(houses):
        house = houses[house_id]
        dynasty = dynasties.get(house.dynasty) if house.dynasty is not None else None
        pairs[house_id] = (house, dynasty, arms_id(house, dynasty))
    recipes = read_arms(save_path, {c for _, _, c in pairs.values() if c is not None})
    return [
        describe_house(house, dynasty, save_date, recipes.get(coat) if coat is not None else None)
        for house, dynasty, coat in pairs.values()
    ]


def interesting_ids(titles: list[TitleRecord]) -> set[int]:
    """Everyone who has ever held one of these titles."""
    ids: set[int] = set()
    for record in titles:
        ids |= record.holder_ids()
    return ids


def select(
    save_path: str, title_key: str, with_vassals: bool = True, log=None, cache_dir=None
) -> list[HandoffCharacter]:
    """The harvestable characters of one snapshot's lineage, oldest id first."""
    log = sys.stderr if log is None else log
    view = gather(save_path, title_key, with_vassals, log=log, cache_dir=cache_dir)
    wanted = interesting_ids(view.titles)
    alive = view.living_characters(wanted)
    print(f"  harvestable: {len(alive)} of {len(wanted)} alive at {view.fp.date}", file=log)
    return [describe(cid, alive[cid], view.fp.date, save_path) for cid in sorted(alive)]


def write_csv(path: Path, rows: list, columns: tuple[str, ...] = COLUMNS) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns))
        writer.writeheader()
        for item in rows:
            writer.writerow(item.row())


def write_ids(path: Path, characters: list[HandoffCharacter]) -> None:
    path.write_text("".join(f"{c.character_id}\n" for c in characters), encoding="utf-8")


def slug(save_date: str) -> str:
    return save_date.replace(".", "_")


def run(
    save_path: str,
    title_key: str,
    out_dir: str,
    with_vassals: bool = True,
    run_id: str | None = None,
    ids_only: bool = False,
) -> int:
    try:
        saves = resolve_saves(save_path, run_id)
    except (FileNotFoundError, LookupError) as exc:
        print(exc, file=sys.stderr)
        return 2

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for path in saves:
        try:
            characters = select(path, title_key, with_vassals)
        except KeyError:
            print(f"warning: {title_key!r} is not in {Path(path).name}, skipped", file=sys.stderr)
            continue
        if not characters:
            print(f"warning: nobody harvestable in {Path(path).name}, no file written", file=sys.stderr)
            continue
        date = characters[0].save_date
        name = f"characters_{slug(date)}." + ("txt" if ids_only else "csv")
        (write_ids if ids_only else write_csv)(out / name, characters)
        houses = houses_of(path, characters, date)
        house_file = f"houses_{slug(date)}.csv"
        write_csv(out / house_file, houses, HOUSE_COLUMNS)
        print(f"  houses: {len(houses)}, {sum(1 for h in houses if h.arms_file)} with arms", file=sys.stderr)
        snapshots.append({
            "save": path,
            "save_date": date,
            "file": name,
            "characters": len(characters),
            "houses_file": house_file,
            "houses": len(houses),
        })

    if not snapshots:
        print(f"no harvestable characters for {title_key!r} in any of the {len(saves)} save(s)", file=sys.stderr)
        return 2

    manifest = {"title": title_key, "snapshots": snapshots}
    (out / "handoff.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    total = sum(s["characters"] for s in snapshots)
    print(f"wrote {len(snapshots)} list(s), {total} character rows, to {out}/", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m ck3parser.handoff",
        description="Write the portrait harvester's character list, one file per snapshot.",
    )
    ap.add_argument("save", help="a .ck3 file, or a directory of saves to treat as one run")
    ap.add_argument("--title", required=True, help="the lineage's title key, e.g. e_germany")
    ap.add_argument("--out", default="handoff", help="output directory (default: ./handoff)")
    ap.add_argument("--no-vassals", action="store_true", help="the title alone, without its vassals")
    ap.add_argument("--run", dest="run_id", help="which run to use when a directory holds several")
    ap.add_argument(
        "--ids-only",
        action="store_true",
        help="write bare ids, one per line, for the harvester's --ids-file",
    )
    args = ap.parse_args(argv)
    return run(
        args.save,
        args.title,
        args.out,
        with_vassals=not args.no_vassals,
        run_id=args.run_id,
        ids_only=args.ids_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
