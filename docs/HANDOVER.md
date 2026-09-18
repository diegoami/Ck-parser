# Handover

State of the CK3 History Extractor as of the end of the scaffold pass, written
so a fresh session (any model) can continue without the conversation history.

## Where things are

| What | Where |
|---|---|
| Plan, design, verified save-format facts | `docs/PLAN.md` |
| Agent rules and commands | `CLAUDE.md` |
| Code | `src/ck3parser/`, `src/ck3graph/` (see README for the module map) |
| Tests and fixture | `tests/`, `tests/fixtures/gamestate_sample.txt` |
| Real saves | GitHub Releases 0.0.2 / 0.0.3 / 0.0.4; `scripts/fetch_saves.sh` downloads and checksums them into `./saves` |
| Branch | work lands on `main` through a PR per task |
| CI | `.github/workflows/ci.yml`, runs `uv run pytest` on the fixture; has not run yet because no PR exists |

## What is done

- **Container reader** (`container.py`): header via the hex length field on the
  `SAV0102…` line, zip-signature fallback, streamed gamestate, synthetic save
  writer for tests.
- **Streaming parser** (`parser.py`): brace-driven, keeps repeated keys,
  `iter_children(lines, path)` streams direct children of a nested section,
  `read_top_level(lines, name)` seeks by a column-0 line scan. Exercised on the
  real saves for `landed_titles`, `living`, `dead_unprunable`,
  `characters.dead_prunable`, `played_character`.
- **Filter** (`filter.py`): title holders + family links decide who is kept.
- **Fingerprint** (`fingerprint.py`): tier 1, header + ~32 KB of gamestate,
  ~3 ms per file.
- **Run grouping** (`runs.py`): RunKey = (random_seed, bookmark_date, rules
  hash, DLC hash); order by date, random_count, meta_real_date, mtime; tier-1
  monotonic checks; tier-2 `played_character.legacy` prefix check; divergence
  splits the run and adds a warning; `runs.json` manifest with incremental
  rescans; CLI `scan` / `verify`. Exit code 1 when any warning exists.
- **Graph loader** (`ck3graph/loader.py`): env config, `DryRunSession`,
  `holder_intervals` (handles `date=holder` and `date={type=...}`),
  MERGE writers for Run / Snapshot / Title / Character / House / HELD_BY.
- **Titles** (`titles.py`): streams `landed_titles` into a compact
  `TitleIndex` (12 915 records, 107 328 history entries, 1.9 s on the sample),
  resolves the numeric `de_facto_liege` / `de_jure_liege` pointers to keys,
  derives tiers including dynamic `x_` titles, and answers
  `immediate_vassals()` and `liege_chain()`. `normalize_history` turns a raw
  history block into `(date, holder, reason)` tuples.
- **The wiki** (`src/ck3wiki/`): `model.py` merges a run's snapshots into one
  picture, `render.py` writes static HTML, `build.py` is the CLI
  (`python -m ck3wiki.build SAVES --out site`). One chronicle per playthrough
  under `site/<seed>-<version>/`, with a landing page above them; the subject
  title is auto-detected per run and `--title` overrides it. This is the
  project's actual deliverable; see PLAN.md §8. Factual pages only, no LLM
  prose. A GitHub Actions workflow publishes it to Pages.
- **Who was played** (`ck3parser/player.py`): `primary_title_key` reads the
  played character from the header, finds their `landed_data.domain`, and
  resolves its first entry to a title key. `ck3parser/characters.py` holds the
  targeted character lookup both it and the hand-off use.
- **Hand-off** (`handoff.py`): writes the portrait harvester's character list,
  one file per snapshot, via
  `python -m ck3parser.handoff SAVES --title KEY --out DIR [--ids-only]`.
  Selection is the lineage's ever-holders narrowed to those alive at that
  snapshot's date, which needs both the `living` section **and** the absence of
  `dead_data`. See PLAN.md §7 for the contract and the measured numbers.
- **Sections** (`sections.py`): `section_index` reports where each top-level
  key of a gamestate starts and ends (4.8 s on a 280 MB save), `verify_parse`
  tokenizes the whole file and checks the braces balance, and
  `python -m ck3parser.sections SAVE [--verify]` prints the table. All three
  real saves parse end to end with balanced braces.
- **Consistency** (`consistency.py`): tier-3 checks between two snapshots of
  one run. Title history up to the earlier date must survive into the later
  snapshot, and nobody may un-die or change death date. Pure functions over
  parsed data. A record present early and absent later is pruning, not a
  disagreement.
- **Live Neo4j** is proven, not just reviewed. `tests/test_integration_neo4j.py`
  runs the real loader against a real database, opt in through
  `CK3_TEST_NEO4J_URI`; it WIPES that database, so point it at a throwaway one.
  It covers schema, idempotent reloads, a tenure closed in place by a later
  snapshot, order independence and the date types.
