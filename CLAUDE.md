# CK3 History Extractor — notes for coding agents

Read `docs/HANDOVER.md` first (state of the project, next tasks). `docs/PLAN.md`
(design, verified facts about the save format) is ~17k tokens: open only the
sections your task touches, found through its `##` headings, not the whole file.

## Commands

```
uv sync --group dev              # install (the SessionStart hook does this on the web)
uv run pytest -q                 # ~200 tests, < 1 s, fixture only; the Neo4j ones skip
scripts/fetch_saves.sh           # every real save (~73 MB each) into ./saves, git-ignored
uv run python -m ck3parser.runs verify saves --json saves/runs.json
uv run python -m ck3parser.pipeline saves/<file>.ck3 --title e_germany --dry-run
uv run python -m ck3parser.pipeline saves --title e_germany --dry-run   # whole run, oldest first
uv run python -m ck3parser.pipeline saves --title e_germany --dry-run --echo  # ... printing every statement: thousands
uv run python -m ck3parser.pipeline saves --title e_germany --people    # ... plus every character and their family edges
uv run python -m ck3parser.sections saves/<file>.ck3 --verify           # top-level layout
uv run python -m ck3parser.handoff saves --title e_germany --out handoff  # portrait harvester list
uv run python -m ck3wiki.build saves --out site                          # the wikis themselves
uv run python -m ck3wiki.build saves --out site --portraits harvested    # ... with images folded in
uv run python -m ck3wiki.build saves --out site --no-family              # ... fast: skips the full character pass
uv run python -m ck3wiki.build saves --out site --no-cache               # ... without the per-save character digests
uv run python -m ck3wiki.build saves --out site --no-kin                 # ... title-holders only, no direct line
uv run python -m ck3wiki.build saves --out site --no-titled-kin          # ... stop at the direct line
uv run python -m ck3wiki.prose saves --out prose                         # rulers' prose, template backend
uv run python -m ck3wiki.prose saves --out prose --backend openai --model M  # ... from a local server
uv run python -m ck3wiki.build saves --out site --prose prose            # ... folded into the pages
```

## Rules

- Never open a save or its `gamestate` with Read, `cat`, `less` or an unbounded
  `grep`: a gamestate is ~280 MB and 14 M lines, some of them long (packed
  `dna`), and one careless look fills the context. Ask the question in Python through
  `iter_children` / `read_top_level` and print a count or a few fields; use
  `ck3parser.sections` for the layout. A raw look is `grep -m 5 … | cut -c 1-200`
  at most.
- The real-save commands report on stderr and take minutes: run them with
  output redirected to a log file and read its tail. Never let
  `--dry-run --echo` print into the conversation, least of all with `--people`.
- Never commit `.ck3` files or an extracted `gamestate`; they are release assets.
- The parser is brace-driven. Never rely on indentation: title entries sit at column 0.
- Everything that touches the real `gamestate` streams it (`iter_children`,
  `read_top_level`). Do not read a whole section into memory.
- Neo4j writes are idempotent `MERGE`s and order independent; nothing deletes.
  The default suite uses `DryRunSession`. `tests/test_integration_neo4j.py` runs
  against a real database, opt in via `CK3_TEST_NEO4J_URI`, and WIPES it.
- Game dates go into the graph as real `date` values, never strings: save dates
  sort wrongly as text (`"99.1.1"` after `"948.3.25"`).
- `Block` subclasses `list`. Test for `Block` before `list` in any isinstance chain.
- Title liege fields are numeric indices into `landed_titles`, not keys. Resolve
  them through `ck3parser.titles.TitleIndex`.
- The graph writes `PARENT_OF` straight off each record's own child list and
  never inverts anything: Cypher walks an edge both ways, so the 80 MB
  inversion `ck3parser.family` needs is pure Python overhead (PLAN.md §12).
  `REAL_FATHER_OF` stays a separate edge, as `real_father` stays out of
  `parents`.
- The population pass filters nobody. `ck3parser.filter` is for pages; a
  filler character is still somebody's parent, and dropping them cuts the
  paths the graph exists to walk.
- Never write character properties with `SET c += $props`. Neo4j *removes* a
  property a map sets to null, so an older snapshot loaded after a newer one
  would erase a death date. Merge each property by hand; what can only ever
  be learnt keeps the first non-null answer.
- The stretch logic lives in `ck3parser.vassalage`, not in the wiki: the wiki
  imports `ck3graph.loader`, so the graph cannot import the wiki back.
- A save has **no vassalage history**: it says who a title's liege *is*, never
  who it has been. A liege change is only ever known to have happened between
  two snapshots, and must be shown as bounds ("between X and Y"), never as a
  date. Never narrow it from the holder history: a title can change liege
  without changing hands (PLAN.md §9).
- A title absent from a save was destroyed or pruned, and the save does not say
  which. Absence is never independence, and never bridges two stretches.
- No LLM SDK dependency. Prose (`ck3wiki.prose`) talks to a model over plain
  HTTP through a pluggable backend; the model is not chosen yet (PLAN.md §15).
- Prose is written from a page's **fact sheet** and nothing else, and carries a
  digest of it. The build shows it only while the digest still matches: stale
  prose is left out, never shown beside a table that contradicts it. A number
  the fact sheet does not hold gets the paragraph rejected, not saved. When a
  paragraph needs a number, put it in the fact sheet; never loosen the check.
- Character names in saves are localization keys with diacritics marked by an
  underscore. Drop the marker, never guess the letter (PLAN.md §8).
- One wiki per playthrough. What separates them is the run, identified by seed
  and game version, never the title the wiki is about.
