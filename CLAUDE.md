# CK3 History Extractor — notes for coding agents

Read `docs/HANDOVER.md` first (state of the project, next tasks), then
`docs/PLAN.md` (design, verified facts about the save format).

## Commands

```
uv sync --group dev              # install (the SessionStart hook does this on the web)
uv run pytest -q                 # 133 tests, < 1 s, fixture only
scripts/fetch_saves.sh           # three real saves (~73 MB each) into ./saves, git-ignored
uv run python -m ck3parser.runs verify saves --json saves/runs.json
uv run python -m ck3parser.pipeline saves/<file>.ck3 --title e_germany --dry-run
uv run python -m ck3parser.pipeline saves --title e_germany --dry-run   # whole run, oldest first
uv run python -m ck3parser.sections saves/<file>.ck3 --verify           # top-level layout
uv run python -m ck3parser.handoff saves --title e_germany --out handoff  # portrait harvester list
uv run python -m ck3wiki.build saves --out site                          # the wikis themselves
uv run python -m ck3wiki.build saves --out site --portraits harvested    # ... with images folded in
```

## Rules

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
- A save has **no vassalage history**: it says who a title's liege *is*, never
  who it has been. A liege change is only ever known to have happened between
  two snapshots, and must be shown as bounds ("between X and Y"), never as a
  date. Never narrow it from the holder history: a title can change liege
  without changing hands (PLAN.md §9).
- A title absent from a save was destroyed or pruned, and the save does not say
  which. Absence is never independence, and never bridges two stretches.
- No LLM SDK dependency yet; narrative generation is deferred (PLAN.md Phase 7).
  The wiki `ck3wiki` builds today is factual, generated straight from save data.
- Character names in saves are localization keys with diacritics marked by an
  underscore. Drop the marker, never guess the letter (PLAN.md §8).
- One wiki per playthrough. What separates them is the run, identified by seed
  and game version, never the title the wiki is about.
- `diegoami/ck_portrait_generator` is the companion tool. It consumes plain data
  files from here and imports no code; see PLAN.md §7 for what it needs. Read its
  `docs/DECISIONS.md` before assuming anything about portraits.
- `diegoami/ck_wiki` is where the wiki is published and where the companion
  commits its images. This repository builds the pages; it does not publish them
  and has no Pages workflow. Generated pages are never committed anywhere.
- `scripts/fetch_saves.sh` must never infer the repository from
  `GITHUB_REPOSITORY`: it runs inside ck_wiki's workflow, where that names
  ck_wiki and the saves are not there.
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
- A `coat_of_arms_id` is an index inside one save, not a global id. Scope
  anything derived from it by the save it was read from.
- A character is harvestable only if they are in `living` AND have no
  `dead_data`; someone who died on the save's date satisfies only the first.
- A save stores parentage **downward only**: `family_data` lists `child`, never
  `father` or `mother` (verified on all 281 916 characters of the 1364 save).
  Parents are found by inverting every child list, which is a full pass with no
  early exit — the one genuinely expensive thing a build does (PLAN.md §10).
- `family_data` mixes shapes: `spouse` repeats as its own key while `child` is a
  list. Use `Block.getall`, never `get`, or you will silently read one spouse.
- A save's top-level key set varies between saves of one run. Never assume a
  section exists.
- Facts labelled "verified" in PLAN.md were checked on three real saves. Anything
  new you assume about the format goes in PLAN.md §5 with a note whether it was
  checked against a real save.
- When you change the save-grouping logic, re-run `runs verify` on the three real
  saves; it must still report one clean run with legacy 19 → 20 → 20.
