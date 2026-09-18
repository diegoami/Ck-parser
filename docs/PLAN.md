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
| `game_rules`, `dlcs`, `version`, `ironman` | plaintext header | free | Constant within a run. `version` is the game version at the **start** of the run, not at save time: the player reports this run was started long ago and carried through later patches, and the DLC list contains DLCs released well after 1.6. It is **part of the RunKey**: three real playthroughs on hand carry 1.6.1.2, 1.4.4 and 1.3.1. |
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
RunKey = (random_seed, version, bookmark_date, game_rules_hash, dlcs_hash)
```

The **seed and the version** are what tell one playthrough from another, and
they are what the wiki names a chronicle by (§8). `version` belongs in the key
rather than being a warning beside it, because it is the version the run was
*started* on (§5) and so cannot drift mid-run: two saves that disagree about it
are two games, not one game that was patched.

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
| A character-id list per save | `play <id>` only works on a **living** character, so a list is scoped to whoever was alive at that save's date | **built**, `ck3parser.handoff` |
| Which characters are "interesting" | entirely this project's call | **defined** for v1, below |
| Coat-of-arms definitions as data | *"Extracting them is tool 1's job"*; `coat_of_arms` is 11% of a save | **built**, `ck3parser.arms`: every wanted recipe is in the manifest, so arms can be drawn rather than captured (§11) |
| A name for every image it must deliver, and a list of which are missing | it has to know what to call a file without asking, and what is still wanted | **built**, `ck3parser.portraits` and `ck3wiki.manifest` |

### The hand-off, as built

"Interesting" in v1 is the lineage the wiki is built from: everyone who has ever
held the target title or one of its immediate vassals, narrowed to those alive
at that snapshot's date. `python -m ck3parser.handoff SAVES --title KEY --out DIR`
writes one CSV per snapshot plus a `handoff.json` manifest, or bare id lists
with `--ids-only`. The format is what their loader already reads: only
`character_id` is required, and unknown columns land in its `extra`.

Liveness needs **both** signals, not one: a character who died on the save's own
date can still sit in the `living` section carrying a `dead_data` block, and
`play` would fail on them.

Measured on the three real saves for `e_germany`:

| Snapshot | Titles in lineage | Distinct current holders | Ever-holders | Harvestable |
|---|---|---|---|---|
| 1358.9.13 | 38 | — | 490 | 26 |
| 1361.1.17 | 20 | **1** | 174 | **2** |
| 1364.3.10 | 52 | 16 | 666 | 25 |

The 1361 dip is real and worth understanding: right after the 1360 succession
Ludwig held all twenty lineage titles **directly**, so the lineage had exactly
one current holder. Every current holder is alive in every snapshot, which is
the sanity check that the liveness rule is not silently dropping people.

Across the run that is **48 distinct characters in 53 rows**, and 5 of them
appear in more than one snapshot. Those 5 are the ones who get a portrait at
several ages, which is the feature their roadmap item 2 is about.

Names are never written. Their loader drops `name` on principle, and `culture`
is omitted too, because in the save it is a numeric id this project cannot yet
resolve and emitting the raw number under that name would be wrong. `dynasty_house`
is named for what it actually is, a house id, not the dynasty id their optional
`dynasty_id` column means.

### Image names, and the manifest

Both projects have to arrive at the same file name for the same image without
talking to each other, so the name is **derived**, never assigned:

    portrait:  sha256(save file's base name)[:12] + "_" + character id + ".png"
    arms:      "arms_" + sha256(the coat of arms' own recipe)[:12] + ".png"

The save's **name** is hashed, not its contents, so either side computes it
without opening 70 MB; the companion only keeps a map from save file name to
checksum. Twelve hex characters is far more than enough for the number of saves
anyone will publish, and keeps the name short and free of spaces.

Keying on the save rather than the date is what gives one portrait **per save**:
the same person at three dates is three images, which is their roadmap item 2.
Arms are not keyed on the save at all, for the reasons in §11.

**Only the living are asked for.** The companion harvests by switching to a
character with `play <id>`, which the game refuses for the dead, so a slot for
someone already buried is work nobody can do. This was got wrong at first and
the numbers were stark: the Germania chronicle asked for 1 330 portraits of
which **53 were capturable**. `dead_data` decides it, and on the real saves that
matches `living_characters` exactly — 26 and 25 of the 1358 and 1364 lineages.
Someone who died on the save's own date still sits in `living` carrying the
block, and is not harvestable either.
A `coat_of_arms_id` is an index inside one run, so it can never name an image
across runs; §11 says what does.

The wiki links every such name **whether or not the file exists yet**. A missing
one renders a dashed placeholder marked *awaiting harvest*; the `src` is already
correct, so dropping the file into the chronicle's `portraits/` directory is the
whole of publishing it — nothing is rebuilt and no link changes.

`portraits.json` is the machine-readable half, so the companion never has to
parse HTML. One sits at the root of the site listing the chronicles, and each
chronicle has its own:

```json
{ "schema": "ck3-images/2", "chronicle": "<seed>-<version>", "images": "portraits",
  "saves":  [ {"file": "...ck3", "checksum": "5a86b836cd32", "date": "1364.3.10"} ],
  "wanted": 53, "missing": 53,
  "portraits": [
    {"file": "5a86b836cd32_50544311.png", "kind": "portrait", "save": "...ck3",
     "checksum": "5a86b836cd32", "save_date": "1364.3.10", "character": 50544311,
     "house": 12345, "page": "characters/50544311.html", "have": false},
    {"file": "arms_4ec4589d5e8a.png", "kind": "arms", "save": "...ck3",
     "checksum": "5a86b836cd32", "house": 12345, "coat_of_arms_id": 13996,
     "page": "houses/12345.html", "have": false,
     "definition": [["pattern", "pattern_solid.dds"], ["color1", "red"],
                    ["colored_emblem", [["texture", "ce_eagle.dds"]]]]}
  ] }
