# CK3 History Extractor — Project Plan

Starting point: the "CK3 History Extractor — Repo Setup Prompt" artifact
(scaffold pass: extract → parse → filter → load one lineage into Neo4j; narrative
generation deferred until a small local LLM is chosen). This document turns that
prompt into a phased plan and adds a new requirement: **grouping save files that
belong to the same CK3 run (playthrough) saved at different in-game dates**, under
the assumption that the player does not save-scum.

Everything in the "Verified against the sample save" section was checked against
the release asset `Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3`
(release 0.0.2, 73.8 MB, sha256 `919ad2c7…946a`). Items marked **verify** are
assumptions that still need a second save from the same run to confirm.

---

## 1. Phases

| Phase | Deliverable | Depends on |
|---|---|---|
| 0 | Repo scaffold exactly as the setup prompt describes (`pyproject.toml`, `src/ck3parser`, `src/ck3graph`, fixtures, `.env.example`, README, CI) | — |
| 1 | Save container + header reader: `.ck3` → metadata dict + streamed `gamestate` | 0 |
| 2 | Streaming Clausewitz parser that survives the real file (see quirks below) | 1 |
| 3 | One-lineage extraction into Neo4j (`(:Title)-[:HELD_BY {from,to}]->(:Character)`) | 2 |
| 4 | **Run grouping**: fingerprint saves, cluster them into runs, order them, verify the chain | 1, 2 (partial) |
| 5 | Multi-snapshot loading: merge several saves of one run into one graph with provenance | 3, 4 |
| 6 | Full-save scale (all referenced characters, all titles) | 5 |
| 7 | Narrative generation (deferred, local LLM) | 6 |

Phases 0–3 are the setup prompt. Phase 4 is the new work and is designed so it can
be built right after Phase 1, because most of the signal lives in the first few
hundred lines of the save.

---

## 2. Phase 0–3: scaffold and single-save pipeline

Follow the setup prompt as written, with these corrections learned from the real
file:

- **`pyproject.toml` dependencies**: `neo4j`, `pytest` only. The prompt's
  dependency line still lists `anthropic`; the rest of the prompt says not to add
  an LLM SDK yet. Do not add it.
- **Container format** (`extract.py`): the file starts with a one-line `SAV…`
  header, then a plaintext `meta_data={ … }` block, then a zip archive whose only
  member is `gamestate`. In the sample the zip starts at byte 27 411, so the header
  is small enough to read fully before touching the zip. Stream the zip member with
  `zipfile` (`ZipFile.open`) in chunks; the sample's `gamestate` is 283 MB
  uncompressed.
- **Parser** (`parser.py`) must be brace-driven, never indentation-driven. Real
  quirks:
  - `landed_titles` is nested twice (`landed_titles={ dynamic_templates={…}
    landed_titles={ 0={…} 1={…} … } }`) and the numbered entries sit at column 0
    with no leading tab.
  - `history={ … }` mixes two forms: `date=holder_id` and
    `date={ type=destroyed }` (or other typed blocks).
  - Lists of anonymous blocks look like `legacy={ { … }\n { … } }`.
  - Keys can be bare integers (`50544311={`), dates (`867.1.1=`), or identifiers.
  - Values can be quoted strings, bare tokens, numbers, dates, `yes`/`no`, and
    inline lists (`skill={ 5 7 4 4 2 9 }`).
- **Section index**: the parser should emit top-level section boundaries so later
  stages can seek. In the sample: `meta_data` (line 1), `date`/`bookmark_date`/
  `random_seed`/`random_count` (lines 415–420), `provinces` (3 035), `landed_titles`
  (238 167), `dynasties` (558 547), `living` (1 857 131), `dead_unprunable`
  (4 337 622), `characters` (9 692 133), `religion`, `wars`, `culture_manager`,
  `played_character` (14 007 265), `currently_played_characters`.
- **Character records** live under `living={ <id>={ first_name birth culture faith
  dynasty_house skill traits family_data alive_data court_data … } }`; dead ones
  under `dead_unprunable` with a `dead_data` block instead of `alive_data`. Culture
  and faith are numeric ids that resolve through `culture_manager` / `religion`.
- **Title names**: `landed_titles` entries carry `key`, `name`, `adj`, `holder`,
  `date`, `history`, `capital`. The player's empire is stored by its display name
  (`meta_title_name="Empire of Germania"`), so name lookups should go through
  `name=` as well as `key=`.

Success criterion stays as in the prompt: fixture tests pass and one traced run on
the fixture loads a handful of nodes into Neo4j.

---

## 3. Phase 4: grouping saves from the same run

### 3.1 Terminology and the core assumption

- **Run** (playthrough): one continuous game started from a bookmark and played
  forward. The player may save many times.
