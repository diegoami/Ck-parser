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
#:
#: 2: an arms `file` is named after the coat of arms' recipe rather than the
#:    save and id, so the same key means a different thing; `definition` added.
#:    Portrait names are unchanged.
SCHEMA = "ck3-images/2"

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
    seen: dict[str, dict] = {}
    for arms in wiki.wanted_arms:
        # the same picture is one image, whoever bears it: a title and the house
        # holding it usually share their arms, and two houses can as well
        if arms.file in seen:
            seen[arms.file]["borne_by"].append(arms.page)
            continue
        entry = {
            "file": arms.file,
            "kind": "arms",
            "save": arms.save,
            "checksum": arms.checksum,
            "coat_of_arms_id": arms.coat_of_arms_id,
            "page": arms.page,
            "borne_by": [arms.page],
            "have": arms.file in have,
            # the recipe the game draws from, so this need not be captured
            # in-game at all: pattern, colours and emblem textures
            "definition": arms.definition,
        }
        if arms.title:
            entry["title"] = arms.title
        else:
            entry["house"] = arms.house
        seen[arms.file] = entry
        out.append(entry)
    return out


def with_releases(saves: list[dict], releases: dict[str, str] | None) -> list[dict]:
    """Tag each save with the release it was published in, when that is known.

    A release is a **batch**, not a run. One run already spans three of them
    (0.0.2, 0.0.3 and 0.0.4 each hold one Germania save), so this is here to say
    where a save came from and where its harvested images belong, never to
    decide which chronicle it joins — the fingerprint does that (docs/PLAN.md §3).
    """
    if not releases:
        return saves
    return [{**save, "release": releases.get(save["file"], "")} for save in saves]


def chronicle_manifest(
    wiki: Wiki, slug: str, have: set[str], releases: dict[str, str] | None = None
) -> dict:
    images = wanted_images(wiki, have)
    return {
        "schema": SCHEMA,
        "chronicle": slug,
        "run_id": wiki.run_id,
        "title": wiki.title_key,
        "images": IMAGE_DIR,
        "saves": with_releases(wiki.saves, releases),
        "wanted": len(images),
        "missing": sum(1 for image in images if not image["have"]),
        "portraits": images,
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_chronicle_manifest(
    out: Path, wiki: Wiki, slug: str, have: set[str], releases: dict[str, str] | None = None
) -> dict:
    """Write ``<chronicle>/portraits.json`` and return what the root needs of it."""
    payload = chronicle_manifest(wiki, slug, have, releases)
    write_json(out / MANIFEST, payload)
    return {
        "slug": slug,
        "manifest": f"{slug}/{MANIFEST}",
        "wanted": payload["wanted"],
        "missing": payload["missing"],
        # the batches this chronicle's saves arrived in; a run may span several
        "releases": sorted({s["release"] for s in payload["saves"] if s.get("release")}),
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
