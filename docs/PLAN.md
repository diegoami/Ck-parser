# CK3 History Extractor — Project Plan

Starting point: the "CK3 History Extractor — Repo Setup Prompt" artifact
(scaffold pass: extract → parse → filter → load one lineage into Neo4j; narrative
generation deferred until a small local LLM is chosen). This document turns that
prompt into a phased plan and adds a new requirement: **grouping save files that
belong to the same CK3 run (playthrough) saved at different in-game dates**, under
the assumption that the player does not save-scum.

Everything in the "Verified against the sample saves" section was checked against
three release assets from the same run:

| Label | Release | File | Size | sha256 |
|---|---|---|---|---|
| A | 0.0.4 | `Fylkir_Asa_of_Immasonian_Fylkirate_1358_09_13.ck3` | 72.8 MB | `69b78aae…8b57` |
| B | 0.0.3 | `Fylkir_Ludwig_of_Immasonian_Fylkirate_1361_01_17.ck3` | 73.1 MB | `a2b12bbb…a37b` |
| C | 0.0.2 | `Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3` | 73.8 MB | `919ad2c7…946a` |

A succession (Åsa → Ludwig, 1360.6.8) falls between A and B, so the chain covers
both a ruler change and a same-ruler interval.

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
  member is `gamestate`. The first line is `SAV0102` + 8 hex digits + 8 hex digits;
  the last 8 hex digits are the byte length of the `meta_data` text that follows
  (checked on all three saves: `0x6b6f` = 27 503, `0x6ae7` = 27 367, `0x6afb` = 27 387), so the reader can
  slice the header exactly instead of searching for `PK\x03\x04`. The middle 8 hex
  digits differ between saves and are not yet understood. The zip starts right
  after the header, so the header is small enough to read fully before touching the
  zip. Stream the zip member with
  `zipfile` (`ZipFile.open`) in chunks; the sample's `gamestate` is 283 MB
  uncompressed.
- **Parser** (`parser.py`) must be brace-driven, never indentation-driven. Real
  quirks:
  - `landed_titles` is nested twice (`landed_titles={ dynamic_templates={…}
    landed_titles={ 0={…} 1={…} … } }`) and the numbered entries sit at column 0
    with no leading tab.
  - `history={ … }` mixes `date=holder_id` with `date={ type=… holder=… }`.
    The type is the *reason* for the succession (`granted`, `revoked`,
    `conquest`, `created`, `abdication`, …) and nearly all carry a holder who
    takes over. The exception is `type=destroyed`, which ends the title: its
    `holder`, when present, names the ruler whose tenure ends, so it must not
    open a new one (verified, §5).
  - Lists of anonymous blocks look like `legacy={ { … }\n { … } }`.
  - Keys can be bare integers (`50544311={`), dates (`867.1.1=`), or identifiers.
  - Values can be quoted strings, bare tokens, numbers, dates, `yes`/`no`, and
    inline lists (`skill={ 5 7 4 4 2 9 }`).
- **Section index**: `ck3parser.sections` walks the file once by line and
  reports where each top-level key starts and ends (4.8 s on the 280 MB
  sample), and `verify_parse` pushes the whole file through the tokenizer to
  confirm the braces balance. Measured section list in §5. In the sample: `meta_data` (line 1), `date`/`bookmark_date`/
  `random_seed`/`random_count` (lines 415–420), `provinces` (3 035), `landed_titles`
  (238 167), `dynasties` (558 547), `living` (1 857 131), `dead_unprunable`
  (4 337 622), `characters` (9 692 133), `religion`, `wars`, `culture_manager`,
  `played_character` (14 007 265), `currently_played_characters`.
- **Character records** live in three places, all with the same record shape
  (`first_name birth culture faith dynasty_house skill traits family_data …`):
  `living={ <id>={…} }`, `dead_unprunable={ <id>={…} }`, and
  `characters={ dead_prunable={ <id>={…} } }` (two tabs deep). Dead records carry
  `dead_data={ date reason liege … }` instead of `alive_data`. The setup prompt only
  mentions the first two; `dead_prunable` is the one the game deletes from over time
  (see Phase 5). Culture and faith are numeric ids that resolve through
  `culture_manager` / `religion`.
- **Title records**: `landed_titles` entries carry `key`, `name`, `adj`, `holder`,
  `date`, `history`, `capital`, `de_jure_liege`, `de_facto_liege`, and sometimes
  `de_jure_vassals`, `heir`, `claim`, `laws`. A player-renamed title keeps its
  original `key` and gets a custom `name`: the sample's empire is `e_germany`
  named "Germania", and the header's `meta_title_name="Empire of Germania"`
  composes the tier with that name. Look titles up by `key`, and use `name` only
  for display.
