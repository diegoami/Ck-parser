"""Traced end-to-end run for one title: extract -> parse -> filter -> load.

    python -m ck3parser.pipeline SAVE --title k_papal_state [--dry-run]

``--dry-run`` prints the Cypher statements instead of touching Neo4j, so the
pipeline can be traced on the fixture without a database.
"""

from __future__ import annotations

import argparse
import sys

from ck3graph.loader import DryRunSession, Neo4jConfig, holder_intervals, load_snapshot, load_title, open_session

from .container import open_gamestate_text, read_header
from .filter import collect_referenced_ids, filter_characters
from .fingerprint import fingerprint
from .parser import Block, PushbackLines, iter_children


def find_title(save_path: str, key: str) -> Block | None:
    with open_gamestate_text(save_path) as f:
        for _, title in iter_children(PushbackLines(f), ("landed_titles", "landed_titles")):
            if isinstance(title, Block) and title.get("key") == key:
                return title
    return None


def characters_by_id(save_path: str, wanted: set[int], section: tuple[str, ...]) -> dict[int, Block]:
    found: dict[int, Block] = {}
    with open_gamestate_text(save_path) as f:
        for cid, char in iter_children(PushbackLines(f), section):
            try:
                cid_int = int(cid)
            except (TypeError, ValueError):
                continue
            if cid_int in wanted and isinstance(char, Block):
                found[cid_int] = char
                if len(found) == len(wanted):
                    break
    return found


def run(save_path: str, title_key: str, dry_run: bool) -> int:
    header = read_header(save_path)
    fp = fingerprint(save_path, with_sha256=False)
    print(f"save: {header.path.name}  date={fp.date}  seed={fp.random_seed}  run={fp.run_id}", file=sys.stderr)
    title = find_title(save_path, title_key)
    if title is None:
        print(f"title {title_key!r} not found", file=sys.stderr)
        return 2
    referenced = collect_referenced_ids([title])
    print(f"title {title_key}: {len(referenced)} referenced character id(s)", file=sys.stderr)
    chars: dict[int, Block] = {}
    for section in (("living",), ("dead_unprunable",), ("characters", "dead_prunable")):
        chars.update(characters_by_id(save_path, referenced - set(chars), section))
    kept = dict(filter_characters(chars.items(), set(referenced)))
    print(f"characters found {len(chars)}, kept after filter {len(kept)}", file=sys.stderr)
    intervals = holder_intervals(title.get("history"), end_date=fp.date, current_holder=title.get("holder"))
    session = DryRunSession() if dry_run else open_session(Neo4jConfig.from_env())
    with session:
        load_snapshot(session, fp)
        load_title(session, fp, title, intervals, kept)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ck3parser.pipeline")
    ap.add_argument("save")
    ap.add_argument("--title", required=True, help="title key, e.g. k_papal_state")
    ap.add_argument("--dry-run", action="store_true", help="print Cypher instead of writing to Neo4j")
    args = ap.parse_args(argv)
    return run(args.save, args.title, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