- Runs are grouped by the save's own **fingerprint**, never by the release it
  came from. On ck_wiki the tags are run seeds today, so a release does hold one
  run — but that is the owner's filing, not a guarantee, and until it moved the
  Germania run sat on three batch-numbered releases at once. The tag is carried
  for delivery only: it says where a save came from and where its images belong
  (PLAN.md §7).
- The saves live on **ck_wiki's** Releases, not this repository's.
  `scripts/fetch_saves.sh` defaults there and takes `SAVES_REPO` to override.
- `diegoami/ck_portrait_generator` is the companion tool. It consumes plain data
  files from here and imports no code; see PLAN.md §7 for what it needs. Read its
  `docs/DECISIONS.md` before assuming anything about portraits.
- `diegoami/ck_wiki` is where the wiki is published and where the companion
  commits its images. This repository builds the pages; it does not publish them
  and has no Pages workflow. Generated pages are never committed anywhere.
- `scripts/fetch_saves.sh` must never infer the repository from
  `GITHUB_REPOSITORY`: it names whichever repository the workflow runs in,
  which is the one place the saves are not guaranteed to be.
- Never write character names into the hand-off: the companion drops them on
  principle. Only emit fields this project can resolve correctly. A house's name
  is not a person's name; the house list keeps it.
- Image names are **derived**, never assigned: `ck3parser.portraits` is the one
  place that spells the rule, and the companion derives the same names. Changing
  it renames every image both projects hold, so it is a contract change, not a
  refactor (PLAN.md §7).
- The wiki links an image whether or not it exists yet. Never make a page's
  `src` depend on the file being there: dropping the file in must be all it
  takes, with nothing rebuilt.
- A `coat_of_arms_id` usually lives on the dynasty, but a house may carry its
  own, and then that one wins. `ck3parser.dynasties.arms_id` decides, and
  `house_name` likewise: the wiki and the hand-off disagreeing means the image a
  page links is not the image the companion is asked for.
- A `coat_of_arms_id` is an index inside one save, not a global id, and never
  names an image. An arms image is named after a digest of the **recipe** the
  game draws it from (`ck3parser.arms`), so the same picture is one file in
  every run. Whether arms are fixed or generated cannot be told from the
  dynasty: 57 of 60 game-keyed dynasties had different artwork between two
  playthroughs (PLAN.md §11).
- A coat-of-arms recipe keeps repeated keys and their order: `colored_emblem`
  appears once per emblem and they are drawn in the order listed. Never put one
  in a dict, and never sort it.
- Titles carry a `coat_of_arms_id` as well as houses — all 12 915 of them in the
  1364 save. A title and a house *can* share one image, because the name comes
  from the recipe and not from the bearer, but rarely: 4 of Germania's 68
  titles. `Arms.title` or `Arms.house` is set, never both (PLAN.md §11).
- A character is harvestable only if they are in `living` AND have no
  `dead_data`; someone who died on the save's date satisfies only the first.
  This binds the **wiki** as much as the hand-off: never link a portrait slot
  for a character who was dead in that save. Getting it wrong once put 1 277
  impossible images into the companion's queue.
- A save stores parentage **downward only**: `family_data` lists `child`, never
  `father` or `mother` (verified on all 281 916 characters of the 1364 save).
  Parents are found by inverting every child list, which is a full pass with no
  early exit — the one genuinely expensive thing a build does (PLAN.md §10).
- `family_data` mixes shapes: `spouse` repeats as its own key while `child` is a
  list. Use `Block.getall`, never `get`, or you will silently read one spouse.
- A culture's `name` is a localization key when the culture has a
  `culture_template` and the game's own text when it has none; a faith's is
  text when it has a `name` at all and a key otherwise. Transcribe a key,
  never guess it, and never show the two the same way (PLAN.md §13).
- `culture_template` says whether the *name* is a key. It does **not** say
  the game shipped the culture: 10 of the 1364 save's 190 templated cultures
  were created during that very run. `created` is the separate question, and
  `1.1.1` in it is a sentinel meaning "from the start", never a date to show.
- A faith whose `tag` is `dynamic_faith_*` was founded during the run and
  carries a `founder`. That is how the wiki can say the Germania run's own
  Folmar founded the faith the Immasonian Fylkirate is named after.
- Character reads go through the `SnapshotView`, never straight at the save:
  `view.find_characters` and `view.family_index` answer out of the cached
  digest when there is one (PLAN.md §14). Calling `find_characters(save, ...)`
  or `read_index(save, ...)` from the wiki puts a build back to minutes.
- A digest is a cache, never a format. Bump `digest.SCHEMA` when the row
  shape changes; old ones are ignored, never migrated. Every failure to read
  one must fall back to the save: a bad cache costs a slow build, never a
  wrong one.
- Siblings get pages. A succession is usually a quarrel between them, so the
  brother who was passed over is worth one; `--no-siblings` goes back to the
  narrow line (PLAN.md §10).
- The chronicle stops one ring past the direct line, and that ring gets pages
  **only where it holds a title itself**: of ~13 000 people there, 98.6% hold
  nothing. A title is what put anyone in; do not widen the gate without a
  measurement, and never iterate it outward (PLAN.md §10).
- A save's top-level key set varies between saves of one run. Never assume a
  section exists.
- Facts labelled "verified" in PLAN.md were checked on three real saves. Anything
  new you assume about the format goes in PLAN.md §5 with a note whether it was
  checked against a real save.
- When you change the save-grouping logic, re-run `runs verify` on the three real
  saves; it must still report one clean run with legacy 19 → 20 → 20.
