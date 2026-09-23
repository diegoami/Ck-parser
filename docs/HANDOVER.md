# Handover

State of the CK3 History Extractor, kept current PR by PR, written so a fresh
session (any model) can continue without the conversation history.

## Where things are

| What | Where |
|---|---|
| Plan, design, verified save-format facts | `docs/PLAN.md` |
| Agent rules and commands | `CLAUDE.md` |
| Code | `src/ck3parser/`, `src/ck3graph/`, `src/ck3wiki/` (see README for the module map) |
| Tests and fixture | `tests/`, `tests/fixtures/gamestate_sample.txt` |
| Real saves | **ck_wiki's** Releases, tagged by run seed; `scripts/fetch_saves.sh` downloads and checksums them into `./saves` |
| Branch | work lands on `main` through a PR per task |
| Published wiki | `diegoami/ck_wiki` — its `images/` holds the companion's harvested images, its `portraits.json` the queue; the pages are built there, never committed |
| CI | `.github/workflows/ci.yml`, runs `uv run pytest` on the fixture on every push and PR, ~15 s |

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
- **Graph loader** (`ck3graph/loader.py`, `ck3graph/people.py`): env config,
  `DryRunSession`, `holder_intervals` (handles `date=holder` and
  `date={type=...}`), MERGE writers for Run / Snapshot / Title / Character /
  House / Dynasty / HELD_BY / MEMBER_OF / OF_DYNASTY / HEADED_BY, vassalage as
  bounded stretches, and the family edges PARENT_OF / REAL_FATHER_OF /
  SPOUSE_OF. `--people` adds every character in the save: one streaming pass,
  ~54 s, 281 916 nodes and 389 639 parent links, written in `UNWIND` batches.
  The graph needs no inversion — Cypher walks a parent edge both ways
  (PLAN.md §12).
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
  prose. `diegoami/ck_wiki` publishes it to Pages; this repository no longer
  does, and its `pages.yml` is gone.
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
- **Houses and dynasties** (`dynasties.py`): a character's `dynasty_house`
  resolves to a house, its dynasty, and the dynasty's `coat_of_arms_id`, all
  streamed by id out of sections holding ~50 000 records each. A house may
  carry its own `coat_of_arms_id`, and then it wins; `arms_id` and `house_name`
  are the one rule each, because the wiki and the hand-off disagreeing means
  the image a page links is not the image the companion is asked for. The wiki
  gives every house a page with its members, head, motto key and founding date,
  and the hand-off writes a `houses_<date>.csv` beside each snapshot's
  characters.
- **Image names and the manifest** (`portraits.py`, `ck3wiki/manifest.py`):
  both projects derive the same file name from the save's base name and the id,
  so nothing has to be negotiated. Every character page carries a portrait slot
  per save it appears in and every house page a slot for its arms, linked
  whether or not the file exists; missing ones render as *awaiting harvest*.
  `portraits.json`, at the site root and in each chronicle, is the
  machine-readable list of what is still wanted. On the five release saves that is
  5 630 images across 3 chronicles, none harvested yet.
- **Vassalage** (`ck3wiki/model.py`, `Vassalage`): every title in the wiki is
  asked of every snapshot who its de facto liege was, through that snapshot's
  own index rather than by assuming it was the subject. Consecutive snapshots
  with the same answer collapse into a stretch carrying bounds, because a save
  has no vassalage history and a change is only ever known to have happened
  between two snapshots. On the three Germania saves, 46 of 68 titles changed
  liege at least once and 2 changed twice. The graph edge is bracketed by
  `first_seen`/`last_seen`, moving only outward.
- **Incremental builds** (`ck3parser/digest.py`): each save's characters are
  written once to a gzipped digest — 281 916 rows, 11 MB, 54 s to write, **2.1 s
  to read back** — and the five per-save character passes become one read.
  Adding a save to a run costs that save's pass, not the run's. Keyed by
  fingerprint, schema-versioned, ignored rather than migrated when stale, and
  every failure falls back to reading the save. `--no-cache` turns it off;
  `.ck3cache/` is git-ignored. Character reads go through `SnapshotView`
  (`view.find_characters`, `view.family_index`), never straight at the save.
