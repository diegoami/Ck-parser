"""The harvest queue, from the companion's side of the table.

    python -m ck3wiki.queue ids MANIFEST --out ids/ [--role ever-holder]
    python -m ck3wiki.queue collect MANIFEST --from harvested/ --to images/

`portraits.json` is the one queue (#27): every portrait the wiki links, which
save it must be captured in, the exact file name to deliver it under, and
whether it is here yet. The companion (`diegoami/ck_portrait_generator`) does
not read it yet: it takes an id list per save and writes `<id>_<save date>.png`.
This bridges both ends until it does, so the queue works today:

``ids``
    one ``<save>.ids`` per save, the ids still missing from it, rulers first,
    in the one-id-per-line form the harvester's ``--ids-file`` takes. One save
    per file because a capture needs its save loaded, and loading is the slow
    step: one load, then every id alive in it.
``collect``
    copies the harvester's ``<id>_<save date>.png`` files to the names the
    wiki links, found in the queue by character and save date, ready to commit
    to ck_wiki's ``images/``. Copies, never moves; never overwrites.

MANIFEST may be a chronicle's ``portraits.json`` or the root one, which names
every chronicle's.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .model import ROLES


def load_entries(manifest: Path) -> list[dict]:
    """Every portrait entry, from a chronicle's manifest or all of a root's."""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if "chronicles" in data:
        entries: list[dict] = []
        for chronicle in data["chronicles"]:
            entries += load_entries(manifest.parent / chronicle["manifest"])
        return entries
    return [e for e in data.get("portraits", []) if e.get("kind") == "portrait"]


def rank(entry: dict) -> tuple[int, int]:
    """Rulers first, then their kin, then the titled ring; by id within each."""
    role = entry.get("role")
    return (ROLES.index(role) if role in ROLES else len(ROLES), int(entry["character"]))


def write_ids(
    entries: list[dict], out: Path, roles: set[str] | None = None, everything: bool = False
) -> dict[str, int]:
    """One ``<save stem>.ids`` per save; returns ids written per file."""
    by_save: dict[str, list[dict]] = {}
    for entry in entries:
        if (everything or not entry.get("have")) and (not roles or entry.get("role") in roles):
            by_save.setdefault(entry["save"], []).append(entry)
    out.mkdir(parents=True, exist_ok=True)
    written = {}
    for save, wanted in sorted(by_save.items()):
        ids = list(dict.fromkeys(str(e["character"]) for e in sorted(wanted, key=rank)))
        name = f"{Path(save).stem}.ids"
        (out / name).write_text("\n".join(ids) + "\n", encoding="utf-8")
        written[name] = len(ids)
    return written


def harvester_name(character: int | str, save_date: str | None) -> str:
    """What the harvester calls a capture today (`harvest_ingame.py`)."""
    return f"{character}_{(save_date or 'nodate').replace('.', '-')}.png"


def collect(entries: list[dict], source: Path, target: Path) -> dict[str, int]:
    """Copy harvested captures to the names the wiki links. Never overwrites."""
    counts = {"copied": 0, "already there": 0, "not harvested": 0}
    target.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        found = source / harvester_name(entry["character"], entry.get("save_date"))
        dest = target / entry["file"]
        if dest.exists():
            counts["already there"] += 1
        elif found.is_file():
            shutil.copyfile(found, dest)
            counts["copied"] += 1
        else:
            counts["not harvested"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ck3wiki.queue", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    ids = sub.add_parser("ids", help="write one --ids-file per save, rulers first")
    ids.add_argument("manifest", type=Path, help="a chronicle's portraits.json, or the root one")
    ids.add_argument("--out", type=Path, default=Path("ids"))
    ids.add_argument("--role", action="append", choices=ROLES,
                     help="only these roles; repeatable (default: all)")
    ids.add_argument("--all", action="store_true", help="include portraits already harvested")
    col = sub.add_parser("collect", help="copy harvested captures to the names the wiki links")
    col.add_argument("manifest", type=Path)
    col.add_argument("--from", dest="source", type=Path, required=True,
                     help="the harvester's output directory")
    col.add_argument("--to", dest="target", type=Path, required=True,
                     help="where the wiki looks: ck_wiki's images/")
    args = ap.parse_args(argv)

    try:
        entries = load_entries(args.manifest)
    except (OSError, ValueError, KeyError) as exc:
        print(f"cannot read {args.manifest}: {exc}", file=sys.stderr)
        return 2
    if args.command == "ids":
        written = write_ids(entries, args.out, set(args.role or ()), args.all)
        for name, n in written.items():
            print(f"  {name}: {n} id(s)", file=sys.stderr)
        print(f"{sum(written.values())} id(s) in {len(written)} file(s) under {args.out}/", file=sys.stderr)
    else:
        counts = collect(entries, args.source, args.target)
        print(", ".join(f"{n} {what}" for what, n in counts.items()), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
