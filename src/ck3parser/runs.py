"""Group save snapshots into runs (playthroughs), order and verify them.

Assumption: no save scumming. Snapshots of one run form a single chain ordered
by in-game date, and anything an earlier snapshot records is a prefix of what
a later one records. Three tiers, cheapest first (docs/PLAN.md §3):

tier 1  fingerprint: bucket on (random_seed, version, bookmark_date, rules);
        order by date, random_count, meta_real_date, mtime; check the
        counters are monotonic. A change of DLC set inside a bucket is the
        same run only if tier 2 confirms it (#30); otherwise it splits.
tier 2  chain check: played_character.legacy of the earlier snapshot must be
        a prefix of the later one (on (character, date)); same player name.
tier 3  content check during the graph load (title history / deaths), see
        ck3graph.

CLI::

    python -m ck3parser.runs scan  DIR [--json runs.json] [--no-hash]
    python -m ck3parser.runs verify DIR [--json runs.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

from .container import open_gamestate_text
from .fingerprint import Fingerprint, fingerprint
from .parser import Block, PushbackLines, date_key, read_top_level


@dataclass
class Snapshot:
    fp: Fingerprint
    mtime: float
    legacy: list[tuple[int, str]] | None = None
    player_account: str | None = None

    @property
    def label(self) -> str:
        return Path(self.fp.file).name

    def sort_key(self):
        return (
            date_key(self.fp.date) if self.fp.date else (0, 0, 0),
            self.fp.random_count or 0,
            date_key(self.fp.meta_real_date) if self.fp.meta_real_date else (0, 0, 0),
            self.mtime,
        )


@dataclass
class Run:
    run_id: str
    random_seed: int | None
    bookmark_date: str | None
    version: str | None = None
    slug: str = ""
    snapshots: list[Snapshot] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: worth knowing, not wrong: a DLC set changed and the chain continued.
    #: Unlike a warning, a note does not make `runs verify` fail.
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "run_id": self.run_id,
            "slug": self.slug,
            "random_seed": self.random_seed,
            "version": self.version,
            "bookmark_date": self.bookmark_date,
            "player_account": next((s.player_account for s in self.snapshots if s.player_account), None),
            "snapshots": [
                {
                    "file": s.fp.file,
                    "date": s.fp.date,
                    "meta_real_date": s.fp.meta_real_date,
                    "random_count": s.fp.random_count,
                    "played_character": s.fp.played_character,
                    "player_name": s.fp.player_name,
                    "sha256": s.fp.sha256,
                    "size": s.fp.size,
                    "legacy_len": len(s.legacy) if s.legacy is not None else None,
                }
                for s in self.snapshots
            ],
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------- tier 1


def find_saves(directory: str | Path) -> list[Path]:
    return sorted(p for p in Path(directory).rglob("*.ck3") if p.is_file())


def group_snapshots(snapshots: Iterable[Snapshot]) -> list[Run]:
    """Tier 1: bucket, order inside each bucket, check monotonic counters.

    The bucket leaves the DLC set out (`Fingerprint.chain_key`). Where it
    changes between two consecutive saves, the legacy chain decides: if the
    later save's continues the earlier's, it is one playthrough with a note;
    if not, it splits, as a different DLC set always used to.
    """
    buckets: dict[tuple, list[Snapshot]] = {}
    for s in snapshots:
        buckets.setdefault(s.fp.chain_key, []).append(s)
    runs: list[Run] = []
    for key, group in buckets.items():
        group.sort(key=Snapshot.sort_key)
        for part, notes, warnings in _split_on_dlc_changes(group):
            first = part[0].fp
            run = Run(
                run_id=first.run_id,
                random_seed=first.random_seed,
                bookmark_date=first.bookmark_date,
                version=first.version,
                slug=first.run_slug,
                warnings=warnings,
                notes=notes,
            )
            runs.extend(_split_on_tier1_failures(run, part))
    runs.sort(key=lambda r: (r.random_seed or 0, r.snapshots[0].sort_key()))
    return _disambiguate(runs)


def _disambiguate(runs: list[Run]) -> list[Run]:
    """Give a repeated run id or slug a `-2`, `-3`... suffix, in run order.

    A slug is a chronicle's output directory, so two runs sharing one would
    overwrite each other's pages. The slug is the seed and the version, and two
    runs can share both: a DLC set changed without the legacy chain continuing,
    or turned off and back on around a break, which also repeats the id (#52).
    The first run keeps its name, so nothing that already had a unique one moves.
    """
    for attr in ("run_id", "slug"):
        seen: dict[str, int] = {}
        for run in runs:
            name = getattr(run, attr)
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                candidate = f"{name}-{seen[name]}"
                while candidate in seen:
                    seen[name] += 1
                    candidate = f"{name}-{seen[name]}"
                seen[candidate] = 1
                setattr(run, attr, candidate)
    return runs


def _split_on_dlc_changes(ordered: list[Snapshot]) -> list[tuple[list[Snapshot], list[str], list[str]]]:
    """Cut a bucket where the DLC set changes and the legacy chain does not continue.

    Tier 2 is read only for the pairs that need it: a build over saves whose
    DLC set never changes pays nothing for this.
    """
    parts: list[tuple[list[Snapshot], list[str], list[str]]] = [([], [], [])]
    prev: Snapshot | None = None
    for s in ordered:
        if prev is not None and prev.fp.dlcs_hash != s.fp.dlcs_hash:
            problem = _chain_problem(prev, s)
            window = f"between {prev.fp.date} ({prev.label}) and {s.fp.date} ({s.label})"
            if problem is None:
                parts[-1][1].append(f"DLC set changed {window}; the legacy chain continues, one run")
            else:
                parts[-1][2].append(f"DLC set changed {window} and {problem}; split")
                parts.append(([], [], []))
        parts[-1][0].append(s)
        prev = s
    return parts


def _chain_problem(a: Snapshot, b: Snapshot) -> str | None:
    """Why `b` is not `a`'s playthrough continued, or None. Reads tier 2 if needed."""
    for s in (a, b):
        if s.legacy is None:
            s.player_account, s.legacy = read_legacy(s.fp.file)
    if not a.legacy or not b.legacy:
        # nothing to compare is no proof: keep them apart, as before #30
        return "a legacy chain is missing"
    if a.player_account != b.player_account:
        return f"the player account differs ({a.player_account!r} vs {b.player_account!r})"
    if not is_prefix(a.legacy, b.legacy):
        return "played_character.legacy is not a prefix"
    return None


def _split_on_tier1_failures(run: Run, ordered: list[Snapshot]) -> list[Run]:
    """Walk consecutive pairs; start a new run when a monotonic check fails."""
    out = [run]
    cur = run
    prev: Snapshot | None = None
    for s in ordered:
        if prev is not None:
            problem = _tier1_pair_problem(prev, s)
            if problem:
                cur.warnings.append(f"divergent chain after {prev.label}: {problem}; split")
                cur = Run(
                    run_id=f"{run.run_id}-{len(out) + 1}",
                    random_seed=run.random_seed,
                    bookmark_date=run.bookmark_date,
                    version=run.version,
                    slug=f"{run.slug}-{len(out) + 1}",
                )
                out.append(cur)
            elif prev.fp.random_count == s.fp.random_count and prev.fp.date == s.fp.date:
                cur.warnings.append(f"{s.label} duplicates {prev.label} (same date and random_count)")
        cur.snapshots.append(s)
        prev = s
    return out


def _tier1_pair_problem(a: Snapshot, b: Snapshot) -> str | None:
    if a.fp.random_count is not None and b.fp.random_count is not None and b.fp.random_count < a.fp.random_count:
        return f"random_count decreases ({a.fp.random_count} -> {b.fp.random_count})"
    if a.fp.meta_real_date and b.fp.meta_real_date and date_key(b.fp.meta_real_date) < date_key(a.fp.meta_real_date):
        return f"meta_real_date goes backwards ({a.fp.meta_real_date} -> {b.fp.meta_real_date})"
    return None


# ---------------------------------------------------------------- tier 2


def read_legacy(path: str | Path) -> tuple[str | None, list[tuple[int, str]]]:
    """Return (player account name, [(character, date), ...]) from ``played_character``."""
    with open_gamestate_text(path) as f:
        block = read_top_level(PushbackLines(f), "played_character")
    if not isinstance(block, Block):
        return None, []
    name = block.get("name")
    legacy = block.get("legacy") or []
    chain = []
    for entry in legacy:
        if isinstance(entry, Block):
            chain.append((entry.get("character"), str(entry.get("date"))))
    return (str(name) if name is not None else None), chain


def is_prefix(shorter: list, longer: list) -> bool:
    return len(shorter) <= len(longer) and longer[: len(shorter)] == shorter


def verify_runs(runs: list[Run]) -> list[Run]:
    """Tier 2: load each snapshot's legacy chain and split runs where it is not a prefix."""
    out: list[Run] = []
    for run in runs:
        for s in run.snapshots:
            if s.legacy is None:
                s.player_account, s.legacy = read_legacy(s.fp.file)
        cur = Run(
            run.run_id, run.random_seed, run.bookmark_date, run.version, run.slug,
            warnings=list(run.warnings), notes=list(run.notes),
        )
        out.append(cur)
        prev: Snapshot | None = None
        for s in run.snapshots:
            if prev is not None:
                problem = None
                if prev.player_account != s.player_account:
                    problem = f"player account differs ({prev.player_account!r} vs {s.player_account!r})"
                elif not is_prefix(prev.legacy or [], s.legacy or []):
                    problem = "played_character.legacy is not a prefix"
                if problem:
                    cur.warnings.append(f"divergent chain after {prev.label}: {problem}; split")
                    cur = Run(
                        f"{run.run_id}-{len(out) + 1}", run.random_seed, run.bookmark_date,
                        run.version, f"{run.slug}-{len(out) + 1}",
                    )
                    out.append(cur)
            cur.snapshots.append(s)
            prev = s
    return out


# ---------------------------------------------------------------- manifest + CLI


def load_manifest(path: str | Path) -> dict[str, dict]:
    """Return {file: snapshot-json} from a manifest, for incremental scans."""
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    known = {}
    for run in data.get("runs", []):
        for s in run.get("snapshots", []):
            known[s["file"]] = s
    return known


def scan(directory: str | Path, with_sha256: bool = True, manifest: str | Path | None = None) -> list[Run]:
    known = load_manifest(manifest) if manifest else {}
    snaps: list[Snapshot] = []
    for path in find_saves(directory):
        st = path.stat()
        prior = known.get(str(path))
        fp = fingerprint(path, with_sha256=with_sha256 and not (prior and prior.get("size") == st.st_size))
        if prior and prior.get("size") == st.st_size and fp.sha256 is None:
            fp.sha256 = prior.get("sha256")
        snaps.append(Snapshot(fp=fp, mtime=st.st_mtime))
    return group_snapshots(snaps)


def write_manifest(runs: list[Run], path: str | Path) -> None:
    # UTF-8 said out loud: with ensure_ascii off, the platform default (cp1252 on
    # Windows) cannot hold every save name a player might choose
    Path(path).write_text(
        json.dumps({"runs": [r.to_json() for r in runs]}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def format_runs(runs: list[Run]) -> str:
    lines = []
    for r in runs:
        lines.append(f"run {r.run_id}  seed={r.random_seed} bookmark={r.bookmark_date}  {len(r.snapshots)} snapshot(s)")
        for s in r.snapshots:
            extra = f" legacy={len(s.legacy)}" if s.legacy is not None else ""
            lines.append(f"  {s.fp.date:>11}  rc={s.fp.random_count}  real={s.fp.meta_real_date}  {s.fp.player_name}  {s.label}{extra}")
        for w in r.warnings:
            lines.append(f"  ! {w}")
        for n in r.notes:
            lines.append(f"  · {n}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ck3parser.runs", description=__doc__.split("CLI::")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "verify"):
        p = sub.add_parser(name)
        p.add_argument("directory")
        p.add_argument("--json", dest="manifest", help="write (and reuse) a runs.json manifest")
        p.add_argument("--no-hash", action="store_true", help="skip sha256 (faster, weaker cache key)")
    args = ap.parse_args(argv)
    runs = scan(args.directory, with_sha256=not args.no_hash, manifest=args.manifest)
    if args.cmd == "verify":
        runs = verify_runs(runs)
    print(format_runs(runs))
    if args.manifest:
        write_manifest(runs, args.manifest)
        print(f"wrote {args.manifest}", file=sys.stderr)
    return 1 if any(r.warnings for r in runs) else 0


if __name__ == "__main__":
    raise SystemExit(main())
