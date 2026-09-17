"""Traced run for one lineage: extract -> parse -> filter -> load.

A lineage is a title plus the titles currently held under it (its immediate
de facto vassals). ``--no-vassals`` narrows it to the title alone.

    python -m ck3parser.pipeline SAVE --title k_papal_state [--dry-run]

``--dry-run`` prints the Cypher instead of touching Neo4j, so the pipeline can
be traced without a database.
"""

from __future__ import annotations

import argparse
import sys

from ck3graph.loader import (
    DryRunSession,
    Neo4jConfig,
    holder_intervals,
    load_snapshot,
    load_title,
    load_vassal_edge,
    open_session,
)

from .container import open_gamestate_text
from .filter import is_filler
from .fingerprint import fingerprint
from .parser import Block, PushbackLines, iter_children
from .titles import TitleIndex, TitleRecord, build_index

CHARACTER_SECTIONS = (("living",), ("dead_unprunable",), ("characters", "dead_prunable"))


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


def run(save_path: str, title_key: str, dry_run: bool, with_vassals: bool = True) -> int:
    fp = fingerprint(save_path, with_sha256=False)
    print(f"save: {save_path}  date={fp.date}  run={fp.run_id}", file=sys.stderr)

    index = build_index(save_path)
    try:
        target, vassals = lineage(index, title_key, with_vassals)
    except KeyError:
        print(f"title {title_key!r} not found among {len(index.by_idx)} titles", file=sys.stderr)
        return 2
    titles = [target, *vassals]
    print(
        f"title {target.key} ({target.display_name}, {target.tier}) with {len(vassals)} immediate vassal(s)",
        file=sys.stderr,
    )

    referenced: set[int] = set()
    for record in titles:
        referenced |= record.holder_ids()
    print(f"referenced characters: {len(referenced)}", file=sys.stderr)

    chars = collect_characters(save_path, referenced)
    kept = {cid: char for cid, char in chars.items() if not is_filler(cid, char, referenced)}
    missing = referenced - chars.keys()
    print(
        f"characters found {len(chars)}, kept {len(kept)}, missing {len(missing)}",
        file=sys.stderr,
    )

    session = DryRunSession() if dry_run else open_session(Neo4jConfig.from_env())
    with session:
        load_snapshot(session, fp)
        for record in titles:
            intervals = holder_intervals(record.history, end_date=fp.date, current_holder=record.holder)
            holders = {iv["holder"] for iv in intervals}
            load_title(session, fp, record, intervals, {c: k for c, k in kept.items() if c in holders})
        for record in vassals:
            load_vassal_edge(session, record, target, fp, kind="de_facto")
            de_jure = index.resolve(record.de_jure_liege)
            if de_jure is not None and de_jure.key != target.key:
                load_vassal_edge(session, record, de_jure, fp, kind="de_jure")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ck3parser.pipeline")
    ap.add_argument("save")
    ap.add_argument("--title", required=True, help="title key, e.g. k_papal_state")
    ap.add_argument("--dry-run", action="store_true", help="print Cypher instead of writing to Neo4j")
    ap.add_argument("--no-vassals", action="store_true", help="load the title alone, without its vassals")
    args = ap.parse_args(argv)
    return run(args.save, args.title, args.dry_run, with_vassals=not args.no_vassals)


if __name__ == "__main__":
    raise SystemExit(main())
