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
| Branch | `claude/ck3-save-grouping-plan-xnss2t` (no pull request opened yet) |
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
- **Pipeline** (`pipeline.py`): one title end to end, `--dry-run` prints Cypher.

Measured on the three real saves (same run, 1358 / 1361 / 1364):

| Command | Result |
|---|---|
| `runs scan saves --no-hash` | one run, correct order, 83 ms |
| `runs verify saves` | legacy 19 → 20 → 20, no warnings, ~11 s |
| `pipeline … --title k_papal_state --dry-run` | 122 holders found, 4 sections streamed, ~25 s |

## What is not done, in the order I would do it

1. **Immediate vassals of the target title** (PLAN.md Phase 3). `pipeline.py`
   loads one title only. Titles carry `de_jure_liege` (a numeric index into
   the `landed_titles` list, not a key) and `de_jure_vassals={ … }`; the real
   save's vassal structure has not been inspected yet. Verify which field
   expresses the *current* (not de jure) liege on a real save before coding.
2. **Multi-snapshot merge loop** (Phase 5). `runs.json` gives the ordered
   snapshots; loop oldest to newest calling `load_snapshot` + `load_title`.
   Loader already sets `first_seen` / `last_seen`. Add the tier-3 content check
   (title history and death dates of the earlier snapshot must appear in the
   later one) as warnings, not aborts. The check logic exists in throwaway form
   only; PLAN.md §5 lists the numbers it produced.
3. **Whole-file parser pass and section index** (Phase 2 milestone 3). Stream
   the entire 280 MB `gamestate` through `iter_top_level(only=set())` once and
   confirm it reaches EOF with balanced braces; record the top-level keys and
   line numbers. Sections not yet touched by anything: `provinces`,
   `dynasties`, `religion`, `culture_manager`, `wars`, `coat_of_arms`, and the
   many `triggered_event` blocks (repeated top-level key).
4. **Character lookup speed.** `pipeline.characters_by_id` streams each
   character section fully once per title (~25 s). For many titles build an
   id → section index once, or parse `living` / `dead_*` a single time and keep
   only referenced ids.
5. **Culture and faith names.** Characters carry numeric `culture` / `faith`
   ids; resolve them through `culture_manager` and `religion` (not parsed yet).
6. **Full-save scale** (Phase 6), then narrative generation (Phase 7, gated on
   choosing a local LLM; no SDK dependency until then).

## Known gaps and gotchas

- `version="1.6.1.2"` in all three saves but the DLC list contains DLCs newer
  than that; the string is stored as-is and only used for a warning on change.
- `meta_real_date` is the real-world save date as years since 1900
  (`126.3.6` = 2026-03-06). It is used for ordering and as a scumming check.
- The middle 8 hex digits of the `SAV0102…` first line are not understood.
- No `playthrough_id` exists in this save version. If a newer version adds one,
  prefer it as the RunKey and keep the seed as fallback.
- `RunKey` includes the DLC hash, so toggling a DLC mid-run would split the
  run. A CLI override is planned, not built.
- The parser assumes no `#` comments and no quoted string spanning lines. Both
  hold in the three saves; neither is enforced.
- `holder_intervals` closes an interval at the next history entry of any kind
  and treats an entry with a `holder` inside a typed block as a new holder.
  Only `type=destroyed` blocks have been seen; other types are untested.
- `filter.is_filler` drops unreferenced characters without a `dynasty_house`.
  On the Papacy trace nothing was dropped because every holder is referenced;
  the filler rule has only been exercised on the fixture.
- Tests never touch Neo4j; `open_session` imports the driver lazily. A local
  Neo4j has not been used in this session at all, so the Cypher has been
  reviewed but not executed.

## How to verify you have not broken anything

```
uv run pytest -q                                   # must stay green
scripts/fetch_saves.sh                             # once
uv run python -m ck3parser.runs verify saves       # one run, 19/20/20, exit 0
uv run python -m ck3parser.pipeline saves/Fylkir_Asa_of_Immasonian_Fylkirate_1358_09_13.ck3 \
    --title k_papal_state --dry-run 2>&1 >/dev/null | grep characters   # "found 122, kept 122"
```

## Conventions

- Branch `claude/ck3-save-grouping-plan-xnss2t`; commit messages explain the
  why and list what was checked against real saves.
- Keep `docs/PLAN.md` §5 (verified facts) and §6 (milestone status) current.
- No hardcoded absolute paths; saves live in a git-ignored `saves/` directory.