- **Snapshot**: one `.ck3` file, a frozen copy of the run at in-game `date`.
- **No save scumming** means the player never loads an older snapshot and plays a
  different future from it. Therefore the snapshots of a run form a **single linear
  chain** ordered by in-game date, and everything recorded in an earlier snapshot
  (title history, deaths, played rulers) is a **strict prefix** of what the later
  snapshot records. Grouping never has to detect branches; it only has to detect
  "same run or not" and then order.

### 3.2 What the file gives us to identify a run

The sample save has **no `playthrough_id`** anywhere in the header or the
gamestate, so the game's own load-menu grouping is not available in this version.
The usable signals, from cheapest to most expensive:

| Signal | Where | Cost to read | Behaviour across snapshots of one run |
|---|---|---|---|
| `random_seed` | gamestate line ~419 | decompress first few KB of the zip member | Same for the whole run (**verify** with a second snapshot). Different runs from the same bookmark get different seeds. This is the primary key. |
| `bookmark_date` | gamestate line ~416 | same | Constant. |
| `game_rules`, `dlcs`, `version`, `ironman` | plaintext header | free | Constant in practice; `version` may change if the game was patched mid-run, so it is a warning, not a key. |
| `played_character.name`, `player=1` | gamestate `played_character` block, far into the file | full stream | Constant (the Paradox account name). |
| `played_character.legacy` | same block | full stream | Ordered list of `{character, date, …}` for every ruler the player controlled. Earlier snapshot's list is a **strict prefix** of the later one (the last entry of the earlier snapshot is the ruler in play and has fewer fields; compare on `(character, date)` only). |
| `meta_main_portrait.id` | header | free | Currently played character id; equals the last `legacy` entry's `character`. |
| `date` / `meta_date` | gamestate line ~415 / header | free | Strictly increasing along the chain. |
| `random_count` | gamestate line ~420 | first few KB | Strictly increasing along the chain (RNG draw counter). Tie-breaker when two snapshots share a date. |
| `meta_real_date` | header | free | Unknown meaning (`126.3.6` in the sample). **Verify**; do not rely on it. |
| Title `history` blocks, character death dates | `landed_titles`, `dead_unprunable` | full parse | Earlier snapshot ⊆ later snapshot for all dates ≤ earlier `date`. |

Character ids alone do **not** identify a run: two runs from the same bookmark
share the same initial ids, and later ids are allocated from the same counters.

### 3.3 Algorithm

Three tiers, each cheaper than the next; most files stop at tier 1.

**Tier 1 — fingerprint (no full parse).**
For each `.ck3` file read the plaintext header, then open the zip and decompress
only until `random_count=` has been seen (a few KB). Produce:

```
Fingerprint = {
  file, size, sha256 (or size+mtime for the cache key),
  version, bookmark_date, random_seed, random_count, date,
  player_name (header), house_name, title_name,
  played_character_id (meta_main_portrait.id),
  game_rules_hash, dlcs_hash, ironman,
}
RunKey = (random_seed, bookmark_date, game_rules_hash, dlcs_hash)
```

Group files by `RunKey`. Inside a group, order by `date`, then `random_count`,
then file mtime.

**Tier 2 — chain check (cheap parse of one block).**
For each group with more than one snapshot, extract `played_character.legacy` from
each and assert, for consecutive snapshots A < B:

1. `A.random_count < B.random_count`
2. `A.legacy` is a prefix of `B.legacy` on `(character, date)`
3. `A.played_character.name == B.played_character.name`

If a check fails, the group is **split at that point** and both halves are reported
as "divergent chain" with the failing check. This is what save scumming or a copied
save would look like, and the plan explicitly does not try to reconcile it.

**Tier 3 — content check (optional, full parse, sampled).**
During the graph load (Phase 5) the loader already parses every snapshot, so it can
verify cheaply that for the player's primary title and its immediate vassals every
`history` entry dated ≤ `A.date` in A appears identically in B, and that every
character dead in A is dead in B with the same date. Any mismatch is logged as a
warning with the title/character id; it does not abort the load.

### 3.4 Outputs

- `runs.json` manifest next to the save directory (or in a configurable cache
  dir), one entry per run:

  ```json
  {
    "run_id": "576691683-867.1.1",
    "random_seed": 576691683,
    "bookmark_date": "867.1.1",
    "player_name": "diegoami",
    "snapshots": [
      {"file": "…_1204_05_01.ck3", "date": "1204.5.1", "random_count": 31280100,
       "played_character": 166423, "sha256": "…"},
      {"file": "…_1364_03_10.ck3", "date": "1364.3.10", "random_count": 53241628,
       "played_character": 50544311, "sha256": "…"}
    ],
    "warnings": []
  }
  ```

- CLI (`python -m ck3parser.runs`): `scan <dir>` prints groups and ordering;
  `verify <dir>` runs tier 2; `--json` writes the manifest. Re-scans are
  incremental: a file whose `(size, sha256)` is already in the manifest is not
  re-read.

