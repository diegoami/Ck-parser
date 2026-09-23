"""Load a lineage into the graph, from one save or from a whole run.

A lineage is a title plus the titles currently held under it (its immediate de
facto vassals); ``--no-vassals`` narrows it to the title alone.

    python -m ck3parser.pipeline SAVE      --title k_papal_state [--dry-run]
    python -m ck3parser.pipeline SAVES_DIR --title k_papal_state [--dry-run]
    python -m ck3parser.pipeline SAVES_DIR --title k_papal_state --dry-run --echo

Given a directory, every snapshot of the run it holds is loaded oldest first.
That matters because CK3 prunes dead characters and destroyed titles as a run
goes on, so an old snapshot is the only source for history a later one has
dropped (docs/PLAN.md §4). Writes are idempotent ``MERGE``s, so a later
snapshot refines what an earlier one wrote and never deletes it.

Consecutive snapshots are checked against each other as they are loaded
(:mod:`ck3parser.consistency`). Disagreements are reported and set the exit
code, but never stop the load.

Exit codes: 0 loaded and consistent, 1 loaded with disagreements, 2 bad
arguments (unknown title, ambiguous directory).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ck3graph.loader import (
    DryRunSession,
    Neo4jConfig,
    Titled,
    holder_intervals,
    load_house,
    load_people,
    load_snapshot,
    load_title,
    load_vassalage,
    open_session,
)
from ck3graph.people import stream_people

from .arms import read_arms
from .characters import find_characters, living_characters
from .consistency import check_snapshots
from .container import open_gamestate_text
from .digest import CharacterDigest, digest_for
from .dynasties import arms_id, find_dynasties, find_houses
from .family import FamilyIndex, read_index
from .filter import is_filler
from .fingerprint import Fingerprint, fingerprint
from .parser import Block, PushbackLines, date_key, iter_children
from .portraits import arms_name
from .runs import Run, scan
from .titles import TitleIndex, TitleRecord, build_index
from .vassalage import INDEPENDENT, stretches

CHARACTER_SECTIONS = (("living",), ("dead_unprunable",), ("characters", "dead_prunable"))


@dataclass
class SnapshotView:
    """Everything one snapshot contributes, before it is written or rendered.

    `digest` is where the character questions go when there is one. Asking the
    view rather than the save is what makes a build incremental: the same two
    questions are answered out of a cached digest in seconds, or off the
    gamestate in a minute, and no caller has to know which
    (:mod:`ck3parser.digest`).
    """

    fp: Fingerprint
    index: TitleIndex
    target: TitleRecord
    vassals: list[TitleRecord]
    characters: dict[int, Block]
    digest: CharacterDigest | None = None

    @property
    def titles(self) -> list[TitleRecord]:
        return [self.target, *self.vassals]

    @property
    def keys(self) -> list[str]:
        return [record.key for record in self.titles]

    def find_characters(self, wanted: set[int]) -> dict[int, Block]:
        if self.digest is not None:
            return self.digest.find(wanted)
        return find_characters(self.fp.file, wanted)

    def family_index(self, wanted: set[int]) -> FamilyIndex:
        if self.digest is not None:
            return self.digest.family_index(wanted)
        return read_index(self.fp.file, wanted)

    def living_characters(self, wanted: set[int]) -> dict[int, Block]:
        """In ``living`` AND carrying no ``dead_data`` -- both, always.

        Someone who died on the save's own date still sits in `living` with the
        block on them, and asking for a portrait of them is work nobody can do
        (docs/PLAN.md §7).
        """
        if self.digest is not None:
            return self.digest.living(wanted)
        return living_characters(self.fp.file, wanted)


def collect_characters(save_path: str, wanted: set[int]) -> dict[int, Block]:
    """Stream the character sections once each, keeping only the wanted ids."""
    found: dict[int, Block] = {}
    for section in CHARACTER_SECTIONS:
        missing = wanted - found.keys()
        if not missing:
            break
        with open_gamestate_text(save_path) as lines:
            for cid, char in iter_children(PushbackLines(lines), section):
                try:
                    cid_int = int(cid)
                except (TypeError, ValueError):
                    continue
                if cid_int in missing and isinstance(char, Block):
                    found[cid_int] = char
                    missing.discard(cid_int)
                    if not missing:
                        break
    return found


def lineage(index: TitleIndex, title_key: str, with_vassals: bool) -> tuple[TitleRecord, list[TitleRecord]]:
    target = index.get(title_key)
    if target is None:
        raise KeyError(title_key)
    return target, (index.immediate_vassals(target) if with_vassals else [])


def gather(
    save_path: str,
    title_key: str,
    with_vassals: bool = True,
    log=None,
    cache_dir=None,
) -> SnapshotView:
    """Parse one save into the lineage and characters this run needs.

    With a `cache_dir`, the save's characters are read from its digest, or
    digested into it the first time. Everything else is read from the save
    either way: the character sections are where a build's minutes go
    (:mod:`ck3parser.digest`).
    """
    log = sys.stderr if log is None else log  # not a default: pytest swaps sys.stderr
    fp = fingerprint(save_path, with_sha256=False)
    digest = digest_for(save_path, fp, cache_dir, log)
    index = build_index(save_path)
    for reason, (key, date) in sorted(index.unknown_reasons().items()):
        print(
            f"warning: unknown history type {reason!r} in {Path(save_path).name}, first at"
            f" {key} {date}; it opened a tenure -- if it ends one, add it to titles.TERMINAL_TYPES",
            file=log,
        )
    target, vassals = lineage(index, title_key, with_vassals)
    print(
        f"{Path(save_path).name} [{fp.date}]: {target.key} ({target.display_name}, {target.tier})"
        f" with {len(vassals)} immediate vassal(s)",
        file=log,
    )
    referenced: set[int] = set()
    for record in (target, *vassals):
        referenced |= record.holder_ids()
    chars = digest.find(referenced) if digest else collect_characters(save_path, referenced)
    kept = {cid: char for cid, char in chars.items() if not is_filler(cid, char, referenced)}
    print(
        f"  characters: {len(referenced)} referenced, {len(chars)} found, {len(kept)} kept,"
        f" {len(referenced - chars.keys())} missing",
        file=log,
    )
    return SnapshotView(
        fp=fp, index=index, target=target, vassals=vassals, characters=kept, digest=digest
    )


def load_view(session, view: SnapshotView) -> None:
    """Write one snapshot's lineage. Every statement is a ``MERGE``.

    Vassalage is *not* written here. A save has no vassalage history, so who a
    title answered to is only known between snapshots and cannot be written
    until all of them have been asked (docs/PLAN.md §9); that is
    :class:`Observations`' job, at the end of the run.
    """
    load_snapshot(session, view.fp)
    for record in view.titles:
        intervals = holder_intervals(
            record.history, end_date=view.fp.date, current_holder=record.holder, holder_since=record.date
        )
        holders = {iv["holder"] for iv in intervals}
        load_title(
            session,
            view.fp,
            record,
            intervals,
            {cid: char for cid, char in view.characters.items() if cid in holders},
        )


@dataclass
class Observations:
    """Who each title answered to, at every snapshot, until the run is done.

    A save says who a title's liege **is** and never who it has been, so a
    change of liege is only ever known to have happened between two snapshots
    and a stretch cannot be written before the last one is read (docs/PLAN.md
    §9).

    What is kept is one liege key per title per date -- short strings -- and the
    names needed to label an edge. The snapshot's `TitleIndex` is not kept: it
    carries 107 328 history entries and is the expensive thing in a run, so it
    is released with the view that built it.

    Every title in the index is observed, not just the lineage, because a title
    that leaves the lineage is not lost: the save still says who took it, which
    is worth more than recording it under the subject because that is how it was
    selected. Only the lineage's own titles get edges, which is decided at the
    end, when the union across snapshots is known.
    """

    snapshots: list[str] = field(default_factory=list)
    lineage: set[str] = field(default_factory=set)
    names: dict[str, Titled] = field(default_factory=dict)
    de_facto: dict[str, dict[str, str | None]] = field(default_factory=dict)
    de_jure: dict[str, dict[str, str | None]] = field(default_factory=dict)

    def add(self, view: SnapshotView) -> None:
        date = view.fp.date
        self.snapshots.append(date)
        self.lineage.update(view.keys)
        for record in view.index.by_key.values():
            self.names[record.key] = Titled(record.key, record.display_name, record.tier)
            for liege_idx, observed in (
                (record.de_facto_liege, self.de_facto),
                (record.de_jure_liege, self.de_jure),
            ):
                liege = view.index.resolve(liege_idx)
                observed.setdefault(record.key, {})[date] = liege.key if liege else INDEPENDENT

    def emit(self, session) -> int:
        """Write one edge per stretch, for the lineage's titles. Returns the count."""
        order = sorted(self.snapshots, key=date_key)
        written = 0
        for key in sorted(self.lineage):
            vassal = self.names.get(key) or Titled(key)
            for kind, observed in (("de_facto", self.de_facto), ("de_jure", self.de_jure)):
                for stretch in stretches(observed.get(key, {}), order):
                    # independence is the absence of an edge, never an edge to
                    # nobody: a title that answered to no one has nothing to
                    # point at, and the node's own first_seen/last_seen is what
                    # tells that apart from a title we did not see
                    if stretch.liege is None or stretch.liege == key:
                        continue
                    liege = self.names.get(stretch.liege) or Titled(stretch.liege)
                    load_vassalage(session, vassal, liege, stretch, kind=kind)
                    written += 1
        return written


