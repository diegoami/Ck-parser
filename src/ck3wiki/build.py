"""Build the static wiki.

    python -m ck3wiki.build SAVES --title e_germany --out site

Given a directory it reads every snapshot of that run, oldest first, and merges
them, so the site includes history the newest save has already pruned. Pass
``--portraits`` to fold in images harvested by the companion project; without
it the pages simply have no portrait.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ck3parser.pipeline import gather, resolve_saves

from .model import build_wiki
from .render import write_site


def run(
    save_path: str,
    title_key: str,
    out_dir: str,
    with_vassals: bool = True,
    run_id: str | None = None,
    portraits: str | None = None,
) -> int:
    try:
        saves = resolve_saves(save_path, run_id)
    except (FileNotFoundError, LookupError) as exc:
        print(exc, file=sys.stderr)
        return 2

    views = []
    for path in saves:
        try:
            views.append(gather(path, title_key, with_vassals))
        except KeyError:
            print(f"warning: {title_key!r} is not in {Path(path).name}, skipped", file=sys.stderr)
    if not views:
        print(f"title {title_key!r} not found in any of the {len(saves)} save(s)", file=sys.stderr)
        return 2

    wiki = build_wiki(views, title_key)
    out = Path(out_dir)
    pages = write_site(wiki, out, Path(portraits) if portraits else None)
    print(
        f"wrote {pages} pages to {out}/ — {len(wiki.titles)} titles,"
        f" {len(wiki.characters)} characters, {len(wiki.snapshots)} snapshot(s)",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ck3wiki.build", description="Build the static CK3 wiki.")
    ap.add_argument("save", help="a .ck3 file, or a directory of saves to treat as one run")
    ap.add_argument("--title", required=True, help="the lineage's title key, e.g. e_germany")
    ap.add_argument("--out", default="site", help="output directory (default: ./site)")
    ap.add_argument("--no-vassals", action="store_true", help="the title alone, without its vassals")
    ap.add_argument("--run", dest="run_id", help="which run to use when a directory holds several")
    ap.add_argument("--portraits", help="directory of harvested portrait images to include")
    args = ap.parse_args(argv)
    return run(
        args.save,
        args.title,
        args.out,
        with_vassals=not args.no_vassals,
        run_id=args.run_id,
        portraits=args.portraits,
    )


if __name__ == "__main__":
    raise SystemExit(main())
