"""Load a lineage into the graph, from one save or from a whole run.

A lineage is a title plus the titles currently held under it (its immediate de
facto vassals); ``--no-vassals`` narrows it to the title alone.

    python -m ck3parser.pipeline SAVE      --title k_papal_state [--dry-run]
    python -m ck3parser.pipeline SAVES_DIR --title k_papal_state [--dry-run]

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
from dataclasses import dataclass
from pathlib import Path

from ck3graph.loader import (
    DryRunSession,
    Neo4jConfig,
    holder_intervals,
    load_snapshot,
    load_title,
    load_vassal_edge,
    open_session,
)

from .consistency import check_snapshots
from .container import open_gamestate_text
from .filter import is_filler
from .fingerprint import Fingerprint, fingerprint
from .parser import Block, PushbackLines, iter_children
from .runs import Run, scan
from .titles import TitleIndex, TitleRecord, build_index

CHARACTER_SECTIONS = (("living",), ("dead_unprunable",), ("characters", "dead_prunable"))


@dataclass
class SnapshotView:
    """Everything one snapshot contributes to the graph, before it is written."""

    fp: Fingerprint
    index: TitleIndex
    target: TitleRecord
    vassals: list[TitleRecord]
    characters: dict[int, Block]

    @property
    def titles(self) -> list[TitleRecord]:
        return [self.target, *self.vassals]

    @property
    def keys(self) -> list[str]:
        return [record.key for record in self.titles]


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


def gather(save_path: str, title_key: str, with_vassals: bool = True, log=None) -> SnapshotView:
    """Parse one save into the lineage and characters the graph needs."""
    log = sys.stderr if log is None else log  # not a default: pytest swaps sys.stderr
    fp = fingerprint(save_path, with_sha256=False)
    index = build_index(save_path)
    target, vassals = lineage(index, title_key, with_vassals)
    print(
        f"{Path(save_path).name} [{fp.date}]: {target.key} ({target.display_name}, {target.tier})"
        f" with {len(vassals)} immediate vassal(s)",
        file=log,
    )
    referenced: set[int] = set()
    for record in (target, *vassals):
        referenced |= record.holder_ids()
    chars = collect_characters(save_path, referenced)
    kept = {cid: char for cid, char in chars.items() if not is_filler(cid, char, referenced)}
    print(
        f"  characters: {len(referenced)} referenced, {len(chars)} found, {len(kept)} kept,"
        f" {len(referenced - chars.keys())} missing",
        file=log,
    )
    return SnapshotView(fp=fp, index=index, target=target, vassals=vassals, characters=kept)


def load_view(session, view: SnapshotView) -> None:
    """Write one snapshot's lineage. Every statement is a ``MERGE``."""
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
    for record in view.vassals:
        load_vassal_edge(session, record, view.target, view.fp, kind="de_facto")
        de_jure = view.index.resolve(record.de_jure_liege)
        if de_jure is not None and de_jure.key != view.target.key:
            load_vassal_edge(session, record, de_jure, view.fp, kind="de_jure")


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
) -> int:
    try:
        saves = resolve_saves(save_path, run_id)
    except (FileNotFoundError, LookupError) as exc:
        print(exc, file=sys.stderr)
        return 2

    warnings: list[str] = []
    session = DryRunSession() if dry_run else open_session(Neo4jConfig.from_env())
    with session:
        previous: SnapshotView | None = None
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
            loaded += 1
            previous = view

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
    ap.add_argument("--dry-run", action="store_true", help="print Cypher instead of writing to Neo4j")
    ap.add_argument("--no-vassals", action="store_true", help="load the title alone, without its vassals")
    ap.add_argument("--run", dest="run_id", help="which run to load when a directory holds several")
    ap.add_argument("--no-check", action="store_true", help="skip the checks between consecutive snapshots")
    args = ap.parse_args(argv)
    return run(
        args.save,
        args.title,
        args.dry_run,
        with_vassals=not args.no_vassals,
        run_id=args.run_id,
        check=not args.no_check,
    )


if __name__ == "__main__":
    raise SystemExit(main())
