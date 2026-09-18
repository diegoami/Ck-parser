"""The image manifest the companion project scans.

The wiki links every portrait and coat of arms by a name both projects derive
from the save's file name (:mod:`ck3parser.portraits`), so a page is written the
same way whether the image exists yet or not. This file is the other half of
that: a machine-readable list of every image the wiki wants, saying which are
still missing, so `diegoami/ck_portrait_generator` can find its work without
parsing HTML.

The companion keeps its own map from save file to checksum; this repeats the
map in ``saves`` so the two can be checked against each other, and gives every
wanted image the `save` it must be captured from. Uploading is a matter of
dropping files into the chronicle's ``portraits/`` directory under the names
given here — nothing needs regenerating, the links already point at them.

Names are never written, here as in the hand-off: the companion drops them on
principle (docs/PLAN.md §7).
"""

from __future__ import annotations

import json
from pathlib import Path

from ck3parser.portraits import IMAGE_DIR

from .model import Wiki

#: Bumped when the shape changes in a way a consumer has to notice.
SCHEMA = "ck3-images/1"

#: The manifest's name, in each chronicle and at the root.
MANIFEST = "portraits.json"


def wanted_images(wiki: Wiki, have: set[str]) -> list[dict]:
    """Every image the wiki links, portraits first, each flagged with `have`."""
    out: list[dict] = []
    for portrait in wiki.wanted_portraits:
        out.append(
            {
                "file": portrait.file,
                "kind": "portrait",
                "save": portrait.save,
                "checksum": portrait.checksum,
                "save_date": portrait.save_date,
                "character": portrait.character,
                "house": wiki.characters[portrait.character].house,
                "page": f"characters/{portrait.character}.html",
                "have": portrait.file in have,
            }
        )
    for arms in wiki.wanted_arms:
        out.append(
            {
                "file": arms.file,
                "kind": "arms",
                "save": arms.save,
                "checksum": arms.checksum,
                "house": arms.house,
                "coat_of_arms_id": arms.coat_of_arms_id,
                "page": f"houses/{arms.house}.html",
                "have": arms.file in have,
            }
        )
    return out


def chronicle_manifest(wiki: Wiki, slug: str, have: set[str]) -> dict:
    images = wanted_images(wiki, have)
    return {
        "schema": SCHEMA,
        "chronicle": slug,
        "run_id": wiki.run_id,
        "title": wiki.title_key,
        "images": IMAGE_DIR,
        "saves": wiki.saves,
        "wanted": len(images),
        "missing": sum(1 for image in images if not image["have"]),
        "portraits": images,
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_chronicle_manifest(out: Path, wiki: Wiki, slug: str, have: set[str]) -> dict:
    """Write ``<chronicle>/portraits.json`` and return what the root needs of it."""
    payload = chronicle_manifest(wiki, slug, have)
    write_json(out / MANIFEST, payload)
    return {
        "slug": slug,
        "manifest": f"{slug}/{MANIFEST}",
        "wanted": payload["wanted"],
        "missing": payload["missing"],
    }


def write_root_manifest(out: Path, chronicles: list[dict]) -> None:
    """One entry point above the chronicles, so a scan starts from a single URL."""
    write_json(
        out / MANIFEST,
        {
            "schema": SCHEMA,
            "chronicles": chronicles,
            "wanted": sum(c["wanted"] for c in chronicles),
            "missing": sum(c["missing"] for c in chronicles),
        },
    )
