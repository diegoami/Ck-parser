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
  parser.py       streaming Clausewitz-script tokenizer/parser
  filter.py       referenced-vs-filler character heuristic
  fingerprint.py  cheap per-save fingerprint (header + first KB of gamestate)
  runs.py         group saves into runs, order and verify them; CLI + runs.json
  pipeline.py     traced extract -> parse -> filter -> load for one title
src/ck3graph/
  loader.py       Neo4j writes (idempotent MERGEs), holder-interval builder
  schema.cypher   unique constraints per node type
tests/            pytest suite over a small hand-written gamestate fixture
docs/PLAN.md      the plan
```

## Setup

Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```
uv sync --group dev
uv run pytest
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

Trace one title through the whole pipeline without a database:

```
uv run python -m ck3parser.pipeline saves/some_save.ck3 --title k_papal_state --dry-run
```

Drop `--dry-run` to write to Neo4j using the `.env` settings.

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
