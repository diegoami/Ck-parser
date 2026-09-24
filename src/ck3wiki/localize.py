"""Write the localization extract: the game's text for the keys the chronicles use.

    python -m ck3wiki.localize SAVES --out localization.json      # the game found where Steam puts it
    python -m ck3wiki.localize SAVES --game "<CK3>/game" --out localization.json

A build with the game installed reads its text directly (`--game`). ck_wiki's
CI has no game, so this writes what it needs instead: every run's model is
built with the game's localization, and whatever the builds looked up is
kept, `$references$` and trait names included, and nothing else (owner's
decision on #31: only the subset the chronicles use is published). Commit it
to ck_wiki and build there with `--localization localization.json`.

A key a new save introduces is missing until this runs again, and until then
the page shows what it showed before #31: the key, transcribed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ck3parser.install import mismatch
from ck3parser.localization import Localization

from .build import discover, load_run, subject_of
from .maps import find_game_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ck3wiki.localize", description=__doc__.splitlines()[0])
    ap.add_argument("save", help="a .ck3 file, or a directory of saves")
    ap.add_argument("--out", type=Path, required=True, help="the extract: ck_wiki's localization.json")
    ap.add_argument("--game", type=Path, help="the game's `game` directory (default: Steam's)")
    ap.add_argument("--title", help="subject title (default: each run's own, as the build does)")
    ap.add_argument("--cache", default=".ck3cache", help="character digests, as for the build")
    args = ap.parse_args(argv)

    root = args.game or find_game_dir()
    if root is None or not (root / "localization" / "english").is_dir():
        print("cannot find the game's localization; pass --game <CK3>/game", file=sys.stderr)
        return 2
    try:
        runs = discover(args.save)
    except (FileNotFoundError, LookupError) as exc:
        print(exc, file=sys.stderr)
        return 2
    loc = Localization.from_game(root)
    print(f"{loc.source}: {len(loc.table):,} keys, game version {loc.version}", file=sys.stderr)
    if not loc.version:
        print(f"nothing written: {mismatch(None, None)}", file=sys.stderr)
        return 2
    for run in runs:
        # only the version that wrote the save (#58): another version's text
        # can look right and be wrong
        problem = mismatch(loc.version, run.version)
        if problem:
            print(f"  {run.slug}: skipped, {problem}", file=sys.stderr)
            continue
        subject = subject_of(run, args.title, sys.stderr)
        if subject is None:
            continue
        before = len(loc.used)
        load_run(run, subject, log=open(os.devnull, "w"), cache_dir=Path(args.cache), loc=loc)
        print(f"  {run.slug}: {len(loc.used) - before} new key(s)", file=sys.stderr)
    try:
        written = loc.write_extract(args.out)
    except (OSError, ValueError) as exc:
        print(f"nothing written: {exc}", file=sys.stderr)
        return 2
    sections = ", ".join(Localization.extract_versions(args.out))
    print(f"{written} key(s) written to {args.out} for {loc.version}; its sections: {sections}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