```

`schema` is bumped when a key already there changes meaning. It went to `/2`
when arms stopped being named after the save and id and started being named
after their recipe (§11); portrait names did not change.

`have` is this build's answer, not a promise: the companion should treat the
absence of the file as the truth and the flag as a hint. `saves` repeats the
checksum map so the two sides can be checked against each other.

### A release is a batch, not a run

`scripts/fetch_saves.sh` records which release each save was published in, and
that tag rides in the manifest's `saves` entries and in the root listing's
`releases`. It says **where a save came from and where its harvested images
belong**. It never decides which chronicle a save joins.

It cannot, and the published data already shows why: the Germania run's three
saves are on releases **0.0.2, 0.0.3 and 0.0.4**, one save each. Treating a
release as a run would split that chronicle into three, each with a single
snapshot, losing every succession the run recorded between them. Runs are
decided by the fingerprint (§3) and nothing else.

The inverse is a useful convention rather than a rule: keeping one run's saves
out of another run's release makes a release a clean delivery unit. Nothing
enforces it, and nothing breaks if it is ignored.

Delivery is a git push. `diegoami/ck_wiki` is where the two projects meet: the
companion commits images to its flat `images/` directory, that push triggers the
build, and `--portraits` folds them in. A chronicle copies only the images it
links, so one flat directory serves every run — the names already carry the
save, so nothing collides.

`ck_wiki` is also where the manifests live in git, committed back by the build,
so the companion reads its queue without going through Pages or parsing HTML.
The pages themselves are never committed: they are rebuilt from this repository
and the saves on its Releases, and published as a Pages artifact.

### Houses and dynasties

A character carries `dynasty_house`; houses live in `dynasties.dynasty_house`
and name a parent dynasty in `dynasties.dynasties`, which is where
`coat_of_arms_id` actually sits — the house does not carry one.

Verified on the 1364 save: 49 891 houses, 48 099 dynasties. Of the dynasties,
45 689 have a `coat_of_arms_id`, 41 128 a `name` key, 2 210 a plain
`localized_name`, 6 320 a `prefix` key, and 4 761 a `key`. That `key` is the
game's own identifier, not a display name: sometimes a number (`"2"`), sometimes
a slug (`"welsh_ap_bleddri"`, `"bovisio"`), so it is never shown. An earlier note
here said it was always a number, which was read off the first four records and
was wrong. A house may have no name of its own, and then the dynasty's name is
the one to show. Houses the game shipped with are dated `9999.1.1`, a sentinel, not a
founding date.

Houses go into the hand-off beside the characters, one `houses_<date>.csv` per
snapshot, carrying the arms id and the derived `arms_file`. They are per
snapshot for the same reason the arms name is: the ids are per save.

**What this project does not owe them.** DNA, in either form. Their D6 retired
DNA-driven rendering, so the packed `dna=` fields (§5) are not part of the
hand-off.

**Where the two designs already agree.** Their roadmap item 2, "walk several
saves automatically", is the same insight as this project's multi-snapshot
loading: successive saves give the same person at different ages, and each save
contributes whoever was alive then. Their manifest has to be keyed on
`(character, save date)` for the same reason this project's graph is.

They stay decoupled: plain data files both ways, no imported code.

---

## 8. The wiki itself

Everything up to here prepares data. `ck3wiki` is the first part that produces
the deliverable:

```
python -m ck3wiki.build saves --title e_germany --out site
```

It reads every snapshot of a run, merges them the way the graph loader does,
and writes a static site: an index, a page per title with its succession table
and its vassals per snapshot, and a page per character with their reigns.

**It is a factual wiki, not a narrative one.** Every page is generated from the
save data directly. Phase 7's LLM-written prose is still gated on choosing a
small local model, and nothing here depends on that choice: the prose, when it
arrives, has a page to live on.

**Why it is built from saves rather than from Neo4j.** Both derive from the same
parsed data, and reading saves directly keeps the site buildable by anyone with
the save files and by CI, with no database to stand up. The graph remains the
place for queries the site does not answer.

### One chronicle per playthrough

Saves are grouped into runs and each run becomes its own chronicle under
`site/<seed>-<version>/`, with a landing page listing them. Nothing is
configured: attaching a save from a different game to a Release adds a
chronicle. Each chronicle's subject is the played character's **primary
title**, which is the first entry of their `landed_data.domain` — checked
across the sample run's succession, where all three snapshots give `e_germany`
even though the ruler changed.

Built from the five saves currently on the Releases, which are three parallel
playthroughs:

| Chronicle | Seed | Version | Saves | Titles | Characters |
|---|---|---|---|---|---|
| Germania | 576691683 | 1.6.1.2 | 3 | 68 | 952 |
| Holy Roman Empire | 633048653 | 1.4.4 | 1 | 84 | 1 495 |
| France | 1370892195 | 1.3.1 | 1 | 109 | 1 701 |

4 412 pages in 2 m 34 s. France's subject is `x_x_5822`, a custom empire, so
dynamic titles work as subjects too.

### What building it found

Rendering the pages and looking at them exposed a merge bug that the graph's own
Cypher had right and the model did not. When two snapshots both see a reign
still open, the **later** snapshot has the better end date, because an open reign
runs to whenever we last looked. Keeping the first one froze the current ruler's
reign at an old save's date: Ludwig's reign read "1360.6.8 – 1361.1.17" on a
wiki whose newest save is 1364.

### Names are an approximation

A save stores `first_name` as a localization *key*, not display text, and marks
diacritics with an underscore: `FranC_ois` is François, `O_zgul` is Özgül,
`Is_mail` is Ismāʿīl. Decoding that properly needs the game's localization
files, which this project deliberately does not read (§2). `clean_name` drops
the marker and never invents a letter, so the wiki shows "Francois" rather than
a wrong guess. 2 070 of 20 000 sampled living characters carry one.

The marker follows the letter it modifies, **except on the first letter, where
it comes in front**: `_Odgrim` is Ǫdgrim, found among Ludwig's siblings. A
leading marker is dropped like any other.

### Portraits and houses

Every character page carries a portrait slot per save the character appears in,
and every house page a slot for its coat of arms, linked by the derived names of
§7 whether or not the image exists yet. `--portraits DIR` folds in whatever the
companion has delivered: files found there are copied into the chronicle and
their slots lose the *awaiting harvest* marking. Nothing else changes, because
the links never depended on the file being there.

Houses get pages of their own under `houses/`, listing their members, their
dynasty, motto and founding date, and marking the dynasty head. Characters link
to their house from the infobox and from the index.

---

## 9. Vassalage, and why it has bounds instead of dates

A save records who **holds** a title and since when: `holder`, `date`, and a
`history` of holders. It records who a title's **liege** is — `de_facto_liege`,
`de_jure_liege` — but not who it has been. There is no vassalage history in the
file. Verified on the three Germania saves.

So vassalage cannot be read the way succession is read. All there is are the
snapshots, and a change is only ever known to have happened *between* two of
them. The wiki says exactly that and never invents a date:

| Under | Seen | Began | Ended |
|---|---|---|---|
| d_optimatoi | 1358.9.13 – 1361.1.17 | by 1358.9.13 | 1361.1.17 – 1364.3.10 |
| Germania | 1364.3.10 | 1361.1.17 – 1364.3.10 | *current* |

A range under Began or Ended is a **window** the change happened somewhere
inside, never a date. "by X" is the first snapshot, with nothing before it to
bound against. Both are the tightest the saves allow.

**Every title is asked, not just the lineage.** A title is in a snapshot's
*lineage* only while it is a direct vassal of the subject, but it is in that
snapshot's `landed_titles` as long as it exists at all. So a vassal that left is
not lost: the save still says who took it. Before this, a non-subject title's
liege was *asserted* to be the subject, because that is how it had been
selected, which could never be wrong and never said anything.

**Absence is not independence.** A title missing from a save was destroyed, or
pruned (§4), and the file does not say which. It is never recorded as a liege,
and it breaks a stretch rather than bridging a gap nothing was seen across.

Measured on the three Germania saves, 68 titles:

| | |
|---|---|
| one stretch (never changed liege) | 20 |
| two stretches | 46 |
| three stretches | 2 |
| absent from at least one save | 0 |
| the subject itself | independent throughout |

The vassal count under Germania swings 37 → 19 → 51. The dip is real: right
after the 1360 succession Ludwig held the lineage titles directly.

**The bounds are often tighter than they look**, and the page already shows why.
Bithynia's own succession table records Ludwig taking it by `conquest_holy_war`
on 1363.1.24 and granting it away on 1363.1.25 — inside the inferred window of
1361.1.17 to 1364.3.10. Narrowing a liege change automatically from the holder
history is tempting and **not** done: a title can change liege without changing
hands, so the two are correlated rather than equivalent, and a date inferred
that way would be a guess wearing a fact's clothes. Leaving both on the page
lets the reader draw the tighter conclusion.

**In the graph**, `(:Title)-[:VASSAL_OF {kind, first_seen, last_seen, as_of}]->(:Title)`.
The bracket moves only outward, so the result does not depend on the order
snapshots load in, and they are observations rather than an interval for the
same reason as above. Nothing is ever deleted, so an edge that stopped being
true stays, bracketed by the dates that saw it.

**Still one level deep.** `TitleIndex.vassals` holds the whole tree for a save,
but `lineage()` takes the subject plus its immediate vassals, so a county under
a vassal duchy is not loaded. Deepening it multiplies the character load (666 at
one level in 1364) and is left for later.

---

## 10. Family, and why parents cost a full pass

**Verified on the 1364 save, all 281 916 characters: not one carries a `father`
or a `mother` key.** Parentage is stored *downward only*. A character's
`family_data` lists:

| Key | Shape | Carried by (of the 1364 lineage's 666) |
|---|---|---|
| `child` | a list | 566 |
| `spouse` | **repeats as its own key** | 550 |
| `former_spouses` | a list | 543 |
| `primary_spouse` | a scalar | 438 |
| `real_father` | a scalar | 12 |
| `betrothed` | a scalar | 1 |
| *no `family_data` at all* | | 27 |

Two shapes in one block, so neither may be read with `get()` alone: `spouse`
appears four times over for a character with four spouses, while `child` arrives
as one list. `Block.getall` is the only correct reader.

### Parents are an inversion

To find someone's parents you must find whoever claimed them as a child, which
means reading **every** character record: a parent may be alive, dead-unprunable
or dead-prunable, and there is no early exit because the parent may be the last
record in the last section. One pass, ~37 s on a 280 MB save, 201 498 children
resolved.

It buys what a cheaper version cannot:

| | of the 666 |
|---|---|
| parents found by inverting the **lineage only** | 447 |
| parents found by inverting the **whole save** | **590** |
| of those, with both parents | 536 |
| with one parent | 54 |

The remaining 76 are founders, or have parents the save has pruned. Siblings
come free: whenever a child list mentions someone wanted, the whole list is
kept, so half-siblings through either parent are included.

`real_father` is never merged into `parents`. The game keeps a bastard's true
father apart from their legal one, and so does this.

A marriage that ended appears under `spouse` in the older snapshot and
`former_spouses` in the newer one, so the union must subtract: "former" is the
later word on it, and listing the person under both names them twice.

### Who gets a page

Holding a title is what put the ever-holders in. The **direct line** — parents,
spouses, former spouses and children — is in by blood or marriage, and gets the
same page and the same portrait rule. Siblings do not: they are named wherever
they appear, and promoting them would buy 689 more pages for the Germania
chronicle that are mostly dead ends.

Measured on the Germania chronicle, across its three saves:

| | pages |
|---|---|
| ever-holders alone | 952 |
| **+ the direct line** | **5 550** |
| + siblings as well | 6 251 |

The portrait queue moves with it, but only for the living: 53 → **1 389**,
because a ruler's spouse and children are usually alive when the ruler is,
while the ever-holders are mostly long dead. Every one of those is capturable,
which is the difference from the 1 330 the wiki asked for before liveness was
enforced.

Anyone the family still reaches who has no page — siblings, and the kin of kin —
is fetched once, from the newest save that still has them, and only far enough
to be named. A name that is not a link is the honest rendering of someone the
wiki knows of but not about.

Promotion happens **before** houses are resolved, because it brings in
characters whose houses must be looked up too. `--no-kin` turns it off.

### One pass, not two

Promoting needs the promoted characters' own parents and children, which would
be a second full inversion if the first one were narrowed to what was asked for.
It is not: `FamilyIndex` keeps the whole map, 201 498 children and 164 612
parents, for about 80 MB. Their spouses come from the records fetched to promote
them, which are needed anyway.

### The cost, and the way out

This is the most expensive thing a build does: one full character pass per
snapshot, on top of the targeted passes the lineage already needs. `--no-family`
skips it, which is what to use when iterating on anything else.

The fixture was wrong about all of this until now: it gave the child a `father`
and `mother`, a shape no save uses. It now claims children from both parents,
as a real save does.

---

## 11. Coats of arms: named by what they look like

A coat of arms is worth harvesting once and reusing, so the question is when two
of them are the same. Neither id nor owner answers it.

**The id cannot.** `coat_of_arms_id` is an index inside one save. Matching
dynasties across two playthroughs by the game's own `key`, 2 of 4 497 shared
keys had the same id.

**Nor can the owner.** The intuition is that a dynasty's arms are fixed by the
game while a house's are generated during play. Checked against the artwork
itself, on dynasties present in two runs:

| dynasty `key` | identical artwork | different |
|---|---|---|
| named (`welsh_ap_bleddri`, `bovisio`) | 3 | 57 |
| numeric (`2`, `100009`) | 55 | 5 |

The same result for Germania vs the HRE and Germania vs France. Named historical
dynasties mostly get **different** arms per playthrough — CK3 generates one when
the game files do not author it — so "is this dynasty game-defined?" does not
predict "are its arms fixed?", and keying on the dynasty would tell the
companion that two different pictures are the same file.

**The recipe can.** `coat_of_arms.coat_of_arms_manager_database` maps an id to
what the game draws:

```
{pattern=pattern_solid.dds, color1=red, color2=red, color3=white,
 colored_emblem={color1=white, color2=white, texture=ce_eagle.dds,
                 instance={scale=[0.9, 0.9]}}}