- **Liege fields** (verified, §5): `de_facto_liege` is the title this one is
  actually held under at save time and is what the vassal structure follows;
  `de_jure_liege` is the map's nominal hierarchy. Both are the *numeric index*
  of another entry in the same section, never a title key, so resolving them
  needs the whole section indexed.
- **Title tiers** come from the key prefix (`e_`/`k_`/`d_`/`c_`/`b_`), except for
  dynamic `x_` titles, whose tier is in the `dynamic_templates` list at the head
  of the section.

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
| `random_seed` | gamestate line ~419 | decompress first few KB of the zip member | Same for the whole run (verified: `576691683` in all three saves, spanning six in-game years and a succession). Different runs from the same bookmark get different seeds. This is the primary key. |
| `bookmark_date` | gamestate line ~416 | same | Constant. |
| `game_rules`, `dlcs`, `version`, `ironman` | plaintext header | free | Constant in practice. `version` (`"1.6.1.2"` in all three saves) appears to be the game version at the **start** of the run, not at save time: the player reports the run was started long ago and carried through later patches, and the DLC list contains DLCs released well after 1.6. Not yet checked against a save from a freshly started game. Kept as a warning, not a key. |
| `played_character.name`, `player=1` | gamestate `played_character` block, far into the file | full stream | Constant (the Paradox account name). |
| `played_character.legacy` | same block | full stream | Ordered list of `{character, date, …}` for every ruler the player controlled. Earlier snapshot's list is a **prefix** of the later one (verified on `(character, date)`: A lists 19 rulers, B and C list the same 19 plus Ludwig, so both the strict-prefix and the equal case are covered). The last entry is the ruler in play and has fewer fields than it will have once the ruler is succeeded; compare on `(character, date)` only. |
| `meta_main_portrait.id` | header | free | Currently played character id; equals the last `legacy` entry's `character`. |
| `date` / `meta_date` | gamestate line ~415 / header | free | Strictly increasing along the chain. |
| `random_count` | gamestate line ~420 | first few KB | Strictly increasing along the chain (RNG draw counter; verified `52 401 480` → `52 761 528` → `53 241 628`). Tie-breaker when two snapshots share a date. |
| `meta_real_date` | header | free | Real-world date the file was saved, as years since 1900: `126.2.21`, `126.2.26`, `126.3.6` = 2026-02-21 / 02-26 / 03-06 for A, B, C. Must be non-decreasing along the chain; a later in-game date with an earlier real date is a scumming signature. Second tie-breaker. |
| Title `history` blocks, character death dates | `landed_titles`, `dead_unprunable` | full parse | Earlier snapshot ⊆ later snapshot for all dates ≤ earlier `date` (verified on both intervals: 12 906 and 12 907 titles, 0 history mismatches; 229 250 and 230 562 dead characters, 0 death-date changes). |

Character ids alone do **not** identify a run: two runs from the same bookmark
share the same initial ids, and later ids are allocated from the same counters.

### 3.3 Algorithm

Three tiers, each cheaper than the next; most files stop at tier 1.

**Tier 1 — fingerprint (no full parse).**
For each `.ck3` file read the plaintext header, then open the zip and decompress
only until `random_count=` has been seen. A prototype of this needed 32 KB of
decompressed `gamestate` and about 3 ms per file on the sample saves, so scanning
a directory of hundreds of saves is instant. Produce:

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
2. `A.meta_real_date <= B.meta_real_date` (header only, so this one runs in tier 1)
3. `A.legacy` is a prefix of `B.legacy` on `(character, date)`
4. `A.played_character.name == B.played_character.name`

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
**prunes** dead characters that nothing references any more. Measured between
consecutive sample saves:

| Movement | A → B (1358.9 → 1361.1) | B → C (1361.1 → 1364.3) |
|---|---|---|
| `dead_prunable` in earlier → **absent from later, zero mentions anywhere** | 1 060 | 1 545 |
| `living` in earlier → `dead_prunable` in later | — | 1 486 |
| `living` in earlier → `dead_unprunable` in later | — | 1 583 |
| `dead_prunable` in earlier → `dead_unprunable` in later (became referenced) | — | 309 |
| New ids in later | 2 404 | 3 413 |
| Ids in earlier missing from later for any other reason | 0 | 0 |
| Dynamic titles (`x_x_*`) in earlier missing from later | 6 | 3 |