def load_houses(session, saves: list[str], wanted: set[int], log=None) -> int:
    """Resolve the houses the loaded characters belong to, newest save first.

    Newest first, then older ones for whatever it could not resolve: a run
    prunes, so a house every living member has left may only still be in an old
    snapshot. The arms are named after the recipe that draws them, never after
    the save's `coat_of_arms_id`, so the graph points at the same image file the
    wiki links (docs/PLAN.md §11).
    """
    log = sys.stderr if log is None else log
    found: set[int] = set()
    for save_file in reversed(saves):
        missing = wanted - found
        if not missing:
            break
        houses = find_houses(save_file, missing)
        dynasties = find_dynasties(
            save_file, {h.dynasty for h in houses.values() if h.dynasty is not None}
        )
        coats = {
            house_id: (house, dynasties.get(house.dynasty) if house.dynasty is not None else None)
            for house_id, house in houses.items()
        }
        recipes = read_arms(save_file, {c for c in (arms_id(h, d) for h, d in coats.values()) if c})
        for house_id, (house, dynasty) in coats.items():
            coat = arms_id(house, dynasty)
            recipe = recipes.get(coat) if coat is not None else None
            # no recipe, no name: a coat_of_arms_id indexes one save and names
            # no picture, so an id alone cannot say which image is wanted
            load_house(session, house, dynasty, arms_name(recipe.digest) if recipe else None)
            found.add(house_id)
    print(f"  houses: {len(wanted)} wanted, {len(found)} resolved", file=log)
    return len(found)