- **Family** (`ck3parser/family.py`): parents, siblings, spouses, former
  spouses and children on every character page. A save stores parentage
  **downward only** — `family_data` lists `child` and never `father` or
  `mother`, verified across all 281 916 characters of the 1364 save — so
  parents are found by inverting every child list. That is a full pass with no
  early exit, ~37 s per snapshot, and it is the most expensive thing a build
  does; `--no-family` skips it. It buys parents for 590 of the Germania
  lineage's 666 characters (536 with both) against 447 for a lineage-only
  inversion. Relatives outside the lineage (2 784 of 3 235) are fetched only
  far enough to be named.
- **Pipeline** (`pipeline.py`): a lineage (title plus its immediate de facto
  vassals) end to end. Given a directory it loads every snapshot of that run
  oldest first, checking consecutive pairs as it goes. `--no-vassals`,
  `--no-check`, `--run <id>` and `--dry-run` flags; a dry run prints its
  statements only with `--echo`. Exit 0 clean, 1 loaded with
  disagreements, 2 bad arguments.

Measured on the three real saves (same run, 1358 / 1361 / 1364):

| Command | Result |
|---|---|
| `runs scan saves --no-hash` | one run, correct order, 83 ms |
| `runs verify saves` | legacy 19 → 20 → 20, no warnings, ~11 s |
| `pipeline … --title k_papal_state --dry-run` | 1 vassal, 139 characters, 0 missing |
| `pipeline … --title e_germany --dry-run` | 51 vassals, 1 184 tenures, 100 vassal edges, 666 characters, ~33 s |
| `pipeline saves/ --title e_germany --dry-run` | 3 snapshots oldest first, 2 324 tenures, 183 vassalage stretches, 276 houses, 0 disagreements, ~2 m 22 s |
| `pipeline … --people` on the 1364 save | 281 916 characters, 389 639 parent links, 471 646 spouse rows, ~54 s |
| `pipeline saves/ --title e_germany` into a live Neo4j | 81 titles, 952 characters, 1 559 tenures, 132 vassal edges, ~1 m 54 s |
| `sections SAVE` | 54 distinct top-level keys, 14 M lines, 4.8 s |
| `sections SAVE --verify` | ~41 M tokens, balanced, max depth 7, ~38 s |
| `handoff saves --title e_germany --run <germany>` | 26 / 2 / 25 harvestable per snapshot, 48 distinct across the run, 22 / 1 / 21 houses, all with arms, ~2 m |
| `ck3wiki.build saves` on all five release saves | 3 chronicles, 21 879 pages, 5 845 images wanted, ~8 min in CI with family and kin |
| `ck3wiki.build <germania>` with family, cold cache | 1 chronicle, 7 393 pages, 2 470 images, 3 m 51 s |
| `ck3wiki.build <germania>` with family, warm cache | the same 7 393 pages, **1 m 06 s** — against 9 m 55 s before the digest and before sibling pages |
| `runs scan` on all five | 3 runs: seeds 576691683 / 633048653 / 1370892195 on versions 1.6.1.2 / 1.4.4 / 1.3.1 |

## What is not done, in the order I would do it

**The wiki comes first.** The graph is a milestone and an interesting artifact
in its own right (PLAN.md §12), but the published chronicle is the deliverable,
and in a first pass it outranks everything the graph could answer.

1. **Narrative prose.** The wiki is factual; Phase 7's LLM-written text is still
   gated on choosing a small local model. Everything it would need now exists:
   succession, vassalage with honest bounds, family, houses and arms.
2. **Widen further, or stop here.** Parents, spouses, children and now
   siblings have pages and portraits (PLAN.md §10). Beyond that lies the second
   hop — a spouse's parents, a sibling's children — which needs no new pass now
   that the digest holds every character, but does need a decision about where a
   chronicle stops. There is no longer a performance reason not to; the reason
   to stop is editorial.
3. **Cache the other sections too, if a build is still too slow.** The
   character digest (PLAN.md §14) took the five character passes down to one
   read. What is left uncached is `landed_titles` (~2 s a save), the dynasties
   section, arms, cultures and faiths — each read once, none of them the shape
   of the problem the characters were. Do this only if a measurement says to.
4. **Deeper lineages**, then **full-save scale** (PLAN.md Phase 6). Vassalage
   has bounded stretches (§9) but still only one level down: a county under a
   vassal duchy is not loaded.
