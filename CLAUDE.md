# CK3 History Extractor — notes for coding agents

Read `docs/HANDOVER.md` first (state of the project, next tasks), then
`docs/PLAN.md` (design, verified facts about the save format).

## Commands

```
uv sync --group dev              # install (the SessionStart hook does this on the web)
uv run pytest -q                 # 30 tests, < 1 s, fixture only
scripts/fetch_saves.sh           # three real saves (~73 MB each) into ./saves, git-ignored
uv run python -m ck3parser.runs verify saves --json saves/runs.json
uv run python -m ck3parser.pipeline saves/<file>.ck3 --title e_germany --dry-run
uv run python -m ck3parser.pipeline saves --title e_germany --dry-run   # whole run, oldest first
```

## Rules

- Never commit `.ck3` files or an extracted `gamestate`; they are release assets.
- The parser is brace-driven. Never rely on indentation: title entries sit at column 0.
- Everything that touches the real `gamestate` streams it (`iter_children`,
  `read_top_level`). Do not read a whole section into memory.
- Neo4j writes are idempotent `MERGE`s; nothing deletes. Tests use `DryRunSession`,
  never a live database.
- `Block` subclasses `list`. Test for `Block` before `list` in any isinstance chain.
- Title liege fields are numeric indices into `landed_titles`, not keys. Resolve
  them through `ck3parser.titles.TitleIndex`.
- No LLM SDK dependency yet; narrative generation is deferred (PLAN.md Phase 7).
- Facts labelled "verified" in PLAN.md were checked on three real saves. Anything
  new you assume about the format goes in PLAN.md §5 with a note whether it was
  checked against a real save.
- When you change the save-grouping logic, re-run `runs verify` on the three real
  saves; it must still report one clean run with legacy 19 → 20 → 20.
