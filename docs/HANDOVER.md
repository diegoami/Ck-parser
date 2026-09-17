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
- **Consistency** (`consistency.py`): tier-3 checks between two snapshots of
  one run. Title history up to the earlier date must survive into the later
  snapshot, and nobody may un-die or change death date. Pure functions over
  parsed data. A record present early and absent later is pruning, not a
  disagreement.
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

## What is not done, in the order I would do it

1. **Run it against a live Neo4j.** Everything so far is `--dry-run`. No
   session has ever executed the Cypher, so the schema, the `MERGE` semantics
   and the driver plumbing are reviewed but unproven. Start Neo4j, apply
   `schema.cypher`, load one lineage from one save, then load the whole run
   over the top and confirm the second pass refines rather than duplicates.
2. **Whole-file parser pass and section index** (PLAN.md Phase 2 milestone 3).
   Stream an entire 280 MB `gamestate` through `iter_top_level(only=set())`
   once and confirm it reaches EOF with balanced braces; record the top-level
   keys and line numbers. Sections still untouched: `provinces`, `dynasties`,
   `religion`, `culture_manager`, `wars`, `coat_of_arms`, and the many
   `triggered_event` blocks (a repeated top-level key).
3. **Character lookup speed.** A single-snapshot lineage load takes ~33 s,
   nearly all of it three full passes over the character sections, so a
   three-snapshot run takes ~1 m 39 s. Build an id -> section index once per
   save, or parse the character sections a single time and keep only
   referenced ids.
4. **Culture and faith names.** Characters carry numeric `culture` / `faith`
   ids; resolve them through `culture_manager` and `religion` (not parsed yet).
5. **Deeper lineages.** `immediate_vassals` is one level by design. A whole
   realm needs a recursive walk with a depth limit, and a decision about
   whether to store `VASSAL_OF` for every level or only the direct one.
6. **Vassalage as intervals.** `VASSAL_OF` is a snapshot fact carrying `as_of`,
   so a title that changed liege between snapshots gets one edge per liege.
   `HELD_BY` shows how intervals would be modelled instead.
7. **Full-save scale** (Phase 6), then narrative generation (Phase 7, gated on
   choosing a local LLM; no SDK dependency until then).

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
uv run python -m ck3parser.pipeline saves --title e_germany --dry-run 2>&1 >/dev/null
# 3 snapshots oldest first, 37/19/51 vassals, 0 missing characters, exit 0
```

## Conventions

- One branch and PR per handover task, cut from the latest `main`; commit
  messages explain the why and list what was checked against real saves.
- Keep `docs/PLAN.md` §5 (verified facts) and §6 (milestone status) current.
- No hardcoded absolute paths; saves live in a git-ignored `saves/` directory.