```

That **is** the picture's identity, so it is what names the image:
`arms_<sha256(recipe)[:12]>.png`. Identical artwork gets one name in every run
and every chronicle and is harvested once; different artwork gets different
names. Nothing has to be classified as fixed or generated.

**How much this actually saves, measured rather than guessed.** Across the three
chronicles the manifests ask for 2 861 arms, which are 2 589 distinct images: a
10% saving. An earlier estimate here said "roughly half", extrapolated from 58 of
120 game-keyed dynasties present in two runs having identical artwork. That
sample was the wrong population. The houses a chronicle wants belong mostly to
the ruling families and their relatives, and those are **generated** houses whose
arms are unique to the playthrough; the game-keyed dynasties that share artwork
are largely ones no page links. The naming is still right — it can never merge
two different pictures, and it costs nothing — but it is not where the win is.
The win is the next section.

Two things the canonical form must get right, both covered by tests:

* `colored_emblem` **repeats as its own key**, once per emblem, so the recipe is
  kept as ordered `[key, value]` pairs. A dict would keep one emblem of three
  and collapse two different coats of arms into one name.
* **Order is part of the recipe.** Emblems are drawn in the order listed, so two
  definitions differing only in order are different pictures.

A house whose recipe cannot be read gets no arms image at all. An id alone
cannot identify a picture, and a name that does not identify one would ask for
the same image twice under different names.

### Titles bear arms too

Every one of the 1364 save's **12 915 titles** carries a `coat_of_arms_id`,
which the title parser used to drop. They are resolved the same way and shown in
the title page's infobox.

Because the name comes from the recipe rather than from who bears it, a title
and the house holding it **share one file** whenever they are drawn alike. That
turns out to be the exception rather than the rule. Measured on the Germania
chronicle, 924 arms images with 944 bearers between them:

| Shared between | Images |
|---|---|
| two houses | 13 |
| a title and a house | **4** |
| two titles | 1 |
| borne by one thing only | 906 |

So only 4 of the 68 titles fly a house's arms — the guess that a realm usually
flies its ruling house's was wrong, and adding titles added 63 genuinely new
images rather than mostly duplicates. The collapsing is still right and still
free; it is simply worth less than it looks, as with the cross-run dedup in the
section above.

The manifest collapses shared images into one request and lists every bearer
under `borne_by`:

```json
{ "file": "arms_750fc7e0a608.png", "kind": "arms", "title": "c_test",
  "page": "titles/c_test.html",
  "borne_by": ["titles/c_test.html", "houses/500.html"], ... }
```

An entry carries `title` or `house`, never both, naming whichever bearer the
manifest saw first; `borne_by` is the full list.

### The companion need not capture them

The recipe rides in the manifest under `definition`. Arms can therefore be
composed offline from the game's texture files — which is what the companion's
own roadmap wanted before portraits went the screenshot route — instead of being
captured one at a time in-game. Portraits still have to be screenshotted; arms
do not.
