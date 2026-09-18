"""A save's characters, reduced to the fields this project reads, cached on disk.

A build reads the character sections of every save **five times over**: once for
the lineage's holders, once for the family inversion, once to promote the direct
line, once to name the relatives beyond it, and once more for a faith's founder.
Each is a pass over a 280 MB gamestate, and the inversion cannot even exit early
(docs/PLAN.md §10). That is where a build's minutes go, and it is paid again in
full every time, even for saves that have not changed since the last build.

So a save's characters are written once to a digest and read from there
afterwards. Measured on the 1364 save: **281 916 characters, 11 MB gzipped,
54 s to write and 2.1 s to read back.** Adding a save to a run now costs that
one save's pass instead of the whole run's.

What is stored is exactly what the wiki and the hand-off ask a character record
for, under one-letter keys because the file has 281 916 of them: name, birth,
sex, house, culture, faith, death and the `family_data` links. Nothing else in a
record is read anywhere in this project, and a digest that stored more would be
a second, slower copy of the save.

The digest is a **cache, not a format**: it is keyed by the save's fingerprint
and thrown away whenever `SCHEMA` changes, so it can never disagree with the
save it came from. Nothing reads a digest whose header does not match.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .container import open_gamestate_text
from .family import Family, FamilyIndex, own_family
from .parser import Block, PushbackLines, iter_children

#: Bump this whenever the row shape changes. Old digests are then ignored, not
#: migrated: rebuilding one costs a minute and a wrong one costs correctness.
SCHEMA = "ck3-characters/1"

#: Where character records live, in the order worth searching. A row records
#: which of them it came from, because `living_characters` needs to know.
SECTIONS = (("living",), ("dead_unprunable",), ("characters", "dead_prunable"))

#: Row keys are one letter because a digest holds 281 916 rows: over that many,
#: `"first_name"` instead of `"n"` is megabytes of nothing.
_FIELDS = (("n", "first_name"), ("b", "birth"), ("h", "dynasty_house"), ("c", "culture"), ("f", "faith"))


def _row(cid: int, char: Block, section: int) -> dict:
    """One character record, reduced. Absent fields are left out, not stored null."""
    row: dict = {"i": cid, "g": section}
    for short, field_name in _FIELDS:
        value = char.get(field_name)
        if value is not None:
            row[short] = value if isinstance(value, int) else str(value)
    if char.get("female"):
        row["w"] = 1
    dead = char.get("dead_data")
    if isinstance(dead, Block):
        # a character with `dead_data` is dead even when the block is empty, so
        # the key is written whether or not there is a date to go in it
        row["d"] = str(dead["date"]) if dead.get("date") is not None else ""
        if dead.get("reason"):
            row["r"] = str(dead["reason"])
    family = char.get("family_data")
    if isinstance(family, Block):
        own = own_family(cid, family)
        if own.children:
            row["k"] = own.children
        if own.spouses:
            row["s"] = own.spouses
        if own.former_spouses:
            row["x"] = own.former_spouses
        if own.real_father is not None:
            row["rf"] = own.real_father
        if own.primary_spouse is not None:
            row["ps"] = own.primary_spouse
    return row


def _block(row: dict) -> Block:
    """Back to the shape every reader here already expects.

    Rebuilding a `Block` rather than inventing a second record type is what lets
    the callers stay the same whether they were handed a save or a digest.
    """
    block = Block()
    for short, field_name in _FIELDS:
        if short in row:
            block.append((field_name, row[short]))
    if row.get("w"):
        block.append(("female", True))
    if "d" in row:
        dead = Block()
        if row["d"]:
            dead.append(("date", row["d"]))
        if row.get("r"):
            dead.append(("reason", row["r"]))
        block.append(("dead_data", dead))
    family = Block()
    for kid in row.get("k", ()):
        family.append(("child", kid))
    for spouse in row.get("s", ()):
        family.append(("spouse", spouse))
    for spouse in row.get("x", ()):
        family.append(("former_spouses", spouse))
    if "rf" in row:
        family.append(("real_father", row["rf"]))
    if "ps" in row:
        family.append(("primary_spouse", row["ps"]))
    block.append(("family_data", family))
    return block


@dataclass
class CharacterDigest:
    """Every character of one save, in the compact rows, answering the same questions.

    The rows stay compact and a `Block` is rebuilt only for a character somebody
    asks for. Holding 281 916 rebuilt blocks would cost several hundred
    megabytes; holding the rows costs about what the family inversion it
    replaces did.
    """

    rows: dict[int, dict] = field(default_factory=dict)

    def find(self, wanted: set[int]) -> dict[int, Block]:
        """The wanted characters, as :func:`ck3parser.characters.find_characters` gives them."""
        return {cid: _block(self.rows[cid]) for cid in wanted if cid in self.rows}

    def living(self, wanted: set[int]) -> dict[int, Block]:
        """In ``living`` AND carrying no ``dead_data``.

        Both conditions, because someone who died on the save's own date still
        sits in `living` with the block on them and is not harvestable either
        (docs/PLAN.md §7).
        """
        return {
            cid: _block(row)
            for cid in wanted
            if (row := self.rows.get(cid)) is not None and row["g"] == 0 and "d" not in row
        }

    def family_index(self, wanted: set[int]) -> FamilyIndex:
        """The same inversion :func:`ck3parser.family.read_index` builds, from memory.

        The save states parentage downward only, so parents still come from
        inverting every child list — but over rows already in hand rather than
        over 280 MB of gamestate.
        """
        index = FamilyIndex()
        for cid, row in self.rows.items():
            if cid in wanted:
                index.own[cid] = Family(
                    id=cid,
                    children=list(row.get("k", ())),
                    spouses=sorted(dict.fromkeys(row.get("s", ()))),
                    former_spouses=sorted(dict.fromkeys(row.get("x", ()))),
                    primary_spouse=row.get("ps"),
                    real_father=row.get("rf"),
                )
            children = row.get("k")
            if not children:
                continue
            # the row's own list, not a copy: this is the largest thing here and
            # nothing mutates it
            index.brood[cid] = children
            for kid in children:
                index.parents.setdefault(kid, []).append(cid)
        return index


def cache_key(fp, save_path: str) -> str:
    """A name that changes whenever the save behind it does.

    The fingerprint already tells one save of a run from another in ~3 ms, and
    the size catches a file replaced under the same name. A full content hash
    would be more certain and would read 73 MB to decide whether to avoid
    reading 280 MB.
    """
    try:
        size = Path(save_path).stat().st_size
    except OSError:
        size = 0
    seed = f"{SCHEMA}|{Path(save_path).name}|{fp.run_id}|{fp.date}|{fp.random_count}|{fp.meta_real_date}|{size}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def digest_path(cache_dir: Path, fp, save_path: str) -> Path:
    return Path(cache_dir) / f"{Path(save_path).stem}-{cache_key(fp, save_path)}.jsonl.gz"


def write_digest(save_path: str, fp, path: Path) -> int:
    """Stream the character sections once and write the digest. Returns the rows.

    Written to a temporary name and renamed, so an interrupted build never
    leaves a half-written digest that a later build would trust.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part")
    written = 0
    with gzip.open(temporary, "wt", encoding="utf-8") as out:
        out.write(json.dumps({"schema": SCHEMA, "key": cache_key(fp, save_path), "date": fp.date}) + "\n")
        for number, section in enumerate(SECTIONS):
            with open_gamestate_text(save_path) as lines:
                for key, char in iter_children(PushbackLines(lines), section):
                    if not isinstance(char, Block):
                        continue
                    try:
                        cid = int(key)
                    except (TypeError, ValueError):
                        continue
                    out.write(
                        json.dumps(_row(cid, char, number), separators=(",", ":"), ensure_ascii=False) + "\n"
                    )
                    written += 1
    temporary.replace(path)
    return written


