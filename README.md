# CK3 History Extractor

Turns Crusader Kings 3 save files into a queryable Neo4j graph of characters,
dynasties and titles, including how titles changed hands over the in-game
centuries. Saves from the same run taken at different dates are grouped and
loaded together so that history the game has pruned from later saves survives.

Wikipedia-style narrative generation from the graph is planned but deferred
until a small local LLM is chosen. See [`docs/PLAN.md`](docs/PLAN.md) for the
phased plan, the save-run grouping design, and the facts verified against real
saves.

## Layout

```
src/ck3parser/
  container.py    .ck3 container: plaintext header + zipped gamestate (streamed)
  characters.py   targeted character lookup
  player.py       who was played, and that run's primary title
  parser.py       streaming Clausewitz-script tokenizer/parser
  filter.py       referenced-vs-filler character heuristic
  fingerprint.py  cheap per-save fingerprint (header + first KB of gamestate)
  runs.py         group saves into runs, order and verify them; CLI + runs.json
  titles.py       title records, liege/vassal structure, history normalisation
  sections.py     top-level layout of a gamestate, and a whole-file parse check
  dynasties.py    houses, their dynasties, and the dynasty's coat-of-arms id
  cultures.py     cultures: what the save names and what it only keys
  faiths.py       faiths, and who founded the ones made during the run
  family.py       parents by inverting every child list; siblings and spouses
  vassalage.py    who a title answered to, as stretches between snapshots
  arms.py         coat-of-arms recipes, and the digest that names their image
  digest.py       per-save character cache: what makes a rebuild incremental
  portraits.py    the image names both this project and the companion derive
  handoff.py      the character and house lists the portrait harvester consumes
  consistency.py  tier-3 checks between two snapshots of one run
  pipeline.py     load a lineage from one save or from a whole run
src/ck3graph/
  loader.py       Neo4j writes (idempotent MERGEs), holder-interval builder
  people.py       one streaming pass for the whole population's family edges
  schema.cypher   unique constraints per node type
src/ck3wiki/
  model.py        one run's history, merged from all its snapshots
  render.py       static HTML
  manifest.py     portraits.json: every image the wiki wants, and what is missing
  build.py        `python -m ck3wiki.build` — the wikis themselves
  prose.py        `python -m ck3wiki.prose` — paragraphs written from each page's facts
tests/            pytest suite over a small hand-written gamestate fixture
docs/PLAN.md      the plan
docs/COMPANION_PROPOSAL.md  the image contract, as filed with the companion
```

## Setup

Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```
uv sync --group dev
uv run pytest
```

The suite runs against a recorded-Cypher stub and needs no database. To exercise
the loader against a real one (this **wipes** the target database, so point it at
a throwaway):

```
CK3_TEST_NEO4J_URI=bolt://localhost:7687 \
    NEO4J_USER=neo4j NEO4J_PASSWORD="$YOUR_TEST_PASSWORD" \
    uv run pytest tests/test_integration_neo4j.py
```

Neo4j Community Edition running locally; copy `.env.example` to `.env` and
fill in `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` (and optionally
`NEO4J_DATABASE`). Apply the schema once:

```
uv run python -c "from ck3graph.loader import *; s=open_session(Neo4jConfig.from_env()); apply_schema(s); s.__exit__(None,None,None)"
```

## Save files

Large `.ck3` saves are **not** committed to git. They are attached to GitHub
Releases of this repository as assets (2 GB per file limit) and fetched by URL
when needed, for example:

```
curl -L -o saves/Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3 \
  https://github.com/diegoami/Ck-parser/releases/download/0.0.2/Fylkir_Ludwig_of_Immasonian_Fylkirate_1364_03_10.ck3
```

GitHub Actions artifacts are not used for this: they are ephemeral,
workflow-run-scoped storage. CI runs only against the tiny fixture in
`tests/fixtures/`.

## Usage

Group a directory of saves into runs (tier 1: header + first KB of each file):

```
uv run python -m ck3parser.runs scan saves/ --json saves/runs.json
```

Also check the played-ruler chain of each run (tier 2; streams each file):

```
uv run python -m ck3parser.runs verify saves/ --json saves/runs.json
```

Trace a lineage (a title plus the titles held under it) without a database:

```
uv run python -m ck3parser.pipeline saves/some_save.ck3 --title k_papal_state --dry-run
```

Point it at a directory instead to load every snapshot of that run, oldest
first, which recovers history the later saves have pruned:

```
uv run python -m ck3parser.pipeline saves --title k_papal_state --dry-run
```

Consecutive snapshots are checked against each other as they load; the exit
code is 0 when they agree and 1 when they do not. `--no-vassals` loads the
title alone, `--no-check` skips the comparison, and `--run <id>` picks one run
when a directory holds several. A dry run reports counts on stderr and prints
nothing else; add `--echo` to see every Cypher statement it would have run.
Drop `--dry-run` to write to Neo4j using the `.env` settings.

Build the wikis, which is what all of this is for:

```
scripts/fetch_saves.sh            # every save on the Releases
uv run python -m ck3wiki.build saves --out site
```

Saves are grouped into playthroughs, and **each playthrough gets its own
chronicle** under `site/<seed>-<version>/`, with a landing page listing them.
A chronicle has an index, a page per title with its succession table, and a page
per character with their reigns, merged across every save of that run so it
includes history the newest one has pruned.

Nothing needs configuring: attaching a save from a different game to a Release
adds a chronicle. Each chronicle is about its played character's primary title
unless `--title` says otherwise. Open `site/index.html` to read it locally.

Publishing happens in [`diegoami/ck_wiki`](https://github.com/diegoami/ck_wiki),
not here: its workflow clones this repository, fetches the saves from these
Releases, builds and deploys to Pages. That repository is also where
`diegoami/ck_portrait_generator` commits the harvested portraits and coats of
arms, which is what `--portraits DIR` folds in.

Write the character list for the companion portrait harvester, one file per
snapshot of the run:

```
uv run python -m ck3parser.handoff saves --title k_papal_state --out handoff
```

Each file lists the characters of that lineage who were **alive** at that
snapshot's date, which is what the harvester can switch to in-game. `--ids-only`
writes bare ids instead. See [`docs/PLAN.md`](docs/PLAN.md) §7 for the contract.

See what a save contains, and check the parser handles all of it:

```
uv run python -m ck3parser.sections saves/some_save.ck3 --verify
```

Extract the raw `gamestate` to disk for inspection:

```
uv run python -c "from ck3parser.container import extract_gamestate; extract_gamestate('saves/some_save.ck3', 'gamestate')"
```

## Status

Skeleton pass. The parser handles everything seen in three real saves but has
only been exercised on the fixture and on the sections the pipeline reads
(`landed_titles`, `living`, `dead_unprunable`, `characters.dead_prunable`,
`played_character`). Assumptions still to confirm on more saves are listed in
the module docstrings and in `docs/PLAN.md` §5.