### 3.5 Edge cases to handle explicitly

- **Ironman**: one file overwritten in place → a run with a single snapshot, which
  is the degenerate case and needs no special code.
- **Autosaves**: several files can share a `date` (autosave + manual save the same
  day). `random_count` orders them; identical `random_count` means identical
  content, keep one.
- **Same seed, different rules or DLC set**: treated as different runs by the
  `RunKey`; reported so the user can override if the game was patched mid-run.
- **Game version changed mid-run**: same `RunKey`, different `version` → allowed,
  logged as a warning on the run.
- **Renamed or moved files**: nothing depends on the filename; the CK3 default
  name (`<Ruler>_<Title>_<YYYY_MM_DD>.ck3`) is only used as a display label.
- **Copied save played forward twice** (branching): shows up as a tier-2 failure
  and is split. Out of scope to merge; out of scope by the stated assumption.

### 3.6 Module layout

```
src/ck3parser/
  container.py     # header + streamed zip member (Phase 1)
  fingerprint.py   # tier-1 fingerprint from header + first KB of gamestate
  runs.py          # grouping, ordering, tier-2 chain check, manifest I/O, CLI
tests/
  fixtures/runs/   # three tiny synthetic .ck3 files: two of one run, one of another
  test_runs.py     # grouping, ordering, prefix check, divergence split
```

Fixture files are generated by a helper in `tests/` (header text + zipped
`gamestate` stub) so they stay a few KB.

---

## 4. Phase 5: loading several snapshots of one run into the graph

Why bother with older snapshots at all if the latest one is a superset: CK3
**prunes** dead characters that nothing references any more. A character who
mattered in 1000 and is gone from the 1364 save is still present, with a full
record, in a 1050 snapshot. Older snapshots recover pruned history.

Rules:

- Graph gets `(:Run {run_id})` and `(:Snapshot {date, file})-[:OF]->(:Run)` nodes.
- Load snapshots **oldest to newest**, upserting by id (`MERGE` on
  `Character.id`, `Title.key`, `Dynasty.id`). A later snapshot overwrites scalar
  properties; it never deletes nodes.
- Every node gets `first_seen` and `last_seen` (snapshot dates) for provenance.
- `HELD_BY` intervals are rebuilt from the newest snapshot that contains the title;
  earlier snapshots only add intervals for titles absent later (destroyed titles
  keep their `history`, so this is rare).
- Character ids are stable within a run (verified indirectly: the `legacy` chain
  references ids across five centuries and they resolve in the current save), so
  merging by id is safe within a run and only within a run.

---

## 5. Verified against the sample save

| Fact | Value |
|---|---|
| Header first line | `SAV01024cd93a6200006afb` |
| Zip starts at byte | 27 411 |
| Zip members | `gamestate` only, 282 981 318 bytes uncompressed |
| `version` | `"1.6.1.2"` (as written in the file) |
| `meta_date` / `date` | `1364.3.10` |
| `bookmark_date` | `867.1.1` |
| `random_seed` / `random_count` | `576691683` / `53241628` |
| `first_start` | `no` |
| `ironman` | `no` (`ironman_manager` block present, `save_interval=three_months`) |
| `meta_player_name` | `"Fylkir Ludwig Åsasson"` |
| `meta_title_name` | `"Empire of Germania"` |
| `meta_house_name` | `"af Munsö"` |
| `meta_main_portrait.id` | `50544311` = `currently_played_characters` |
| `played_character.legacy` | 20 entries, `867.1.1` → `1360.6.8` |
| `dlcs` | 14 entries, includes DLCs newer than the `version` string suggests |
| `playthrough_id` | **absent** (header and gamestate) |

Assumptions still to **verify** with a second snapshot of the same run:

1. `random_seed` is constant across snapshots of one run.
2. `played_character.legacy` of the earlier snapshot is a prefix of the later one.
3. `random_count` increases monotonically with `date`.
4. Whether newer CK3 versions add a `playthrough_id`; if so, use it as the
   `RunKey` and keep the seed as a fallback.

The quickest way to close these: play the sample run forward a few months, save
again, and run `scan` on both files.

---

## 6. Milestones

1. Phase 0 scaffold merged, CI green on fixtures.
2. Phase 1 container reader handles the real file; fingerprint extractable in
   under a second per file without full decompression.
3. Phase 2 parser streams the full 283 MB `gamestate` without errors and emits
   the section index.
4. Phase 4 `scan`/`verify` group a directory of saves; tests cover grouping,
   ordering, prefix check, and divergence split.
5. Phase 3 + 5: one lineage from all snapshots of one run in Neo4j with
   `Run`/`Snapshot` provenance.
6. Phase 6 full-save scale; Phase 7 narrative generation once the local LLM is
   chosen.
