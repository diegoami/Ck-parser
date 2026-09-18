# Proposal for `diegoami/ck_portrait_generator`: find the work in a manifest

*This file is the proposal as it should be filed against the companion
repository. It is kept here so the contract has one source, and so it can be
reviewed alongside the code that produces it.*

---

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
{ "schema": "ck3-images/1",
  "chronicles": [ { "slug": "576691683-1-6-1-2",
                    "manifest": "576691683-1-6-1-2/portraits.json",
                    "wanted": 1606, "missing": 1606 } ],
  "wanted": 5630, "missing": 5630 }
```

Chronicle:

```json
{ "schema": "ck3-images/1",
  "chronicle": "576691683-1-6-1-2",
  "title": "e_germany",
  "images": "portraits",
  "saves": [ { "file": "Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3",
               "checksum": "5a86b836cd32", "date": "1364.3.10" } ],
  "wanted": 1606, "missing": 1606,
  "portraits": [
    { "file": "5a86b836cd32_50544311.png", "kind": "portrait",
      "save": "Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3",
      "checksum": "5a86b836cd32", "save_date": "1364.3.10",
      "character": 50544311, "house": 12345,
      "page": "characters/50544311.html", "have": false },
    { "file": "arms_4ec4589d5e8a.png", "kind": "arms",
      "save": "Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3",
      "checksum": "5a86b836cd32", "house": 12345, "coat_of_arms_id": 13996,
      "page": "houses/12345.html", "have": false } ] }
```

* `saves` is the checksum map, repeated so you can check it against your own
  rather than trust ours.
* `have` is one build's answer, not a promise. Treat the file's absence as the
  truth and the flag as a hint.
* `kind` is `portrait` or `arms`. If you only do portraits today, filter on it
  and ignore the rest; the arms entries are a standing request, not a blocker.
* Unknown keys will be added over time. `schema` only changes when something
  already there changes meaning.

No names, here as in the hand-off. You drop them on principle and we do not
write them.

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
   Of 120 dynasties present in two of our playthroughs, 58 were byte-identical.
2. **You can draw them instead of capturing them.** Composing arms offline from
   the game's texture files is what your roadmap wanted before portraits went the
   screenshot route. Everything needed is in `definition`, so ~3 000 in-game
   captures become a rendering job. Portraits still need the game; arms do not.

Why not key on the dynasty, given that the game ships many coats of arms? We
checked: of 60 dynasties carrying the game's own named key and present in two
runs, **57 had different artwork**. CK3 generates arms for whatever the files do
not author, and the save does not say which is which. Keying on the dynasty
would have told you two different pictures were the same file.

It is kept as ordered `[key, value]` pairs rather than an object because
`colored_emblem` repeats once per emblem, and because emblems are drawn in the
order listed.

## Houses and coats of arms

New on our side: houses are now read out of the save and shown. A character
carries `dynasty_house`; the house names a dynasty; the dynasty carries
`coat_of_arms_id`. Each snapshot's hand-off now has a `houses_<date>.csv`
beside its `characters_<date>.csv`, with the house id, dynasty id, arms id,
name, motto key, founding date and the derived `arms_file`.

Whether arms are worth capturing from the game window, or are better rendered
from the `coat_of_arms` section of the save, is your call — the ids and the
names are here either way, and the manifest will keep listing them as wanted
until files with those names appear.

## What we are not asking for

Nothing about DNA, in either form: your D6 retired it and we have not revived
it. Nothing about how you drive the game. And no code dependency in either
direction — this stays plain data files both ways, as it has been.

## Reference

`ck3parser/portraits.py` in `diegoami/Ck-parser` is the one place the naming
rule is written down, and `ck3wiki/manifest.py` produces the files above.
`docs/PLAN.md` §7 carries the reasoning, and `diegoami/ck_wiki`'s README states
the same contract from the delivery side.