def resolve_saves(path: str, run_id: str | None = None, log=None) -> list[str]:
    """One save path, or every snapshot of the run in a directory, oldest first."""
    log = sys.stderr if log is None else log
    target = Path(path)
    if target.is_file():
        return [str(target)]
    runs: list[Run] = scan(target, with_sha256=False)
    if not runs:
        raise FileNotFoundError(f"no .ck3 saves under {target}")
    if run_id is not None:
        runs = [r for r in runs if r.run_id == run_id]
        if not runs:
            known = ", ".join(r.run_id for r in scan(target, with_sha256=False)) or "none"
            raise LookupError(f"no run {run_id!r} under {target}; known runs: {known}")
    elif len(runs) > 1:
        names = "\n".join(f"  {r.run_id}  ({len(r.snapshots)} snapshots)" for r in runs)
        raise LookupError(f"{target} holds {len(runs)} runs; pick one with --run\n{names}")
    run = runs[0]
    for warning in run.warnings:
        print(f"warning: {warning}", file=log)
    print(f"run {run.run_id}: {len(run.snapshots)} snapshot(s), oldest first", file=log)
    return [snapshot.fp.file for snapshot in run.snapshots]


def run(
    save_path: str,
    title_key: str,
    dry_run: bool,
    with_vassals: bool = True,
    run_id: str | None = None,
    check: bool = True,
    with_people: bool = False,
    echo: bool = False,
) -> int:
    try:
        saves = resolve_saves(save_path, run_id)
    except (FileNotFoundError, LookupError) as exc:
        print(exc, file=sys.stderr)
        return 2

    warnings: list[str] = []
    # a dry run echoes only on request: a whole run is thousands of statements,
    # and with --people hundreds of megabytes of parameters
    session = DryRunSession(echo=echo) if dry_run else open_session(Neo4jConfig.from_env())
    with session:
        previous: SnapshotView | None = None
        observed = Observations()
        houses: set[int] = set()
        loaded = 0
        for path in saves:
            try:
                view = gather(path, title_key, with_vassals)
            except KeyError:
                # a dynamic title can genuinely vanish from a later save, so skip
                # this snapshot rather than abandoning the ones that do have it
                print(f"warning: {title_key!r} is not in {Path(path).name}, skipped", file=sys.stderr)
                continue
            if check and previous is not None:
                found = check_snapshots(
                    previous.index,
                    previous.fp.date,
                    previous.characters,
                    view.index,
                    view.characters,
                    keys=sorted(set(previous.keys) | set(view.keys)),
                )
                for warning in found:
                    print(f"  disagreement: {warning}", file=sys.stderr)
                warnings += found
            load_view(session, view)
            observed.add(view)
            houses.update(
                house for char in view.characters.values()
                if isinstance(house := char.get("dynasty_house"), int)
            )
            if with_people:
                counts = load_people(session, view.fp, stream_people(view.fp.file))
                print(
                    "  everyone: "
                    + ", ".join(f"{n} {what}" for what, n in counts.items() if n)
                    + " (rows; a marriage is named by both records and merges into one edge)",
                    file=sys.stderr,
                )
            loaded += 1
            previous = view

        if loaded:
            # both need every snapshot read first: a vassalage stretch is only
            # known between two of them, and a house may survive only in an old
            # one
            print(f"  vassalage: {observed.emit(session)} stretch(es)", file=sys.stderr)
            load_houses(session, saves, houses)

    if dry_run:
        hint = "" if echo else "; --echo prints them"
        print(f"dry run: {len(session.statements)} statement(s) recorded, none written{hint}", file=sys.stderr)
    if not loaded:
        print(f"title {title_key!r} not found in any of the {len(saves)} save(s)", file=sys.stderr)
        return 2
    if warnings:
        print(f"{len(warnings)} disagreement(s) between snapshots", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ck3parser.pipeline")
    ap.add_argument("save", help="a .ck3 file, or a directory of saves to load as one run")
    ap.add_argument("--title", required=True, help="title key, e.g. k_papal_state")
    ap.add_argument("--dry-run", action="store_true", help="record Cypher instead of writing to Neo4j")
    ap.add_argument("--echo", action="store_true", help="with --dry-run, print every statement to stdout")
    ap.add_argument("--no-vassals", action="store_true", help="load the title alone, without its vassals")
    ap.add_argument("--run", dest="run_id", help="which run to load when a directory holds several")
    ap.add_argument("--no-check", action="store_true", help="skip the checks between consecutive snapshots")
    ap.add_argument(
        "--people",
        action="store_true",
        help="also load every character in the save and their family edges (a full pass per snapshot)",
    )
    args = ap.parse_args(argv)
    return run(
        args.save,
        args.title,
        args.dry_run,
        with_vassals=not args.no_vassals,
        run_id=args.run_id,
        check=not args.no_check,
        with_people=args.people,
        echo=args.echo,
    )


if __name__ == "__main__":
    raise SystemExit(main())