5. **The graph, once the wiki is where it should be.** It now holds what the
   wiki knows and more (PLAN.md §12), so the remaining work is the *query* side,
   not the loading side: pairing it with a local LM and seeing whether Cypher it
   composes actually answers *how many cousins has X*, *how closely are X and Y
   related*, *the vassal tree of X as of 1361*. Relatedness is genealogical, not
   DNA: the packed `dna=` field stays untouched.

   Two things to know before touching it. `VASSAL_OF` stretches are identified
   by where they start, so loading a strict subset of a run's snapshots after
   the whole run can leave an overlapping stretch — the price of a loader that
   never deletes, and one the CLI never pays. And the graph has no page-sized
   notion of who matters: `--people` loads all 281 916 characters on purpose,
   because a cousin two hops up and two back down usually leaves the lineage on
   the way.

   Worth restating so nobody later mistakes enthusiasm for necessity:
   relatedness, cousins, "vassals who are my kin" and "vassals in my house" are
   all computable today from `FamilyIndex` plus the wiki model, with no
   database. Some of them arguably belong on a **page** rather than in a query —
   "vassals who share my house" is a chronicle fact, the difference between a
   realm held by kin and one held by strangers.

   | | Where it belongs |
   |---|---|
   | asked constantly, same shape | a section on a page |
   | asked once, specific | an ad-hoc script over `FamilyIndex` |
   | asked unpredictably, in words | graph + LM |

### Done since this list was last written

- **Sessions read less.** `pipeline --dry-run` no longer prints every statement
  (`--echo` brings that back), `CLAUDE.md` asks for PLAN.md by section rather
  than whole, and forbids opening a save or gamestate raw.

- **The saves moved to ck_wiki's Releases**, tagged by run seed
  (`1370892195`, `633048653`, `576691683`) rather than by batch number.
  `fetch_saves.sh` defaults there; all five checksums verified against the
  copies this repository's releases held. This repository now has no releases
  at all, so the duplicates are gone too.

- **Siblings have pages.** A succession is usually a quarrel between them, so
  the brother who was passed over is worth one (PLAN.md §10). `--no-siblings`
  goes back to the narrow line.
- **Builds are incremental**, through a per-save character digest (PLAN.md §14).

- **Cultures and faiths are resolved and have pages** (`ck3parser/cultures.py`,
  `ck3parser/faiths.py`). Every character page names both, the index lists them,
  and each gets a page with who holds it. A faith founded during the run names
  its founder, which is how the Germania chronicle can finally say that its own
  Folmar founded the faith the Immasonian Fylkirate is named after. 63 cultures
  and 21 faiths on that run, 84 pages. A culture's name is a key when it has a
  template and the game's own text when it has none, and a template says nothing
  about *when* the culture began (PLAN.md §13).

- **The graph has caught up with the wiki.** It was writing what it wrote before
  family and vassalage existed. It now holds `PARENT_OF`, `REAL_FATHER_OF`,
  `SPOUSE_OF`, named `House` and `Dynasty` nodes with their arms, and vassalage
  as bounded stretches instead of a single `as_of` edge. Germania: 183 stretches
  over 67 titles, 48 of them seen under more than one liege, 276 houses
  resolved. `--people` adds the whole population.

- **Coat-of-arms definitions are parsed** (`ck3parser.arms`), titles included:
  all 12 915 titles of the 1364 save carry a `coat_of_arms_id` the parser used
  to drop. Arms are named after the recipe that draws them, so a title and the
  house holding it share one file (PLAN.md §11).
- **The companion proposal is filed** as
  [ck_portrait_generator#1](https://github.com/diegoami/ck_portrait_generator/issues/1),
  with the deliverable — a release on ck_wiki holding the saves and the images
  harvested from them — in a follow-up comment.
- **ck_wiki publishes.** Run 6 built all three chronicles with family and kin in
  ~8 minutes, committed the manifests back at schema `ck3-images/2` and
  deployed. Pages must be set to the **GitHub Actions** source, not a branch;
  that cost several runs to discover and is recorded in ck_wiki's README.

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
- The default suite never touches Neo4j; `open_session` imports the driver
  lazily. Only `tests/test_integration_neo4j.py` executes the Cypher, and it
  skips unless `CK3_TEST_NEO4J_URI` is set.

## How to verify you have not broken anything

```
uv run pytest -q                                   # must stay green
scripts/fetch_saves.sh                             # once
uv run python -m ck3parser.runs verify saves       # one run, 19/20/20, exit 0
uv run python -m ck3parser.sections saves/<file>.ck3 --verify   # balanced, 54 keys

uv run python -m ck3parser.handoff saves --title e_germany --out handoff
# 26 / 2 / 25 harvestable per snapshot, 48 distinct characters

uv run python -m ck3wiki.build saves --out site   # one chronicle per run

uv run python -m ck3parser.pipeline saves --title e_germany --dry-run
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