- **Pipeline** (`pipeline.py`): a lineage (title plus its immediate de facto
  vassals) end to end. Given a directory it loads every snapshot of that run
  oldest first, checking consecutive pairs as it goes. `--no-vassals`,
  `--no-check`, `--run <id>` and `--dry-run` flags. Exit 0 clean, 1 loaded with
  disagreements, 2 bad arguments.

Measured on the three real saves (same run, 1358 / 1361 / 1364):

| Command | Result |
|---|---|
| `runs scan saves --no-hash` | one run, correct order, 83 ms |
| `runs verify saves` | legacy 19 → 20 → 20, no warnings, ~11 s |
| `pipeline … --title k_papal_state --dry-run` | 1 vassal, 139 characters, 0 missing |
| `pipeline … --title e_germany --dry-run` | 51 vassals, 1 184 tenures, 100 vassal edges, 666 characters, ~33 s |
| `pipeline saves/ --title e_germany --dry-run` | 3 snapshots oldest first, 2 324 tenures, 208 vassal edges, 0 disagreements, ~1 m 39 s |
| `pipeline saves/ --title e_germany` into a live Neo4j | 81 titles, 952 characters, 1 559 tenures, 132 vassal edges, ~1 m 54 s |
| `sections SAVE` | 54 distinct top-level keys, 14 M lines, 4.8 s |
| `sections SAVE --verify` | ~41 M tokens, balanced, max depth 7, ~38 s |
| `handoff saves --title e_germany` | 26 / 2 / 25 harvestable per snapshot, 48 distinct across the run, ~2 m |
| `ck3wiki.build saves` on all five release saves | 3 chronicles, 4 412 pages, ~2 m 34 s |
| `runs scan` on all five | 3 runs: seeds 576691683 / 633048653 / 1370892195 on versions 1.6.1.2 / 1.4.4 / 1.3.1 |

## What is not done, in the order I would do it

1. **Narrative prose.** The wiki is factual; Phase 7's LLM-written text is still
   gated on choosing a small local model. The pages are the place it would go.
2. **Parse coat-of-arms definitions.** The companion's roadmap wants dynasty and
   title arms composed offline from save data plus install textures, and says
   extracting them is this project's job (PLAN.md §7). `coat_of_arms` is 11% of
   a save and titles carry `coat_of_arms_id`, which the title parser drops.
   Arms would also be the obvious thing to put on a title page.
3. **Character lookup speed.** A lineage load takes ~34 s per snapshot, nearly
   all of it full passes over the character sections; the wiki and the hand-off
   each pay it again. The section index gives line ranges, so what is missing is
   an id -> offset index within the character sections.
4. **Culture and faith names.** Numeric ids resolved through `culture_manager`
   and `religion`. Both the hand-off and the wiki omit culture until then.
5. **Dynasties and houses.** The wiki shows a bare house id because the
   `dynasties` section (9.3% of a save) is never parsed. House pages are the
   obvious next page type.
6. **Widen what counts as "interesting".** Spouses, heirs and claimants are all
   in reach and none are included.
7. **Deeper lineages**, **vassalage as intervals**, then **full-save scale**
   (PLAN.md Phase 6).

## Known gaps and gotchas

- `version="1.6.1.2"` in all three saves while the DLC list contains DLCs
  released well after 1.6. The player started this run on 1.6.1.2 and carried
  it through later patches, so the field records the version at run start, not
  at save time (unverified against a freshly started game). Stored as-is; only
  used for a warning on change.
- `meta_real_date` is the real-world save date as years since 1900
  (`126.3.6` = 2026-03-06). It is used for ordering and as a scumming check.
- The middle 8 hex digits of the `SAV0102…` first line are not understood.
- No `playthrough_id` exists in this save version. If a newer version adds one,
  prefer it as the RunKey and keep the seed as fallback.
- `RunKey` includes the DLC hash, so toggling a DLC mid-run would split the
  run. A CLI override is planned, not built.
- The parser assumes no `#` comments and no quoted string spanning lines. Both
  hold in the three saves; neither is enforced.
- `holder_intervals` closes a tenure at the next history entry of any kind.
  A typed entry opens a new tenure unless its type is in
  `titles.TERMINAL_TYPES`, which holds `destroyed` alone. That list was derived
  from the 16 reason types in the sample saves (PLAN.md §5); a save containing
  a terminal type not in it would invent a tenure, so revisit the list if an
  unknown reason shows up.
- `Block` subclasses `list`, so anything accepting "a block or a list of
  tuples" must test for `Block` first. `holder_intervals` does; new code
  should too.
- `immediate_vassals` follows `de_facto_liege` only. The explicit
  `de_jure_vassals` list on some titles is parsed but unused.
- The lineage changes shape across a succession: the sample empire has 37
  immediate vassals in 1358, 19 in 1361 just after the 1360 succession, and 51
  in 1364. That is game history, confirmed by title-level comparison (21 kept,
  16 lost, 30 gained between the outer two), not a parsing artifact.
- Tier-3 checks compare only the titles in the lineage being loaded, and only
  the characters it fetched. A whole-save comparison would be a stronger
  verification of the run grouping and is not wired up.
