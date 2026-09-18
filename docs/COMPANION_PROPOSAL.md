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

def arms_name(save_file: str, coat_of_arms_id: int) -> str:
    return f"{save_checksum(save_file)}_arms_{coat_of_arms_id}.png"
```

The save file's **base name** is hashed, not its contents: you can compute it
without opening 70 MB, and it does not matter where either side keeps the save.
Twelve hex characters is far more than the number of saves anyone will publish.

Two consequences worth stating plainly:

* Keying on the **save**, not the date, is what gives one portrait per save. The
  same person in three snapshots is three images — your roadmap item 2, made
  explicit in the file name.
* A `coat_of_arms_id` is an index **inside one save**, so arms are scoped by the
  save too. The same number means different arms in a different playthrough.

You already keep a map from save file to what you harvested from it. The
proposal is that the checksum becomes a column of that map — one line of code,
and no other state to keep in sync.

## Where the work list lives

The wiki publishes `portraits.json` at the root of the site and again in each
chronicle. It names every image the wiki links, including the ones nobody has
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
    { "file": "5a86b836cd32_arms_13996.png", "kind": "arms",
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
4. **Upload.** Attach the images to a Release of `diegoami/Ck-parser`, loose as
   `.png` or bundled in a `.zip` — `scripts/fetch_portraits.sh` collects both,
   and the Pages build folds whatever is there into the site. The file names are
   the only thing that has to be right; any directory structure inside a bundle
   is flattened away. (A `portraits/` directory beside the build works the same
   way locally: `ck3wiki.build saves --out site --portraits portraits`.)

That last step is all there is to publishing. The wiki already links every one
of those names, whether or not the file exists: a missing image renders as a
dashed placeholder marked *awaiting harvest*, and the `src` is already correct.
Nothing is rebuilt and no link changes when the file lands.

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
`docs/PLAN.md` §7 carries the reasoning.