def read_digest(path: Path, fp=None, save_path: str = "") -> CharacterDigest | None:
    """A digest, or None when there is none, it is stale, or it is damaged.

    Every failure is None rather than an exception: a cache that cannot be read
    must cost a slow build, never a failed one.
    """
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            header = json.loads(fh.readline() or "{}")
            if header.get("schema") != SCHEMA:
                return None
            if fp is not None and header.get("key") != cache_key(fp, save_path):
                return None
            rows: dict[int, dict] = {}
            for line in fh:
                row = json.loads(line)
                # first section wins, because that is what find_characters does:
                # the sections are searched in order and the first hit is kept
                rows.setdefault(row["i"], row)
    except (OSError, ValueError, KeyError):
        return None
    return CharacterDigest(rows=rows)


def digest_for(save_path: str, fp, cache_dir: Path | None, log=None) -> CharacterDigest | None:
    """The save's digest, read from the cache or built into it. None without a cache.

    This is the whole incremental story: a save already digested is read in
    about two seconds, and one that is not is digested now and read in about two
    seconds every time after.
    """
    if cache_dir is None:
        return None
    path = digest_path(cache_dir, fp, save_path)
    cached = read_digest(path, fp, save_path)
    if cached is not None:
        if log is not None:
            print(f"  cached: {len(cached.rows)} characters from {path.name}", file=log)
        return cached
    written = write_digest(save_path, fp, path)
    if log is not None:
        print(f"  digested: {written} characters into {path.name}", file=log)
    return read_digest(path, fp, save_path)
