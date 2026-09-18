"""Build the wiki, one chronicle per playthrough.

    python -m ck3wiki.build saves --out site

Saves are grouped into runs by :mod:`ck3parser.runs`, and each run becomes its
own chronicle under ``site/<seed>-<version>/``, because the seed and the game
version are what tell one playthrough from another. A landing page at the root
lists them, so dropping more saves into the source adds more chronicles without
any configuration.

Each chronicle needs a subject title. ``--title`` sets it for all of them;
otherwise it is the played character's primary title in that run's newest save,
which is what the playthrough was about.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ck3parser.fingerprint import fingerprint
from ck3parser.pipeline import gather
from ck3parser.player import primary_title_key
from ck3parser.runs import Run, Snapshot, scan

from .model import build_wiki
from .render import write_landing, write_site


def discover(save_path: str, run_id: str | None = None) -> list[Run]:
    """The runs to build: every run in a directory, or the one run of a file."""
    path = Path(save_path)
    if path.is_file():
        fp = fingerprint(path, with_sha256=False)
        return [
            Run(
                run_id=fp.run_id,
                random_seed=fp.random_seed,
                bookmark_date=fp.bookmark_date,
                version=fp.version,
                slug=fp.run_slug,
                snapshots=[Snapshot(fp=fp, mtime=path.stat().st_mtime)],
            )
        ]
    if not path.is_dir():
        raise FileNotFoundError(f"no such save or directory: {path}")
    runs = scan(path, with_sha256=False)
    if not runs:
        raise FileNotFoundError(f"no .ck3 saves under {path}")
    if run_id is not None:
        runs = [r for r in runs if r.run_id == run_id or r.slug == run_id]
        if not runs:
            raise LookupError(f"no run {run_id!r} under {path}")
    return runs


def subject_of(run: Run, override: str | None, log) -> str | None:
    """Which title this chronicle is about."""
    if override:
        return override
    newest = run.snapshots[-1]
    key = primary_title_key(newest.fp.file, fp=newest.fp)
    if key is None:
        print(f"warning: cannot tell what run {run.slug} is about; pass --title", file=log)
    return key


def build_one(run: Run, subject: str, with_vassals: bool, out: Path, portraits: Path | None, log) -> dict | None:
    views = []
    for snapshot in run.snapshots:
        try:
            views.append(gather(snapshot.fp.file, subject, with_vassals, log=log))
        except KeyError:
            print(f"warning: {subject!r} is not in {Path(snapshot.fp.file).name}, skipped", file=log)
    if not views:
        print(f"warning: nothing to build for run {run.slug}", file=log)
        return None
    wiki = build_wiki(views, subject)
    pages = write_site(wiki, out / run.slug, portraits, top=True)
    root = wiki.root
    print(f"  {run.slug}: {pages} pages", file=log)
    return {
        "slug": run.slug,
        "name": root.name if root else subject,
        "seed": run.random_seed,
        "version": run.version,
        "snapshots": len(wiki.snapshots),
        "titles": len(wiki.titles),
        "characters": len(wiki.characters),
    }


def run_build(
    save_path: str,
    out_dir: str,
    title: str | None = None,
    with_vassals: bool = True,
    run_id: str | None = None,
    portraits: str | None = None,
    log=None,
) -> int:
    log = sys.stderr if log is None else log
    try:
        runs = discover(save_path, run_id)
    except (FileNotFoundError, LookupError) as exc:
        print(exc, file=sys.stderr)
        return 2

    out = Path(out_dir)
    shots = Path(portraits) if portraits else None
    print(f"{len(runs)} run(s) to build", file=log)
    entries = []
    for run in runs:
        subject = subject_of(run, title, log)
        if subject is None:
            continue
        entry = build_one(run, subject, with_vassals, out, shots, log)
        if entry is not None:
            entries.append(entry)

    if not entries:
        print("no chronicles could be built", file=sys.stderr)
        return 2
    write_landing(out, entries)
    total = sum(e["titles"] + e["characters"] + 1 for e in entries)
    print(f"wrote {len(entries)} chronicle(s), {total} pages, to {out}/", file=log)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ck3wiki.build", description="Build the static CK3 wiki.")
    ap.add_argument("save", help="a .ck3 file, or a directory of saves holding one or more runs")
    ap.add_argument("--out", default="site", help="output directory (default: ./site)")
    ap.add_argument("--title", help="subject title for every chronicle (default: the played character's)")
    ap.add_argument("--no-vassals", action="store_true", help="the title alone, without its vassals")
    ap.add_argument("--run", dest="run_id", help="build only this run (its id or slug)")
    ap.add_argument("--portraits", help="directory of harvested portrait images to include")
    args = ap.parse_args(argv)
    return run_build(
        args.save,
        args.out,
        title=args.title,
        with_vassals=not args.no_vassals,
        run_id=args.run_id,
        portraits=args.portraits,
    )


if __name__ == "__main__":
    raise SystemExit(main())