So roughly 500 characters a year vanish from the file, and the only source for
them is an earlier snapshot. Destroyed dynamic titles vanish the same way. Older
snapshots recover pruned history.

Rules (implemented in `pipeline.run` over a directory of saves):

- Graph gets `(:Run {run_id})` and `(:Snapshot {date, file})-[:OF]->(:Run)` nodes.
- Load snapshots **oldest to newest**, upserting by id (`MERGE` on
  `Character.id`, `Title.key`, `Dynasty.id`). A later snapshot overwrites scalar
  properties; it never deletes nodes.
- Every node gets `first_seen` and `last_seen` (snapshot dates) for provenance.
- `HELD_BY` merges on `(title, from)`, so the same tenure seen in several
  snapshots stays one relationship: a tenure still open in an early snapshot
  (`to` = that snapshot's date, `open`) is closed in place by a later one that
  records its end.
- Character ids are stable within a run, and so are title indices: of the 12 904
  title keys shared by the 1358 and 1364 saves, **all** sit at the same index.
  Code still resolves by key, because indices carry no meaning across runs.
- Consecutive snapshots are compared as they load (tier 3, §3.3). Disagreements
  are reported and set the exit code; they never stop the load, and a record
  present early and absent later is not a disagreement, since that is pruning.

All of the above is **order independent**, which running it for real proved
necessary: loading one save and then the whole run over the top corrupted
`first_seen` until the writers were changed to move it only earlier and
`last_seen` only later. A tenure one snapshot saw open and another saw closed
stays closed whichever order they load in.

Game dates are written as real `date` values, never strings. Save dates sort
wrongly as text, so `"99.1.1"` lands after `"948.3.25"` and every ordering or
range query over history is silently wrong. All 64 876 distinct dates in the
sample saves are valid calendar dates between year 3 and the 9999 "never"
sentinel, so the conversion is lossless.

Known limitation: `VASSAL_OF` records vassalage **as of** a snapshot, not as an
interval. A title that changed liege between snapshots ends up with an edge to
each liege, distinguished by `as_of`. Modelling vassalage as intervals the way
`HELD_BY` does is future work.

---

## 5. Verified against the sample saves

| Fact | Save A (0.0.4) | Save B (0.0.3) | Save C (0.0.2) |
|---|---|---|---|
| Header first line | `SAV01025353630600006b6f` | `SAV0102df33d85900006ae7` | `SAV01024cd93a6200006afb` |
| `gamestate` uncompressed bytes | 279 463 917 | 280 027 292 | 282 981 318 |
| `version` | `"1.6.1.2"` | same | same |
| `meta_date` / `date` | `1358.9.13` | `1361.1.17` | `1364.3.10` |
| `meta_real_date` | `126.2.21` | `126.2.26` | `126.3.6` |
| `bookmark_date` | `867.1.1` | same | same |
| `random_seed` | `576691683` | same | same |
| `random_count` | `52401480` | `52761528` | `53241628` |
| `first_start` / `ironman` | `no` / `no` | same | same |
| `meta_player_name` | `"Fylkir Åsa the Scholar"` | `"Fylkir Ludwig Åsasson"` | same as B |
| `meta_title_name` / `meta_house_name` | `"Empire of Germania"` / `"af Munsö"` | same | same |
| `meta_main_portrait.id` | `33747696` | `50544311` | `50544311` |
| `played_character.name` | `"diegoami"` | same | same |
| `played_character.legacy` | 19 entries, last `(33747696, 1323.7.5)` | 20 entries, last `(50544311, 1360.6.8)` | same as B |
| `landed_titles` entries | 12 912 | 12 910 | 12 915 |
| `living` / `dead_unprunable` / `dead_prunable` | 40 377 / 229 250 / 9 077 | 40 356 / 230 562 / 9 130 | 40 449 / 232 458 / 9 009 |
| `playthrough_id` | absent | absent | absent |
| DLC and game-rule sets | identical across all three | | |

Results of the checks the plan relies on, run with a throwaway script over the
three gamestates, on both consecutive intervals:

| Check | A → B | B → C |
|---|---|---|
| Same `random_seed`, DLCs, rules | yes | yes |
| `random_count` and `meta_real_date` increase with `date` | yes | yes |
| `legacy` of earlier is a prefix of later | yes, strict (Ludwig appended) | yes, equal |
| Title history of earlier ⊆ later for dates ≤ earlier `date` | 12 906 titles, 0 mismatches | 12 907 titles, 0 mismatches |
| Every dead character in earlier is dead in later with the same date | 0 differences, 0 resurrections | 0 differences, 0 resurrections |
| Characters present earlier but gone later | 1 060, all from `dead_prunable` | 1 545, all from `dead_prunable` |

Note that `meta_player_name` and `meta_main_portrait.id` change at a succession,
so neither belongs in the `RunKey`; they are display data only.

### Title structure (checked on save C, 1364.3.10)

| Fact | Value |
|---|---|
| Title entries | 12 915, of which 10 399 currently held |
| Titles with `de_facto_liege` | 11 779, **0** dangling, **0** self-referencing |
| Explicit `de_jure_vassals` lists | present on some titles, e.g. `e_germany` |
| Dynamic `x_` titles | 785, all covered by `dynamic_templates`: 726 `x_mc_` (mercenary), 32 `x_ho_` (holy order), 27 `x_x_` (custom) |
| History entries | 79 305 plain `date=holder`, 28 023 typed |
| Typed entries carrying a holder | all but 105, which are `type=destroyed` |
| Distinct succession reasons | 16, led by `revoked` (5 588), `granted` (4 240), `conquest_claim` (3 473), `abdication` (2 873), `conquest` (2 796), `created` (2 266) |
| Titles whose history ends `destroyed` | 262, of which **262** have no current holder |
| `e_germany` (the player's empire) | 51 immediate de facto vassals: 10 kingdoms, 15 duchies, 26 counties |

Two consequences for the loader, both now implemented:

1. A `destroyed` entry **closes** a tenure and opens none. Its `holder` repeats
   the outgoing ruler; treating it as a new holder would invent a tenure for a
   title that no longer exists. Every one of the 262 titles ending that way is
   unheld, which is what makes the reading safe.
2. Every other typed entry opens a tenure, and its type is worth keeping as the
   `reason` on the relationship.

Character records also carry `landed_data.domain={ … }`, the list of title
indices a character holds directly, which is a second route to the same
structure and is not used yet.

### Who holds a title, and since when

The title's own `holder` and `date` beat its `history` for the tenure in
progress, because in real saves they disagree:

| Case | Count in save C |
|---|---|
| Held titles with **no** history at all | 6 079 |
| Held titles whose history ends with the current holder | 3 979 |
| Held titles whose `date` is later than the last history entry | 341 |

In every one of those 341 the current holder differs from the last history
entry, and every one of those entries is `type=leased_out`: a theocratic lease
changes hands without an entry being appended. So `date` is "current holder
holds since", and the loader opens the final tenure from it whenever the
history does not already end with the current holder. A tenure that still has
no start date is dropped, because Neo4j cannot `MERGE` a relationship on a null
property and `Title.holder` already records who holds it.

Data characteristic worth knowing: pre-bookmark history is sparse, so 21 of the
1 559 tenures in the empire load run past their holder's recorded death. For
example `c_bithynia` has consecutive entries at 752 and 855 with one holder
between them. That is the save's own granularity, not a loader artifact, and it
is left as the save states it.

### The whole file parses, and what is in it

Every one of the three saves streams through the tokenizer end to end with
**balanced braces**, which is the standing proof that the parser copes with a
real save rather than only the sections the pipeline reads:

| Save | Top-level entries | Distinct keys | Lines | Tokens | Max depth |
|---|---|---|---|---|---|
| A (1358) | 10 525 | 54 | 13 860 090 | 41 222 469 | 7 |
| B (1361) | 10 562 | 55 | 13 862 806 | 41 275 750 | 8 |
| C (1364) | 10 707 | 54 | 14 007 580 | 41 675 455 | 7 |

The key set is **not** fixed across saves of one run: B also has a top-level
`player_event`, so code must not assume a section exists. `triggered_event` is a
repeated top-level key, 10 654 times in save C.

Where the bulk of a save actually is, by share of lines in save C:

| Section | Lines | Share |
|---|---|---|
| `dead_unprunable` | 5 354 511 | 38.2% |
| `living` | 2 480 491 | 17.7% |
| `coat_of_arms` | 1 541 870 | 11.0% |
| `dynasties` | 1 298 582 | 9.3% |
| `opinions` | 1 157 939 | 8.3% |
| `artifacts` | 350 092 | 2.5% |
| `landed_titles` | 320 380 | 2.3% |
| `provinces` | 235 132 | 1.7% |
| `triggered_event` (10 654 entries) | 237 306 | 1.7% |
| `culture_manager` | 122 126 | 0.9% |

### Per-character DNA is stored packed, not readable

The gamestate holds 87 727 `dna="…"` fields, one per character record, in CK3's
**packed** base64-like form. The readable `gene_…={ … }` blocks appear only in
the header's `meta_data` portraits, 253 gene lines in total for the player's
own three portraits. Anything wanting readable genes per character would have to
decode the packed form; the companion project has solved that format but has
retired it as a harvesting mechanism (see §7).

### Loading the whole run (three snapshots, one lineage)

Loading `e_germany` from all three saves oldest first takes 1 m 39 s and writes
3 snapshots, 2 324 tenures and 208 vassal edges, with **zero** tier-3
disagreements: every history entry and death date the earlier snapshots record
survives unchanged into the later ones.

The lineage itself churns across the 1360 succession, which is game history
rather than a parsing artifact:

| Snapshot | Holder | Immediate vassals |
|---|---|---|
| 1358.9.13 | Åsa (33747696) | 37 |
| 1361.1.17 | Ludwig (50544311) | 19 |
| 1364.3.10 | Ludwig (50544311) | 51 |

Between 1358 and 1364 the empire kept 21 vassal titles, lost 16 and gained 30.

Still open:

1. Whether newer CK3 versions add a `playthrough_id`; if so, use it as the
   `RunKey` and keep the seed as a fallback.
2. Meaning of the middle 8 hex digits of the `SAV0102…` header line.
3. Behaviour of the `RunKey` when a DLC is enabled or disabled mid-run (the
   `dlcs_hash` would split the run; the CLI needs an override for that case).

---

## 6. Milestones

1. Phase 0 scaffold merged, CI green on fixtures. **Done** (scaffold pass).
2. Phase 1 container reader handles the real file; fingerprint extractable in
   under a second per file without full decompression. **Done**: tier-1 scan of
   the three real saves takes 83 ms in total.
3. Phase 2 parser streams the full 283 MB `gamestate` without errors and emits
   the section index. **Done**: all three saves tokenize end to end with
   balanced braces (~41 M tokens, ~38 s each) and `ck3parser.sections` prints
   the top-level index in 4.8 s. Results in §5.
4. Phase 4 `scan`/`verify` group a directory of saves; tests cover grouping,
   ordering, prefix check, and divergence split. **Done**: `verify` on the three
   real saves reports one clean run in about 11 s.
5. Phase 3 + 5: one lineage from all snapshots of one run in Neo4j with
   `Run`/`Snapshot` provenance. **Done, against a live database.** The empire
   lineage over all three snapshots writes 81 titles, 952 characters, 1 559
   tenures and 132 vassal edges in 1 m 54 s. The multi-snapshot design pays
   off measurably there: 286 of those characters and 16 of those vassal links
   exist **only** in the oldest snapshot, having been pruned from the newest.
   An opt-in integration suite (`tests/test_integration_neo4j.py`) pins the
   behaviour.
6. Phase 6 full-save scale; Phase 7 narrative generation once the local LLM is
   chosen.

---

## 7. The companion project, and what it needs from here

`diegoami/ck_portrait_generator` is the second of two tools. Its
`docs/DECISIONS.md` (branch `findings-and-direction`) settles the split, and it
changes what this project owes it.

**The direction (their D6, D7, D9).** Portraits are no longer generated from a
model. They are **harvested from the running game**: CK3 in debug mode and
observer mode, `play <id>` to switch to a character, then screenshot the
character window. That dissolved the accessory problem, because the game has
already computed hair, clothes and headgear. The generative model, the packed
DNA codec as a harvesting route, and accessory compositing are all retired.

**What that makes this project responsible for.** They state it plainly: *"Out
of scope for this repo: how tool 1 decides which characters are 'interesting',
and the shape of the hand-off file. This repo consumes a plain character-id list
and nothing more."* So:

| They need | Constraint | Status here |
|---|---|---|
| A character-id list per save | `play <id>` only works on a **living** character, so a list is scoped to whoever was alive at that save's date | not built |
| Which characters are "interesting" | entirely this project's call | not defined |
| Coat-of-arms definitions as data | *"Extracting them is tool 1's job"*; `coat_of_arms` is 11% of a save and titles carry `coat_of_arms_id` | not parsed |

**What this project does not owe them.** DNA, in either form. Their D6 retired
DNA-driven rendering, so the packed `dna=` fields (§5) are not part of the
hand-off.

**Where the two designs already agree.** Their roadmap item 2, "walk several
saves automatically", is the same insight as this project's multi-snapshot
loading: successive saves give the same person at different ages, and each save
contributes whoever was alive then. Their manifest has to be keyed on
`(character, save date)` for the same reason this project's graph is.

They stay decoupled: plain data files both ways, no imported code.