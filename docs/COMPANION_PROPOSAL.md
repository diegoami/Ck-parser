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
| [`diegoami/Ck-parser`](https://github.com/diegoami/Ck-parser) | reads the saves, writes the pages | nothing — it holds code and nothing else |
| [`diegoami/ck_wiki`](https://github.com/diegoami/ck_wiki) | the saves, the images, the manifests, the published pages | **everything**: upload saves to its Releases, read `portraits.json` for your queue, push captures to `images/` |
| `diegoami/ck_portrait_generator` | captures the images | unchanged, except for where the queue comes from and what the files are called |

`ck_wiki` is the one you need write access to, and as of now it is the *only*
one either of us puts files into. The saves used to be on `Ck-parser`'s Releases
and have moved here, so `ck_wiki` now holds every input and every output of a
run: saves, images, manifests, pages. `Ck-parser` is code.

Its CI clones the parser, fetches the saves from **this repository's** Releases,
rebuilds the site, commits the refreshed manifests back, and deploys to
<https://diegoami.github.io/ck_wiki/>. Pushing to `images/` is what triggers
that, so a push both delivers the images and republishes the pages that link
them.

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
             "release": "576691683" } ]
```

and the root listing gives the releases a chronicle draws on, which may be
several.

**Images still go to `images/` as well**, committed, because that is what the
site serves and what triggers a rebuild. The release is the archive; the
directory is the live copy. Putting a file in both is deliberate.

### A release tag is filing, and the build does not depend on it

The releases are now tagged with the run's **seed** — `576691683`,
`633048653`, `1370892195` — so one release does hold one run, which is the
tidy arrangement and the one to keep to.

But the build does not read the tag to decide anything. `fetch_saves.sh` reads
**every** release, deduplicates by checksum, and groups the saves by their own
fingerprint (seed, game version, bookmark date). Two consequences worth having
in writing:

* **A save filed under the wrong tag still builds correctly.** It lands in the
  right chronicle regardless, because the fingerprint decides. Only the
  archival tidiness suffers, and that is fixable later by moving the asset.
* **A save from a brand-new run does not need you to know its seed.** Put it
  anywhere — a release called `incoming` is fine — and the build will discover
  the run and create its chronicle. Our reply on the issue tells you the seed
  it computed, so the release can be named properly afterwards.

So: group your uploads by run because it keeps the archive readable, not
because anything breaks if you do not. The `chronicle` field in a manifest is
the authoritative answer to which run a save belongs to; `release` is where the
file happens to sit.

## The loop, end to end

Neither side watches the other. Each does its part and then says so, and an
issue is how it says so — readable by a person and by an agent, and a durable
record of what was asked and answered. The trigger for a *rebuild* is a git
push, not the issue; the issue is the handshake.

```
  you                                        us
  ───                                        ──
  1. upload save  ──→ ck_wiki Releases
     send the dispatch (starts the build)
     open an issue on Ck-parser  ─────────→  2. build the wiki from it
                                                manifests committed to ck_wiki
  4. read the queue  ←── portraits.json  ←──  3. open an issue here with
     capture the images                          the counts and the links
     push to ck_wiki images/  ───────────────→ 5. rebuild fires on that push
     (an issue is a courtesy, not a trigger)     images appear on the pages
```

### 1. You add a save

Upload the `.ck3` to a release on **`diegoami/ck_wiki`**, in the release for
that run where you know it — you hold your saves per run already, so this
costs you nothing. If it is a run we have never seen, any release will do; see
*A release tag is filing* above for why nothing breaks.

Then **send the dispatch**, which is what actually starts the build:

```sh
gh api repos/diegoami/ck_wiki/dispatches -f event_type=saves-updated
```

and open an issue on `diegoami/Ck-parser` titled something like
**"New save: `<file name>`"**. The dispatch starts a machine; the issue tells a
person. What we need in the issue:

* the file name, and the release you put it on;
* if you know it, which run it belongs to and which existing chronicle that is.

That is all. We can derive everything else from the file.

### 2. We build the wiki from it

We fetch every save from `ck_wiki`'s Releases, group them into runs by
fingerprint, and rebuild. The build writes `portraits.json` at the site root
and one per chronicle, and CI **commits those manifests back into `ck_wiki`**,
so your queue is in git and needs no HTML parsing and no Pages round-trip.

Every manifest carries a `docs` block pointing at the rule for deriving file
names, so a consumer that has the queue always has the rule with it:

```json
"docs": {
  "names": ".../docs/COMPANION_PROPOSAL.md#the-rule",
  "contract": ".../docs/COMPANION_PROPOSAL.md",
  "images": "https://github.com/diegoami/ck_wiki/tree/main/images"
}
```

### 3. We tell you what is wanted

We reply on your issue, or open one on `ck_portrait_generator`, with:

* the **chronicle slug** and the **run seed** we computed — so you can name the
  release properly if this was a new run;
* how many images are wanted and how many are still missing;
* the link to that chronicle's `portraits.json`;
* the reminder that captures go to `ck_wiki`'s `images/`, flat.

### 4. You capture and push

Read the manifest, take the entries with `"have": false`, capture them, and push
them to `ck_wiki`'s `images/` directory under exactly the `file` name the
manifest gives.

**That push is the trigger.** `ck_wiki`'s workflow runs on any push touching
`images/**`, so delivering the images and republishing the pages are the same
action. An issue telling us you have pushed is welcome as a record, but nothing
waits on it.

### 5. There is no step 5

The rebuild that step 4 triggered has already folded the images in. The pages
link every image by a derived name whether or not the file exists, so an image
appearing is the whole of "integrating" it — nothing is regenerated, nothing is
rewired, and `have` flips to `true` in the next manifest.

### How step 1 actually starts the build

Uploading a save to a `ck_wiki` release does not dependably start anything on
its own. Adding an asset to a release that **already exists** — which is how a
save is normally added, into the release for its run — does not reliably fire a
release event, so a trigger relying on that would work for a new run and stay
silent for every save after the first. `ck_wiki`'s workflow has an `on: release`
trigger for the new-run case, but the dependable path is one API call:

```sh
gh api repos/diegoami/ck_wiki/dispatches -f event_type=saves-updated
```

Send that after uploading, and the build starts immediately. It is the same
kind of call as opening the issue, and it is what an agent should send when it
has finished step 1.

If it is ever missed, nothing is lost: `ck_wiki` rebuilds on a Monday schedule,
so a save can sit unbuilt for at most a week. The issue in step 1 remains worth
opening either way — the dispatch starts a machine, the issue tells a person.

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
| the loop, as a checklist | *The loop, end to end*, above |
| where the saves live | `diegoami/ck_wiki`'s Releases, tagged by run seed |

Questions, disagreements and "this would be easier if you sent X instead" are
all welcome — the shape of the hand-off is ours to change, and it has changed
three times already because measuring something proved an assumption wrong.
