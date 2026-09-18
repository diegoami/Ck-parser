# Proposal for `diegoami/ck_portrait_generator`: find the work in a manifest

*This file is the proposal as it should be filed against the companion
repository. It is kept here so the contract has one source, and so it can be
reviewed alongside the code that produces it.*

---

## The three repositories

Nothing here needs you to import our code, and nothing needs us to import
yours. Three repositories, three jobs:

| Repository | Job | What you do with it |
|---|---|---|
| [`diegoami/Ck-parser`](https://github.com/diegoami/Ck-parser) | reads the saves, writes the pages | nothing — but the saves are attached to its **Releases**, and those are the files you harvest from |
| [`diegoami/ck_wiki`](https://github.com/diegoami/ck_wiki) | publishes the wiki, holds the images | **read** `portraits.json` for your queue; **push** your captures to `images/` |
| `diegoami/ck_portrait_generator` | captures the images | unchanged, except for where the queue comes from and what the files are called |

`ck_wiki` is the one you need write access to. Its CI clones the parser, fetches
the saves from the parser's Releases, rebuilds the site, commits the refreshed
manifests back, and deploys to <https://diegoami.github.io/ck_wiki/>. Pushing to
`images/` is what triggers that, so a push both delivers the images and
republishes the pages that link them.

## What changes for you

Nothing about how you harvest. `play <id>`, observer mode, screenshot the
character window — all unchanged. What changes is **how you learn what to
capture and what to call the result**, and it removes the last piece of manual
coordination between the two tools.

Today the hand-off tells you *who* to capture. It does not tell you what the
wiki will call the image, so the wiki has to go looking for whatever files
appeared and guess which belongs to whom. That guess is the thing to delete.

## The rule

Both sides derive the same name from the same two facts, and never assign one:

```python
import hashlib
from pathlib import Path

def save_checksum(save_file: str) -> str:
    return hashlib.sha256(Path(save_file).name.encode("utf-8")).hexdigest()[:12]

def portrait_name(save_file: str, character_id: int) -> str:
    return f"{save_checksum(save_file)}_{character_id}.png"

def arms_name(recipe_digest: str) -> str:            # see "Coats of arms" below
    return f"arms_{recipe_digest}.png"
```

The save file's **base name** is hashed, not its contents: you can compute it
without opening 70 MB, and it does not matter where either side keeps the save.
Twelve hex characters is far more than the number of saves anyone will publish.

Two consequences worth stating plainly:

* Keying on the **save**, not the date, is what gives one portrait per save. The
  same person in three snapshots is three images — your roadmap item 2, made
  explicit in the file name.
* A `coat_of_arms_id` is an index **inside one save** and never names an image.
  Arms are named after the recipe that draws them, so the same picture is one
  file in every run — see below.

You already keep a map from save file to what you harvested from it. The
proposal is that the checksum becomes a column of that map — one line of code,
and no other state to keep in sync.

## Where the work list lives

`portraits.json` is committed to `diegoami/ck_wiki`, at the root and again in
each chronicle's directory, and published at the same paths on the site. Read
it from whichever is easier — git means no HTML, no Pages, and no waiting for a
deploy. It names every image the wiki links, including the ones nobody has
captured yet.

Root:

```json
{ "schema": "ck3-images/2",
  "chronicles": [ { "slug": "576691683-1-6-1-2",
                    "manifest": "576691683-1-6-1-2/portraits.json",
                    "wanted": 2250, "missing": 2250 } ],
  "wanted": 5845, "missing": 5845 }
```

Chronicle:

```json
{ "schema": "ck3-images/2",
  "chronicle": "576691683-1-6-1-2",
  "title": "e_germany",
  "images": "portraits",
  "saves": [ { "file": "Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3",
               "checksum": "5a86b836cd32", "date": "1364.3.10" } ],
  "wanted": 2250, "missing": 2250,
  "portraits": [
    { "file": "5a86b836cd32_50544311.png", "kind": "portrait",
      "save": "Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3",
      "checksum": "5a86b836cd32", "save_date": "1364.3.10",
      "character": 50544311, "house": 12345,
      "page": "characters/50544311.html", "have": false },
    { "file": "arms_4ec4589d5e8a.png", "kind": "arms",
      "save": "Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3",
      "checksum": "5a86b836cd32", "house": 12345, "coat_of_arms_id": 13996,
      "page": "houses/12345.html", "have": false,
      "definition": [["pattern", "pattern_solid.dds"], ["color1", "red"],
                     ["colored_emblem", [["texture", "ce_eagle.dds"]]]] } ] }
```

* **Every `portrait` entry is someone who was alive in that save.** `play <id>`
  refuses the dead, so asking for a portrait of a buried character is work
  nobody can do; the wiki now applies the same liveness rule your hand-off has
  always had. We got this wrong at first and the queue was 96% impossible — 1 330
  portraits of which 53 were capturable. If you hit a character `play` refuses,
  that is our bug, so please say so.
* `saves` is the checksum map, repeated so you can check it against your own
  rather than trust ours.
* `have` is one build's answer, not a promise. Treat the file's absence as the
  truth and the flag as a hint.
* `kind` is `portrait` or `arms`. If you only do portraits today, filter on it
  and ignore the rest; the arms entries are a standing request, not a blocker.
* Unknown keys will be added over time. `schema` only changes when something
  already there changes meaning. **It is at `/2`**: arms names changed from
  `<save checksum>_arms_<id>.png` to `arms_<recipe digest>.png`. Portrait names
  did not change, so if you only do portraits, `/1` and `/2` are the same to you.

* **It is no longer only rulers.** The wiki used to hold whoever had held one of
  the lineage's titles. It now also holds their parents, spouses and children,
  because a dynastic chronicle is about the family, not the office. For one
  chronicle that took the character pages from 952 to 5 550, and the portrait
  queue from 53 to 1 389 — the newcomers are mostly *alive*, which is why the
  capturable count went up rather than down.

No names, here as in the hand-off. You drop them on principle and we do not
write them.

## The deliverable: a release in `ck_wiki`

A finished batch of work is a **GitHub release on `diegoami/ck_wiki`** holding
both halves of it:

* the **save files** the batch covers, and
* the **images harvested from them** — portraits captured in-game, arms rendered
  or captured.

That makes a release self-contained: someone with only the release can rebuild
the chronicle and see it fully illustrated, without hunting for which save a
portrait came from. Each save in the manifest carries the release it was
published in:

```json
"saves": [ { "file": "Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3",
             "checksum": "5a86b836cd32", "date": "1364.3.10",
             "release": "0.0.4" } ]
```

and the root listing gives the releases a chronicle draws on, which may be
several.

**Images still go to `images/` as well**, committed, because that is what the
site serves and what triggers a rebuild. The release is the archive; the
directory is the live copy. Putting a file in both is deliberate.

### One thing a release is *not*

It is not a run. Do not group by it, and do not assume the saves in one release
belong together. Ours do not: the Germania chronicle's three saves are on
releases **0.0.2, 0.0.3 and 0.0.4**, one save each, and grouping by release
would split one playthrough into three single-snapshot chronicles. Which saves
belong to which run is decided by their fingerprint — seed, game version,
bookmark date — and the manifest has already done it for you. The `chronicle`
a manifest belongs to is the answer; `release` is just where the file came from.

## What we ask you to build

1. **Scan.** Fetch the root `portraits.json`, follow each chronicle's manifest,
   and collect the entries where the file is not already in hand. That is the
   work queue, and it needs no configuration beyond one URL.
2. **Match.** Group the queue by `save`. A save you have is a harvesting
   session; a save you do not have is a skip, not an error.
3. **Name.** Write each capture to the `file` the manifest gives, verbatim.
   Deriving it yourself with the function above must give the same answer —
   worth asserting once, in a test.
4. **Upload.** Commit the images to `images/` in
   [`diegoami/ck_wiki`](https://github.com/diegoami/ck_wiki). That directory is
   flat and shared across chronicles — the names already carry the save, so
   nothing collides — and the push triggers the build. The file names are the
   only thing that has to be right. (Locally the same thing is
   `ck3wiki.build saves --out site --portraits images`.)

5. **Archive.** Attach the batch's saves and images to a release on `ck_wiki`,
   so the release stands on its own. The commit in step 4 is what publishes;
   this is what makes the work reproducible later.

That last step is all there is to publishing. The wiki already links every one
of those names, whether or not the file exists: a missing image renders as a
dashed placeholder marked *awaiting harvest*, and the `src` is already correct.
Nothing is rebuilt and no link changes when the file lands.

## Coats of arms: you should not have to capture these

An arms image is named `arms_<sha256(recipe)[:12]>.png`, where the recipe is what
the game draws from — a pattern, some colours, one or more emblems. The manifest
carries it under `definition`:

```json
"definition": [["pattern", "pattern_solid.dds"], ["color1", "red"],
               ["colored_emblem", [["color1", "white"], ["texture", "ce_eagle.dds"]]]]
```

Two consequences for you:

1. **Identical artwork is one file.** The same arms in three chronicles ask once.
   Measured across our three: 2 861 requests, 2 589 distinct images. Only 10%,
   because the houses a chronicle links are mostly generated ones whose arms are
   unique to that playthrough — worth having, but not the reason to do this.
2. **You can draw them instead of capturing them.** This is the reason to do
   this. Composing arms offline from the game's texture files is what your
   roadmap wanted before portraits went the screenshot route. Everything needed
   is in `definition`, so **2 589 in-game captures become a rendering job**.
   Portraits still need the game; arms do not.

Why not key on the dynasty, given that the game ships many coats of arms? We
checked: of 60 dynasties carrying the game's own named key and present in two
runs, **57 had different artwork**. CK3 generates arms for whatever the files do
not author, and the save does not say which is which. Keying on the dynasty
would have told you two different pictures were the same file.

It is kept as ordered `[key, value]` pairs rather than an object because
`colored_emblem` repeats once per emblem, and because emblems are drawn in the
order listed.

## Houses, and the hand-off CSVs

Houses are read out of the save and shown now. A character carries
`dynasty_house`; the house names a dynasty; the arms id sits on the house when
it has one of its own and on the dynasty otherwise. Each snapshot's hand-off has
a `houses_<date>.csv` beside its `characters_<date>.csv`, carrying the house id,
dynasty id, arms id, name, dynasty name, motto key, founding date and the
derived `arms_file`.

**The manifest is the work queue; the CSVs are context.** If the two ever
disagree about a file name, the manifest is right and we have a bug. The CSVs
stay because they carry per-snapshot detail the manifest does not, and because
`--ids-only` still writes the bare id list your `--ids-file` takes.

## What we are not asking for

Nothing about DNA, in either form: your D6 retired it and we have not revived
it. Nothing about how you drive the game. And no code dependency in either
direction — this stays plain data files both ways, as it has been.

## If you implement only one thing

Read `ck_wiki/portraits.json`, filter to `kind == "portrait"` and `have == false`,
group by `save`, capture, and push the files to `ck_wiki/images/` under the
names given. Everything else in this document is either the reasoning behind
that or an offer to do less work.

## Reference

| What | Where |
|---|---|
| the naming rule, in one file | `ck3parser/portraits.py` in `diegoami/Ck-parser` |
| the arms recipe and its digest | `ck3parser/arms.py` |
| what produces the manifests | `ck3wiki/manifest.py` |
| the reasoning | `docs/PLAN.md` §7 (images), §10 (family), §11 (coats of arms) |
| the same contract from the delivery side | `diegoami/ck_wiki`'s README |

Questions, disagreements and "this would be easier if you sent X instead" are
all welcome — the shape of the hand-off is ours to change, and it has changed
three times already because measuring something proved an assumption wrong.