- A default argument like `log=sys.stderr` binds at import time and escapes
  pytest's capture. `gather` and `resolve_saves` resolve the stream at call
  time instead.
- Neo4j cannot `MERGE` a relationship on a null property. A tenure with no
  start date is dropped rather than written, which is why `holder_intervals`
  filters its own output.
- 21 of the 1 559 tenures in the empire load run past their holder's recorded
  death, because pre-bookmark history is sparse (`c_bithynia` jumps from 752 to
  855 with one holder between). That is the save's granularity, left as stated.
  `MATCH ()-[h:HELD_BY]->(c) WHERE c.death IS NOT NULL AND h.to > c.death`
  finds them.
- Character names in a save are localization *keys* with diacritics marked by an
  underscore (`FranC_ois`). The wiki drops the marker rather than guessing the
  letter; real names need the game's localization files, which this project does
  not read.
- Two titles can share a display name (a duchy and a kingdom of Pomerania), so
  a name alone never identifies a title. The key does.
- What separates one wiki from another is the **run**, identified by seed and
  game version, not the title it is about. Three real playthroughs are on the
  Releases and they differ in seed, version and bookmark date.
- Pages is enabled and the wiki publishes: run 3 of the `Wiki` workflow built
  and deployed, and the repository reports `has_pages: true`. Getting there
  took two failed runs, and the lesson is worth keeping: **enabling Pages
  cannot be automated.** Creating a Pages site needs admin rights and
  `GITHUB_TOKEN` tops out at write, so `enablement: true` on
  `actions/configure-pages` fails with "Resource not accessible by
  integration". Only the settings page or a PAT with admin scope can do it.
- This container cannot reach `diegoami.github.io`; the egress proxy refuses
  it. The published site therefore cannot be verified from a session here,
  only the workflow run that produced it.
- A run's subject title can be a dynamic one: France's is `x_x_5822`, a custom
  empire, so anything assuming a static key prefix will break on it.
- A character can sit in the `living` section and still carry `dead_data`, if
  they died on the save's own date. `handoff.living_characters` requires both
  signals; anything else deciding who is alive should too.
- The harvestable population swings hard between snapshots of one run (26, then
  2, then 25 for the same lineage), because a ruler who has just inherited
  holds everything directly. A small list is not evidence of a bug.
- The top-level key set is not fixed even within one run: the 1361 save has a
  `player_event` section the other two lack. Never assume a section exists.
- Per-character DNA is stored **packed** (87 727 `dna="…"` fields); readable
  gene blocks exist only for the player's portraits in `meta_data`. The
  companion project no longer needs either (PLAN.md §7).
- 671 titles have two history entries on the same date, so a title can have two
  tenures starting the same day, one of them zero length. Anything assuming one
  tenure per (title, start date) is wrong; the graph keys them by holder too.
- No local Neo4j install is needed to run the integration suite here: Maven
  Central is reachable and `org.neo4j.test:neo4j-harness` starts an in-process
  server with Bolt. Docker has no daemon in this environment and
  `dist.neo4j.org` is blocked by the proxy.
- `filter.is_filler` drops unreferenced characters without a `dynasty_house`.
  On the real traces nothing is dropped, because every character the pipeline
  asks for is referenced by construction; the filler rule has only been
  exercised on the fixture. `filter.filter_characters`, which expands the
  referenced set through family links, is likewise unused by the pipeline and
  waits for the pass that streams whole character sections.
- Tests never touch Neo4j; `open_session` imports the driver lazily. A local
  Neo4j has not been used in this session at all, so the Cypher has been
  reviewed but not executed.

## How to verify you have not broken anything

```
uv run pytest -q                                   # must stay green
scripts/fetch_saves.sh                             # once
uv run python -m ck3parser.runs verify saves       # one run, 19/20/20, exit 0
uv run python -m ck3parser.sections saves/<file>.ck3 --verify   # balanced, 54 keys

uv run python -m ck3parser.handoff saves --title e_germany --out handoff
# 26 / 2 / 25 harvestable per snapshot, 48 distinct characters

uv run python -m ck3wiki.build saves --out site   # one chronicle per run

uv run python -m ck3parser.pipeline saves --title e_germany --dry-run 2>&1 >/dev/null
# 3 snapshots oldest first, 37/19/51 vassals, 0 missing characters, exit 0

# against a throwaway database (this WIPES it):
CK3_TEST_NEO4J_URI=bolt://127.0.0.1:7687 \
    NEO4J_USER=neo4j NEO4J_PASSWORD="$YOUR_TEST_PASSWORD" \
    uv run pytest tests/test_integration_neo4j.py     # 8 passed
```

## Conventions

- One branch and PR per handover task, cut from the latest `main`; commit
  messages explain the why and list what was checked against real saves.
- Keep `docs/PLAN.md` §5 (verified facts) and §6 (milestone status) current.
- No hardcoded absolute paths; saves live in a git-ignored `saves/` directory.
